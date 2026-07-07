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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.api.actions import router as actions_router
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router
from app.storage.database import get_db, close_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: initialize DB on startup, close on shutdown."""
    await get_db()  # Ensure schema is created
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
