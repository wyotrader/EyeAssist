#!/usr/bin/env python3
"""
EyeAssist Agent Orchestrator
The central intelligence that connects the LLM to RAG knowledge and vision models.

Receives a clinician's query, uses the LLM to plan which tools to invoke,
executes them, and synthesizes results into a coherent clinical response.

Can be used as:
  1. A standalone service (port 8300) called by the EyeAssist gateway
  2. A Python module imported by other pipeline components

Architecture:
  User Query → Orchestrator → LLM (plan) → Tool Execution → LLM (synthesize) → Response

Usage:
    python3 orchestrator.py
    # Or: uvicorn orchestrator:app --host 0.0.0.0 --port 8300
"""

import sys as _sys_bootstrap
import os as _os_bootstrap
_sys_bootstrap.path.insert(0, _os_bootstrap.path.dirname(_os_bootstrap.path.dirname(_os_bootstrap.path.abspath(__file__))))

import os
import json
import time
import logging
import uuid
from typing import Optional
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi import UploadFile, File
from fastapi.responses import Response
from reports import render
from reports.integrators.erg import ERGIntegrator
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# === Configuration ===

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:32b-a3b")
RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://localhost:8100")
VISION_SERVICE_URL = os.environ.get("VISION_SERVICE_URL", "http://localhost:8200")
SERVICE_PORT = 8300
LOG_DIR = os.path.expanduser("~/eyeassist/logs")
TOOL_REGISTRY_PATH = os.path.expanduser("~/eyeassist/config/tool-registry.yaml")

os.makedirs(LOG_DIR, exist_ok=True)

# === Tool Definitions (for LLM reasoning) ===

AVAILABLE_TOOLS = {
    # RAG tools
    "rag_search": {
        "description": "Search the ophthalmology knowledge base for clinical guidelines, textbook references, and evidence-based information. Use this for any clinical question requiring authoritative references.",
        "parameters": {
            "query": "The clinical question to search for",
            "collections": "List of collections to search: osd, glaucoma, retina, cornea, neuro, pediatric, refractive, general",
        },
        "type": "rag",
    },

    # Posterior vision tools
    "retfound_screening": {
        "description": "General retinal disease screening from a color fundus photo or OCT image. Use as a first-pass screening tool to detect abnormalities.",
        "parameters": {"image": "Fundus photo or OCT image", "modality": "cfp or oct"},
        "type": "vision",
        "endpoint": "/analyze/posterior/retfound",
    },
    "dr_grading": {
        "description": "Grade diabetic retinopathy severity on the 5-level ICDR scale from a fundus photo. Use when DR is suspected or for diabetic patient screening.",
        "parameters": {"image": "Color fundus photograph"},
        "type": "vision",
        "endpoint": "/analyze/posterior/dr-grading",
    },
    "glaucoma_detection": {
        "description": "Detect glaucoma and assess progression risk from OCT RNFL thickness maps. Provides glaucoma probability and progression risk scores.",
        "parameters": {"image": "OCT RNFL thickness map"},
        "type": "vision",
        "endpoint": "/analyze/posterior/glaucoma",
    },
    "disc_cup_segmentation": {
        "description": "Segment the optic disc and cup from a fundus photo to calculate cup-to-disc ratio (CDR). Use for glaucoma assessment.",
        "parameters": {"image": "Color fundus photograph"},
        "type": "vision",
        "endpoint": "/analyze/posterior/fairseg",
    },
    "vessel_segmentation": {
        "description": "Segment retinal arteries and veins from a fundus photo. Provides artery/vein ratio, vessel density, and tortuosity metrics.",
        "parameters": {"image": "Color fundus photograph"},
        "type": "vision",
        "endpoint": "/analyze/posterior/vessel",
    },
    "vf_prediction": {
        "description": "Predict 10-2 visual field from 24-2 total deviation values. Use when 10-2 testing was not performed.",
        "parameters": {"td_values_24_2": "52 total deviation values from 24-2 Humphrey VF"},
        "type": "vision",
        "endpoint": "/analyze/posterior/vf-predict",
    },

    # Anterior vision tools
    "meibography_analysis": {
        "description": "Analyze meibomian glands from infrared meibography. Returns meiboscore, gland count, dropout percentage, and morphology metrics (length, width, tortuosity). Essential for MGD and dry eye assessment.",
        "parameters": {"image": "Infrared meibography image", "eyelid": "upper or lower"},
        "type": "vision",
        "endpoint": "/analyze/anterior/meibography",
    },
    "corneal_disease_classification": {
        "description": "Classify corneal disease from slit-lamp photographs. Detects infectious keratitis and differentiates bacterial vs fungal keratitis.",
        "parameters": {"image": "Slit-lamp photograph of cornea"},
        "type": "vision",
        "endpoint": "/analyze/anterior/corneal-disease",
    },
    "keratoconus_screening": {
        "description": "Screen for keratoconus from Pentacam corneal topography parameters. Differentiates normal, subclinical KC, and established KC.",
        "parameters": {"k1": "Flat K", "k2": "Steep K", "kmax": "Max K", "pachymetry_min": "Thinnest pachymetry", "anterior_elevation": "Max anterior elevation", "posterior_elevation": "Max posterior elevation"},
        "type": "vision",
        "endpoint": "/analyze/anterior/keratoconus",
    },
    "osd_workup": {
        "description": "Multi-factor dry eye disease assessment. Integrates clinical measurements (TBUT, Schirmer, OSDI, staining, meibography) with TFOS DEWS II criteria for DED subtype classification and severity grading.",
        "parameters": {"tbut": "seconds", "schirmer": "mm", "osdi_score": "0-100", "corneal_staining_grade": "0-5", "lid_margin_findings": "text", "meibography_result": "dict from meibography_analysis"},
        "type": "vision",
        "endpoint": "/analyze/anterior/osd-workup",
    },
}


