#!/usr/bin/env python3
"""
EyeAssist Vision Pipeline API
FastAPI service providing endpoints for all posterior and anterior segment models.
Currently returns mock responses; swap in real model inference when GPU is available.

Usage:
    python3 vision_service.py
    # Or: uvicorn vision_service:app --host 0.0.0.0 --port 8200

Endpoints:
    POST /analyze/posterior/retfound          - General retinal screening
    POST /analyze/posterior/dr-grading        - Diabetic retinopathy grading
    POST /analyze/posterior/glaucoma          - Glaucoma detection + progression
    POST /analyze/posterior/fairseg           - Optic disc/cup segmentation (CDR)
    POST /analyze/posterior/vessel            - Vessel segmentation
    POST /analyze/posterior/vf-predict        - Visual field 10-2 prediction from 24-2

    POST /analyze/anterior/meibography       - Meibomian gland analysis
    POST /analyze/anterior/corneal-disease    - Corneal disease classification
    POST /analyze/anterior/keratoconus        - Keratoconus screening from topography
    POST /analyze/anterior/osd-workup         - Multi-factor DED assessment

    GET  /models                              - List all models and status
    GET  /health                              - Health check
"""

import os
import json
import re
import fitz  # PyMuPDF
import time
import uuid
import logging
import base64
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# === Configuration ===

SERVICE_PORT = 8200
USE_GPU = False  # Set True when running on native Ubuntu with GPUs
LOG_DIR = os.path.expanduser("~/eyeassist/logs")
os.makedirs(LOG_DIR, exist_ok=True)

# === Enums ===

class Modality(str, Enum):
    CFP = "cfp"                         # Color fundus photography
    OCT = "oct"                         # OCT B-scan
    OCT_RNFLT = "oct_rnflt"             # OCT RNFL thickness map
    MEIBOGRAPHY = "meibography_ir"       # Infrared meibography
    SLIT_LAMP = "slit_lamp"             # Slit-lamp photograph
    PENTACAM = "pentacam_topography"     # Pentacam export data
    VISUAL_FIELD = "visual_field"        # Visual field data
    EXTERNAL_PHOTO = "external_photo"    # External face/eye photo

class ModelStatus(str, Enum):
    MOCK = "mock"       # Returning mock responses
    LOADED = "loaded"   # Model loaded on GPU, real inference
    ERROR = "error"     # Model failed to load


# === Response Models ===

class AnalysisMetadata(BaseModel):
    model_name: str
    model_version: str
    inference_mode: str = "mock"  # "mock" or "gpu"
    processing_time_ms: float
    timestamp: str
    analysis_id: str

class RetFoundResult(BaseModel):
    metadata: AnalysisMetadata
    disease_probabilities: dict[str, float]
    top_finding: str
    confidence: float
    feature_vector_available: bool = False

class DRGradingResult(BaseModel):
    metadata: AnalysisMetadata
    icdr_grade: int
    icdr_label: str
    grade_probabilities: dict[str, float]
    csme_probability: float
    referral_recommended: bool

class GlaucomaResult(BaseModel):
    metadata: AnalysisMetadata
    glaucoma_probability: float
    progression_risk: dict[str, float]
    md_value: Optional[float] = None
    classification: str

class FairSegResult(BaseModel):
    metadata: AnalysisMetadata
    disc_area_pixels: int
    cup_area_pixels: int
    cdr_vertical: float
    cdr_horizontal: float
    cdr_area: float
    segmentation_mask_b64: Optional[str] = None

class VesselResult(BaseModel):
    metadata: AnalysisMetadata
    artery_vein_ratio: float
    vessel_density: float
    tortuosity_index: float
    segmentation_mask_b64: Optional[str] = None

class VFPredictionResult(BaseModel):
    metadata: AnalysisMetadata
    predicted_10_2_values: list[float]
    prediction_confidence: float

class MeibographyResult(BaseModel):
    metadata: AnalysisMetadata
    meiboscore: int
    meiboscore_label: str
    gland_count: int
    dropout_percentage: float
    avg_gland_length: float
    avg_gland_width: float
    avg_tortuosity: float
    total_gland_area_ratio: float
    segmentation_mask_b64: Optional[str] = None

