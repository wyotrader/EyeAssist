
# ================================================================
# REPORT GENERATION — ERG
# ================================================================

class _OrchestratorLLMAdapter:
    """Wraps call_llm() in the shape ERGIntegrator expects."""

    def generate(self, prompt: str, format: Optional[str] = None,
                 system_prompt: Optional[str] = None,
                 temperature: float = 0.2):
        if format == "json":
            sys_msg = (system_prompt or "") + (
                "\n\nReturn ONLY a valid JSON object with no surrounding "
                "prose, no markdown fences, and no <think> blocks."
            )
        else:
            sys_msg = system_prompt

        raw = call_llm(prompt, sys_msg, temperature=temperature)

        if format != "json":
            return raw

        import re as _re, json as _json
        cleaned = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        try:
            return _json.loads(cleaned)
        except _json.JSONDecodeError:
            fence = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, _re.DOTALL)
            if fence:
                try:
                    return _json.loads(fence.group(1))
                except _json.JSONDecodeError:
                    pass
            brace = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
            if brace:
                try:
                    return _json.loads(brace.group(0))
                except _json.JSONDecodeError:
                    pass
            logging.warning(f"LLM JSON parse failed; raw response was: {raw[:300]}")
            return {}


class _OrchestratorRAGAdapter:
    """Wraps execute_rag_search() in the shape ERGIntegrator expects."""

    def query(self, collection, query: str, n_results: int = 5):
        if isinstance(collection, str):
            collections = [collection]
        else:
            collections = list(collection)

        result = execute_rag_search(query=query, collections=collections)
        if not result.get("success"):
            logging.warning(f"RAG query failed: {result.get('error')}")
            return []

        return [{
            "text": result.get("context", ""),
            "source": ", ".join(result.get("sources", [])),
        }]


@app.post("/report/erg")
async def report_erg(
    pdf: UploadFile = File(..., description="RETeval ERG report PDF"),
    patient_name: str = Form(""),
    dob_age: str = Form(""),
    sex: str = Form(""),
    mrn: str = Form(""),
    reason: str = Form(""),
    ordering_provider: str = Form("Jason B. Whitman, O.D."),
    interpreting_provider: str = Form("Jason B. Whitman, O.D."),
):
    """Full ERG report generation pipeline. Returns a rendered PDF."""
    session_id = str(uuid.uuid4())[:12]
    logging.info(f"[{session_id}] /report/erg pipeline starting")

    pdf_bytes = await pdf.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF upload")

    try:
        vision_resp = requests.post(
            f"{VISION_SERVICE_URL}/analyze/diagnostic/erg",
            files={"pdf": (pdf.filename or "erg.pdf", pdf_bytes, "application/pdf")},
            timeout=600,
        )
        vision_resp.raise_for_status()
        vision_data = vision_resp.json()
    except Exception as e:
        logging.error(f"[{session_id}] Vision extraction failed: {e}")
        raise HTTPException(status_code=502, detail=f"Vision extraction failed: {e}")

    logging.info(
        f"[{session_id}] Vision extraction complete: "
        f"confidence={vision_data.get('extraction_confidence')}, "
        f"warnings={vision_data.get('warnings', [])}"
    )

    vision_output = {
        "test_date": vision_data.get("test_date"),
        "device": vision_data.get("device", {}),
        "measurements": vision_data.get("measurements", {}),
        "confidence": vision_data.get("extraction_confidence", 0.0),
    }

    patient_meta = {
        "name": patient_name,
        "dob_age": dob_age,
        "sex": sex,
        "mrn": mrn,
        "reason": reason,
        "ordering_provider": ordering_provider,
        "interpreting_provider": interpreting_provider,
    }

    integrator = ERGIntegrator(
        llm_client=_OrchestratorLLMAdapter(),
        rag_client=_OrchestratorRAGAdapter(),
    )

    try:
        context = integrator.build_context(vision_output, patient_meta)
    except Exception as e:
        logging.exception(f"[{session_id}] ERGIntegrator failed")
        raise HTTPException(status_code=500, detail=f"Integrator failed: {e}")

    try:
        pdf_out = render(context=context, template_path=integrator.template_path)
    except Exception as e:
        logging.exception(f"[{session_id}] Renderer failed")
        raise HTTPException(status_code=500, detail=f"Renderer failed: {e}")

    logging.info(f"[{session_id}] /report/erg complete: {len(pdf_out)} bytes")

    safe_name = (patient_name or "patient").replace(" ", "_").replace(",", "")
    return Response(
        content=pdf_out,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="ERG_Report_{safe_name}.pdf"',
            "X-Extraction-Confidence": str(vision_data.get("extraction_confidence", 0.0)),
            "X-Vision-Warnings": "; ".join(vision_data.get("warnings", [])),
        },
    )
