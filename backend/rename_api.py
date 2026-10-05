"""Authenticated bridge to the approved Google Apps Script rename plan."""
import asyncio
import os
import secrets

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter(prefix="/api/v1/rename", tags=["Photo renaming"])
_task = None
_last = {"state": "idle"}
_stop = False


def authorize_rename(authorization: str | None = Header(default=None)):
    token = os.environ.get("RENAME_API_TOKEN")
    if not token:
        raise HTTPException(503, "Rename API is not configured")
    if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Invalid rename token")


async def call_script(action: str):
    url = os.environ.get("GOOGLE_RENAME_SCRIPT_URL")
    token = os.environ.get("RENAME_API_TOKEN")
    if not url or not token:
        raise HTTPException(503, "Google rename script is not configured")
    try:
        async with httpx.AsyncClient(timeout=220, follow_redirects=True) as client:
            response = await client.post(url, json={"action": action, "token": token, "limit": 25})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        # Never return a request URL/token or upstream HTML to clients.
        raise HTTPException(502, "Google rename script did not return valid data") from None
    if not data.get("ok"):
        raise HTTPException(502, str(data.get("error", "Rename script failed")))
    return data


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
        _last = {"state": "error", "error": error.detail}
    except asyncio.CancelledError:
        _last["state"] = "interrupted"
        raise


@router.get("/status", dependencies=[Depends(authorize_rename)])
async def status():
    # During a batch the script lock is held; last response is served immediately.
    if _task is not None and not _task.done():
        return _last
    return dict(await call_script("status"), state=_last.get("state", "idle"))


@router.post("/start", dependencies=[Depends(authorize_rename)])
async def start():
    global _task, _stop, _last
    if _task is not None and not _task.done():
        return {"started": False, "state": "running"}
    initial = await call_script("status")
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