class CornealDiseaseResult(BaseModel):
    metadata: AnalysisMetadata
    is_infectious: bool
    infectious_probability: float
    bacterial_probability: float
    fungal_probability: float
    fungal_subtype: Optional[str] = None
    top_diagnosis: str
    confidence: float

class KeratoconusResult(BaseModel):
    metadata: AnalysisMetadata
    kc_probability: float
    classification: str
    stage: Optional[str] = None
    key_features: dict[str, float]

class OSDWorkupInput(BaseModel):
    tbut: Optional[float] = Field(None, description="Tear break-up time in seconds")
    schirmer: Optional[float] = Field(None, description="Schirmer test result in mm")
    osdi_score: Optional[float] = Field(None, description="OSDI questionnaire score (0-100)")
    corneal_staining_grade: Optional[int] = Field(None, description="Oxford/NEI staining grade (0-5)")
    conjunctival_staining_grade: Optional[int] = Field(None, description="Conjunctival staining grade (0-5)")
    lid_margin_findings: Optional[str] = Field(None, description="Lid margin observations")
    meibum_quality: Optional[str] = Field(None, description="Meibum quality (clear/cloudy/granular/inspissated)")
    meibum_expressibility: Optional[int] = Field(None, description="Expressibility grade (0-3)")
    tear_osmolarity: Optional[float] = Field(None, description="Tear osmolarity in mOsm/L")
    mmp9_positive: Optional[bool] = Field(None, description="MMP-9 inflammatory marker result")
    meibography_result: Optional[dict] = Field(None, description="Output from meibography analysis model")

class OSDWorkupResult(BaseModel):
    metadata: AnalysisMetadata
    ded_subtype: str
    severity_grade: str
    severity_score: float
    aqueous_deficiency_score: float
    evaporative_score: float
    inflammatory_component: bool
    findings_summary: list[str]
    missing_data: list[str]
    classification_basis: str


# === Model Registry ===

MODEL_REGISTRY = {
    # Posterior
    "retfound":         {"name": "RETFound", "version": "1.0-MAE", "status": ModelStatus.MOCK, "track": "posterior"},
    "dr_grading":       {"name": "DR Grading", "version": "1.0", "status": ModelStatus.MOCK, "track": "posterior"},
    "glaucoma":         {"name": "Harvard-GDP Glaucoma", "version": "1.0-ICCV2023", "status": ModelStatus.MOCK, "track": "posterior"},
    "fairseg":          {"name": "FairSeg", "version": "1.0-ICLR2024", "status": ModelStatus.MOCK, "track": "posterior"},
    "vessel":           {"name": "Vessel Segmentation", "version": "1.0", "status": ModelStatus.MOCK, "track": "posterior"},
    "vf_predict":       {"name": "VFTransformer", "version": "1.0-TVST2024", "status": ModelStatus.MOCK, "track": "posterior"},
    # Anterior
    "meibography":      {"name": "MG Segmentation", "version": "1.0-CAMG", "status": ModelStatus.MOCK, "track": "anterior"},
    "corneal_disease":  {"name": "Corneal Disease", "version": "1.0", "status": ModelStatus.MOCK, "track": "anterior"},
    "keratoconus":      {"name": "Keratoconus Screening", "version": "1.0", "status": ModelStatus.MOCK, "track": "anterior"},
    "osd_workup":       {"name": "OSD Integrator", "version": "1.0", "status": ModelStatus.MOCK, "track": "anterior"},
    # Diagnostic studies (PDF-based reports)
    "erg":              {"name": "ERG Extraction (RETeval)", "version": "1.0", "status": ModelStatus.MOCK, "track": "diagnostic"},
}


def make_metadata(model_key: str, start_time: float) -> AnalysisMetadata:
    reg = MODEL_REGISTRY[model_key]
    return AnalysisMetadata(
        model_name=reg["name"],
        model_version=reg["version"],
        inference_mode="mock" if reg["status"] == ModelStatus.MOCK else "gpu",
        processing_time_ms=round((time.time() - start_time) * 1000, 2),
        timestamp=datetime.now().isoformat(),
        analysis_id=str(uuid.uuid4())[:8],
    )


