#!/usr/bin/env python3
"""
EyeAssist OSD Integrator
Multi-factor dry eye disease assessment engine that integrates clinical
measurements with TFOS DEWS II classification criteria via RAG.

This is an LLM-powered tool — it takes structured clinical data, queries
the RAG knowledge base for relevant guidelines, and uses the LLM to
synthesize a comprehensive OSD workup report.

Can be used as:
  1. Standalone CLI tool for testing
  2. Called by the orchestrator as a tool
  3. FastAPI endpoint (integrated into vision_service.py)

Usage:
    python3 osd_integrator.py --interactive
    python3 osd_integrator.py --json '{"tbut": 4, "schirmer": 12, "osdi_score": 38}'
    python3 osd_integrator.py --demo
"""

import argparse
import json
import os
import sys
import logging
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

import requests

# === Configuration ===

RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://localhost:8100")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:35b")


# === Data Model ===

@dataclass
class OSDWorkupData:
    """Structured input for OSD assessment."""
    # Tear film
    tbut: Optional[float] = None              # seconds
    tbut_method: Optional[str] = None         # "fluorescein" or "non-invasive"
    schirmer: Optional[float] = None          # mm (5 min)
    schirmer_type: Optional[str] = None       # "I" (with anesthesia) or "II" (without)
    tear_osmolarity: Optional[float] = None   # mOsm/L
    tear_osmolarity_interocular_diff: Optional[float] = None  # mOsm/L difference between eyes
    tear_meniscus_height: Optional[float] = None  # mm

    # Ocular surface
    corneal_staining_grade: Optional[int] = None      # Oxford 0-5 or NEI 0-15
    corneal_staining_scale: Optional[str] = None      # "oxford" or "nei"
    conjunctival_staining_grade: Optional[int] = None  # Oxford 0-5 or NEI 0-6
    conjunctival_staining_location: Optional[str] = None  # "nasal", "temporal", "both"
    lid_wiper_epitheliopathy: Optional[bool] = None

    # Meibomian glands
    meibum_quality: Optional[str] = None       # "clear", "cloudy", "granular", "inspissated", "none"
    meibum_expressibility: Optional[int] = None  # 0-3
    lid_margin_findings: Optional[str] = None   # free text
    meiboscore_upper: Optional[int] = None      # 0-3
    meiboscore_lower: Optional[int] = None      # 0-3
    mg_dropout_percentage: Optional[float] = None
    mg_gland_count: Optional[int] = None
    mg_avg_tortuosity: Optional[float] = None
    mg_avg_length: Optional[float] = None

    # Inflammation
    mmp9_positive: Optional[bool] = None
    tear_lactoferrin: Optional[float] = None   # mg/mL
    lid_margin_telangiectasia: Optional[bool] = None

    # Symptoms
    osdi_score: Optional[float] = None          # 0-100
    deq5_score: Optional[float] = None          # 0-22
    speed_score: Optional[float] = None         # 0-28
    symptom_description: Optional[str] = None   # free text

    # Patient context
    age: Optional[int] = None
    sex: Optional[str] = None                   # "M" or "F"
    contact_lens_wear: Optional[bool] = None
    screen_time_hours: Optional[float] = None
    medications: Optional[list[str]] = field(default_factory=list)
    systemic_conditions: Optional[list[str]] = field(default_factory=list)
    prior_ocular_surgery: Optional[list[str]] = field(default_factory=list)
    current_dry_eye_treatments: Optional[list[str]] = field(default_factory=list)
    environment: Optional[str] = None           # "dry/arid", "humid", "office/AC"

    # Eye
    eye: Optional[str] = None                   # "OD", "OS", "OU"
    visit_date: Optional[str] = None
    prior_visit_data: Optional[dict] = None     # For longitudinal comparison


# === Assessment Logic ===

