#!/usr/bin/env python3
"""
EyeAssist RAG Service
FastAPI service that provides retrieval-augmented generation from ChromaDB.
Runs on port 8100 and serves as the bridge between the EyeAssist gateway and the knowledge base.

Usage:
    python3 rag_service.py
    # Or with uvicorn directly:
    uvicorn rag_service:app --host 0.0.0.0 --port 8100
"""

import os
import json
import logging
from typing import Optional
from contextlib import asynccontextmanager

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
import unittest.mock as _mock
import sys as _sys
_sys.modules["posthog"] = _mock.MagicMock()
import chromadb
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Suppress ChromaDB telemetry noise (capture() signature mismatch)

# === Configuration ===

CHROMA_DIR = os.path.expanduser("~/eyeassist/data/chromadb")

# CHANGED: PubMedBERT — 768-dim, trained on PubMed title-abstract pairs
# Replaces: "all-MiniLM-L6-v2" (384-dim, general English)
# NOTE: ChromaDB was wiped and re-ingested with this model on 2026-03-30.
#       Do NOT revert without wiping ChromaDB again — dimension mismatch will corrupt queries.
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"

DEFAULT_N_RESULTS = 5
MAX_N_RESULTS = 15
SERVICE_PORT = 8100

# Distance threshold for cosine space (0-2 range, lower = more similar).
# 0.5 = tight/high confidence, 0.9 = reasonable relevance cutoff. Tune as needed.
RELEVANCE_THRESHOLD = 0.9

# Collection-to-subspecialty routing keywords
COLLECTION_ROUTING = {
    "osd": ["dry eye", "meibomian", "mgd", "tear film", "tbut", "schirmer", "osdi",
            "ocular surface", "blepharitis", "lid margin", "meibography", "lipid layer",
            "evaporative", "aqueous deficient", "dews", "tfos"],
    "cornea": ["cornea", "keratitis", "keratoconus", "corneal", "ectasia", "fuchs",
               "dystrophy", "endothelial", "crosslinking", "cxl", "transplant", "graft",
               "pterygium", "ulcer"],
    "glaucoma": ["glaucoma", "iop", "intraocular pressure", "optic nerve", "cup to disc",
                 "rnfl", "visual field", "humphrey", "oct nerve", "trabeculectomy",
                 "tube shunt", "slt", "angle", "gonioscopy", "progression"],
    "retina": ["retina", "diabetic retinopathy", "macular", "amd", "drusen",
               "anti-vegf", "injection", "oct macula", "vitreous", "detachment",
               "vein occlusion", "artery occlusion", "epiretinal", "edema", "npdr", "pdr"],
    "pediatric": ["pediatric", "amblyopia", "strabismus", "lazy eye", "patching",
                  "rop", "retinopathy of prematurity", "child", "infant"],
    "neuro": ["neuro", "optic neuritis", "papilledema", "visual pathway", "nystagmus",
              "cranial nerve", "pupil", "diplopia", "idiopathic intracranial"],
    "uveitis": ["uveitis", "iritis", "panuveitis", "intermediate uveitis", "posterior uveitis",
                "choroiditis", "vasculitis", "sarcoid", "behcet", "hla-b27"],
    "refractive": ["refractive", "lasik", "prk", "smile", "iol", "lens implant",
                   "cataract", "phaco", "presbyopia", "myopia control"],
    "general": ["comprehensive", "exam", "screening", "icd", "coding", "drug",
                "medication", "preservative", "allergy"],
}

