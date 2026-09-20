import sys
from pathlib import Path

# Ensure backend directory is on sys.path for app module imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app

__all__ = ["app"]
