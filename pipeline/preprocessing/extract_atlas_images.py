#!/usr/bin/env python3
"""
EyeAssist Atlas Image Extraction Pipeline
Extracts images from ophthalmology atlas PDFs along with their captions,
figure numbers, and surrounding clinical context.

Builds a structured reference image library at ~/eyeassist/data/images/reference/

Usage:
    python3 extract_atlas_images.py /path/to/atlas.pdf
    python3 extract_atlas_images.py /path/to/atlas.pdf --modality cfp --min-size 100
    python3 extract_atlas_images.py --scan-all
    python3 extract_atlas_images.py --stats
    python3 extract_atlas_images.py --search "macular hole"
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Missing PyMuPDF. Install with: pip3 install PyMuPDF --break-system-packages")
    sys.exit(1)

# === Configuration ===

IMAGE_DIR = os.path.expanduser("~/eyeassist/data/images/reference")
METADATA_DIR = os.path.expanduser("~/eyeassist/data/images/metadata")
MIN_IMAGE_WIDTH = 100   # pixels - skip tiny decorative images
MIN_IMAGE_HEIGHT = 100
MIN_IMAGE_BYTES = 5000  # skip very small files (icons, bullets)

# Modality detection keywords in captions/context
MODALITY_KEYWORDS = {
    "cfp": ["fundus", "color fundus", "fundus photograph", "retinal photograph",
            "optic disc", "optic nerve head", "macula photo"],
    "oct": ["oct", "optical coherence tomography", "b-scan", "retinal layers",
            "cross-section", "thickness map", "rnfl", "ganglion cell"],
    "fa": ["fluorescein", "angiography", "angiogram", "ffa", "early phase",
           "late phase", "arteriovenous phase", "hyperfluorescence"],
    "icg": ["indocyanine", "icg", "icga"],
    "autofluorescence": ["autofluorescence", "faf", "fundus autofluorescence",
                         "hyperautofluorescent", "hypoautofluorescent"],
    "slit_lamp": ["slit-lamp", "slit lamp", "biomicroscopy", "anterior segment photo",
                  "corneal", "iris", "lens opacity", "anterior chamber"],
    "meibography": ["meibography", "meibomian", "infrared", "meiboscore",
                    "gland dropout", "ir image"],
    "external": ["external photo", "face photo", "lid", "proptosis",
                 "strabismus photo", "cover test"],
    "vf": ["visual field", "humphrey", "perimetry", "total deviation",
           "pattern deviation", "grayscale", "threshold"],
    "topography": ["topography", "pentacam", "keratometry", "elevation map",
                   "corneal map", "orbscan", "curvature"],
    "erg": ["erg", "electroretinogram", "scotopic", "photopic", "waveform",
            "a-wave", "b-wave", "flicker"],
    "ultrasound": ["ultrasound", "b-scan ultrasound", "a-scan", "echography",
                   "orbital ultrasound"],
}

# Clinical finding keywords for tagging
FINDING_KEYWORDS = {
    "hemorrhage": ["hemorrhage", "haemorrhage", "bleeding", "blood"],
    "exudate": ["exudate", "hard exudate", "lipid deposit", "circinate"],
    "drusen": ["drusen", "druse", "drusenoid"],
    "edema": ["edema", "oedema", "thickening", "swelling", "cme", "cystoid"],
    "neovascularization": ["neovascularization", "nv", "nvd", "nve", "cnv", "new vessels"],
    "atrophy": ["atrophy", "atrophic", "geographic atrophy", "thinning"],
    "detachment": ["detachment", "detached", "rd", "rhegmatogenous", "tractional"],
    "membrane": ["membrane", "epiretinal", "erm", "pucker"],
    "hole": ["hole", "macular hole", "full-thickness"],
    "infiltrate": ["infiltrate", "corneal infiltrate", "ulcer", "abscess"],
    "opacity": ["opacity", "cataract", "posterior capsule", "lens opacity"],
    "gland_dropout": ["gland dropout", "meibomian loss", "gland atrophy"],
    "disc_edema": ["disc edema", "disc swelling", "papilledema", "papillitis"],
    "cupping": ["cupping", "cup-to-disc", "excavation", "neuroretinal rim"],
    "ischemia": ["ischemia", "ischaemia", "non-perfusion", "cotton wool"],
    "scarring": ["scar", "scarring", "fibrosis", "disciform"],
}


# === Helper Functions ===

def get_image_id(source: str, page: int, img_index: int) -> str:
    """Generate deterministic image ID."""
    content = f"{source}:{page}:{img_index}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def detect_modality(text: str) -> str:
    """Detect imaging modality from caption/context text."""
    text_lower = text.lower()
    scores = {}
    for modality, keywords in MODALITY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[modality] = score
    if scores:
        return max(scores, key=scores.get)
    return "unknown"


def detect_findings(text: str) -> list[str]:
    """Detect clinical findings mentioned in caption/context."""
    text_lower = text.lower()
    findings = []
    for finding, keywords in FINDING_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            findings.append(finding)
    return findings


def extract_figure_number(text: str) -> Optional[str]:
    """Extract figure number from text (e.g., 'Figure 4.12', 'Fig. 3-7')."""
    patterns = [
        r'(?:Figure|Fig\.?)\s*(\d+[\.\-]\d+(?:[\.\-]\d+)?)',
        r'(?:Figure|Fig\.?)\s*(\d+)',
        r'(?:Plate|Image)\s*(\d+[\.\-]?\d*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"Figure {match.group(1)}"
    return None


def get_surrounding_text(page, img_rect, max_chars=500) -> str:
    """Extract text near the image on the same page."""
    page_text_blocks = page.get_text("blocks")
    nearby_text = []

    img_center_y = (img_rect.y0 + img_rect.y1) / 2

    # Sort blocks by vertical distance from image center
    for block in page_text_blocks:
        if block[6] == 0:  # text block (not image)
            block_center_y = (block[1] + block[3]) / 2
            distance = abs(block_center_y - img_center_y)
            text = block[4].strip()
            if text and len(text) > 10:
                nearby_text.append((distance, text))

    nearby_text.sort(key=lambda x: x[0])

    # Take closest text blocks up to max_chars
    result = []
    total_chars = 0
    for _, text in nearby_text:
        if total_chars + len(text) > max_chars:
            break
        result.append(text)
        total_chars += len(text)

    return " ".join(result)


def get_caption_text(page, img_rect) -> str:
    """Extract the most likely caption text (typically just below the image)."""
    page_text_blocks = page.get_text("blocks")
    candidates = []

    for block in page_text_blocks:
        if block[6] == 0:  # text block
            block_top = block[1]
            block_left = block[0]
            text = block[4].strip()

            # Caption is typically just below the image, within ~50 pixels
            vertical_gap = block_top - img_rect.y1
            if 0 < vertical_gap < 80:
                # And horizontally overlapping
                if block_left < img_rect.x1 and block[2] > img_rect.x0:
                    candidates.append((vertical_gap, text))

    # Also check for text just above (some atlases caption above)
    for block in page_text_blocks:
        if block[6] == 0:
            block_bottom = block[3]
            text = block[4].strip()
            vertical_gap = img_rect.y0 - block_bottom
            if 0 < vertical_gap < 50:
                if block[0] < img_rect.x1 and block[2] > img_rect.x0:
                    candidates.append((vertical_gap + 100, text))  # Lower priority

    if candidates:
        candidates.sort(key=lambda x: x[0])
        # Combine close caption blocks
        caption_parts = []
        for _, text in candidates[:3]:
            if any(kw in text.lower() for kw in ["figure", "fig.", "plate", "image"]):
                caption_parts.insert(0, text)  # Figure label goes first
            else:
                caption_parts.append(text)
        return " ".join(caption_parts)

    return ""


# === Main Extraction ===

def extract_images_from_pdf(pdf_path: str, default_modality: str = "unknown",
                            min_width: int = MIN_IMAGE_WIDTH,
                            min_height: int = MIN_IMAGE_HEIGHT) -> list[dict]:
    """Extract all qualifying images from a PDF with metadata."""
    pdf_path = os.path.abspath(pdf_path)
    filename = os.path.basename(pdf_path)
    doc = fitz.open(pdf_path)

    print(f"\n{'='*60}")
    print(f"Extracting images from: {filename}")
    print(f"Pages: {len(doc)}")
    print(f"{'='*60}")

    extracted = []
    skipped_small = 0
    skipped_bytes = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]

            try:
                # Extract image
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                image_ext = base_image.get("ext", "png")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Filter by size
                if width < min_width or height < min_height:
                    skipped_small += 1
                    continue

                if len(image_bytes) < MIN_IMAGE_BYTES:
                    skipped_bytes += 1
                    continue

                # Get image rectangle on page for spatial text analysis
                img_rects = page.get_image_rects(xref)
                img_rect = img_rects[0] if img_rects else fitz.Rect(0, 0, width, height)

                # Extract caption and context
                caption = get_caption_text(page, img_rect)
                context = get_surrounding_text(page, img_rect)
                figure_number = extract_figure_number(caption) or extract_figure_number(context)

                # Detect modality and findings
                combined_text = f"{caption} {context}"
                modality = detect_modality(combined_text)
                if modality == "unknown":
                    modality = default_modality
                findings = detect_findings(combined_text)

                # Generate ID and file path
                image_id = get_image_id(filename, page_num + 1, img_index)
                image_filename = f"{image_id}.{image_ext}"

                metadata = {
                    "image_id": image_id,
                    "source_pdf": filename,
                    "page_number": page_num + 1,
                    "figure_number": figure_number,
                    "caption": caption[:500] if caption else "",
                    "clinical_context": context[:800] if context else "",
                    "modality": modality,
                    "finding_tags": findings,
                    "width": width,
                    "height": height,
                    "file_size_bytes": len(image_bytes),
                    "image_filename": image_filename,
                    "extracted_at": datetime.now().isoformat(),
                }

                extracted.append({
                    "metadata": metadata,
                    "image_bytes": image_bytes,
                    "image_ext": image_ext,
                })

            except Exception as e:
                print(f"  Warning: Failed to extract image on page {page_num + 1}: {e}")
                continue

        # Progress
        if (page_num + 1) % 50 == 0:
            print(f"  Processed {page_num + 1}/{len(doc)} pages, {len(extracted)} images extracted...")

    doc.close()

    print(f"\nExtraction complete:")
    print(f"  Total images extracted: {len(extracted)}")
    print(f"  Skipped (too small): {skipped_small}")
    print(f"  Skipped (too few bytes): {skipped_bytes}")

    return extracted


def save_extracted_images(images: list[dict], organize_by: str = "modality"):
    """Save extracted images and metadata to disk."""
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(METADATA_DIR, exist_ok=True)

    saved = 0
    for img_data in images:
        meta = img_data["metadata"]
        image_bytes = img_data["image_bytes"]

        # Organize by modality or source
        if organize_by == "modality":
            subdir = os.path.join(IMAGE_DIR, meta["modality"])
        elif organize_by == "source":
            source_name = Path(meta["source_pdf"]).stem
            subdir = os.path.join(IMAGE_DIR, source_name)
        else:
            subdir = IMAGE_DIR

        os.makedirs(subdir, exist_ok=True)

        # Save image
        image_path = os.path.join(subdir, meta["image_filename"])
        with open(image_path, "wb") as f:
            f.write(image_bytes)

        # Update metadata with saved path
        meta["image_path"] = image_path

        # Save metadata sidecar
        meta_path = os.path.join(METADATA_DIR, f"{meta['image_id']}.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        saved += 1

    print(f"Saved {saved} images to {IMAGE_DIR}")
    return saved


def scan_all_atlases():
    """Scan all PDF files in the documents directories for atlas images."""
    doc_root = os.path.expanduser("~/eyeassist/data/documents")
    atlas_patterns = ["atlas", "diagnostic", "clinical signs", "kanski"]

    # Find PDFs that are likely atlases (image-heavy)
    all_pdfs = []
    for root, dirs, files in os.walk(doc_root):
        for f in files:
            if f.lower().endswith(".pdf"):
                all_pdfs.append(os.path.join(root, f))

    print(f"Found {len(all_pdfs)} PDFs in documents directory.")
    print("Processing atlas-like PDFs...")

    total_images = 0
    for pdf_path in sorted(all_pdfs):
        filename = os.path.basename(pdf_path).lower()
        # Prioritize likely atlases but process all
        is_atlas = any(p in filename for p in atlas_patterns)

        if is_atlas:
            print(f"\n*** ATLAS: {os.path.basename(pdf_path)} ***")
        else:
            print(f"\nProcessing: {os.path.basename(pdf_path)}")

        images = extract_images_from_pdf(pdf_path)
        if images:
            saved = save_extracted_images(images)
            total_images += saved

    print(f"\n{'='*60}")
    print(f"Total images extracted across all PDFs: {total_images}")
    print(f"Image library location: {IMAGE_DIR}")
    print(f"Metadata location: {METADATA_DIR}")
    print(f"{'='*60}")


def show_stats():
    """Show statistics about the image library."""
    if not os.path.exists(METADATA_DIR):
        print("No metadata found. Run extraction first.")
        return

    meta_files = list(Path(METADATA_DIR).glob("*.json"))
    print(f"\nImage Library Statistics")
    print(f"{'='*50}")
    print(f"Total images: {len(meta_files)}")

    # Count by modality
    modality_counts = {}
    source_counts = {}
    finding_counts = {}
    with_caption = 0
    with_figure_num = 0

    for mf in meta_files:
        with open(mf) as f:
            meta = json.load(f)

        mod = meta.get("modality", "unknown")
        modality_counts[mod] = modality_counts.get(mod, 0) + 1

        src = meta.get("source_pdf", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

        for finding in meta.get("finding_tags", []):
            finding_counts[finding] = finding_counts.get(finding, 0) + 1

        if meta.get("caption"):
            with_caption += 1
        if meta.get("figure_number"):
            with_figure_num += 1

    print(f"\nBy modality:")
    for mod, count in sorted(modality_counts.items(), key=lambda x: -x[1]):
        print(f"  {mod:<20} {count:>5}")

    print(f"\nBy source:")
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<50} {count:>5}")

    print(f"\nBy clinical finding:")
    for finding, count in sorted(finding_counts.items(), key=lambda x: -x[1]):
        print(f"  {finding:<20} {count:>5}")

    print(f"\nCaption coverage: {with_caption}/{len(meta_files)} ({100*with_caption/max(len(meta_files),1):.1f}%)")
    print(f"Figure number coverage: {with_figure_num}/{len(meta_files)} ({100*with_figure_num/max(len(meta_files),1):.1f}%)")


def search_images(query: str, n_results: int = 10):
    """Search the image library by caption/context text."""
    if not os.path.exists(METADATA_DIR):
        print("No metadata found. Run extraction first.")
        return

    query_lower = query.lower()
    results = []

    for mf in Path(METADATA_DIR).glob("*.json"):
        with open(mf) as f:
            meta = json.load(f)

        searchable = f"{meta.get('caption', '')} {meta.get('clinical_context', '')} {meta.get('modality', '')} {' '.join(meta.get('finding_tags', []))}".lower()

        # Simple keyword matching (will be replaced by embedding search in Phase 2)
        score = sum(1 for word in query_lower.split() if word in searchable)
        if score > 0:
            results.append((score, meta))

    results.sort(key=lambda x: -x[0])

    print(f"\nSearch: \"{query}\"")
    print(f"Results: {min(len(results), n_results)} of {len(results)} matches")
    print("-" * 60)

    for i, (score, meta) in enumerate(results[:n_results]):
        print(f"\n--- Result {i+1} (relevance: {score}) ---")
        print(f"  Source: {meta['source_pdf']} | Page {meta['page_number']}")
        print(f"  Figure: {meta.get('figure_number', 'N/A')}")
        print(f"  Modality: {meta['modality']}")
        print(f"  Findings: {', '.join(meta.get('finding_tags', [])) or 'none detected'}")
        caption = meta.get('caption', '')
        if caption:
            print(f"  Caption: {caption[:200]}{'...' if len(caption) > 200 else ''}")
        print(f"  File: {meta.get('image_path', meta['image_filename'])}")


# === CLI ===

def main():
    parser = argparse.ArgumentParser(description="EyeAssist Atlas Image Extraction Pipeline")
    parser.add_argument("path", nargs="?", help="Path to atlas PDF")
    parser.add_argument("--modality", "-m", default="unknown",
                       help="Default modality if auto-detection fails")
    parser.add_argument("--min-size", type=int, default=MIN_IMAGE_WIDTH,
                       help="Minimum image dimension in pixels")
    parser.add_argument("--organize-by", choices=["modality", "source"], default="modality",
                       help="How to organize extracted images")
    parser.add_argument("--scan-all", action="store_true",
                       help="Scan all PDFs in the documents directory")
    parser.add_argument("--stats", action="store_true",
                       help="Show image library statistics")
    parser.add_argument("--search", "-s", help="Search image library by keywords")
    parser.add_argument("--n-results", "-n", type=int, default=10,
                       help="Number of search results")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.search:
        search_images(args.search, args.n_results)
        return

    if args.scan_all:
        scan_all_atlases()
        return

    if not args.path:
        parser.print_help()
        return

    images = extract_images_from_pdf(
        args.path,
        default_modality=args.modality,
        min_width=args.min_size,
        min_height=args.min_size,
    )

    if images:
        save_extracted_images(images, organize_by=args.organize_by)


if __name__ == "__main__":
    main()
