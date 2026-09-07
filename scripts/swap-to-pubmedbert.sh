#!/usr/bin/env bash
# =============================================================================
# EyeAssist — ChromaDB Reingest with Cosine Distance
# Wipes ChromaDB and re-ingests all collections with:
#   - NeuML/pubmedbert-base-embeddings (768-dim)
#   - hnsw:space = cosine (scores 0-2, replaces L2 default)
#
# Run as jwhitman on eyeassist-dev
# Estimated time: 2-4 hours (18,966 chunks, CPU only)
#
# Usage:
#   chmod +x swap-to-pubmedbert.sh
#   ./swap-to-pubmedbert.sh
#
# To run in background (recommended):
#   nohup ./swap-to-pubmedbert.sh > ~/eyeassist/logs/pubmedbert-swap.log 2>&1 &
#   tail -f ~/eyeassist/logs/pubmedbert-swap.log
# =============================================================================

set -e

VENV="$HOME/eyeassist/venv"
PYTHON="$VENV/bin/python"
INGEST="$HOME/eyeassist/pipeline/rag/ingest.py"
CHROMA_DIR="$HOME/eyeassist/data/chromadb"
DOCS_DIR="$HOME/eyeassist/data/documents"
LOG_DIR="$HOME/eyeassist/logs"
MODEL="NeuML/pubmedbert-base-embeddings"

mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/pubmedbert-swap-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================"
echo "  EyeAssist — PubMedBERT Embedding Swap"
echo "  Started: $(date)"
echo "  Log: $LOGFILE"
echo "================================================================"
echo ""

# --- Step 1: Stop RAG-dependent services ---
echo "[1/6] Stopping services..."
sudo systemctl stop eyeassist-orchestrator eyeassist-rag
echo "      eyeassist-orchestrator and eyeassist-rag stopped."
echo ""

# --- Step 2: Download PubMedBERT model into local cache ---
echo "[2/6] Pre-downloading PubMedBERT model (cached to ~/.cache/huggingface)..."
$PYTHON - <<EOF
from sentence_transformers import SentenceTransformer
import os
model_name = "$MODEL"
print(f"Downloading: {model_name}")
model = SentenceTransformer(model_name)
dim = model.get_sentence_embedding_dimension()
print(f"Downloaded successfully. Embedding dimension: {dim}")
assert dim == 768, f"Expected 768 dimensions, got {dim}. Wrong model!"
print("Dimension check passed.")
EOF
echo ""

# --- Step 3: Back up ChromaDB ---
echo "[3/6] Backing up existing ChromaDB..."
BACKUP_DIR="$HOME/eyeassist/data/chromadb-backup-$(date +%Y%m%d-%H%M%S)"
cp -r "$CHROMA_DIR" "$BACKUP_DIR"
echo "      Backup saved to: $BACKUP_DIR"
echo ""

# --- Step 4: Wipe ChromaDB ---
echo "[4/6] Wiping ChromaDB..."
rm -rf "$CHROMA_DIR"
mkdir -p "$CHROMA_DIR"
echo "      ChromaDB wiped clean."
echo ""

# --- Step 5: Re-ingest all collections ---
echo "[5/6] Starting full re-ingestion..."
echo "      This will take 2-4 hours on CPU."
echo ""

# Map each collection directory to its collection name
# Adjust paths if your layout differs
declare -A COLLECTION_MAP=(
    ["cornea"]="cornea"
    ["general"]="general"
    ["glaucoma"]="glaucoma"
    ["neuro"]="neuro"
    ["oculoplastics"]="oculoplastics"
    ["osd"]="osd"
    ["pediatric"]="pediatric"
    ["refractive"]="refractive"
    ["retina"]="retina"
    ["uveitis"]="uveitis"
)

TOTAL_COLLECTIONS=${#COLLECTION_MAP[@]}
CURRENT=0

for COLLECTION in "${!COLLECTION_MAP[@]}"; do
    CURRENT=$((CURRENT + 1))
    DIR="$DOCS_DIR/$COLLECTION"
    COL_NAME="${COLLECTION_MAP[$COLLECTION]}"

    if [ ! -d "$DIR" ]; then
        echo "  [$CURRENT/$TOTAL_COLLECTIONS] SKIP: $DIR not found"
        continue
    fi

    FILE_COUNT=$(find "$DIR" -maxdepth 1 \( -name "*.pdf" -o -name "*.txt" -o -name "*.md" \) | wc -l)
    if [ "$FILE_COUNT" -eq 0 ]; then
        echo "  [$CURRENT/$TOTAL_COLLECTIONS] SKIP: $DIR is empty"
        continue
    fi

    echo "  [$CURRENT/$TOTAL_COLLECTIONS] Ingesting collection: $COL_NAME ($FILE_COUNT files)"
    $PYTHON "$INGEST" "$DIR" --collection "$COL_NAME" --batch 2>&1 | tee -a "$LOGFILE"
    echo ""
done

# --- Step 6: Verify and restart services ---
echo "[6/6] Verifying results..."
$PYTHON "$INGEST" --list-collections

echo ""
echo "Restarting services..."
sudo systemctl start eyeassist-rag
sleep 5  # Give RAG a moment to load the model

# Quick health check
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/health)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "RAG service health check: OK (200)"
    curl -s http://localhost:8100/health | python3 -m json.tool
else
    echo "WARNING: RAG service returned HTTP $HTTP_STATUS — check logs"
    echo "  sudo journalctl -u eyeassist-rag -n 50"
fi

sudo systemctl start eyeassist-orchestrator
echo "eyeassist-orchestrator started."

echo ""
echo "================================================================"
echo "  PubMedBERT swap complete!"
echo "  Finished: $(date)"
echo "  Full log: $LOGFILE"
echo "  Backup (old MiniLM DB): $BACKUP_DIR"
echo "================================================================"
echo ""
echo "Next steps:"
echo "  1. Run validation queries:"
echo "     $PYTHON $INGEST --query 'TFOS DEWS II evaporative dry eye' --collection osd"
echo "     $PYTHON $INGEST --query 'RNFL thinning glaucomatous optic neuropathy' --collection glaucoma"
echo "     $PYTHON $INGEST --query 'disc edema papilledema vs pseudopapilledema' --collection neuro"
echo "  2. Check /inject distance scores in EyeAssist UI for a few real queries"
echo "  3. If retrieval looks sparse, raise RELEVANCE_THRESHOLD in rag_service.py (try 1.0)"
echo "  4. Once validated, delete the backup: rm -rf $BACKUP_DIR"
