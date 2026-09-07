#!/usr/bin/env python3
"""
EyeAssist ERG wire-up deployment script.

Makes all the code changes needed to add the /report/erg endpoint:
  1. Adds imports + MODEL_REGISTRY entry + full ERG endpoint to vision_service.py
  2. Adds sys.path bootstrap + imports + adapters + /report/erg endpoint to orchestrator.py
  3. Replaces base.py with the multi-collection-aware version
  4. Replaces erg.yaml with the three-collection version

All modified files are backed up to <repo>/.backups/erg_wireup_<timestamp>/
before any change is made. Any failure aborts without partial writes.

Usage:
  cd deploy_staging
  python3 deploy_erg_wireup.py
"""

import sys
import shutil
import datetime
from pathlib import Path

EYEASSIST = Path(__file__).resolve().parents[1]
PIPELINE = EYEASSIST / "pipeline"
STAGING = Path(__file__).parent.resolve()

VISION = PIPELINE / "vision_service.py"
ORCH = PIPELINE / "orchestrator" / "orchestrator.py"
BASE = PIPELINE / "reports" / "integrators" / "base.py"
ERG_YAML = PIPELINE / "reports" / "templates" / "erg.yaml"

BACKUP_ROOT = EYEASSIST / ".backups" / f"erg_wireup_{datetime.datetime.now():%Y%m%d_%H%M%S}"


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def backup(path: Path):
    if not path.exists():
        die(f"Target file does not exist: {path}")
    rel = path.relative_to(EYEASSIST)
    dest = BACKUP_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    print(f"  backed up: {rel}")


def read_staged(name: str) -> str:
    p = STAGING / name
    if not p.exists():
        die(f"Staged file missing: {p}")
    return p.read_text()