# === Request/Response Models ===

class OrchestratorQuery(BaseModel):
    message: str
    image_b64: Optional[str] = None
    image_modality: Optional[str] = None
    clinical_data: Optional[dict] = None
    conversation_history: Optional[list[dict]] = None
    session_id: Optional[str] = None

class ToolCall(BaseModel):
    tool_name: str
    parameters: dict
    reasoning: str

class ToolResult(BaseModel):
    tool_name: str
    success: bool
    result: Optional[dict] = None
    error: Optional[str] = None
    execution_time_ms: float

class OrchestratorResponse(BaseModel):
    session_id: str
    plan: list[ToolCall]
    tool_results: list[ToolResult]
    synthesized_response: str
    sources_used: list[str]
    total_time_ms: float


# === LLM Interface ===

def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.3) -> str:
    """Call Ollama LLM and return the response text."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": 2048},
            },
            timeout=900,  # 5 min timeout for CPU inference
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logging.error(f"LLM call failed: {e}")
        return f"[LLM Error: {str(e)}]"


# === Tool Execution ===

def execute_rag_search(query: str, collections: list[str] = None) -> dict:
    """Query the RAG service."""
    try:
        results = []
        searched = []
        targets = collections or [None]

        for collection in targets:
            payload = {"query": query, "n_results": 5}
            if collection:
                payload["collection"] = collection
            resp = requests.post(f"{RAG_SERVICE_URL}/query", json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            searched.extend([c.strip() for c in data.get("collection_searched", "").split(",") if c.strip()])
            results.extend(data.get("results", []))

        results.sort(key=lambda item: item.get("distance", 999))
        results = results[:5]
        context = format_rag_context(results)
        return {
            "success": True,
            "context": context,
            "sources": list({item.get("source", "unknown") for item in results}),
            "evidence": [
                {
                    "title": item.get("source", "unknown"),
                    "page": item.get("page"),
                    "collection": item.get("collection", "unknown"),
                    "distance": item.get("distance"),
                }
                for item in results
            ],
            "collections_searched": sorted(set(searched)),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def format_rag_context(results: list[dict]) -> str:
    if not results:
        return ""

    lines = [
        "=== RETRIEVED CLINICAL REFERENCES ===",
        "Use this information to ground the response. Cite sources when referencing specific guidelines.",
        "",
    ]
    for i, result in enumerate(results, 1):
        lines.append(f"--- Reference {i} (Source: {result.get('source', 'unknown')}, Page {result.get('page', 0)}) ---")
        lines.append(result.get("text", ""))
        lines.append("")
    lines.append("=== END REFERENCES ===")
    return "\n".join(lines)


def execute_vision_tool(endpoint: str, image_bytes: bytes = None, form_data: dict = None, json_data: dict = None) -> dict:
    """Call a vision pipeline endpoint."""
    try:
        url = f"{VISION_SERVICE_URL}{endpoint}"

        if image_bytes:
            files = {"image": ("image.png", image_bytes, "image/png")}
            resp = requests.post(url, files=files, data=form_data or {}, timeout=60)
        elif json_data:
            resp = requests.post(url, json=json_data, timeout=60)
        elif form_data:
            resp = requests.post(url, data=form_data, timeout=60)
        else:
            return {"success": False, "error": "No input data provided"}

        resp.raise_for_status()
        return {"success": True, "result": resp.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_tool(tool_call: ToolCall, image_bytes: bytes = None, clinical_data: dict = None) -> ToolResult:
    """Execute a single tool call and return the result."""
    start = time.time()
    tool_def = AVAILABLE_TOOLS.get(tool_call.tool_name)

    if not tool_def:
        return ToolResult(
            tool_name=tool_call.tool_name,
            success=False,
            error=f"Unknown tool: {tool_call.tool_name}",
            execution_time_ms=0,
        )

    result = None

    if tool_def["type"] == "rag":
        query = tool_call.parameters.get("query", "")
        collections = tool_call.parameters.get("collections", None)
        if isinstance(collections, str):
            collections = [c.strip() for c in collections.split(",")]
        result = execute_rag_search(query, collections)

    elif tool_def["type"] == "vision":
        endpoint = tool_def["endpoint"]

        if tool_call.tool_name == "osd_workup":
            # OSD workup takes JSON clinical data
            workup_data = clinical_data or tool_call.parameters
            result = execute_vision_tool(endpoint, json_data=workup_data)
        elif tool_call.tool_name == "keratoconus_screening":
            # Keratoconus takes form data
            result = execute_vision_tool(endpoint, form_data=tool_call.parameters)
        elif tool_call.tool_name == "vf_prediction":
            result = execute_vision_tool(endpoint, form_data=tool_call.parameters)
        else:
            # Image-based tools
            if image_bytes:
                form_data = {k: v for k, v in tool_call.parameters.items() if k != "image"}
                result = execute_vision_tool(endpoint, image_bytes=image_bytes, form_data=form_data)
            else:
                result = {"success": False, "error": "No image provided for vision tool"}

    elapsed = (time.time() - start) * 1000

    return ToolResult(
        tool_name=tool_call.tool_name,
        success=result.get("success", False) if result else False,
        result=result if result and result.get("success") else None,
        error=result.get("error") if result and not result.get("success") else None,
        execution_time_ms=round(elapsed, 2),
    )


# === Planning ===

PLANNING_SYSTEM_PROMPT = """You are the EyeAssist planning agent. Your job is to analyze a clinician's query and determine which tools to call to answer it.