class OSDAssessor:
    """Rule-based pre-analysis before LLM synthesis."""

    def __init__(self, data: OSDWorkupData):
        self.data = data
        self.findings = []
        self.missing = []
        self.evaporative_score = 0.0
        self.aqueous_score = 0.0
        self.inflammatory = False
        self.severity_score = 0.0

    def assess(self) -> dict:
        """Run the full multi-factor assessment."""
        self._assess_tear_film()
        self._assess_ocular_surface()
        self._assess_meibomian_glands()
        self._assess_inflammation()
        self._assess_symptoms()
        self._assess_risk_factors()
        self._classify()
        return self._build_result()

    def _assess_tear_film(self):
        d = self.data

        # TBUT
        if d.tbut is not None:
            method = f" ({d.tbut_method})" if d.tbut_method else ""
            if d.tbut < 5:
                self.findings.append(f"TBUT severely reduced at {d.tbut}s{method} (normal >10s, diagnostic cutoff <10s per TFOS DEWS II)")
                self.evaporative_score += 0.3
                self.severity_score += 0.25
            elif d.tbut < 10:
                self.findings.append(f"TBUT reduced at {d.tbut}s{method} (diagnostic cutoff <10s per TFOS DEWS II)")
                self.evaporative_score += 0.15
                self.severity_score += 0.1
            else:
                self.findings.append(f"TBUT normal at {d.tbut}s{method}")
        else:
            self.missing.append("TBUT (critical for DED diagnosis)")

        # Schirmer
        if d.schirmer is not None:
            stype = f" type {d.schirmer_type}" if d.schirmer_type else ""
            if d.schirmer < 5:
                self.findings.append(f"Schirmer{stype} severely reduced at {d.schirmer}mm (aqueous deficiency confirmed)")
                self.aqueous_score += 0.4
                self.severity_score += 0.25
            elif d.schirmer < 10:
                self.findings.append(f"Schirmer{stype} borderline at {d.schirmer}mm (possible aqueous deficiency)")
                self.aqueous_score += 0.15
                self.severity_score += 0.1
            else:
                self.findings.append(f"Schirmer{stype} adequate at {d.schirmer}mm")
        else:
            self.missing.append("Schirmer test")

        # Tear osmolarity
        if d.tear_osmolarity is not None:
            if d.tear_osmolarity >= 308:
                self.findings.append(f"Tear osmolarity elevated at {d.tear_osmolarity} mOsm/L (diagnostic cutoff ≥308 mOsm/L)")
                self.severity_score += 0.15
                if d.tear_osmolarity >= 316:
                    self.findings.append(f"Osmolarity ≥316 mOsm/L suggests moderate-severe disease")
                    self.severity_score += 0.1
            else:
                self.findings.append(f"Tear osmolarity normal at {d.tear_osmolarity} mOsm/L")

            if d.tear_osmolarity_interocular_diff and d.tear_osmolarity_interocular_diff > 8:
                self.findings.append(f"Interocular osmolarity difference {d.tear_osmolarity_interocular_diff} mOsm/L (>8 is significant)")
                self.severity_score += 0.05
        else:
            self.missing.append("Tear osmolarity")

        # Tear meniscus
        if d.tear_meniscus_height is not None:
            if d.tear_meniscus_height < 0.2:
                self.findings.append(f"Tear meniscus height reduced at {d.tear_meniscus_height}mm (normal ≥0.2mm)")
                self.aqueous_score += 0.1

    def _assess_ocular_surface(self):
        d = self.data

        # Corneal staining
        if d.corneal_staining_grade is not None:
            scale = f" ({d.corneal_staining_scale})" if d.corneal_staining_scale else ""
            if d.corneal_staining_scale == "nei":
                # NEI scale: 0-15
                if d.corneal_staining_grade >= 6:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/15{scale}: significant surface damage")
                    self.inflammatory = True
                    self.severity_score += 0.2
                elif d.corneal_staining_grade >= 3:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/15{scale}: mild-moderate surface involvement")
                    self.severity_score += 0.1
                else:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/15{scale}: minimal")
            else:
                # Oxford scale: 0-5
                if d.corneal_staining_grade >= 3:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/5{scale}: significant surface damage")
                    self.inflammatory = True
                    self.severity_score += 0.2
                elif d.corneal_staining_grade >= 1:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/5{scale}: mild surface involvement")
                    self.severity_score += 0.1
                else:
                    self.findings.append(f"Corneal staining grade {d.corneal_staining_grade}/5{scale}: clear")
        else:
            self.missing.append("Corneal staining")

        # Conjunctival staining
        if d.conjunctival_staining_grade is not None:
            loc = f" ({d.conjunctival_staining_location})" if d.conjunctival_staining_location else ""
            if d.conjunctival_staining_grade >= 2:
                self.findings.append(f"Conjunctival staining grade {d.conjunctival_staining_grade}{loc}: surface compromise")
                self.severity_score += 0.1
            elif d.conjunctival_staining_grade >= 1:
                self.findings.append(f"Conjunctival staining grade {d.conjunctival_staining_grade}{loc}: mild")

        # Lid wiper
        if d.lid_wiper_epitheliopathy:
            self.findings.append("Lid wiper epitheliopathy present (friction-related damage)")
            self.evaporative_score += 0.05
            self.severity_score += 0.05

    def _assess_meibomian_glands(self):
        d = self.data

        # Meibum quality
        if d.meibum_quality:
            quality_map = {
                "clear": (0, "Normal meibum quality: clear"),
                "cloudy": (0.1, "Meibum quality: cloudy (mild MGD)"),
                "granular": (0.2, "Meibum quality: granular (moderate MGD)"),
                "inspissated": (0.3, "Meibum quality: inspissated/toothpaste-like (significant MGD)"),
                "none": (0.35, "No meibum expressible (severe MGD / gland obstruction)"),
            }
            score, finding = quality_map.get(d.meibum_quality.lower(), (0, f"Meibum quality: {d.meibum_quality}"))
            self.evaporative_score += score
            self.findings.append(finding)
            if score >= 0.2:
                self.severity_score += 0.15

        # Expressibility
        if d.meibum_expressibility is not None:
            if d.meibum_expressibility >= 2:
                self.findings.append(f"Meibum expressibility grade {d.meibum_expressibility}/3: reduced")
                self.evaporative_score += 0.15
                self.severity_score += 0.1
            elif d.meibum_expressibility == 1:
                self.findings.append(f"Meibum expressibility grade 1/3: mildly reduced")
                self.evaporative_score += 0.05

        # Meiboscores
        if d.meiboscore_upper is not None or d.meiboscore_lower is not None:
            upper = d.meiboscore_upper if d.meiboscore_upper is not None else "N/A"
            lower = d.meiboscore_lower if d.meiboscore_lower is not None else "N/A"
            max_score = max(d.meiboscore_upper or 0, d.meiboscore_lower or 0)

            self.findings.append(f"Meiboscore: upper {upper}/3, lower {lower}/3")

            if max_score >= 3:
                self.findings.append("Grade 3 dropout (>66% gland loss): severe structural MGD")
                self.evaporative_score += 0.3
                self.severity_score += 0.2
            elif max_score >= 2:
                self.findings.append("Grade 2 dropout (33-66% gland loss): moderate structural MGD")
                self.evaporative_score += 0.2
                self.severity_score += 0.15
            elif max_score >= 1:
                self.findings.append("Grade 1 dropout (<33% gland loss): mild structural MGD")
                self.evaporative_score += 0.1
                self.severity_score += 0.05

        # Detailed MG metrics (from AI model)
        if d.mg_dropout_percentage is not None:
            self.findings.append(f"MG dropout: {d.mg_dropout_percentage:.1f}%")
        if d.mg_gland_count is not None:
            self.findings.append(f"MG gland count: {d.mg_gland_count}")
        if d.mg_avg_tortuosity is not None:
            if d.mg_avg_tortuosity > 1.3:
                self.findings.append(f"MG tortuosity elevated at {d.mg_avg_tortuosity:.2f} (suggests gland distortion)")
        if d.mg_avg_length is not None:
            if d.mg_avg_length < 3.0:
                self.findings.append(f"MG average length reduced at {d.mg_avg_length:.1f}mm (gland shortening)")
                self.evaporative_score += 0.05

        # Lid margin
        if d.lid_margin_findings:
            self.findings.append(f"Lid margin: {d.lid_margin_findings}")
            lid_lower = d.lid_margin_findings.lower()
            if any(t in lid_lower for t in ["telangiectasia", "redness", "irregular", "notching", "keratinization", "plugging"]):
                self.evaporative_score += 0.1
                if "telangiectasia" in lid_lower:
                    self.inflammatory = True
                    self.findings.append("Lid margin telangiectasia: consider rosacea component")

        if d.lid_margin_telangiectasia:
            if "telangiectasia" not in (d.lid_margin_findings or "").lower():
                self.findings.append("Lid margin telangiectasia present: inflammatory/rosacea component")
                self.inflammatory = True
                self.evaporative_score += 0.1

    def _assess_inflammation(self):
        d = self.data

        if d.mmp9_positive is not None:
            if d.mmp9_positive:
                self.findings.append("MMP-9 positive: active ocular surface inflammation")
                self.inflammatory = True
                self.severity_score += 0.15
            else:
                self.findings.append("MMP-9 negative")
        else:
            self.missing.append("MMP-9")

        if d.tear_lactoferrin is not None:
            if d.tear_lactoferrin < 1.1:
                self.findings.append(f"Tear lactoferrin reduced at {d.tear_lactoferrin} mg/mL (suggests aqueous deficiency)")
                self.aqueous_score += 0.1

    def _assess_symptoms(self):
        d = self.data

        if d.osdi_score is not None:
            if d.osdi_score >= 33:
                self.findings.append(f"OSDI score {d.osdi_score}: severe symptoms")
                self.severity_score += 0.2
            elif d.osdi_score >= 23:
                self.findings.append(f"OSDI score {d.osdi_score}: moderate symptoms")
                self.severity_score += 0.15
            elif d.osdi_score >= 13:
                self.findings.append(f"OSDI score {d.osdi_score}: mild symptoms")
                self.severity_score += 0.05
            else:
                self.findings.append(f"OSDI score {d.osdi_score}: minimal symptoms")
        else:
            self.missing.append("OSDI score")

        if d.deq5_score is not None:
            if d.deq5_score >= 6:
                self.findings.append(f"DEQ-5 score {d.deq5_score}: dry eye likely (cutoff ≥6)")
            else:
                self.findings.append(f"DEQ-5 score {d.deq5_score}: below diagnostic threshold")

        if d.speed_score is not None:
            self.findings.append(f"SPEED score {d.speed_score}/28")

        if d.symptom_description:
            self.findings.append(f"Patient symptoms: {d.symptom_description}")

    def _assess_risk_factors(self):
        d = self.data
        risk_factors = []

        if d.age and d.age > 50:
            risk_factors.append(f"Age {d.age} (increased DED risk)")
        if d.sex and d.sex.upper() == "F":
            risk_factors.append("Female sex (higher DED prevalence)")
        if d.contact_lens_wear:
            risk_factors.append("Contact lens wear")
            self.evaporative_score += 0.05
        if d.screen_time_hours and d.screen_time_hours > 6:
            risk_factors.append(f"Extended screen time ({d.screen_time_hours}h/day)")
            self.evaporative_score += 0.05
        if d.environment:
            risk_factors.append(f"Environment: {d.environment}")

        # Medications that cause or worsen dry eye
        drying_meds = ["antihistamine", "antidepressant", "beta blocker", "diuretic",
                       "isotretinoin", "anticholinergic", "oral contraceptive"]
        if d.medications:
            for med in d.medications:
                if any(dm in med.lower() for dm in drying_meds):
                    risk_factors.append(f"Drying medication: {med}")
                    self.aqueous_score += 0.05

        # Systemic conditions
        autoimmune = ["sjogren", "rheumatoid", "lupus", "scleroderma", "thyroid",
                      "rosacea", "gvhd", "stevens-johnson"]
        if d.systemic_conditions:
            for condition in d.systemic_conditions:
                if any(ai in condition.lower() for ai in autoimmune):
                    risk_factors.append(f"Associated systemic condition: {condition}")
                    if "sjogren" in condition.lower():
                        self.aqueous_score += 0.2
                    if "rosacea" in condition.lower():
                        self.evaporative_score += 0.15
                        self.inflammatory = True

        if d.prior_ocular_surgery:
            for surgery in d.prior_ocular_surgery:
                risk_factors.append(f"Prior surgery: {surgery}")
                if any(s in surgery.lower() for s in ["lasik", "prk", "cataract"]):
                    self.aqueous_score += 0.05

        if risk_factors:
            self.findings.append("Risk factors: " + "; ".join(risk_factors))

    def _classify(self):
        """TFOS DEWS II-based classification."""
        self.evaporative_score = min(self.evaporative_score, 1.0)
        self.aqueous_score = min(self.aqueous_score, 1.0)
        self.severity_score = min(self.severity_score, 1.0)

        # Subtype
        if self.evaporative_score > 0.4 and self.aqueous_score > 0.3:
            self.ded_subtype = "Mixed mechanism (evaporative-predominant with aqueous component)"
        elif self.evaporative_score > 0.3 and self.aqueous_score > 0.3:
            self.ded_subtype = "Mixed mechanism (both evaporative and aqueous deficiency)"
        elif self.evaporative_score > 0.3:
            self.ded_subtype = "Evaporative dry eye (likely MGD-related)"
        elif self.aqueous_score > 0.3:
            self.ded_subtype = "Aqueous deficient dry eye"
        elif self.evaporative_score > 0.15 or self.aqueous_score > 0.15:
            self.ded_subtype = "Mild/early DED — subtype trending " + (
                "evaporative" if self.evaporative_score > self.aqueous_score else "aqueous deficient")
        else:
            self.ded_subtype = "Subclinical / borderline — insufficient objective evidence for DED classification"

        # Severity (TFOS DEWS II severity grading)
        if self.severity_score >= 0.55:
            self.severity_grade = "Severe (TFOS DEWS II Level 3-4)"
        elif self.severity_score >= 0.35:
            self.severity_grade = "Moderate (TFOS DEWS II Level 2-3)"
        elif self.severity_score >= 0.15:
            self.severity_grade = "Mild (TFOS DEWS II Level 1-2)"
        else:
            self.severity_grade = "Minimal / subclinical"

    def _build_result(self) -> dict:
        return {
            "ded_subtype": self.ded_subtype,
            "severity_grade": self.severity_grade,
            "severity_score": round(self.severity_score, 3),
            "evaporative_score": round(self.evaporative_score, 3),
            "aqueous_deficiency_score": round(self.aqueous_score, 3),
            "inflammatory_component": self.inflammatory,
            "findings": self.findings,
            "missing_data": self.missing,
            "data_completeness": f"{len(self.findings)}/{len(self.findings) + len(self.missing)} parameters assessed",
        }


