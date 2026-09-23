from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import PureWindowsPath
from typing import Any, Iterable


def _folder_name(path: str | None) -> str:
    if not path:
        return "unknown"
    return PureWindowsPath(path).name


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def linked_source_count(plan: dict[str, Any], results: list[dict[str, Any]]) -> int:
    """Count unique originals already tied to completed output rows.

    Each produced catalog image consumes its source frame and, when present,
    the label frame used to identify the product. This mirrors the conservative
    progress method used in the existing KIXBOX reports.
    """
    by_destination = {
        item.get("destination"): item
        for item in plan.get("files", [])
        if item.get("destination")
    }
    linked: set[str] = set()
    for result in results:
        item = by_destination.get(result.get("destination"))
        if item is None:
            # Older reports may differ only by slash direction or folder prefix.
            destination = str(result.get("destination", "")).replace("\\", "/")
            item = next(
                (
                    row
                    for key, row in by_destination.items()
                    if str(key).replace("\\", "/") == destination
                ),
                None,
            )
        if not item:
            continue
        if item.get("source"):
            linked.add(str(item["source"]))
        if item.get("label_source"):
            linked.add(str(item["label_source"]))
    return len(linked)


def summarize_run(
    plan: dict[str, Any],
    results: list[dict[str, Any]],
    completed_at: str,
) -> dict[str, Any]:
    source_total = len(plan.get("records", [])) or len(plan.get("snapshot", []))
    planned = len(plan.get("files", []))
    ready = sum(row.get("state") == "ready" for row in results)
    manual = sum(row.get("state") == "manual" for row in results)
    failed = sum(row.get("state") == "failed" for row in results)
    finished = len(results) >= planned and planned > 0
    processed = source_total if finished else linked_source_count(plan, results)
    cost = sum(float(row.get("summary", {}).get("estimated_total_usd", 0) or 0) for row in results)
    return {
        "run_id": plan.get("run_id", "unknown"),
        "folder": _folder_name(plan.get("scan_folder")),
        "source_total": source_total,
        "processed": min(processed, source_total),
        "ready": ready,
        "manual": manual,
        "failed": failed,
        "planned_outputs": planned,
        "result_outputs": len(results),
        "state": "completed" if finished else "processing",
        "completed_at": completed_at,
        "cost_usd": round(cost, 6),
    }


def select_latest_by_folder(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for run in runs:
        folder = run["folder"]
        previous = selected.get(folder)
        if previous is None or _parse_time(run.get("completed_at")) > _parse_time(previous.get("completed_at")):
            selected[folder] = run
    return sorted(selected.values(), key=lambda row: _parse_time(row.get("completed_at")))


def build_snapshot(
    runs: list[dict[str, Any]],
    target_total: int,
    costs_by_day: dict[str, float] | None = None,
    credit_topups_usd: float | None = None,
    now: datetime | None = None,
    data_status: str = "live",
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    runs = select_latest_by_folder(runs)
    processed_source = sum(int(row["processed"]) for row in runs)
    ready_total = sum(int(row["ready"]) for row in runs)
    manual_total = sum(int(row["manual"]) for row in runs)
    failed_total = sum(int(row["failed"]) for row in runs)
    remaining = max(target_total - processed_source, 0)

    daily_map: dict[str, dict[str, float]] = defaultdict(lambda: {"processed": 0, "ready": 0, "cost_usd": 0.0})
    for row in runs:
        day = _parse_time(row.get("completed_at")).date().isoformat()
        daily_map[day]["processed"] += int(row["processed"])
        daily_map[day]["ready"] += int(row["ready"])
        daily_map[day]["cost_usd"] += float(row.get("cost_usd", 0))

    costs_by_day = costs_by_day or {}
    for day, value in costs_by_day.items():
        daily_map[day]["cost_usd"] = float(value)

    # Use seven completed calendar days for an honest delivery forecast.
    forecast_days = [(now.date() - timedelta(days=offset)).isoformat() for offset in range(7, 0, -1)]
    source_7d = sum(daily_map[day]["processed"] for day in forecast_days)
    ready_7d = sum(daily_map[day]["ready"] for day in forecast_days)
    average_source = source_7d / 7
    average_ready = ready_7d / 7
    eta_days = remaining / average_source if average_source > 0 else None
    eta_at = now + timedelta(days=eta_days) if eta_days is not None else None

    daily_days = sorted(daily_map)[-14:]
    daily = [
        {
            "date": day,
            "processed": int(daily_map[day]["processed"]),
            "ready": int(daily_map[day]["ready"]),
            "cost_usd": round(float(daily_map[day]["cost_usd"]), 4),
        }
        for day in daily_days
    ]

    current = next((row for row in reversed(runs) if row["state"] == "processing"), None)
    costs_total = sum(costs_by_day.values()) if costs_by_day else sum(float(row.get("cost_usd", 0)) for row in runs)
    today_key = now.date().isoformat()
    costs_today = float(costs_by_day.get(today_key, 0)) if costs_by_day else float(daily_map[today_key]["cost_usd"])
    last_7_keys = [(now.date() - timedelta(days=i)).isoformat() for i in range(7)]
    costs_7d = sum(float(costs_by_day.get(day, 0)) for day in last_7_keys) if costs_by_day else sum(float(daily_map[day]["cost_usd"]) for day in last_7_keys)
    ready_last_7 = sum(int(daily_map[day]["ready"]) for day in last_7_keys)
    cost_per_ready = costs_7d / ready_last_7 if ready_last_7 else None
    output_ratio = ready_total / processed_source if processed_source else 0
    projected_ready = remaining * output_ratio
    projected_cost = projected_ready * cost_per_ready if cost_per_ready is not None else None
    balance = credit_topups_usd - costs_total if credit_topups_usd is not None else None

    return {
        "generated_at": now.isoformat(),
        "data_status": data_status,
        "target_total": target_total,
        "processed_source": processed_source,
        "remaining_source": remaining,
        "progress_percent": round(processed_source / target_total * 100, 1) if target_total else 0,
        "ready_total": ready_total,
        "manual_total": manual_total,
        "failed_total": failed_total,
        "average_daily_source_7d": round(average_source, 1),
        "average_daily_ready_7d": round(average_ready, 1),
        "estimated_days_remaining": round(eta_days, 1) if eta_days is not None else None,
        "estimated_completion_at": eta_at.isoformat() if eta_at is not None else None,
        "current_batch": current,
        "daily": daily,
        "batches": list(reversed(runs)),
        "credits": {
            "configured": credit_topups_usd is not None,
            "balance_usd": round(balance, 2) if balance is not None else None,
            "costs_today_usd": round(costs_today, 2),
            "costs_7d_usd": round(costs_7d, 2),
            "costs_total_usd": round(costs_total, 2),
            "cost_per_ready_usd": round(cost_per_ready, 4) if cost_per_ready is not None else None,
            "projected_cost_remaining_usd": round(projected_cost, 2) if projected_cost is not None else None,
            "enough_to_finish": (balance >= projected_cost) if balance is not None and projected_cost is not None else None,
        },
    }
