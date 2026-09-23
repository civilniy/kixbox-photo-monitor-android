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


def _actual_balance() -> float | None:
    value = os.environ.get("OPENAI_ACTUAL_BALANCE_USD")
    return float(value) if value not in (None, "") else None


def _load_fallback() -> dict[str, Any]:
    fallback = BASE_DIR / "sample_snapshot.json"
    if not fallback.exists():
        return {}
    value = json.loads(fallback.read_text(encoding="utf-8"))
    value["generated_at"] = datetime.now(timezone.utc).isoformat()
    value["data_status"] = "sample"
    return value


def _error_text(source: str, exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"{source}: {message}"


async def _fetch_photo_snapshot() -> dict[str, Any]:
    feed_url = os.environ.get("GOOGLE_APPS_SCRIPT_FEED_URL")
    if feed_url:
        # A first traversal of the shared Drive can take several minutes.
        # It runs in the background, so this does not delay opening the API port.
        timeout = httpx.Timeout(330.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(feed_url)
            response.raise_for_status()
            feed_snapshot = response.json()
        if feed_snapshot.get("data_status") != "live":
            raise RuntimeError(feed_snapshot.get("error") or "Google feed is not live")
        return feed_snapshot

    source = DriveSource()
    runs = await asyncio.to_thread(source.load_runs)
    return build_snapshot(
        runs=runs,
        target_total=int(os.environ.get("TARGET_SOURCE_TOTAL", "23000")),
        now=datetime.now(timezone.utc),
        data_status="live",
    )


async def _fetch_costs() -> tuple[dict[str, float], dict[str, float]]:
    project_id = os.environ.get("OPENAI_PROJECT_ID")
    project_costs = await fetch_openai_costs(project_id=project_id)
    organization_costs = await fetch_openai_costs() if project_id else project_costs
    return project_costs, organization_costs


async def refresh_snapshot() -> None:
    global snapshot, refresh_error
    admin_configured = bool(os.environ.get("OPENAI_ADMIN_KEY"))
    photo_task = asyncio.create_task(_fetch_photo_snapshot())
    costs_task = asyncio.create_task(_fetch_costs())

    photo_result, costs_result = await asyncio.gather(
        photo_task,
        costs_task,
        return_exceptions=True,
    )

    errors: list[str] = []
    if isinstance(photo_result, BaseException):
        errors.append(_error_text("Google Drive", photo_result))
        next_snapshot = dict(snapshot) if snapshot else _load_fallback()
    else:
        next_snapshot = photo_result

    if isinstance(costs_result, BaseException):
        errors.append(_error_text("OpenAI costs", costs_result))
    elif admin_configured:
        project_costs_result, organization_costs_result = costs_result
        next_snapshot["credits"] = build_credits(
            costs_by_day=project_costs_result,
            daily=next_snapshot.get("daily", []),
            processed_source=int(next_snapshot.get("processed_source", 0) or 0),
            ready_total=int(next_snapshot.get("ready_total", 0) or 0),
            remaining_source=int(next_snapshot.get("remaining_source", 0) or 0),
            credit_topups_usd=_credit_topups(),
            opening_balance_usd=_opening_balance(),
            actual_balance_usd=_actual_balance(),
            configured=True,
            balance_costs_by_day=organization_costs_result,
        )

    snapshot = next_snapshot
    refresh_error = "; ".join(errors) or None


async def refresh_loop() -> None:
    while True:
        await refresh_snapshot()
        await asyncio.sleep(max(60, int(os.environ.get("REFRESH_MINUTES", "15")) * 60))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global snapshot
    if not snapshot:
        snapshot = _load_fallback()
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
