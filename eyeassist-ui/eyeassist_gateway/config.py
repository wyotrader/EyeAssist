from pathlib import Path
import os
import secrets

BASE_DIR = Path(__file__).resolve().parents[1]

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'backend' / 'data' / 'webui.db'}")
SESSION_SECRET = os.environ.get("EYEASSIST_SESSION_SECRET") or secrets.token_urlsafe(32)
SESSION_COOKIE = os.environ.get("EYEASSIST_SESSION_COOKIE", "eyeassist_session")
SESSION_SECURE = os.environ.get("EYEASSIST_SESSION_SECURE", "false").lower() == "true"
SESSION_MAX_AGE_SECONDS = int(os.environ.get("EYEASSIST_SESSION_MAX_AGE_SECONDS", "28800"))
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8300")
RAG_URL = os.environ.get("RAG_SERVICE_URL", "http://localhost:8100")
VISION_URL = os.environ.get("VISION_SERVICE_URL", "http://localhost:8200")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
STATIC_DIR = Path(os.environ.get("EYEASSIST_STATIC_DIR", BASE_DIR / "build"))