# === RAG Integration ===

def get_rag_context(query: str) -> str:
    """Query the RAG service for relevant OSD guidelines."""
    try:
        resp = requests.post(
            f"{RAG_SERVICE_URL}/inject",
            json={"message": query, "collections": ["osd"], "n_results": 5},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("augmented_message", "")
    except Exception as e:
        logging.warning(f"RAG query failed: {e}")
    return ""


def build_rag_query(data: OSDWorkupData, assessment: dict) -> str:
    """Build a targeted RAG query based on the assessment findings."""
    parts = []

    subtype = assessment["ded_subtype"]
    if "evaporative" in subtype.lower():
        parts.append("TFOS DEWS II evaporative dry eye meibomian gland dysfunction management")
    if "aqueous" in subtype.lower():
        parts.append("TFOS DEWS II aqueous deficient dry eye Sjogren lacrimal")
    if assessment["inflammatory_component"]:
        parts.append("ocular surface inflammation MMP-9 anti-inflammatory treatment")
    if data.meiboscore_upper and data.meiboscore_upper >= 2:
        parts.append("meibomian gland dropout grading treatment")
    if data.osdi_score and data.osdi_score >= 33:
        parts.append("severe dry eye disease management stepped approach")

    if not parts:
        parts.append("TFOS DEWS II dry eye classification diagnosis")

    return " ".join(parts)


# === LLM Synthesis ===

OSD_SYNTHESIS_PROMPT = """You are EyeAssist, an ophthalmology clinical decision support assistant. You are generating a comprehensive Ocular Surface Disease (OSD) workup report.

You have been provided with:
1. A rule-based pre-assessment of the clinical data
2. Retrieved clinical guidelines from the TFOS DEWS II reports and other OSD references

Generate a structured OSD workup report following this exact format:

## 1. Meibomian Gland Findings
[Summarize MG-related findings from the assessment. If no MG data, note this.]

## 2. Tear Film Assessment
[TBUT, Schirmer, osmolarity findings and their clinical significance]

## 3. Ocular Surface Assessment
[Staining, lid margin, lid wiper findings]

## 4. Symptom Correlation
[OSDI/DEQ-5/SPEED scores and how they correlate with objective findings]

## 5. DED Classification (TFOS DEWS II)
- **Subtype**: [evaporative / aqueous deficient / mixed / borderline]
- **Severity**: [mild / moderate / severe]
- **Inflammatory component**: [yes/no and basis]
- **Classification basis**: [which specific findings drove this classification]

## 6. Clinical Correlation and Considerations
[Risk factors, medication effects, systemic associations. What additional data would strengthen the assessment. Note any symptom-sign discordance. Consider rosacea screening if telangiectasia present.]

## 7. Missing Data
[List what tests were not available and how they would impact the assessment]

## Confidence Note
[State confidence level and caveats]

Rules:
- Ground your response in the retrieved TFOS DEWS II references where applicable
- Be specific about which findings support the classification
- Note any discordance between symptoms and signs
- Never recommend specific treatments — present considerations only
- Flag if data is insufficient for confident classification"""


def synthesize_with_llm(data: OSDWorkupData, assessment: dict, rag_context: str) -> str:
    """Use the LLM to synthesize the final OSD workup report."""
    data_summary = json.dumps(asdict(data), indent=2, default=str)
    assessment_summary = json.dumps(assessment, indent=2)

    prompt = f"""Clinical data provided:
{data_summary}

Pre-assessment results:
{assessment_summary}

{rag_context}

Generate the OSD workup report following the specified format."""

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": OSD_SYNTHESIS_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 3000},
            },
            timeout=900,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "[LLM synthesis failed]")
    except Exception as e:
        logging.error(f"LLM synthesis failed: {e}")
        return f"[LLM synthesis unavailable: {e}]\n\nRule-based assessment:\n{assessment_summary}"


