import secrets
from fastapi import Request
from ..config import get_settings
from ..utils.errors import AppError

def is_allowed_origin(origin: str, request: Request, allowed_list: list[str]) -> bool:
    if origin in allowed_list or "*" in allowed_list:
        return True
    # Allow any Vercel deployment preview or production domain
    if origin.endswith(".vercel.app") or origin == "https://vercel.app":
        return True
    # Allow same-origin requests
    req_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin.rstrip("/") == req_origin.rstrip("/"):
        return True
    return False

async def authorize(request: Request) -> None:
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin is not None:
        allowed = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
        if not is_allowed_origin(origin, request, allowed):
            raise AppError("origin_not_allowed", "This request origin is not allowed.", 403)
    if settings.api_token:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {settings.api_token}"
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise AppError("authentication_required", "A valid local API bearer token is required.", 401)

