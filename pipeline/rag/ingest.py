#!/usr/bin/env python3
"""
EyeAssist RAG Ingestion Pipeline
Processes PDF/text documents into ChromaDB for retrieval-augmented generation.

Usage:
    python ingest.py /path/to/document.pdf --collection posterior_segment
    python ingest.py /path/to/documents/ --collection anterior_segment --batch
    python ingest.py --list-collections
    python ingest.py --query "TFOS DEWS II dry eye classification" --collection anterior_segment
"""

import argparse
import os
import sys
import hashlib
import json
from pathlib import Path
from typing import Optional

# --- Install dependencies if needed ---
def check_deps():
    missing = []
    try:
        import chromadb
    except ImportError:
        missing.append("chromadb")
    try:
        import sentence_transformers
    except ImportError:
        missing.append("sentence-transformers")
    try:
        import fitz  # PyMuPDF
    except ImportError:
        missing.append("PyMuPDF")
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)} --break-system-packages")
        sys.exit(1)

check_deps()

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import fitz  # PyMuPDF

# Suppress ChromaDB telemetry noise (capture() signature mismatch)
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# === Configuration ===

CHROMA_DIR = os.path.expanduser("~/eyeassist/data/chromadb")
CHUNK_SIZE = 800       # tokens (approximate, using word count / 0.75)
CHUNK_OVERLAP = 128    # token overlap between chunks

# CHANGED: PubMedBERT — 768-dim, trained on PubMed title-abstract pairs
# Replaces: "all-MiniLM-L6-v2" (384-dim, general English)
# NOTE: ChromaDB was wiped and re-ingested with this model on 2026-03-30.
#       Do NOT revert without wiping ChromaDB again — dimension mismatch will corrupt queries.
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"

COLLECTIONS = {
    "cornea":"Corneal disease in practice",
    "general":"General ophthalmology including cataracts",
    "glaucoma":"Glaucoma practice",
    "neuro":"Neuro-ophthalmology practice",
    "oculoplastics":"Lid procedures",
    "osd":"Ocular surface disease",
    "pediatric":"Pediatric specific practice such as strabismus",
    "refractive":"Refractive surgery, etc.",
    "retina":"Retinal practice",
    "uveitis":"Uveitis entities"
    }

# === Helper Functions ===

def get_chroma_client():
    """Initialize persistent ChromaDB client."""
    os.makedirs(CHROMA_DIR, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_DIR)


def get_embedding_model():
    """Load sentence transformer embedding model."""
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Embedding model loaded. Dimension: {model.get_sentence_embedding_dimension()}")
    return model


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """Extract text from PDF, returning a list of page dicts."""
    doc = fitz.open(pdf_path)
    pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append({
                "page_number": page_num + 1,
                "text": text.strip(),
            })
    doc.close()
    return pages