Available tools:
{tools_description}

Respond ONLY with a JSON array of tool calls. Each tool call should have:
- "tool_name": the exact tool name from the list above
- "parameters": a dict of parameters for that tool
- "reasoning": a brief explanation of why this tool is needed

Rules:
1. ALWAYS include "rag_search" to ground the response in evidence. Choose the most relevant collection(s).
2. Only include vision tools if the query involves image analysis or the user has uploaded an image.
3. For dry eye / OSD queries, consider both "rag_search" (osd collection) and "osd_workup" if clinical measurements are provided.
4. For glaucoma queries with imaging, consider both "glaucoma_detection" and "disc_cup_segmentation".
5. Keep the plan focused — typically 1-3 tools. Don't call tools that aren't relevant.
6. For general knowledge questions, "rag_search" alone is sufficient.

Respond with ONLY the JSON array, no other text. Example:
[
  {"tool_name": "rag_search", "parameters": {"query": "TFOS DEWS II evaporative dry eye classification", "collections": "osd"}, "reasoning": "Need DEWS II criteria for DED subtyping"},
  {"tool_name": "osd_workup", "parameters": {}, "reasoning": "Clinical measurements provided, run formal assessment"}
]"""


def format_tools_description() -> str:
    """Format tool descriptions for the planning prompt."""
    lines = []
    for name, tool in AVAILABLE_TOOLS.items():
        params = ", ".join(f"{k}: {v}" for k, v in tool["parameters"].items())
        lines.append(f"- {name}: {tool['description']}\n  Parameters: {params}")
    return "\n".join(lines)


def plan_tool_calls(query: str, has_image: bool, has_clinical_data: bool, clinical_data: dict = None) -> list[ToolCall]:
    """Use the LLM to plan which tools to call."""
    tools_desc = format_tools_description()
    system = PLANNING_SYSTEM_PROMPT.replace("{tools_description}", tools_desc)

    context_hints = []
    if has_image:
        context_hints.append("The user has uploaded an image for analysis.")
    if has_clinical_data and clinical_data:
        context_hints.append(f"Clinical data provided: {json.dumps(clinical_data)}")
    context = " ".join(context_hints)

    prompt = f"Clinician query: {query}"
    if context:
        prompt += f"\n\nContext: {context}"
    prompt += "\n\nPlan the tool calls (JSON array only):"

    response = call_llm(prompt, system, temperature=0.1)

    # Parse JSON from response
    try:
        # Try to extract JSON array from response
        response = response.strip()
        # Handle cases where LLM wraps in markdown
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()

        # Find the JSON array
        start_idx = response.find("[")
        end_idx = response.rfind("]") + 1
        if start_idx >= 0 and end_idx > start_idx:
            json_str = response[start_idx:end_idx]
            tool_calls_raw = json.loads(json_str)
        else:
            raise ValueError("No JSON array found")

        tool_calls = []
        for tc in tool_calls_raw:
            tool_calls.append(ToolCall(
                tool_name=tc.get("tool_name", ""),
                parameters=tc.get("parameters", {}),
                reasoning=tc.get("reasoning", ""),
            ))
        return tool_calls

    except Exception as e:
        logging.warning(f"Failed to parse plan, falling back to RAG-only: {e}")
        # Fallback: just do a RAG search
        return [ToolCall(
            tool_name="rag_search",
            parameters={"query": query},
            reasoning="Fallback: RAG search for general clinical information",
        )]


# === Synthesis ===

SYNTHESIS_SYSTEM_PROMPT = """You are EyeAssist, an ophthalmology clinical decision support assistant. You have just executed a series of tools to gather information for a clinician's query.

