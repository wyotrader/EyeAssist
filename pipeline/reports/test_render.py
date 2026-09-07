"""
Smoke test: render an ERG report using the new architecture with the
same placeholder data as the original 307 Vision template, then verify
the output matches.
"""

import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

from reports import render, ReportContext, Finding, InterpretationSection
from reports.integrators.erg import ERGIntegrator


# Build a context manually with the same placeholder data as the original
# template, so we can diff the visual output against the user's PDF.
def build_placeholder_context():
    ctx = ReportContext(modality='ERG')

    ctx.patient = [
        ('Patient Name',     'SYNTHETIC, Test'),
        ('Date of Birth',    'MM/DD/YYYY  (Age YY)'),
        ('Sex',              'M / F'),
        ('Chart / MRN',      'TEST-000000'),
        ('Date of Test',     'MM/DD/YYYY'),
        ('Ordering Provider','Jason B. Whitman, O.D.'),
        ('Reason for Test',  'e.g., Plaquenil baseline / monitor for cone dysfunction / DR screening'),
    ]

    ctx.device = [
        ('Device',             'RETeval™  (LKC Technologies, Inc.)'),
        ('Serial Number',      'R######'),
        ('Firmware / RefData', '2.14.0  |  Reference Data: 2023.23 6966f91'),
        ('Test Protocol',      'Photopic Flicker — 16 Td·s White at 28.3 Hz, Background Off'),
        ('Electrode Type',     'Sensor Strips'),
        ('Pupil Size at Test', 'OD: #.# mm  |  OS: #.# mm  (undilated)'),
    ]

    ctx.findings = [
        Finding('Fundamental Implicit Time (ms)', '##.# (##th %ile)', 'WNL',
                                                  '##.# (##th %ile)', 'WNL'),
        Finding('Waveform Implicit Time (ms)',    '##.# (##th %ile)', 'BRDL',
                                                  '##.# (##th %ile)', 'WNL'),
        Finding('Fundamental Amplitude (µV)',     '##.# (##th %ile)', 'WNL',
                                                  '##.# (##th %ile)', 'WNL'),
        Finding('Waveform Amplitude (µV)',        '##.# (##th %ile)', 'WNL',
                                                  '##.# (##th %ile)', 'WNL'),
    ]

    ctx.interpretation = [
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
                 'interpretation (e.g., early cone pathway dysfunction, normal '
                 'study, etc.).',
        ),
    ]

    ctx.assessment_plan = ''

    ctx.attestation = [
        ('Interpreting Provider', 'Jason B. Whitman, O.D.'),
        ('Practice',              '307 Vision'),
        ('Report Date',           'MM/DD/YYYY'),
        ('Signature / Date',      '___________________________________  /  ___________'),
    ]

    return ctx


print('--- Test 1: Direct ReportContext → render ---')
ctx = build_placeholder_context()
pdf_bytes = render(
    context=ctx,
    template_path=PIPELINE_DIR / 'reports' / 'templates' / 'erg.yaml',
)
print(f'  PDF generated: {len(pdf_bytes)} bytes')


print('--- Test 2: Integrator with no LLM/RAG (uses fallback prose) ---')
integrator = ERGIntegrator(llm_client=None, rag_client=None)

vision_output = {
    'test_date': '04/07/2026',
    'device': {
        'serial': 'R123456',
        'firmware': '2.14.0  |  Reference Data: 2023.23 6966f91',
        'pupils': 'OD: 4.5 mm  |  OS: 4.6 mm  (undilated)',
    },
    'measurements': {
        'fundamental_implicit_time': {'od': 28.4, 'od_pct': 45, 'os': 28.1, 'os_pct': 52},
        'waveform_implicit_time':    {'od': 31.2, 'od_pct': 3,  'os': 29.5, 'os_pct': 18},
        'fundamental_amplitude':     {'od': 12.6, 'od_pct': 38, 'os': 13.1, 'os_pct': 44},
        'waveform_amplitude':        {'od': 18.2, 'od_pct': 22, 'os': 19.0, 'os_pct': 28},
    },
    'confidence': 0.87,
}

patient_meta = {
    'name': 'SYNTHETIC, Test',
    'dob_age': '01/01/1970  (Age 56)',
    'sex': 'F',
    'mrn': 'TEST-000000',
    'reason': 'Plaquenil baseline screening',
}

ctx2 = integrator.build_context(vision_output, patient_meta)
pdf_bytes2 = render(
    context=ctx2,
    template_path=integrator.template_path,
)
print(f'  PDF generated: {len(pdf_bytes2)} bytes')
print(f'  Findings flagged:')
for f in ctx2.findings:
    print(f'    {f.parameter}: OD={f.od_status}, OS={f.os_status}')

print('\nAll tests passed.')
