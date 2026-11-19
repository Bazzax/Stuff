"""Entry point for hosts that look for an `app` object in app.py (Vercel's FastAPI support does)."""
from reviewer.main import app  # noqa: F401
