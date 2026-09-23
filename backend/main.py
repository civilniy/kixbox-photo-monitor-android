from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from drive_source import DriveSource
from engine import build_credits, build_snapshot
from openai_costs import fetch_openai_costs


BASE_DIR = Path(__file__).resolve().parent
snapshot: dict[str, Any] = {}
refresh_error: str | None = None


def _credit_topups() -> float | None:
    value = os.environ.get("OPENAI_CREDIT_TOPUPS_USD")
    return float(value) if value not in (None, "") else None


def _opening_balance() -> float:
    value = os.environ.get("OPENAI_OPENING_BALANCE_USD")
    return float(value) if value not in (None, "") else 0.0


async def refresh_snapshot() -> None:
    global snapshot, refresh_error
    try:
        feed_url = os.environ.get("GOOGLE_APPS_SCRIPT_FEED_URL")
        if feed_url:
            timeout = httpx.Timeout(210.0, connect=20.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(feed_url)
                response.raise_for_status()
                feed_snapshot = response.json()
            if feed_snapshot.get("data_status") != "live":
                raise RuntimeError(feed_snapshot.get("error") or "Google feed is not live")
            project_id = os.environ.get("OPENAI_PROJECT_ID")
            costs = await fetch_openai_costs(project_id=project_id)
            if os.environ.get("OPENAI_ADMIN_KEY"):
                organization_costs = await fetch_openai_costs() if project_id else costs
                feed_snapshot["credits"] = build_credits(
                    costs_by_day=costs,
                    daily=feed_snapshot.get("daily", []),
                    processed_source=int(feed_snapshot.get("processed_source", 0) or 0),
                    ready_total=int(feed_snapshot.get("ready_total", 0) or 0),
                    remaining_source=int(feed_snapshot.get("remaining_source", 0) or 0),
                    credit_topups_usd=_credit_topups(),
                    opening_balance_usd=_opening_balance(),
                    configured=True,
                    balance_costs_by_day=organization_costs,
                )
            snapshot = feed_snapshot
        else:
            source = DriveSource()
            runs = await asyncio.to_thread(source.load_runs)
            costs = await fetch_openai_costs(project_id=os.environ.get("OPENAI_PROJECT_ID"))
            snapshot = build_snapshot(
                runs=runs,
                target_total=int(os.environ.get("TARGET_SOURCE_TOTAL", "23000")),
                costs_by_day=costs,
                credit_topups_usd=_credit_topups(),
                opening_balance_usd=_opening_balance(),
                now=datetime.now(timezone.utc),
                data_status="live",
            )
        refresh_error = None
    except Exception as exc:
        refresh_error = str(exc)
        fallback = BASE_DIR / "sample_snapshot.json"
        if not snapshot and fallback.exists():
            snapshot = json.loads(fallback.read_text(encoding="utf-8"))
            snapshot["generated_at"] = datetime.now(timezone.utc).isoformat()
            snapshot["data_status"] = "sample"


async def refresh_loop() -> None:
    while True:
        await refresh_snapshot()
        await asyncio.sleep(max(60, int(os.environ.get("REFRESH_MINUTES", "15")) * 60))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await refresh_snapshot()
    task = asyncio.create_task(refresh_loop())
    yield
    task.cancel()


app = FastAPI(title="KIXBOX Photo Monitor API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Authorization"],
)


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("MONITOR_API_TOKEN")
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid monitor token")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": bool(snapshot), "data_status": snapshot.get("data_status"), "refresh_error": refresh_error}


@app.get("/api/v1/monitor", dependencies=[Depends(authorize)])
def monitor() -> dict[str, Any]:
    if not snapshot:
        raise HTTPException(status_code=503, detail="Snapshot is not ready")
    return snapshot


@app.post("/api/v1/refresh", dependencies=[Depends(authorize)])
async def refresh() -> dict[str, Any]:
    await refresh_snapshot()
    return {"ok": refresh_error is None, "refresh_error": refresh_error, "generated_at": snapshot.get("generated_at")}