# === Main Pipeline ===

def run_osd_workup(data: OSDWorkupData, use_llm: bool = True, use_rag: bool = True) -> dict:
    """Run the complete OSD workup pipeline."""
    logging.info("Starting OSD workup assessment...")

    # Step 1: Rule-based assessment
    assessor = OSDAssessor(data)
    assessment = assessor.assess()
    logging.info(f"Assessment complete: {assessment['ded_subtype']}, {assessment['severity_grade']}")

    # Step 2: RAG context retrieval
    rag_context = ""
    if use_rag:
        rag_query = build_rag_query(data, assessment)
        logging.info(f"RAG query: {rag_query}")
        rag_context = get_rag_context(rag_query)
        logging.info(f"RAG context retrieved: {len(rag_context)} chars")

    # Step 3: LLM synthesis
    report = ""
    if use_llm:
        logging.info("Synthesizing report with LLM...")
        report = synthesize_with_llm(data, assessment, rag_context)
        logging.info("Report synthesized.")
    else:
        report = json.dumps(assessment, indent=2)

    return {
        "assessment": assessment,
        "report": report,
        "rag_query": rag_query if use_rag else None,
        "timestamp": datetime.now().isoformat(),
    }


# === CLI ===

def interactive_mode():
    """Interactive CLI for entering OSD workup data."""
    print("\n" + "="*60)
    print("  EyeAssist OSD Workup — Interactive Mode")
    print("  Enter values or press Enter to skip")
    print("="*60 + "\n")

    def ask_float(prompt, default=None):
        val = input(f"  {prompt}: ").strip()
        if val:
            try:
                return float(val)
            except ValueError:
                return default
        return default

    def ask_int(prompt, default=None):
        val = input(f"  {prompt}: ").strip()
        if val:
            try:
                return int(val)
            except ValueError:
                return default
        return default

    def ask_str(prompt, default=None):
        val = input(f"  {prompt}: ").strip()
        return val if val else default

    def ask_bool(prompt, default=None):
        val = input(f"  {prompt} (y/n): ").strip().lower()
        if val in ("y", "yes"):
            return True
        elif val in ("n", "no"):
            return False
        return default

    print("--- Tear Film ---")
    tbut = ask_float("TBUT (seconds)")
    schirmer = ask_float("Schirmer (mm)")
    osmolarity = ask_float("Tear osmolarity (mOsm/L)")

    print("\n--- Ocular Surface ---")
    corneal_staining = ask_int("Corneal staining grade (Oxford 0-5)")
    conjunctival_staining = ask_int("Conjunctival staining grade")

    print("\n--- Meibomian Glands ---")
    meibum = ask_str("Meibum quality (clear/cloudy/granular/inspissated/none)")
    expressibility = ask_int("Meibum expressibility (0-3)")
    meiboscore_u = ask_int("Meiboscore upper lid (0-3)")
    meiboscore_l = ask_int("Meiboscore lower lid (0-3)")
    lid_margin = ask_str("Lid margin findings")

    print("\n--- Inflammation ---")
    mmp9 = ask_bool("MMP-9 positive?")

    print("\n--- Symptoms ---")
    osdi = ask_float("OSDI score (0-100)")
    symptoms = ask_str("Symptom description")

    print("\n--- Patient Context ---")
    age = ask_int("Age")
    sex = ask_str("Sex (M/F)")

    data = OSDWorkupData(
        tbut=tbut, schirmer=schirmer, tear_osmolarity=osmolarity,
        corneal_staining_grade=corneal_staining, corneal_staining_scale="oxford",
        conjunctival_staining_grade=conjunctival_staining,
        meibum_quality=meibum, meibum_expressibility=expressibility,
        meiboscore_upper=meiboscore_u, meiboscore_lower=meiboscore_l,
        lid_margin_findings=lid_margin,
        mmp9_positive=mmp9, osdi_score=osdi, symptom_description=symptoms,
        age=age, sex=sex,
    )

    print("\n" + "="*60)
    print("  Running OSD Assessment...")
    print("="*60)

    # Run without LLM first (instant), then offer LLM synthesis
    result = run_osd_workup(data, use_llm=False, use_rag=False)
    assessment = result["assessment"]

    print(f"\n  Subtype: {assessment['ded_subtype']}")
    print(f"  Severity: {assessment['severity_grade']}")
    print(f"  Evaporative score: {assessment['evaporative_score']}")
    print(f"  Aqueous score: {assessment['aqueous_deficiency_score']}")
    print(f"  Inflammatory: {assessment['inflammatory_component']}")
    print(f"\n  Findings ({len(assessment['findings'])}):")
    for f in assessment["findings"]:
        print(f"    • {f}")
    if assessment["missing_data"]:
        print(f"\n  Missing data ({len(assessment['missing_data'])}):")
        for m in assessment["missing_data"]:
            print(f"    ○ {m}")

    # Offer LLM synthesis
    do_llm = input("\n  Generate full LLM-synthesized report? (y/n): ").strip().lower()
    if do_llm in ("y", "yes"):
        print("\n  Synthesizing with LLM (this may take a few minutes on CPU)...")
        full_result = run_osd_workup(data, use_llm=True, use_rag=True)
        print("\n" + "="*60)
        print("  OSD WORKUP REPORT")
        print("="*60)
        print(full_result["report"])


