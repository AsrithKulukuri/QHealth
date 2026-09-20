import hashlib
import logging
from typing import Optional
from ..config import get_settings
from ..utils.errors import AppError

logger = logging.getLogger("qhealth.supabase_storage")

_client = None

def get_supabase_client():
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.supabase_url:
        return None
    key = settings.supabase_service_role_key or settings.supabase_anon_key
    if not key:
        return None
    try:
        from supabase import create_client
        _client = create_client(settings.supabase_url, key)
        return _client
    except Exception as exc:
        logger.error("supabase_client_init_failed error=%s", type(exc).__name__)
        return None

def ensure_bucket_exists(bucket_name: Optional[str] = None) -> bool:
    settings = get_settings()
    bucket = bucket_name or settings.supabase_bucket
    client = get_supabase_client()
    if client is None:
        return False
    try:
        existing = [b.name for b in client.storage.list_buckets()]
        if bucket not in existing:
            client.storage.create_bucket(bucket, options={"public": False})
            logger.info("supabase_bucket_created bucket=%s", bucket)
        return True
    except Exception as exc:
        logger.warning("ensure_bucket_failed bucket=%s error=%s", bucket, type(exc).__name__)
        return False

def upload_to_supabase(path: str, data: bytes, content_type: Optional[str] = None) -> str:
    settings = get_settings()
    client = get_supabase_client()
    if client is None:
        raise AppError("storage_unavailable", "Supabase storage is not configured.")
    ensure_bucket_exists()
    file_opts = {"upsert": "true"}
    if content_type:
        file_opts["content-type"] = content_type
    try:
        client.storage.from_(settings.supabase_bucket).upload(path, data, file_options=file_opts)
        return hashlib.sha256(data).hexdigest()
    except Exception as exc:
        logger.error("supabase_upload_failed path=%s error=%s", path, type(exc).__name__)
        raise AppError("storage_error", "Failed to persist artifact to cloud storage.") from exc

def download_from_supabase(path: str) -> bytes:
    settings = get_settings()
    client = get_supabase_client()
    if client is None:
        raise AppError("storage_unavailable", "Supabase storage is not configured.")
    try:
        return client.storage.from_(settings.supabase_bucket).download(path)
    except Exception as exc:
        logger.error("supabase_download_failed path=%s error=%s", path, type(exc).__name__)
        raise AppError("storage_error", "Failed to retrieve artifact from cloud storage.") from exc

def delete_from_supabase(path: str) -> None:
    settings = get_settings()
    client = get_supabase_client()
    if client is None:
        return
    try:
        client.storage.from_(settings.supabase_bucket).remove([path])
    except Exception as exc:
        logger.warning("supabase_delete_failed path=%s error=%s", path, type(exc).__name__)