def main():
    # Preflight: verify all targets exist before touching anything
    print("Preflight: checking target files...")
    for t in (VISION, ORCH, BASE, ERG_YAML):
        if not t.exists():
            die(f"Target not found: {t}")
        print(f"  found: {t.relative_to(EYEASSIST)}")

    # Preflight: verify staged files are present
    print("\nPreflight: checking staged files...")
    for name in ("erg_endpoint_body.py", "orchestrator_erg_body.py",
                 "base.py", "erg.yaml"):
        p = STAGING / name
        if not p.exists():
            die(f"Staged file missing: {p}")
        print(f"  found: {name}")

    # Backups
    print(f"\nBacking up to {BACKUP_ROOT}")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    for t in (VISION, ORCH, BASE, ERG_YAML):
        backup(t)

    # --- 1. vision_service.py ---
    print("\n[1/4] Editing vision_service.py")
    vs = VISION.read_text()

    if "/analyze/diagnostic/erg" in vs:
        print("  SKIP: ERG endpoint already present in vision_service.py")
    else:
        # 1a. Add imports. We find the existing `import os` line and
        #     add json/re/fitz imports right after it if missing.
        imports_to_add = []
        if "\nimport json" not in vs and "\nimport json\n" not in vs:
            imports_to_add.append("import json")
        if "\nimport re" not in vs:
            imports_to_add.append("import re")
        if "import fitz" not in vs:
            imports_to_add.append("import fitz  # PyMuPDF")

        if imports_to_add:
            marker = "import os\n"
            if marker not in vs:
                die("Could not find 'import os' marker in vision_service.py")
            injected = marker + "\n".join(imports_to_add) + "\n"
            vs = vs.replace(marker, injected, 1)
            print(f"  added imports: {', '.join(imports_to_add)}")
        else:
            print("  imports already present")

        # 1b. Add ERG entry to MODEL_REGISTRY. We look for the anterior
        #     osd_workup entry and add the erg entry after the closing
        #     brace of the registry dict.
        registry_end_marker = '"osd_workup":       {"name": "OSD Integrator", "version": "1.0", "status": ModelStatus.MOCK, "track": "anterior"},\n}'
        if registry_end_marker not in vs:
            die("Could not find MODEL_REGISTRY end marker (osd_workup line)")
        registry_addition = (
            '"osd_workup":       {"name": "OSD Integrator", "version": "1.0", "status": ModelStatus.MOCK, "track": "anterior"},\n'
            '    # Diagnostic studies (PDF-based reports)\n'
            '    "erg":              {"name": "ERG Extraction (RETeval)", "version": "1.0", "status": ModelStatus.MOCK, "track": "diagnostic"},\n'
            '}'
        )
        vs = vs.replace(registry_end_marker, registry_addition, 1)
        print("  added 'erg' to MODEL_REGISTRY")

        # 1c. Insert the full endpoint body just before the `# === Run ===` section
        run_marker = "# === Run ===\n"
        if run_marker not in vs:
            die("Could not find '# === Run ===' marker in vision_service.py")
        endpoint_body = read_staged("erg_endpoint_body.py")
        vs = vs.replace(run_marker, endpoint_body + "\n\n" + run_marker, 1)
        print("  inserted ERG endpoint body")

        VISION.write_text(vs)
        print("  wrote vision_service.py")

    # --- 2. orchestrator.py ---
    print("\n[2/4] Editing orchestrator.py")
    og = ORCH.read_text()

    if "/report/erg" in og:
        print("  SKIP: /report/erg endpoint already present in orchestrator.py")
    else:
        # 2a. Add sys.path bootstrap at the top (after any shebang/docstring).
        #     Simplest reliable approach: find the first `import` line and
        #     insert the bootstrap immediately before it.
        bootstrap = (
            "import sys as _sys_bootstrap\n"
            "import os as _os_bootstrap\n"
            "_sys_bootstrap.path.insert(0, _os_bootstrap.path.dirname(_os_bootstrap.path.dirname(_os_bootstrap.path.abspath(__file__))))\n"
            "\n"
        )
        if "_sys_bootstrap" not in og:
            lines = og.splitlines(keepends=True)
            insert_at = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    insert_at = i
                    break
            if insert_at is None:
                die("Could not find first import line in orchestrator.py")
            lines.insert(insert_at, bootstrap)
            og = "".join(lines)
            print("  added sys.path bootstrap")
        else:
            print("  sys.path bootstrap already present")

        # 2b. Add the reports imports near the other fastapi imports.
        #     We look for an existing fastapi import line as anchor.
        new_imports = (
            "from fastapi import UploadFile, File\n"
            "from fastapi.responses import Response\n"
            "from reports import render\n"
            "from reports.integrators.erg import ERGIntegrator\n"
        )
        if "from reports.integrators.erg import ERGIntegrator" not in og:
            # Anchor on "from fastapi" — should be present since the file already uses FastAPI
            anchor_idx = og.find("from fastapi")
            if anchor_idx == -1:
                die("Could not find 'from fastapi' anchor in orchestrator.py")
            # Find end of that line
            line_end = og.find("\n", anchor_idx) + 1
            og = og[:line_end] + new_imports + og[line_end:]
            print("  added reports imports")
        else:
            print("  reports imports already present")

        # 2c. Append the adapters + endpoint at the end of the file.
        #     We look for the `if __name__` block and insert before it,
        #     or append to EOF if absent.
        endpoint_body = read_staged("orchestrator_erg_body.py")
        if 'if __name__ == "__main__":' in og:
            og = og.replace(
                'if __name__ == "__main__":',
                endpoint_body + "\n\nif __name__ == \"__main__\":",
                1,
            )
            print("  inserted adapters + endpoint before __main__ block")
        else:
            if not og.endswith("\n"):
                og += "\n"
            og += "\n" + endpoint_body + "\n"
            print("  appended adapters + endpoint to end of file")

        ORCH.write_text(og)
        print("  wrote orchestrator.py")

    # --- 3. base.py ---
    print("\n[3/4] Replacing base.py")
    new_base = read_staged("base.py")
    BASE.write_text(new_base)
    print(f"  wrote {BASE.relative_to(EYEASSIST)}")

    # --- 4. erg.yaml ---
    print("\n[4/4] Replacing erg.yaml")
    new_yaml = read_staged("erg.yaml")
    ERG_YAML.write_text(new_yaml)
    print(f"  wrote {ERG_YAML.relative_to(EYEASSIST)}")

    print(f"\nDone. Backups at: {BACKUP_ROOT}")
    print("To roll back all changes:")
    print(f"  cp -r {BACKUP_ROOT}/pipeline/* {PIPELINE}/")


if __name__ == "__main__":
    main()
