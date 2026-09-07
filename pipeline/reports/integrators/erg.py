"""
ERG Integrator — RETeval full-field ERG.

Consumes vision output from eyeassist-vision (which has analyzed the
rasterized RETeval PDF via Gemma 4 vision) and produces a ReportContext.

Flow:
  vision_output → parse → normative comparison → flag findings →
    query retina RAG collection → LLM generates interpretation prose →
      assemble ReportContext

Option A architecture: this integrator calls the LLM internally.
"""

from datetime import date

from .base import Integrator
from ..schemas import ReportContext, Finding, InterpretationSection


# ── Normative thresholds (placeholder — replace with real LKC reference data) ─
# Percentile-based flagging for the photopic flicker protocol.
# These thresholds match the WNL / BRDL / ABNL conventions used in the
# original 307 Vision template.
def flag_percentile(pct: float) -> str:
    """Map a percentile rank to a status flag."""
    if pct >= 5:
        return 'WNL'
    elif pct >= 1:
        return 'BRDL'
    else:
        return 'ABNL'


class ERGIntegrator(Integrator):
    modality = 'ERG'
    template_filename = 'erg.yaml'

    def build_context(self, vision_output: dict, patient_meta: dict) -> ReportContext:
        ctx = ReportContext(modality=self.modality)

        # ── Patient & test info ────────────────────────────────────────
        ctx.patient = [
            ('Patient Name',      patient_meta.get('name', '')),
            ('Date of Birth',     patient_meta.get('dob_age', '')),
            ('Sex',               patient_meta.get('sex', '')),
            ('Chart / MRN',       patient_meta.get('mrn', '')),
            ('Date of Test',      vision_output.get('test_date', '')),
            ('Ordering Provider', patient_meta.get('ordering_provider', 'Jason B. Whitman, O.D.')),
            ('Reason for Test',   patient_meta.get('reason', '')),
        ]

        # ── Device & protocol ──────────────────────────────────────────
        device = vision_output.get('device', {})
        ctx.device = [
            ('Device',             device.get('name', 'RETeval™  (LKC Technologies, Inc.)')),
            ('Serial Number',      device.get('serial', '')),
            ('Firmware / RefData', device.get('firmware', '')),
            ('Test Protocol',      device.get('protocol', 'Photopic Flicker — 16 Td·s White at 28.3 Hz, Background Off')),
            ('Electrode Type',     device.get('electrode', 'Sensor Strips')),
            ('Pupil Size at Test', device.get('pupils', '')),
        ]

        # ── Findings (normative comparison + flagging) ────────────────
        ctx.findings = self._build_findings(vision_output)

        # ── Interpretation (LLM with RAG) ──────────────────────────────
        interp_text, citations = self._generate_interpretation(ctx.findings, vision_output)
        ctx.interpretation = interp_text
        ctx.citations = citations

        # ── Assessment & plan (LLM follow-on) ──────────────────────────
        ctx.assessment_plan = self._generate_assessment_plan(ctx.findings, ctx.interpretation)

        # ── Attestation ────────────────────────────────────────────────
        ctx.attestation = [
            ('Interpreting Provider', patient_meta.get('interpreting_provider', 'Jason B. Whitman, O.D.')),
            ('Practice',              '307 Vision'),
            ('Report Date',           date.today().strftime('%m/%d/%Y')),
            ('Signature / Date',      '___________________________________  /  ___________'),
        ]

        ctx.confidence = vision_output.get('confidence', 0.0)
        return ctx

    # ── Helpers ────────────────────────────────────────────────────────

    def _build_findings(self, vision_output: dict) -> list[Finding]:
        """
        Convert raw vision output into Finding rows with WNL/BRDL/ABNL flags.

        vision_output['measurements'] is expected to be a dict like:
            {
              'fundamental_implicit_time': {'od': 28.4, 'od_pct': 45,
                                            'os': 28.1, 'os_pct': 52},
              'waveform_implicit_time':    {...},
              'fundamental_amplitude':     {...},
              'waveform_amplitude':        {...},
            }
        """
        m = vision_output.get('measurements', {})

        param_map = [
            ('fundamental_implicit_time', 'Fundamental Implicit Time (ms)'),
            ('waveform_implicit_time',    'Waveform Implicit Time (ms)'),
            ('fundamental_amplitude',     'Fundamental Amplitude (µV)'),
            ('waveform_amplitude',        'Waveform Amplitude (µV)'),
        ]

        findings = []
        for key, label in param_map:
            data = m.get(key, {})
            od_v = data.get('od')
            od_pct = data.get('od_pct')
            os_v = data.get('os')
            os_pct = data.get('os_pct')

            if od_v is None or os_v is None:
                # Missing data — emit a placeholder row that won't crash render
                findings.append(Finding(
                    parameter=label,
                    od_value='—', od_status='WNL',
                    os_value='—', os_status='WNL',
                ))
                continue

            findings.append(Finding(
                parameter=label,
                od_value=f'{od_v:.1f} ({od_pct}th %ile)',
                od_status=flag_percentile(od_pct),
                os_value=f'{os_v:.1f} ({os_pct}th %ile)',
                os_status=flag_percentile(os_pct),
            ))

        return findings

    def _generate_interpretation(self, findings: list[Finding], vision_output: dict):
        """
        Query the retina RAG collection and have the LLM generate the
        three interpretation paragraphs (Implicit Times, Amplitudes,
        Overall Pattern).

        Returns (list[InterpretationSection], list[citation_strings]).
        """
        # Build a structured findings summary for the LLM
        findings_summary = '\n'.join(
            f'- {f.parameter}: OD {f.od_value} [{f.od_status}], '
            f'OS {f.os_value} [{f.os_status}]'
            for f in findings
        )

        rag_query = (
            'RETeval photopic flicker ERG interpretation: implicit time '
            'prolongation, amplitude reduction, cone pathway dysfunction, '
            'ISCEV standards'
        )

        rag_chunks = []
        citations = []
        if self.rag is not None:
            rag_results = self.rag.query(
                collection=self.rag_collection,
                query=rag_query,
                n_results=5,
            )
            rag_chunks = [r['text'] for r in rag_results]
            citations = [r.get('source', '') for r in rag_results]

        rag_context = '\n\n'.join(rag_chunks) if rag_chunks else ''

        prompt = self._build_interpretation_prompt(findings_summary, rag_context)

        if self.llm is None:
            # Fallback for testing without an LLM connected
            sections = [
                InterpretationSection(
                    label='Implicit Times',
                    text='Describe fundamental and waveform implicit times relative to '
                         'age-matched normals. Note any prolongation and laterality.',
                ),
                InterpretationSection(
                    label='Amplitudes',
                    text='Describe fundamental and waveform amplitudes. Note absolute '
                         'values and percentile rank. Comment on inter-ocular asymmetry '
                         'if present.',
                ),
                InterpretationSection(
                    label='Overall Pattern',
                    text='Synthesize findings. State the most likely physiologic '
                         'interpretation (e.g., early cone pathway dysfunction, '
                         'normal study, etc.).',
                ),
            ]
            return sections, citations

        llm_response = self.llm.generate(prompt=prompt, format='json')
        sections = [
            InterpretationSection(label='Implicit Times',  text=llm_response['implicit_times']),
            InterpretationSection(label='Amplitudes',      text=llm_response['amplitudes']),
            InterpretationSection(label='Overall Pattern', text=llm_response['overall_pattern']),
        ]
        return sections, citations

    def _build_interpretation_prompt(self, findings_summary: str, rag_context: str) -> str:
        return f"""You are interpreting a RETeval full-field ERG (photopic flicker protocol) for an ophthalmology clinical report. Ground your interpretation in ISCEV standards and the reference material below.

CLINICAL REFERENCE MATERIAL:
{rag_context}

PATIENT FINDINGS:
{findings_summary}

Produce a JSON object with exactly these three keys:
  "implicit_times": 2-3 sentences describing fundamental and waveform implicit times relative to age-matched normals, noting any prolongation and laterality.
  "amplitudes": 2-3 sentences describing fundamental and waveform amplitudes, noting absolute values, percentile rank, and inter-ocular asymmetry.
  "overall_pattern": 2-3 sentences synthesizing findings into the most likely physiologic interpretation (e.g., normal study, early cone pathway dysfunction, generalized retinal dysfunction).

Be precise. Do not invent values not present in the findings. Do not include any text outside the JSON object."""

    def _generate_assessment_plan(self, findings, interpretation) -> str:
        """Brief A&P narrative — LLM-generated, or empty for now."""
        if self.llm is None:
            return ''
        # Real implementation would prompt the LLM with the structured
        # findings + interpretation and ask for a 2-3 sentence A&P.
        return ''
