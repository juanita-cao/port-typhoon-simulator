"""FastAPI app — Port Typhoon Impact Simulator demo API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.cors import configure_cors
from backend.routers import simulation as sim_router

app = FastAPI(
    title="Port Typhoon Impact Simulator",
    version="1.0.0",
)

configure_cors(app)
app.include_router(sim_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve built React frontend — must be mounted last so /api/* routes take priority.
# Path: main.py is at src/backend/main.py; dist is at frontend/dist/ (repo root).
_DIST = Path(__file__).parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")