def log_analysis(model_key: str, analysis_id: str, result: dict):
    """Log every analysis for audit trail."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "model": model_key,
        "analysis_id": analysis_id,
        "mode": MODEL_REGISTRY[model_key]["status"],
    }
    logging.info(f"ANALYSIS: {log_entry}")


# === App Setup ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("EyeAssist Vision Pipeline starting...")
    logging.info(f"GPU mode: {USE_GPU}")
    for key, info in MODEL_REGISTRY.items():
        logging.info(f"  {info['name']}: {info['status']}")
    yield
    logging.info("Vision Pipeline shutting down.")


app = FastAPI(
    title="EyeAssist Vision Pipeline",
    description="Posterior and anterior segment ophthalmic image analysis",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Health & Info Endpoints ===

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "gpu_mode": USE_GPU,
        "models": {k: v["status"] for k, v in MODEL_REGISTRY.items()},
    }

@app.get("/models")
async def list_models():
    return {
        "posterior": {k: v for k, v in MODEL_REGISTRY.items() if v["track"] == "posterior"},
        "anterior": {k: v for k, v in MODEL_REGISTRY.items() if v["track"] == "anterior"},
    }


# ================================================================
# POSTERIOR SEGMENT ENDPOINTS
# ================================================================

@app.post("/analyze/posterior/retfound", response_model=RetFoundResult)
async def analyze_retfound(
    image: UploadFile = File(...),
    modality: Modality = Form(Modality.CFP),
):
    """General retinal disease screening with RETFound."""
    start = time.time()
    contents = await image.read()

    # TODO: Replace mock with real inference when GPU available
    # real_result = retfound_model.predict(preprocess(contents, modality))

    result = RetFoundResult(
        metadata=make_metadata("retfound", start),
        disease_probabilities={
            "normal": 0.62,
            "diabetic_retinopathy": 0.18,
            "amd": 0.08,
            "glaucoma_suspect": 0.07,
            "other": 0.05,
        },
        top_finding="No significant pathology detected",
        confidence=0.62,
        feature_vector_available=False,
    )
    log_analysis("retfound", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/posterior/dr-grading", response_model=DRGradingResult)
async def analyze_dr(
    image: UploadFile = File(...),
):
    """Diabetic retinopathy severity grading (ICDR scale)."""
    start = time.time()
    contents = await image.read()

    result = DRGradingResult(
        metadata=make_metadata("dr_grading", start),
        icdr_grade=2,
        icdr_label="Moderate NPDR",
        grade_probabilities={
            "0_no_dr": 0.05,
            "1_mild_npdr": 0.15,
            "2_moderate_npdr": 0.52,
            "3_severe_npdr": 0.20,
            "4_pdr": 0.08,
        },
        csme_probability=0.35,
        referral_recommended=True,
    )
    log_analysis("dr_grading", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/posterior/glaucoma", response_model=GlaucomaResult)
async def analyze_glaucoma(
    image: UploadFile = File(...),
    modality: Modality = Form(Modality.OCT_RNFLT),
):
    """Glaucoma detection and progression risk from OCT RNFLT."""
    start = time.time()
    contents = await image.read()

    result = GlaucomaResult(
        metadata=make_metadata("glaucoma", start),
        glaucoma_probability=0.73,
        progression_risk={
            "md_based": 0.45,
            "vfi_based": 0.38,
            "td_pointwise": 0.52,
        },
        md_value=-4.2,
        classification="Glaucoma suspect - moderate risk",
    )
    log_analysis("glaucoma", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/posterior/fairseg", response_model=FairSegResult)
async def analyze_fairseg(
    image: UploadFile = File(...),
):
    """Optic disc/cup segmentation and CDR calculation."""
    start = time.time()
    contents = await image.read()

    result = FairSegResult(
        metadata=make_metadata("fairseg", start),
        disc_area_pixels=45200,
        cup_area_pixels=18080,
        cdr_vertical=0.65,
        cdr_horizontal=0.58,
        cdr_area=0.40,
        segmentation_mask_b64=None,
    )
    log_analysis("fairseg", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/posterior/vessel", response_model=VesselResult)
async def analyze_vessel(
    image: UploadFile = File(...),
):
    """Retinal vessel segmentation and metrics."""
    start = time.time()
    contents = await image.read()

    result = VesselResult(
        metadata=make_metadata("vessel", start),
        artery_vein_ratio=0.67,
        vessel_density=0.34,
        tortuosity_index=1.12,
        segmentation_mask_b64=None,
    )
    log_analysis("vessel", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/posterior/vf-predict", response_model=VFPredictionResult)
async def predict_visual_field(
    td_values_24_2: list[float] = Form(...),
):
    """Predict 10-2 visual field from 24-2 total deviation values."""
    start = time.time()

    if len(td_values_24_2) != 52:
        raise HTTPException(status_code=400, detail="Expected 52 total deviation values for 24-2 VF")

    # Mock: generate plausible 10-2 values based on central 24-2 values
    mock_10_2 = [v * 0.95 + 0.5 for v in td_values_24_2[:68]]  # 10-2 has 68 points
    mock_10_2 = mock_10_2[:68] if len(mock_10_2) >= 68 else mock_10_2 + [0.0] * (68 - len(mock_10_2))

    result = VFPredictionResult(
        metadata=make_metadata("vf_predict", start),
        predicted_10_2_values=mock_10_2,
        prediction_confidence=0.78,
    )
    log_analysis("vf_predict", result.metadata.analysis_id, result.dict())
    return result


# ================================================================
# ANTERIOR SEGMENT ENDPOINTS
# ================================================================

@app.post("/analyze/anterior/meibography", response_model=MeibographyResult)
async def analyze_meibography(
    image: UploadFile = File(...),
    eyelid: str = Form("upper"),  # "upper" or "lower"
):
    """Meibomian gland segmentation and morphology analysis from IR meibography."""
    start = time.time()
    contents = await image.read()

    result = MeibographyResult(
        metadata=make_metadata("meibography", start),
        meiboscore=2,
        meiboscore_label="Grade 2 - Partial dropout (33-66% area loss)",
        gland_count=18,
        dropout_percentage=42.5,
        avg_gland_length=3.8,
        avg_gland_width=0.45,
        avg_tortuosity=1.15,
        total_gland_area_ratio=0.575,
        segmentation_mask_b64=None,
    )
    log_analysis("meibography", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/anterior/corneal-disease", response_model=CornealDiseaseResult)
async def analyze_corneal_disease(
    image: UploadFile = File(...),
):
    """Corneal disease classification from slit-lamp photographs."""
    start = time.time()
    contents = await image.read()

    result = CornealDiseaseResult(
        metadata=make_metadata("corneal_disease", start),
        is_infectious=True,
        infectious_probability=0.87,
        bacterial_probability=0.62,
        fungal_probability=0.38,
        fungal_subtype=None,
        top_diagnosis="Bacterial keratitis",
        confidence=0.62,
    )
    log_analysis("corneal_disease", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/anterior/keratoconus", response_model=KeratoconusResult)
async def analyze_keratoconus(
    k1: float = Form(..., description="Flat keratometry (D)"),
    k2: float = Form(..., description="Steep keratometry (D)"),
    kmax: float = Form(..., description="Maximum keratometry (D)"),
    pachymetry_min: float = Form(..., description="Thinnest pachymetry (µm)"),
    anterior_elevation: float = Form(..., description="Max anterior elevation (µm)"),
    posterior_elevation: float = Form(..., description="Max posterior elevation (µm)"),
    is_asymmetry: float = Form(0.0, description="Inferior-superior asymmetry (D)"),
):
    """Keratoconus screening from Pentacam corneal topography parameters."""
    start = time.time()

    # Mock classification logic based on published thresholds
    kc_score = 0.0
    features = {
        "k1": k1, "k2": k2, "kmax": kmax,
        "pachymetry_min": pachymetry_min,
        "anterior_elevation": anterior_elevation,
        "posterior_elevation": posterior_elevation,
        "is_asymmetry": is_asymmetry,
    }

    if kmax > 47.2:
        kc_score += 0.25
    if pachymetry_min < 470:
        kc_score += 0.30
    if posterior_elevation > 30:
        kc_score += 0.25
    if is_asymmetry > 1.4:
        kc_score += 0.20

    if kc_score >= 0.7:
        classification = "Keratoconus"
        stage = "Stage II (Moderate)" if kmax < 52 else "Stage III (Advanced)"
    elif kc_score >= 0.3:
        classification = "Keratoconus suspect"
        stage = "Subclinical"
    else:
        classification = "Normal"
        stage = None

    result = KeratoconusResult(
        metadata=make_metadata("keratoconus", start),
        kc_probability=min(kc_score, 1.0),
        classification=classification,
        stage=stage,
        key_features=features,
    )
    log_analysis("keratoconus", result.metadata.analysis_id, result.dict())
    return result


@app.post("/analyze/anterior/osd-workup", response_model=OSDWorkupResult)
async def analyze_osd_workup(
    workup: OSDWorkupInput,
):
    """
    Multi-factor dry eye disease assessment.
    Integrates clinical measurements with TFOS DEWS II classification criteria.
    """
    start = time.time()

    findings = []
    missing = []
    evaporative_score = 0.0
    aqueous_score = 0.0
    inflammatory = False

    # --- Evaluate each input ---

    # TBUT
    if workup.tbut is not None:
        if workup.tbut < 5:
            findings.append(f"TBUT severely reduced at {workup.tbut}s (normal >10s)")
            evaporative_score += 0.3
        elif workup.tbut < 10:
            findings.append(f"TBUT reduced at {workup.tbut}s (normal >10s)")
            evaporative_score += 0.15
        else:
            findings.append(f"TBUT normal at {workup.tbut}s")
    else:
        missing.append("TBUT")

    # Schirmer
    if workup.schirmer is not None:
        if workup.schirmer < 5:
            findings.append(f"Schirmer severely reduced at {workup.schirmer}mm (aqueous deficiency likely)")
            aqueous_score += 0.4
        elif workup.schirmer < 10:
            findings.append(f"Schirmer borderline at {workup.schirmer}mm")
            aqueous_score += 0.15
        else:
            findings.append(f"Schirmer adequate at {workup.schirmer}mm")
    else:
        missing.append("Schirmer test")

    # OSDI
    if workup.osdi_score is not None:
        if workup.osdi_score >= 33:
            findings.append(f"OSDI score {workup.osdi_score}: severe symptoms")
        elif workup.osdi_score >= 23:
            findings.append(f"OSDI score {workup.osdi_score}: moderate symptoms")
        elif workup.osdi_score >= 13:
            findings.append(f"OSDI score {workup.osdi_score}: mild symptoms")
        else:
            findings.append(f"OSDI score {workup.osdi_score}: minimal symptoms")
    else:
        missing.append("OSDI score")

    # Staining
    if workup.corneal_staining_grade is not None:
        if workup.corneal_staining_grade >= 3:
            findings.append(f"Corneal staining grade {workup.corneal_staining_grade}: significant surface damage")
            inflammatory = True
        elif workup.corneal_staining_grade >= 1:
            findings.append(f"Corneal staining grade {workup.corneal_staining_grade}: mild surface involvement")
    else:
        missing.append("Corneal staining")

    # Tear osmolarity
    if workup.tear_osmolarity is not None:
        if workup.tear_osmolarity >= 308:
            findings.append(f"Tear osmolarity elevated at {workup.tear_osmolarity} mOsm/L")
            evaporative_score += 0.1
            aqueous_score += 0.1
        else:
            findings.append(f"Tear osmolarity normal at {workup.tear_osmolarity} mOsm/L")
    else:
        missing.append("Tear osmolarity")

    # MMP-9
    if workup.mmp9_positive is not None:
        if workup.mmp9_positive:
            findings.append("MMP-9 positive: inflammatory component present")
            inflammatory = True
        else:
            findings.append("MMP-9 negative")
    else:
        missing.append("MMP-9")

    # Meibum quality
    if workup.meibum_quality:
        if workup.meibum_quality in ("granular", "inspissated"):
            findings.append(f"Meibum quality: {workup.meibum_quality} (MGD indicator)")
            evaporative_score += 0.2
        elif workup.meibum_quality == "cloudy":
            findings.append(f"Meibum quality: cloudy (mild MGD)")
            evaporative_score += 0.1

    # Meibum expressibility
    if workup.meibum_expressibility is not None:
        if workup.meibum_expressibility >= 2:
            findings.append(f"Meibum expressibility grade {workup.meibum_expressibility}: reduced")
            evaporative_score += 0.15

    # Lid margin
    if workup.lid_margin_findings:
        findings.append(f"Lid margin: {workup.lid_margin_findings}")
        if any(term in workup.lid_margin_findings.lower() for term in
               ["telangiectasia", "redness", "irregular", "notching", "keratinization"]):
            evaporative_score += 0.1
            inflammatory = True

    # Meibography model results
    if workup.meibography_result:
        mg = workup.meibography_result
        meiboscore = mg.get("meiboscore", 0)
        dropout = mg.get("dropout_percentage", 0)
        if meiboscore >= 2:
            findings.append(f"Meibography: meiboscore {meiboscore}, {dropout:.1f}% dropout")
            evaporative_score += 0.25
        elif meiboscore >= 1:
            findings.append(f"Meibography: meiboscore {meiboscore}, {dropout:.1f}% dropout (mild)")
            evaporative_score += 0.1

    # --- Classify ---
    evaporative_score = min(evaporative_score, 1.0)
    aqueous_score = min(aqueous_score, 1.0)
    total_score = (evaporative_score + aqueous_score) / 2

    if evaporative_score > 0.4 and aqueous_score > 0.3:
        ded_subtype = "Mixed (evaporative-predominant with aqueous component)"
    elif evaporative_score > 0.3:
        ded_subtype = "Evaporative dry eye (likely MGD-related)"
    elif aqueous_score > 0.3:
        ded_subtype = "Aqueous deficient dry eye"
    else:
        ded_subtype = "Mild/borderline DED - subtype indeterminate"

    if total_score >= 0.5:
        severity = "Severe"
    elif total_score >= 0.3:
        severity = "Moderate"
    elif total_score >= 0.15:
        severity = "Mild"
    else:
        severity = "Minimal/subclinical"

    basis_parts = []
    if workup.tbut is not None:
        basis_parts.append("TBUT")
    if workup.schirmer is not None:
        basis_parts.append("Schirmer")
    if workup.meibography_result:
        basis_parts.append("meibography")
    if workup.osdi_score is not None:
        basis_parts.append("OSDI")
    classification_basis = f"Classification based on: {', '.join(basis_parts) if basis_parts else 'insufficient data'}"

    result = OSDWorkupResult(
        metadata=make_metadata("osd_workup", start),
        ded_subtype=ded_subtype,
        severity_grade=severity,
        severity_score=round(total_score, 3),
        aqueous_deficiency_score=round(aqueous_score, 3),
        evaporative_score=round(evaporative_score, 3),
        inflammatory_component=inflammatory,
        findings_summary=findings,
        missing_data=missing,
        classification_basis=classification_basis,
    )
    log_analysis("osd_workup", result.metadata.analysis_id, result.dict())
    return result



# ================================================================
# DIAGNOSTIC STUDY ENDPOINTS — PDF-based reports
# ================================================================

PDF_RASTER_DPI = 100
PDF_MAX_PAGES = 10
OLLAMA_URL_VS = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:35b")


class ERGMeasurementPair(BaseModel):
    od: Optional[float] = None
    od_pct: Optional[int] = None
    os: Optional[float] = None
    os_pct: Optional[int] = None


class ERGExtractionResult(BaseModel):
    metadata: AnalysisMetadata
    test_date: Optional[str] = None
    device: dict[str, Optional[str]] = Field(default_factory=dict)
    measurements: dict[str, ERGMeasurementPair] = Field(default_factory=dict)
    raw_text: str = ""
    extraction_confidence: float = 0.0
    page_count: int = 0
    warnings: list[str] = Field(default_factory=list)


def _rasterize_pdf_to_pngs(pdf_bytes: bytes, dpi: int = PDF_RASTER_DPI,
                            max_pages: int = PDF_MAX_PAGES) -> list[bytes]:
    """Rasterize a PDF to PNG byte buffers, one per page, capped at max_pages."""
    pngs = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page_count = min(len(doc), max_pages)
        for page_idx in range(page_count):
            page = doc[page_idx]
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pngs.append(pix.tobytes("png"))
    return pngs


def _call_ollama_vision(prompt: str, png_list: list[bytes],
                         model: str = None, temperature: float = 0.1) -> str:
    """Send rasterized images + prompt to Ollama. Low temperature for extraction."""
    import requests as _req
    model = model or OLLAMA_VISION_MODEL
    images_b64 = [base64.b64encode(p).decode("ascii") for p in png_list]
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt, "images": images_b64}
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 2048}, "think": False,
    }
    resp = _req.post(f"{OLLAMA_URL_VS}/api/chat", json=payload, timeout=1800)
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


def _strip_thinking_blocks(text: str) -> str:
    """Strip Qwen3.5 <think>...</think> chain-of-thought before JSON parsing."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json_block(text: str) -> Optional[dict]:
    """Find and parse the first JSON object, tolerating prose or markdown fences."""
    cleaned = _strip_thinking_blocks(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


ERG_EXTRACTION_PROMPT = """You are extracting structured data from a RETeval full-field ERG report (LKC Technologies). The report shows photopic flicker measurements for both eyes, with raw values and age-matched percentile ranks.

CRITICAL RULES:
- OD = right eye (oculus dexter), OS = left eye (oculus sinister). Do not confuse them.
- For any field you cannot read with confidence, return null. Do NOT guess.
- Return ONLY the JSON object below — no prose, no markdown fences, no commentary.
- Numeric values must be numbers, not strings. Percentiles must be integers 0-100.

Return this exact JSON schema:

{
  "test_date": "MM/DD/YYYY or null",
  "device": {
    "serial": "string or null",
    "firmware": "string or null",
    "protocol": "string or null",
    "electrode": "string or null",
    "pupils": "OD: X.X mm | OS: X.X mm or null"
  },
  "measurements": {
    "fundamental_implicit_time": {"od": null, "od_pct": null, "os": null, "os_pct": null},
    "waveform_implicit_time":    {"od": null, "od_pct": null, "os": null, "os_pct": null},
    "fundamental_amplitude":     {"od": null, "od_pct": null, "os": null, "os_pct": null},
    "waveform_amplitude":        {"od": null, "od_pct": null, "os": null, "os_pct": null}
  }
}

Implicit times are in milliseconds (ms). Amplitudes are in microvolts (uV). Percentiles are the age-matched normative rank shown on the report. Replace each null with the actual value if and only if you can read it directly from the image."""


@app.post("/analyze/diagnostic/erg", response_model=ERGExtractionResult)
async def analyze_erg(
    pdf: UploadFile = File(..., description="RETeval ERG report PDF"),
):
    """Extract structured measurements from a RETeval full-field ERG PDF."""
    start = time.time()
    warnings = []

    pdf_bytes = await pdf.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    try:
        pngs = _rasterize_pdf_to_pngs(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF rasterization failed: {e}")
    if not pngs:
        raise HTTPException(status_code=400, detail="PDF contained no pages")
    page_count = len(pngs)
    if page_count == PDF_MAX_PAGES:
        warnings.append(f"PDF truncated to first {PDF_MAX_PAGES} pages")

    try:
        raw_text = _call_ollama_vision(ERG_EXTRACTION_PROMPT, pngs)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}")

    parsed = _extract_json_block(raw_text)
    if parsed is None:
        warnings.append("Could not parse JSON from model response - measurements empty")
        parsed = {}

    measurements_raw = parsed.get("measurements", {}) or {}
    expected_params = [
        "fundamental_implicit_time", "waveform_implicit_time",
        "fundamental_amplitude",     "waveform_amplitude",
    ]
    measurements: dict[str, ERGMeasurementPair] = {}
    filled_fields = 0
    total_fields = 0
    for key in expected_params:
        raw = measurements_raw.get(key) or {}
        pair = ERGMeasurementPair(
            od=raw.get("od"),
            od_pct=raw.get("od_pct"),
            os=raw.get("os"),
            os_pct=raw.get("os_pct"),
        )
        measurements[key] = pair
        for field_value in (pair.od, pair.od_pct, pair.os, pair.os_pct):
            total_fields += 1
            if field_value is not None:
                filled_fields += 1
    confidence = round(filled_fields / total_fields, 2) if total_fields else 0.0
    if confidence < 0.5:
        warnings.append(f"Low extraction confidence ({confidence}) - manual review recommended")

    result = ERGExtractionResult(
        metadata=make_metadata("erg", start),
        test_date=parsed.get("test_date"),
        device=parsed.get("device", {}) or {},
        measurements=measurements,
        raw_text=raw_text,
        extraction_confidence=confidence,
        page_count=page_count,
        warnings=warnings,
    )
    log_analysis("erg", result.metadata.analysis_id, result.dict())
    return result



# === Run ===

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    logging.info(f"Starting EyeAssist Vision Pipeline on port {SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
