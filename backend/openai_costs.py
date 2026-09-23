from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx


async def fetch_openai_costs(project_id: str | None = None) -> dict[str, float]:
    """Read official costs with an OpenAI Admin API key.

    If project_id is provided, only costs attributed to that project are
    returned. Omitting it returns organization-wide costs.
    """
    key = os.environ.get("OPENAI_ADMIN_KEY")
    if not key:
        return {}
    start_date = os.environ.get("OPENAI_COST_START_DATE", "2026-08-01")
    start_time = int(datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc).timestamp())
    params: dict[str, Any] = {
        "start_time": start_time,
        "end_time": int(time.time()) + 1,
        "bucket_width": "1d",
        "limit": 180,
    }
    if project_id:
        params["project_ids"] = [project_id]
    headers = {"Authorization": f"Bearer {key}"}
    costs: dict[str, float] = defaultdict(float)
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            response = await client.get("https://api.openai.com/v1/organization/costs", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            for bucket in payload.get("data", []):
                day = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc).date().isoformat()
                costs[day] += sum(float(row.get("amount", {}).get("value", 0) or 0) for row in bucket.get("results", []))
            page = payload.get("next_page")
            if not payload.get("has_more") or not page:
                break
            params["page"] = page
    return dict(costs)