def extract_text_from_txt(txt_path: str) -> list[dict]:
    """Extract text from a plain text file."""
    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return [{"page_number": 1, "text": text.strip()}]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into chunks by approximate token count.
    Uses paragraph boundaries where possible for semantic coherence.
    """
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_word_count = 0
    target_words = int(chunk_size * 0.75)  # rough tokens-to-words conversion
    overlap_words = int(overlap * 0.75)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_words = len(para.split())

        # If a single paragraph exceeds chunk size, split by sentences
        if para_words > target_words:
            sentences = para.replace(". ", ".\n").split("\n")
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sent_words = len(sent.split())
                if current_word_count + sent_words > target_words and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    # Keep overlap
                    overlap_text = " ".join(current_chunk).split()
                    current_chunk = overlap_text[-overlap_words:] if len(overlap_text) > overlap_words else overlap_text
                    current_word_count = len(current_chunk)
                current_chunk.append(sent)
                current_word_count += sent_words
        else:
            if current_word_count + para_words > target_words and current_chunk:
                chunks.append(" ".join(current_chunk))
                overlap_text = " ".join(current_chunk).split()
                current_chunk = overlap_text[-overlap_words:] if len(overlap_text) > overlap_words else overlap_text
                current_word_count = len(current_chunk)
            current_chunk.append(para)
            current_word_count += para_words

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return [c for c in chunks if len(c.split()) > 20]  # Filter tiny chunks


def generate_chunk_id(source: str, page: int, chunk_idx: int) -> str:
    """Generate deterministic ID for deduplication."""
    content = f"{source}:{page}:{chunk_idx}"
    return hashlib.md5(content.encode()).hexdigest()


# === Main Operations ===

def ingest_document(file_path: str, collection_name: str, domain_tags: Optional[list] = None):
    """Ingest a single document into ChromaDB."""
    file_path = os.path.abspath(file_path)
    filename = os.path.basename(file_path)
    ext = Path(file_path).suffix.lower()

    print(f"\n{'='*60}")
    print(f"Ingesting: {filename}")
    print(f"Collection: {collection_name}")
    print(f"{'='*60}")

    # Extract text
    if ext == ".pdf":
        pages = extract_text_from_pdf(file_path)
    elif ext in (".txt", ".md"):
        pages = extract_text_from_txt(file_path)
    else:
        print(f"Unsupported file type: {ext}")
        return

    if not pages:
        print("No text extracted from document.")
        return

    print(f"Extracted text from {len(pages)} pages.")

    # Chunk
    all_chunks = []
    for page_data in pages:
        chunks = chunk_text(page_data["text"])
        for idx, chunk in enumerate(chunks):
            all_chunks.append({
                "id": generate_chunk_id(filename, page_data["page_number"], idx),
                "text": chunk,
                "metadata": {
                    "source": filename,
                    "page": page_data["page_number"],
                    "chunk_index": idx,
                    "collection": collection_name,
                    "domain_tags": json.dumps(domain_tags or []),
                    "char_count": len(chunk),
                    "word_count": len(chunk.split()),
                    "embedding_model": EMBEDDING_MODEL,  # NEW: track model version in metadata
                },
            })

    print(f"Created {len(all_chunks)} chunks.")

    if not all_chunks:
        print("No chunks to ingest.")
        return

    # Embed
    model = get_embedding_model()
    texts = [c["text"] for c in all_chunks]
    print(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32).tolist()

    # Store in ChromaDB
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "description": COLLECTIONS.get(collection_name, "Custom collection"),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimension": 768,
            "hnsw:space": "cosine",  # cosine distance — scores in 0-2 range, lower is better
        },
    )

    # Upsert in batches (ChromaDB has limits on batch size)
    batch_size = 100
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
            embeddings=batch_embeddings,
        )

    print(f"\nSuccess! Ingested {len(all_chunks)} chunks into '{collection_name}'.")
    print(f"Collection now has {collection.count()} total chunks.")


def ingest_directory(dir_path: str, collection_name: str, domain_tags: Optional[list] = None):
    """Ingest all supported documents in a directory."""
    supported = {".pdf", ".txt", ".md"}
    files = [f for f in Path(dir_path).iterdir() if f.suffix.lower() in supported]
    if not files:
        print(f"No supported files found in {dir_path}")
        return
    print(f"Found {len(files)} documents to ingest.")
    for f in sorted(files):
        ingest_document(str(f), collection_name, domain_tags)


def list_collections():
    """List all ChromaDB collections and their stats."""
    client = get_chroma_client()
    collections = client.list_collections()
    if not collections:
        print("No collections found. Ingest some documents first!")
        return
    print(f"\n{'Collection':<30} {'Chunks':<10} {'Embed Model':<45} {'Description'}")
    print("-" * 120)
    for col_info in collections:
        col = client.get_collection(str(col_info))
        desc = col.metadata.get("description", "")
        embed = col.metadata.get("embedding_model", "unknown")
        print(f"{str(col_info):<30} {col.count():<10} {embed:<45} {desc}")


def query_collection(query: str, collection_name: str, n_results: int = 5):
    """Test query against a collection."""
    model = get_embedding_model()
    query_embedding = model.encode([query]).tolist()

    client = get_chroma_client()
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        print(f"Collection '{collection_name}' not found.")
        return

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    print(f"\nQuery: \"{query}\"")
    print(f"Collection: {collection_name}")
    print(f"Results: {len(results['documents'][0])}")
    print("-" * 80)

    for i, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
    ):
        print(f"\n--- Result {i+1} (distance: {dist:.4f}) ---")
        print(f"Source: {meta.get('source', 'unknown')} | Page: {meta.get('page', '?')}")
        # Show first 300 chars
        preview = doc[:300] + "..." if len(doc) > 300 else doc
        print(f"Content: {preview}")


# === CLI ===

def main():
    parser = argparse.ArgumentParser(description="EyeAssist RAG Ingestion Pipeline")
    parser.add_argument("path", nargs="?", help="Path to document or directory")
    parser.add_argument(
        "--collection", "-c",
        choices=list(COLLECTIONS.keys()) + ["custom"],
        default="general_ophthalmology",
        help="Target collection",
    )
    parser.add_argument("--batch", "-b", action="store_true", help="Ingest all files in directory")
    parser.add_argument("--tags", "-t", nargs="+", help="Domain tags (e.g., retina glaucoma)")
    parser.add_argument("--list-collections", "-l", action="store_true", help="List all collections")
    parser.add_argument("--query", "-q", help="Test query against a collection")
    parser.add_argument("--n-results", "-n", type=int, default=5, help="Number of query results")

    args = parser.parse_args()

    if args.list_collections:
        list_collections()
        return

    if args.query:
        query_collection(args.query, args.collection, args.n_results)
        return

    if not args.path:
        parser.print_help()
        return

    if args.batch or os.path.isdir(args.path):
        ingest_directory(args.path, args.collection, args.tags)
    else:
        ingest_document(args.path, args.collection, args.tags)


if __name__ == "__main__":
    main()