Synthesize all the tool results into a coherent clinical response following this format:

1. **Observations**: What the data shows (objective findings from tools).
2. **Assessment**: Clinical significance and differential considerations.
3. **Relevant Guidelines**: Applicable guidelines from the retrieved references.
4. **Considerations**: Suggested next steps or additional information needed.
5. **Confidence Note**: Your confidence level and any caveats.

Rules:
- Ground your response in the retrieved references. Cite sources when referencing specific guidelines.
- Present vision model results with their confidence scores.
- Flag any low-confidence results prominently.
- Never provide definitive diagnoses or specific treatment recommendations.
- If tool calls failed, acknowledge the missing information and work with what's available.
- Be concise but thorough."""


def synthesize_response(query: str, tool_results: list[ToolResult]) -> str:
    """Use the LLM to synthesize tool results into a final response."""
    # Build context from tool results
    context_parts = []
    for tr in tool_results:
        if tr.success and tr.result:
            if tr.tool_name == "rag_search":
                context_parts.append(f"=== RETRIEVED REFERENCES ===\n{tr.result.get('context', 'No context retrieved')}")
            else:
                context_parts.append(f"=== {tr.tool_name.upper()} RESULT ===\n{json.dumps(tr.result.get('result', tr.result), indent=2)}")
        elif not tr.success:
            context_parts.append(f"=== {tr.tool_name.upper()} ===\n[Tool call failed: {tr.error}]")

    tool_context = "\n\n".join(context_parts)

    prompt = f"""Clinician's query: {query}

Tool results:
{tool_context}

