"""
Lite Ailoha Server — FastAPI application entry point.

A lightweight AI-powered backend for analyzing chat screenshots
and generating actionable cards (meetings, contacts, reminders).

Architecture:
- iOS client sends chat screenshot as base64
- VISION_MODEL (Coordinator) structures the conversation, LLM_MODEL (Subagents) extracts actions
- Results are streamed back via SSE: event:struct → event:card × N → event:insight → event:done

Endpoints:
    POST /api/v1/analyze                 — SSE streaming analysis
    POST /api/v1/actions/{id}/confirm    — Confirm a proposed action
    POST /api/v1/actions/{id}/cancel     — Cancel a proposed action
    GET  /api/v1/sessions/{id}           — Query session data for quality evaluation
    GET  /health                          — Health check
"""
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.api.actions import router as actions_router
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router
from app.storage.database import get_db, close_db

# 配置日志：INFO 级别 + 清晰的时间格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 手动加载 .env 到 os.environ（pydantic-settings 不会自动注入）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
_env_path = os.path.abspath(_env_path)
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip("\"'")
                if key not in os.environ:
                    os.environ[key] = value
    logger.info("Loaded .env from %s (%d vars)", _env_path,
                 sum(1 for line in open(_env_path) if line.strip() and not line.strip().startswith("#") and "=" in line))

# LangSmith 追踪：LangChain 直接从 os.environ 读取 LANGCHAIN_* 变量，
# 这里兼容 LANGSMITH_* 和 LANGCHAIN_* 两种前缀
_tracing_on = (
    os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    or os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
)
if _tracing_on:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    for _src, _dst in [
        ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
        ("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"),
        ("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"),
    ]:
        if os.environ.get(_src) and not os.environ.get(_dst):
            os.environ[_dst] = os.environ[_src]
    logger.info(
        "LangSmith tracing ENABLED | project=%s | endpoint=%s",
        os.environ.get("LANGCHAIN_PROJECT", "?"),
        os.environ.get("LANGCHAIN_ENDPOINT", "?"),
    )
else:
    logger.info("LangSmith tracing DISABLED")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: initialize DB on startup, close on shutdown."""
    await get_db()
    yield
    await close_db()


app = FastAPI(
    title="Lite Ailoha API",
    description="AI-powered chat screenshot analysis — privacy-first (OCR on-device)",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow iOS client connections from any origin during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(health_router)
app.include_router(analyze_router)
app.include_router(actions_router)
app.include_router(sessions_router)
