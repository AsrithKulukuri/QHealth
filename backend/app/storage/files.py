import hashlib
import logging
import os
import re
from pathlib import Path
from uuid import UUID, uuid4
from ..config import get_settings
from ..utils.errors import AppError

logger = logging.getLogger("qhealth.files")

def sanitize_filename(name: str) -> str:
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:160] or "dataset.csv"

def safe_path(area: str, identity: str, suffix: str) -> Path:
    if area not in {"data/datasets", "models", "experiments"} or suffix not in {".csv", ".dill", ".json", ".html"}:
        raise AppError("invalid_path", "Unsupported storage location.")
    try:
        identity = str(UUID(str(identity)))
    except ValueError as exc:
        raise AppError("invalid_id", "Resource IDs must be UUIDs.") from exc
    base = (get_settings().root / area).resolve()
    path = (base / f"{identity}{suffix}").resolve()
    if path.parent != base:
        raise AppError("invalid_path", "Unsafe storage path.")
    return path

def supabase_key_for(path: Path) -> str:
    settings = get_settings()
    rel = path.resolve().relative_to(settings.root.resolve())
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "data":
        return "/".join(parts[1:])
    return "/".join(parts)

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()

def atomic_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass  # Windows may not implement POSIX mode semantics.
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    
    sha = hashlib.sha256(value).hexdigest()
    settings = get_settings()
    if settings.is_supabase_storage_enabled:
        from .supabase_storage import upload_to_supabase
        try:
            key = supabase_key_for(path)
            content_type = "text/csv" if path.suffix == ".csv" else \
                           "text/html" if path.suffix == ".html" else \
                           "application/json" if path.suffix == ".json" else \
                           "application/octet-stream"
            upload_to_supabase(key, value, content_type)
        except Exception as exc:
            logger.warning("supabase_sync_failed path=%s error=%s", path.name, type(exc).__name__)

    return sha

def verify(path: Path, expected: str) -> None:
    if path.is_file() and digest(path) == expected:
        return
    
    settings = get_settings()
    if settings.is_supabase_storage_enabled:
        from .supabase_storage import download_from_supabase
        try:
            key = supabase_key_for(path)
            data = download_from_supabase(key)
            if hashlib.sha256(data).hexdigest() == expected:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return
        except Exception as exc:
            logger.warning("supabase_download_verify_failed path=%s error=%s", path.name, type(exc).__name__)
    
    raise AppError("integrity_error", "Stored artifact is missing or its integrity hash has changed.", 409)

def delete_artifact(area: str, identity: str, suffix: str) -> None:
    path = safe_path(area, identity, suffix)
    path.unlink(missing_ok=True)
    settings = get_settings()
    if settings.is_supabase_storage_enabled:
        from .supabase_storage import delete_from_supabase
        key = supabase_key_for(path)
        delete_from_supabase(key)

def save_model(identity: str, bundle: dict) -> str:
    import dill
    return atomic_bytes(safe_path("models", identity, ".dill"), dill.dumps(bundle, protocol=5))

def load_model(identity: str, expected: str) -> dict:
    # Only application-created, hash-checked artifacts. NEVER accept uploaded models.
    import dill
    path = safe_path("models", identity, ".dill")
    verify(path, expected)
    return dill.loads(path.read_bytes())