Synthesize these results into a clinical response following the EyeAssist output format."""

    return call_llm(prompt, SYNTHESIS_SYSTEM_PROMPT, temperature=0.3)




def plan_tool_calls_fast(query, has_image, has_clinical_data, clinical_data=None):
    """CPU-friendly keyword-based planning. No LLM call needed."""
    tools = []
    q = query.lower()

    # Detect best collection(s) for RAG search
    collections = []

    osd_kw = ["dry eye", "meibomian", "mgd", "tear", "tbut", "schirmer", "osdi",
              "ocular surface", "blepharitis", "lid margin", "meibography", "dews"]
    glaucoma_kw = ["glaucoma", "iop", "intraocular pressure", "optic nerve", "cup to disc",
                   "rnfl", "visual field", "humphrey", "trabeculectomy", "migs"]
    retina_kw = ["retina", "diabetic", "macular", "amd", "drusen", "vegf", "vitreous",
                 "detachment", "npdr", "pdr", "4-2-1", "epiretinal", "vein occlusion"]
    cornea_kw = ["cornea", "keratitis", "keratoconus", "dystrophy", "ulcer", "crosslinking",
                 "ectasia", "fuchs", "transplant"]
    neuro_kw = ["optic neuritis", "papilledema", "nystagmus", "diplopia", "cranial nerve",
                "neuro", "visual pathway", "idiopathic intracranial"]
    pediatric_kw = ["amblyopia", "strabismus", "esotropia", "exotropia", "pediatric",
                    "child", "infant", "rop", "retinopathy of prematurity"]
    refractive_kw = ["lasik", "prk", "refractive surgery", "iol", "cataract", "phaco",
                     "presbyopia", "myopia control", "lens implant"]

    if any(kw in q for kw in osd_kw): collections.append("osd")
    if any(kw in q for kw in glaucoma_kw): collections.append("glaucoma")
    if any(kw in q for kw in retina_kw): collections.append("retina")
    if any(kw in q for kw in cornea_kw): collections.append("cornea")
    if any(kw in q for kw in neuro_kw): collections.append("neuro")
    if any(kw in q for kw in pediatric_kw): collections.append("pediatric")
    if any(kw in q for kw in refractive_kw): collections.append("refractive")
    if not collections: collections = ["general"]

    tools.append(ToolCall(
        tool_name="rag_search",
        parameters={"query": query, "collections": ",".join(collections)},
        reasoning=f"Search {','.join(collections)} for clinical references",
    ))

    # Add vision tools if image is present
    if has_image:
        if any(kw in q for kw in ["fundus", "retina", "disc", "cup", "dr", "diabetic"]):
            tools.append(ToolCall(tool_name="retfound_screening", parameters={"modality": "cfp"}, reasoning="Screen fundus image"))
        if any(kw in q for kw in ["dr grade", "diabetic retinopathy", "npdr", "pdr"]):
            tools.append(ToolCall(tool_name="dr_grading", parameters={}, reasoning="Grade DR severity"))
        if any(kw in q for kw in ["glaucoma", "disc", "cup", "cdr"]):
            tools.append(ToolCall(tool_name="disc_cup_segmentation", parameters={}, reasoning="Segment disc/cup for CDR"))
        if any(kw in q for kw in ["meibom", "meibography"]):
            tools.append(ToolCall(tool_name="meibography_analysis", parameters={"eyelid": "upper"}, reasoning="Analyze meibography"))
        if any(kw in q for kw in ["cornea", "keratitis", "slit"]):
            tools.append(ToolCall(tool_name="corneal_disease_classification", parameters={}, reasoning="Classify corneal disease"))

    # Add OSD workup if clinical data provided
    if has_clinical_data and clinical_data:
        osd_keys = ["tbut", "schirmer", "osdi_score", "meibography_result",
                     "corneal_staining_grade", "tear_osmolarity", "mmp9_positive"]
        if any(k in clinical_data for k in osd_keys):
            tools.append(ToolCall(tool_name="osd_workup", parameters={}, reasoning="Run DED assessment with clinical data"))

    return tools


# === Main Orchestration ===

def orchestrate(query: OrchestratorQuery) -> OrchestratorResponse:
    """Main orchestration pipeline: plan → execute → synthesize."""
    start_time = time.time()
    session_id = query.session_id or str(uuid.uuid4())[:12]

    logging.info(f"[{session_id}] Orchestrating query: {query.message[:100]}...")

    # Decode image if provided
    image_bytes = None
    if query.image_b64:
        import base64
        image_bytes = base64.b64decode(query.image_b64)

    # Phase 1: Plan
    logging.info(f"[{session_id}] Phase 1: Planning tool calls...")
    tool_calls = plan_tool_calls_fast(
        query=query.message,
        has_image=image_bytes is not None,
        has_clinical_data=query.clinical_data is not None,
        clinical_data=query.clinical_data,
    )
    logging.info(f"[{session_id}] Plan: {[tc.tool_name for tc in tool_calls]}")

    # Phase 2: Execute tools
    logging.info(f"[{session_id}] Phase 2: Executing {len(tool_calls)} tool(s)...")
    tool_results = []
    for tc in tool_calls:
        logging.info(f"[{session_id}]   Executing: {tc.tool_name}")
        result = execute_tool(tc, image_bytes=image_bytes, clinical_data=query.clinical_data)
        tool_results.append(result)
        logging.info(f"[{session_id}]   Result: {'OK' if result.success else 'FAILED'} ({result.execution_time_ms}ms)")

    # Phase 3: Synthesize
    logging.info(f"[{session_id}] Phase 3: Synthesizing response...")
    response_text = synthesize_response(query.message, tool_results)

    # Collect sources
    sources = []
    for tr in tool_results:
        if tr.success and tr.result:
            if "sources" in tr.result:
                sources.extend(tr.result["sources"])
            elif "result" in tr.result and isinstance(tr.result["result"], dict):
                src = tr.result["result"].get("metadata", {}).get("model_name", "")
                if src:
                    sources.append(src)

    total_ms = round((time.time() - start_time) * 1000, 2)
    logging.info(f"[{session_id}] Complete in {total_ms}ms")

    return OrchestratorResponse(
        session_id=session_id,
        plan=tool_calls,
        tool_results=tool_results,
        synthesized_response=response_text,
        sources_used=list(set(sources)),
        total_time_ms=total_ms,
    )


# === FastAPI App ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("EyeAssist Orchestrator starting...")
    logging.info(f"  LLM: {OLLAMA_URL} ({OLLAMA_MODEL})")
    logging.info(f"  RAG: {RAG_SERVICE_URL}")
    logging.info(f"  Vision: {VISION_SERVICE_URL}")

    # Verify connections
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        logging.info(f"  Ollama models: {models}")
    except:
        logging.warning("  Ollama not reachable!")

    try:
        r = requests.get(f"{RAG_SERVICE_URL}/health", timeout=5)
        logging.info(f"  RAG service: healthy ({r.json().get('total_chunks', '?')} chunks)")
    except:
        logging.warning("  RAG service not reachable!")

    try:
        r = requests.get(f"{VISION_SERVICE_URL}/health", timeout=5)
        logging.info(f"  Vision service: healthy")
    except:
        logging.warning("  Vision service not reachable!")

    yield
    logging.info("Orchestrator shutting down.")


app = FastAPI(
    title="EyeAssist Orchestrator",
    description="Agent orchestrator connecting LLM, RAG, and vision pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check with dependency status."""
    deps = {}
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        deps["ollama"] = "healthy"
    except:
        deps["ollama"] = "unreachable"
    try:
        r = requests.get(f"{RAG_SERVICE_URL}/health", timeout=3)
        deps["rag_service"] = "healthy"
    except:
        deps["rag_service"] = "unreachable"
    try:
        r = requests.get(f"{VISION_SERVICE_URL}/health", timeout=3)
        deps["vision_service"] = "healthy"
    except:
        deps["vision_service"] = "unreachable"

    return {"status": "healthy", "dependencies": deps, "model": OLLAMA_MODEL}


