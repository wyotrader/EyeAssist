#!/bin/bash
set -e
echo "============================================"
echo "  EyeAssist Full RAG Re-ingestion"
echo "============================================"

ROOT="${EYEASSIST_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON="${EYEASSIST_PYTHON:-$ROOT/.venv/bin/python}"
ingest() { "$PYTHON" "$ROOT/pipeline/rag/ingest.py" "$@"; }
DOCS="$ROOT/data/documents"

echo "[1/10] General..."
ingest "$DOCS/general/" -c general -t "general" "textbook" --batch

echo "[2/10] Retina..."
ingest "$DOCS/retina/" -c retina -t "retina" --batch

echo "[3/10] Neuro..."
ingest "$DOCS/neuro/" -c neuro -t "neuro" --batch

echo "[4/10] OSD..."
ingest "$DOCS/osd/" -c osd -t "dry_eye" "OSD" --batch

echo "[5/10] Glaucoma..."
ingest "$DOCS/glaucoma/" -c glaucoma -t "glaucoma" --batch

echo "[6/10] Cornea..."
ingest "$DOCS/cornea/" -c cornea -t "cornea" --batch

echo "[7/10] Pediatric..."
ingest "$DOCS/pediatric/" -c pediatric -t "pediatric" --batch

echo "[8/10] Refractive..."
ingest "$DOCS/refractive/" -c refractive -t "refractive" --batch

echo "[9/10] Oculoplastics..."
ingest "$DOCS/oculoplastics/" -c oculoplastics -t "oculoplastics" --batch

echo "[10/10] Uveitis..."
ingest "$DOCS/uveitis/" -c uveitis -t "uveitis" --batch

echo ""
echo "============================================"
echo "  Re-ingestion complete!"
echo "============================================"
ingest --list-collections
