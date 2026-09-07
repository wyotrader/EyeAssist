#!/usr/bin/env python3
"""
EyeAssist Vision Pipeline Test Suite
Tests all endpoints with sample data to verify the API is working correctly.

Usage: python3 test_vision.py
"""

import requests
import json
import sys
import os

BASE_URL = "http://localhost:8200"

# Create a tiny test image (1x1 pixel PNG)
TINY_PNG = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
    0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00,
    0x0C, 0x49, 0x44, 0x41, 0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
    0x00, 0x00, 0x02, 0x00, 0x01, 0xE2, 0x21, 0xBC, 0x33, 0x00, 0x00, 0x00,
    0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
])


def test(name, method, endpoint, **kwargs):
    """Run a single test."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"  {method.upper()} {endpoint}")
    try:
        if method == "get":
            r = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
        elif method == "post":
            r = requests.post(f"{BASE_URL}{endpoint}", timeout=10, **kwargs)
        else:
            print(f"  SKIP: Unknown method {method}")
            return False

        if r.status_code == 200:
            data = r.json()
            print(f"  STATUS: {r.status_code} OK")
            # Print key fields
            if isinstance(data, dict):
                for key in list(data.keys())[:8]:
                    val = data[key]
                    if isinstance(val, dict):
                        print(f"  {key}: {json.dumps(val, indent=2)[:200]}")
                    elif isinstance(val, list):
                        print(f"  {key}: [{len(val)} items]")
                    else:
                        print(f"  {key}: {val}")
            print(f"  PASS")
            return True
        else:
            print(f"  STATUS: {r.status_code}")
            print(f"  BODY: {r.text[:300]}")
            print(f"  FAIL")
            return False
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: Connection refused. Is the vision service running?")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    print("EyeAssist Vision Pipeline Test Suite")
    print(f"Target: {BASE_URL}")

    results = []

    # --- Health & Info ---
    results.append(test("Health Check", "get", "/health"))
    results.append(test("List Models", "get", "/models"))

    # --- Posterior Segment ---
    results.append(test(
        "RETFound - Retinal Screening", "post", "/analyze/posterior/retfound",
        files={"image": ("test.png", TINY_PNG, "image/png")},
        data={"modality": "cfp"},
    ))

    results.append(test(
        "DR Grading", "post", "/analyze/posterior/dr-grading",
        files={"image": ("test.png", TINY_PNG, "image/png")},
    ))

    results.append(test(
        "Glaucoma Detection", "post", "/analyze/posterior/glaucoma",
        files={"image": ("test.png", TINY_PNG, "image/png")},
        data={"modality": "oct_rnflt"},
    ))

    results.append(test(
        "FairSeg - Disc/Cup CDR", "post", "/analyze/posterior/fairseg",
        files={"image": ("test.png", TINY_PNG, "image/png")},
    ))

    results.append(test(
        "Vessel Segmentation", "post", "/analyze/posterior/vessel",
        files={"image": ("test.png", TINY_PNG, "image/png")},
    ))

    # --- Anterior Segment ---
    results.append(test(
        "Meibography Analysis", "post", "/analyze/anterior/meibography",
        files={"image": ("test.png", TINY_PNG, "image/png")},
        data={"eyelid": "upper"},
    ))

    results.append(test(
        "Corneal Disease", "post", "/analyze/anterior/corneal-disease",
        files={"image": ("test.png", TINY_PNG, "image/png")},
    ))

    results.append(test(
        "Keratoconus Screening", "post", "/analyze/anterior/keratoconus",
        data={
            "k1": 44.5,
            "k2": 46.2,
            "kmax": 49.8,
            "pachymetry_min": 455,
            "anterior_elevation": 18,
            "posterior_elevation": 38,
            "is_asymmetry": 1.8,
        },
    ))

    results.append(test(
        "OSD Workup - Full Data", "post", "/analyze/anterior/osd-workup",
        json={
            "tbut": 4.0,
            "schirmer": 12.0,
            "osdi_score": 38.0,
            "corneal_staining_grade": 2,
            "conjunctival_staining_grade": 1,
            "lid_margin_findings": "Telangiectasia bilateral, mild notching",
            "meibum_quality": "granular",
            "meibum_expressibility": 2,
            "tear_osmolarity": 312.0,
            "mmp9_positive": True,
            "meibography_result": {
                "meiboscore": 3,
                "dropout_percentage": 55.0,
                "gland_count": 14,
            },
        },
    ))

    results.append(test(
        "OSD Workup - Partial Data", "post", "/analyze/anterior/osd-workup",
        json={
            "tbut": 6.0,
            "osdi_score": 22.0,
            "schirmer": 4.0,
        },
    ))

    # --- Summary ---
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} tests passed")
    if passed == total:
        print("All tests PASSED!")
    else:
        print(f"{total - passed} test(s) FAILED")
    print(f"{'='*60}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
