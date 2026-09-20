"""Vercel serverless entrypoint exporting the FastAPI app."""
from app.main import app

__all__ = ["app"]
