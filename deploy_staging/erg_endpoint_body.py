
# ================================================================
# DIAGNOSTIC STUDY ENDPOINTS — PDF-based reports
# ================================================================

PDF_RASTER_DPI = 200
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
        "options": {"temperature": temperature, "num_predict": 2048},
    }
    resp = _req.post(f"{OLLAMA_URL_VS}/api/chat", json=payload, timeout=600)
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