@app.post("/orchestrate", response_model=OrchestratorResponse)
async def orchestrate_query(query: OrchestratorQuery):
    """Main orchestration endpoint."""
    return orchestrate(query)


@app.post("/quick-query")
async def quick_query(message: str = Form(...)):
    """Simple text-only query endpoint for quick testing."""
    query = OrchestratorQuery(message=message)
    result = orchestrate(query)
    return {
        "query": message,
        "response": result.synthesized_response,
        "tools_used": [tc.tool_name for tc in result.plan],
        "time_ms": result.total_time_ms,
    }


@app.get("/tools")
async def list_tools():
    """List all available tools."""
    return AVAILABLE_TOOLS


# === Run ===


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
            timeout=1800,
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




# ================================================================
# STREAMING ORCHESTRATION ENDPOINT
# ================================================================

from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import asyncio


def call_llm_stream(prompt: str, system_prompt: str = "", temperature: float = 0.3):
    """
    Call Ollama LLM with streaming enabled. Yields content chunks.
    This is a generator that yields string chunks as they arrive.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": True,
                "options": {"temperature": temperature, "num_predict": 4096},
            },
            timeout=900,
            stream=True,
        )
        resp.raise_for_status()

        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logging.error(f"LLM streaming call failed: {e}")
        yield f"[LLM Error: {str(e)}]"


def synthesize_response_stream(query: str, tool_results: list[ToolResult]):
    """
    Stream the synthesis response token by token.
    Yields string chunks as they arrive from the LLM.
    """
    context_parts = []
    for tr in tool_results:
        if tr.success and tr.result:
            if tr.tool_name == "rag_search":
                context_parts.append(
                    f"=== RETRIEVED REFERENCES ===\n{tr.result.get('context', 'No context retrieved')}"
                )
            else:
                context_parts.append(
                    f"=== {tr.tool_name.upper()} RESULT ===\n"
                    f"{json.dumps(tr.result.get('result', tr.result), indent=2)}"
                )
        elif not tr.success:
            context_parts.append(
                f"=== {tr.tool_name.upper()} ===\n[Tool call failed: {tr.error}]"
            )

    tool_context = "\n\n".join(context_parts)

    prompt = f"""Clinician's query: {query}

