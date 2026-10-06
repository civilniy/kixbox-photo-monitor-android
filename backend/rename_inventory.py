"""Read-only inventory through existing Drive credentials, outside Apps Script quotas."""
from collections import deque
from datetime import datetime, timezone
from drive_source import DriveSource, FOLDER_MIME

ROOT = "10WDNKBJMtuwwGiVD6p1OhSOG9jQcNq-f"

def scan_inventory(work=None):
    source = DriveSource()
    root = source.drive.files().get(fileId=ROOT, fields="id,mimeType", supportsAllDrives=True).execute(num_retries=2)
    if root["mimeType"] != FOLDER_MIME:
        raise ValueError("Approved ready root is not a folder")
    started = datetime.now(timezone.utc).isoformat()
    pending = deque([(ROOT, None, False)])
    visited = {ROOT}
    rows = {}
    excluded = 0
    review = (work or {}).get("review_ids", {})
    review = {k: set(v) for k, v in review.items()}
    while pending:
        folder, top, renamed = pending.popleft()
        for item in source.list_children(folder):
            kind = item["mimeType"]
            if kind == FOLDER_MIME:
                if item["id"] in visited:
                    continue
                visited.add(item["id"])
                if item["name"] in ("Отчёты переименования", "Отчеты переименования"):
                    continue
                owner = top or item["id"]
                if top is None:
                    rows[owner] = dict(id=owner, name=item["name"], total=0, renamed=0, review=0)
                pending.append((item["id"], owner, renamed or item["name"] == "Переименовано"))
            elif kind.startswith("image/"):
                owner = top or ROOT
                row = rows.setdefault(owner, dict(id=owner, name="В корне «02 готово»", total=0, renamed=0, review=0))
                row["total"] += 1
                if renamed:
                    row["renamed"] += 1
                elif item["id"] in review.get(owner, set()):
                    row["review"] += 1
            else:
                excluded += 1
    return dict(generated_at=datetime.now(timezone.utc).isoformat(), scan_started_at=started,
                folders=sorted(rows.values(), key=lambda r: r["name"]), root_id=ROOT,
                excluded_files=excluded, inventory_source="direct_drive_readonly")