def demo_mode():
    """Run with a demo patient case."""
    print("\n  Running demo case: 62F with moderate-severe evaporative DED...\n")

    demo = OSDWorkupData(
        tbut=4.0, tbut_method="fluorescein",
        schirmer=12.0, schirmer_type="I",
        tear_osmolarity=312.0, tear_osmolarity_interocular_diff=12.0,
        corneal_staining_grade=2, corneal_staining_scale="oxford",
        conjunctival_staining_grade=1, conjunctival_staining_location="nasal",
        lid_wiper_epitheliopathy=True,
        meibum_quality="granular", meibum_expressibility=2,
        meiboscore_upper=3, meiboscore_lower=2,
        mg_dropout_percentage=55.0, mg_gland_count=14,
        mg_avg_tortuosity=1.35, mg_avg_length=2.8,
        lid_margin_findings="Telangiectasia bilateral, mild notching, orifice plugging",
        lid_margin_telangiectasia=True,
        mmp9_positive=True,
        osdi_score=38.0, deq5_score=12.0,
        symptom_description="Burning, foreign body sensation, blurry vision worse in afternoon, difficulty with screen use",
        age=62, sex="F",
        contact_lens_wear=False, screen_time_hours=7.0,
        medications=["Lisinopril", "Atorvastatin"],
        systemic_conditions=["Rosacea (cutaneous)", "Hypertension"],
        current_dry_eye_treatments=["Artificial tears PRN", "Warm compresses"],
        environment="Office with AC, dry climate (Wyoming)",
        eye="OU",
    )

    result = run_osd_workup(demo, use_llm=False, use_rag=False)
    assessment = result["assessment"]

    print(json.dumps(assessment, indent=2))


def main():
    parser = argparse.ArgumentParser(description="EyeAssist OSD Integrator")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive input mode")
    parser.add_argument("--json", "-j", help="JSON string with OSD workup data")
    parser.add_argument("--demo", "-d", action="store_true", help="Run demo case")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM synthesis (rule-based only)")
    parser.add_argument("--no-rag", action="store_true", help="Skip RAG retrieval")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.interactive:
        interactive_mode()
        return

    if args.demo:
        demo_mode()
        return

    if args.json:
        raw = json.loads(args.json)
        data = OSDWorkupData(**raw)
        result = run_osd_workup(data, use_llm=not args.no_llm, use_rag=not args.no_rag)
        print(json.dumps(result, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
