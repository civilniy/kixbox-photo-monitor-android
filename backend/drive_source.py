from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from engine import summarize_run


FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveSource:
    def __init__(self) -> None:
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if raw:
            info = json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
            )
        elif path:
            credentials = service_account.Credentials.from_service_account_file(
                path, scopes=["https://www.googleapis.com/auth/drive.readonly"]
            )
        else:
            raise RuntimeError("Google Drive credentials are not configured")
        self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.reports_folder_id = os.environ["GOOGLE_REPORTS_FOLDER_ID"]

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = None
        while True:
            response = self.drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,mimeType,createdTime,modifiedTime,size)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            items.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return items

    def child(self, folder_id: str, name: str) -> dict[str, Any] | None:
        return next((row for row in self.list_children(folder_id) if row["name"] == name), None)

    def load_json(self, file_id: str) -> Any:
        payload = self.drive.files().get_media(fileId=file_id).execute()
        return json.loads(payload.decode("utf-8"))

    def load_runs(self) -> list[dict[str, Any]]:
        report_folders = [
            row for row in self.list_children(self.reports_folder_id)
            if row["mimeType"] == FOLDER_MIME and row["name"].startswith("MASS_ANALYZE_")
        ]
        report_folders.sort(key=lambda row: row.get("createdTime", ""), reverse=True)
        max_runs = int(os.environ.get("MAX_REPORT_RUNS", "60"))
        runs: list[dict[str, Any]] = []
        for folder in report_folders[:max_runs]:
            try:
                plan_file = self.child(folder["id"], "plan.json")
                retouch_folder = self.child(folder["id"], "mass_retouch")
                if not plan_file or not retouch_folder:
                    continue
                result_file = self.child(retouch_folder["id"], "mass_result.json")
                if not result_file:
                    continue
                plan = self.load_json(plan_file["id"])
                results = self.load_json(result_file["id"])
                runs.append(summarize_run(plan, results, result_file.get("modifiedTime") or folder.get("modifiedTime") or datetime.now(timezone.utc).isoformat()))
            except Exception:
                # One corrupt historical report must not take down the monitor.
                continue
        return runs
