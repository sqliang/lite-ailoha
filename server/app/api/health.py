"""
Health check endpoint.
"""
from fastapi import APIRouter
from app.schemas.response import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    """Simple liveness probe."""
    return HealthResponse()