# === Global State ===
embedding_model = None
chroma_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup."""
    global embedding_model, chroma_client
    logging.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    logging.info(f"Embedding model loaded. Dimension: {embedding_model.get_sentence_embedding_dimension()}")
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR, settings=chromadb.Settings(anonymized_telemetry=False))
    logging.info(f"ChromaDB connected at {CHROMA_DIR}")

    # List available collections
    collections = chroma_client.list_collections()
    for col in collections:
        c = chroma_client.get_collection(str(col))
        embed = c.metadata.get("embedding_model", "unknown")
        logging.info(f"  Collection '{str(col)}': {c.count()} chunks [model: {embed}]")

    yield

    logging.info("RAG service shutting down.")


# === FastAPI App ===

app = FastAPI(
    title="EyeAssist RAG Service",
    description="Retrieval-augmented generation service for ophthalmology knowledge",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Request/Response Models ===

class RAGQuery(BaseModel):
    query: str
    collection: Optional[str] = None  # If None, auto-route based on query content
    n_results: int = DEFAULT_N_RESULTS
    include_metadata: bool = True


class RAGResult(BaseModel):
    text: str
    source: str
    page: int
    distance: float
    collection: str


class RAGResponse(BaseModel):
    query: str
    collection_searched: str
    results: list[RAGResult]
    context_block: str  # Pre-formatted context block ready to inject into LLM prompt


class ContextInjectRequest(BaseModel):
    """Request format for gateway context injection."""
    message: str
    collections: Optional[list[str]] = None
    n_results: int = DEFAULT_N_RESULTS


class ContextInjectResponse(BaseModel):
    """Returns the user message with RAG context prepended."""
    original_message: str
    augmented_message: str
    sources_used: list[str]
    collections_searched: list[str]


# === Routing Logic ===

def detect_collections(query: str) -> list[str]:
    """Detect which collections to search based on query content."""
    query_lower = query.lower()
    scores = {}

    for collection, keywords in COLLECTION_ROUTING.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[collection] = score

    if not scores:
        # Default: search general + osd + retina (most common)
        return ["general", "osd", "retina"]

    # Return top 2 matching collections (or 1 if there's a clear winner)
    sorted_collections = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_collections) == 1 or sorted_collections[0][1] > sorted_collections[1][1] * 2:
        return [sorted_collections[0][0]]
    return [c[0] for c in sorted_collections[:2]]


def format_context_block(results: list[RAGResult]) -> str:
    """Format retrieved chunks into a context block for the LLM."""
    if not results:
        return ""

    lines = [
        "=== RETRIEVED CLINICAL REFERENCES ===",
        "The following evidence was retrieved from the EyeAssist knowledge base.",
        "Use this information to ground your response. Cite sources when referencing specific guidelines.",
        ""
    ]

    for i, r in enumerate(results, 1):
        lines.append(f"--- Reference {i} (Source: {r.source}, Page {r.page}) ---")
        lines.append(r.text)
        lines.append("")

    lines.append("=== END REFERENCES ===")
    return "\n".join(lines)


# === Endpoints ===

@app.get("/health")
async def health():
    """Health check."""
    collections = chroma_client.list_collections()
    col_info = {}
    for col in collections:
        c = chroma_client.get_collection(str(col))
        col_info[str(col)] = c.count()
    return {
        "status": "healthy",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": 768,
        "relevance_threshold": RELEVANCE_THRESHOLD,
        "collections": col_info,
        "total_chunks": sum(col_info.values()),
    }


@app.post("/query", response_model=RAGResponse)
async def query_rag(request: RAGQuery):
    """Query a specific collection or auto-route."""
    n = min(request.n_results, MAX_N_RESULTS)

    # Determine collection(s) to search
    if request.collection:
        collections_to_search = [request.collection]
    else:
        collections_to_search = detect_collections(request.query)

    # Embed query
    query_embedding = embedding_model.encode([request.query]).tolist()

    # Search across collections
    all_results = []
    collection_searched = []

    for col_name in collections_to_search:
        try:
            collection = chroma_client.get_collection(col_name)
        except Exception:
            continue

        collection_searched.append(col_name)
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                all_results.append(RAGResult(
                    text=doc,
                    source=meta.get("source", "unknown"),
                    page=meta.get("page", 0),
                    distance=dist,
                    collection=col_name,
                ))

    # Sort by distance and take top n
    all_results.sort(key=lambda x: x.distance)
    top_results = all_results[:n]

    # Format context block
    context_block = format_context_block(top_results)

    return RAGResponse(
        query=request.query,
        collection_searched=", ".join(collection_searched),
        results=top_results,
        context_block=context_block,
    )


@app.post("/inject", response_model=ContextInjectResponse)
async def inject_context(request: ContextInjectRequest):
    """
    Main endpoint for gateway context injection.
    Takes a user message, retrieves relevant context, and returns
    an augmented message with RAG context prepended.
    """
    # Auto-detect or use specified collections
    if request.collections:
        collections_to_search = request.collections
    else:
        collections_to_search = detect_collections(request.message)

    # Embed and search
    query_embedding = embedding_model.encode([request.message]).tolist()
    all_results = []

    for col_name in collections_to_search:
        try:
            collection = chroma_client.get_collection(col_name)
        except Exception:
            continue

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=request.n_results,
            include=["documents", "metadatas", "distances"],
        )

        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                # CHANGED: threshold 1.2 → RELEVANCE_THRESHOLD (0.9) for PubMedBERT cosine space
                if dist < RELEVANCE_THRESHOLD:
                    all_results.append(RAGResult(
                        text=doc,
                        source=meta.get("source", "unknown"),
                        page=meta.get("page", 0),
                        distance=dist,
                        collection=col_name,
                    ))

    # Sort and take top results
    all_results.sort(key=lambda x: x.distance)
    top_results = all_results[:request.n_results]

    # Build augmented message
    sources = list(set(r.source for r in top_results))
    context_block = format_context_block(top_results)

    if context_block:
        augmented = f"{context_block}\n\n--- USER QUESTION ---\n{request.message}"
    else:
        augmented = request.message

    return ContextInjectResponse(
        original_message=request.message,
        augmented_message=augmented,
        sources_used=sources,
        collections_searched=collections_to_search,
    )


@app.get("/collections")
async def list_collections():
    """List all available collections."""
    collections = chroma_client.list_collections()
    result = {}
    for col in collections:
        c = chroma_client.get_collection(str(col))
        result[str(col)] = {
            "chunks": c.count(),
            "description": c.metadata.get("description", ""),
            "embedding_model": c.metadata.get("embedding_model", "unknown"),
        }
    return result


# === Run ===

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    logging.info(f"Starting EyeAssist RAG Service on port {SERVICE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
