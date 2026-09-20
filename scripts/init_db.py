"""Initialize the local SQLite schema; no models are trained by this command."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.database import init_db
from app.config import get_settings

def main():
    settings = get_settings()
    init_db()
    if settings.is_postgres_enabled:
        print(f"PostgreSQL schema '{settings.effective_schema}' initialized on Supabase.")
    else:
        print(f"SQLite schema initialized under: {settings.root / 'data'}")
    if settings.is_supabase_storage_enabled:
        print(f"Supabase Storage bucket '{settings.supabase_bucket}' verified and ready.")

if __name__ == "__main__":
    main()