Tool results:
{tool_context}

Synthesize these results into a clinical response following the EyeAssist output format."""

    for chunk in call_llm_stream(prompt, SYNTHESIS_SYSTEM_PROMPT, temperature=0.3):
        yield chunk


class OrchestrateStreamRequest(BaseModel):
    """Request model for streaming orchestration."""
    message: str
    image_b64: Optional[str] = None
    image_modality: Optional[str] = None
    clinical_data: Optional[dict] = None
    session_id: Optional[str] = None


@app.post("/orchestrate/stream")
async def orchestrate_stream(query: OrchestrateStreamRequest, request: Request):
    """
    Streaming orchestration endpoint.
    
    Returns Server-Sent Events (SSE) with:
    - First event: metadata (session_id, plan, tool_results)
    - Subsequent events: synthesis tokens as they stream from the LLM
    - Final event: done marker with timing
    
    SSE format:
        data: {"type": "metadata", "session_id": "...", "plan": [...], "tool_results": [...]}
        data: {"type": "token", "content": "..."}
        data: {"type": "done", "total_time_ms": 1234.56}
    """
    start_time = time.time()
    session_id = query.session_id or str(uuid.uuid4())[:12]

    logging.info(f"[{session_id}] /orchestrate/stream starting: {query.message[:100]}...")

    image_bytes = None
    if query.image_b64:
        import base64
        image_bytes = base64.b64decode(query.image_b64)

    logging.info(f"[{session_id}] Phase 1: Planning...")
    tool_calls = plan_tool_calls_fast(
        query=query.message,
        has_image=image_bytes is not None,
        has_clinical_data=query.clinical_data is not None,
        clinical_data=query.clinical_data,
    )
    logging.info(f"[{session_id}] Plan: {[tc.tool_name for tc in tool_calls]}")

    logging.info(f"[{session_id}] Phase 2: Executing {len(tool_calls)} tool(s)...")
    tool_results = []
    for tc in tool_calls:
        logging.info(f"[{session_id}]   Executing: {tc.tool_name}")
        result = execute_tool(tc, image_bytes=image_bytes, clinical_data=query.clinical_data)
        tool_results.append(result)
        logging.info(
            f"[{session_id}]   Result: {'OK' if result.success else 'FAILED'} "
            f"({result.execution_time_ms}ms)"
        )

    sources = []
    for tr in tool_results:
        if tr.success and tr.result:
            if "sources" in tr.result:
                sources.extend(tr.result["sources"])

    evidence = []
    for tr in tool_results:
        if tr.success and tr.result and tr.tool_name == "rag_search":
            evidence.extend(tr.result.get("evidence", []))

    metadata_payload = {
        "type": "metadata",
        "session_id": session_id,
        "plan": [{"tool_name": tc.tool_name} for tc in tool_calls],
        "tool_results": [
            {
                "tool_name": tr.tool_name,
                "success": tr.success,
                "execution_time_ms": tr.execution_time_ms,
                "error": tr.error,
            }
            for tr in tool_results
        ],
        "sources_used": list(set(sources)),
        "evidence": evidence,
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        yield f"data: {json.dumps(metadata_payload)}\n\n"

        logging.info(f"[{session_id}] Phase 3: Streaming synthesis...")
        
        for chunk in synthesize_response_stream(query.message, tool_results):
            if await request.is_disconnected():
                break
            token_event = {"type": "token", "content": chunk}
            yield f"data: {json.dumps(token_event)}\n\n"

        total_ms = round((time.time() - start_time) * 1000, 2)
        done_event = {"type": "done", "total_time_ms": total_ms}
        yield f"data: {json.dumps(done_event)}\n\n"

        logging.info(f"[{session_id}] /orchestrate/stream complete in {total_ms}ms")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info(f"Starting EyeAssist Orchestrator on port {SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
