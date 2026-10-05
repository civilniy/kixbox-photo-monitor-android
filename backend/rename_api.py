"""Authenticated bridge to the approved Google Apps Script rename plan."""
import asyncio
import os
import secrets
import json

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException

router = APIRouter(prefix="/api/v1/rename", tags=["Photo renaming"])
_task = None
_last = {"state": "idle"}
_stop = False
_start_lock = asyncio.Lock()


def authorize_rename(authorization: str | None = Header(default=None)):
    token = os.environ.get("RENAME_API_TOKEN")
    if not token:
        raise HTTPException(503, "Rename API is not configured")
    if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Invalid rename token")


async def call_script(action: str, payload: dict | None = None):
    url = os.environ.get("GOOGLE_RENAME_SCRIPT_URL")
    token = os.environ.get("RENAME_API_TOKEN")
    if not url or not token:
        raise HTTPException(503, "Google rename script is not configured")
    try:
        attempts = max(1, min(5, int(os.environ.get("RENAME_HTTP_RETRIES", "3"))))
    except ValueError:
        attempts = 3
    async with httpx.AsyncClient(timeout=220, follow_redirects=True) as client:
        for attempt in range(attempts):
            try:
                request = {"action": action, "token": token, "limit": 25}
                if payload is not None:
                    request["plan"] = payload
                response = await client.post(url, json=request)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Invalid response")
                if data.get("ok"):
                    return data
                if data.get("error") != "Busy":
                    raise HTTPException(502, str(data.get("error", "Rename script failed")))
            except (httpx.HTTPError, ValueError):
                pass
            if attempt + 1 < attempts:
                # The persisted plan makes retries safe after a partial batch.
                await asyncio.sleep(2 ** attempt)
    raise HTTPException(502, "Google rename script did not return valid data after retries")


async def run_queue():
    global _last
    _last = dict(_last, state="running")
    try:
        while not _stop:
            data = await call_script("run")
            _last = dict(data, state="running")
            if data.get("errors"):
                _last["state"] = "needs_review"
                return
            if data["completed"] == data["total"]:
                _last["state"] = "completed"
                return
            if data.get("attempted", 0) == 0:
                _last["state"] = "needs_review"
                return
            await asyncio.sleep(0.5)
        _last["state"] = "stopped"
    except HTTPException as error:
        _last = dict(_last, state="error", error=error.detail)
    except asyncio.CancelledError:
        _last["state"] = "interrupted"
        raise


@router.get("/status", dependencies=[Depends(authorize_rename)])
async def status():
    # During a batch the script lock is held; last response is served immediately.
    if _task is not None and not _task.done():
        return _last
    result = dict(await call_script("status"), state=_last.get("state", "idle"))
    if _last.get("error"):
        result["error"] = _last["error"]
    return result


@router.post("/start", dependencies=[Depends(authorize_rename)])
async def start(expected: dict | None = Body(default=None)):
    global _task, _stop, _last
    async with _start_lock:
        if _task is not None and not _task.done():
            return {"started": False, "state": "running"}
        initial = await call_script("status")
        if expected and expected.get("request_id") != initial.get("request_id"):
            raise HTTPException(409, "Active plan differs from requested plan")
        if initial.get("errors"):
            return dict(initial, started=False, state="needs_review")
        _stop = False
        _last = dict(initial, state="running")
        _task = asyncio.create_task(run_queue())
        return dict(_last, started=True)


@router.post("/stop", dependencies=[Depends(authorize_rename)])
async def stop():
    global _stop
    _stop = True
    return {"state": "stopping_after_current_batch"}


@router.post("/plan", dependencies=[Depends(authorize_rename)])
async def submit_plan(plan: dict = Body(...)):
    """Stage a reviewed queue without starting it; Google persists its audit log."""
    global _last
    ops = plan.get("operations")
    if not isinstance(ops, list) or not 1 <= len(ops) <= 1000:
        raise HTTPException(422, "A plan needs 1 to 1000 operations")
    if len(json.dumps(plan, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise HTTPException(413, "Plan is too large")
    async with _start_lock:
        if _task is not None and not _task.done():
            raise HTTPException(409, "Current queue is running")
        result = await call_script("import_plan", plan)
        _last = dict(result, state="prepared")
        return _last


@router.get("/registry", dependencies=[Depends(authorize_rename)])
async def registry():
    return await call_script("registry")
