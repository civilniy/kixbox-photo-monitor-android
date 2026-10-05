# KIXBOX persistent rename connection

The established route is always **Render → Google Apps Script → Drive**.
Do not rename directly with the Google Drive connector.

## Permanent server entrypoint

- Device: accuratelavende.aeza.network, Desktop Commander ID `818c9d8d-bd74-42c8-8dff-902e110ce20f`.
- Client: `/opt/kixbox-rename/rename_client.py` (Python standard library only).
- Existing restricted rename credential: `/etc/kixbox-rename/client.json`, root-owned, mode 0600. Never print or put this file in a report or repository.
- Queues and exported registries: `/var/lib/kixbox-rename/`.
- Render service: `srv-dapvvv67bikc73bgtekg`.
- Confirmed Render workspace: `tea-d5k9squ3jp1c73ej409g`.
- Service URL: https://kixbox-photo-monitor.onrender.com

## Routine commands

```bash
python3 /opt/kixbox-rename/rename_client.py status
python3 /opt/kixbox-rename/rename_client.py submit --plan /var/lib/kixbox-rename/plan.json
python3 /opt/kixbox-rename/rename_client.py start --request-id REQUEST_ID
python3 /opt/kixbox-rename/rename_client.py registry --output /var/lib/kixbox-rename/result.json
```

No browser sign-in, Render dashboard, new API key, or Apps Script edit is needed for each ordinary queue.
Keep the configured token and permissions unchanged. Normal platform approval policies still apply; this does not disable them.

## Queue contract

The plan includes `request_id` (8–80 letters/digits/hyphens/underscores), `day` (`2026_08_DD` or `2026_09_DD`), `source_excel`, and 1–1000 `operations`.
Each reviewed operation includes `id`, original `name`, `new_name`, current `parent`, `destination`, `day`, `reviewed: true`, `status: pending`.
Only one day and one destination per plan. The source and destination must be inside the established KIXBOX ready root; destination must be that day's «Переименовано».

Import only follows a completed queue. A new plan gets a separate JSON registry in the day's «Отчёты переименования». The previous registry is preserved.
The request ID and an immutable digest prevent duplicate submissions and unnoticed changes to a queued mapping. The worker validates original names, current parents, image type, and name collisions before changing files.
Start requires the intended request ID. After a timeout, inspect status before repeating anything. Export the registry and verify Drive IDs, names, and destination before reporting completion.

## Sources

Backend: `civilniy/kixbox-photo-monitor-android`, `backend/rename_api.py`.
Apps Script project: `162PgD7RzSJh5gO-Zz-tshw44AEoA-VhYIOkoI0u0FgJVqwlPLxxVYhuc`.
Keep using its existing deployment and shared secret. Browser is needed only for exceptional maintenance, not the daily queue workflow.

## Android folder monitoring (v1.1)

`GET /api/v1/rename-monitor` uses the existing **MONITOR_API_TOKEN** (read only).
Never put the rename/write credential into the APK. All writes still use Render → Apps Script.
The inventory recursively scans all immediate folders under the approved ready root. Only image MIME types count; report folders, non-images and shortcuts are not followed. Images within «Переименовано» count as renamed, including prior sessions. Images outside day folders appear as a separate root row. Empty folders remain visible, but are not counted complete.

The denominator is the current image inventory, not the old retouch target. Retouch can add files and lower the percentage. Full scans are checkpointed by page, repeat no sooner than 5 minutes, and publish atomically after completion. The prior timestamp remains visible while scanning. Android polls the cached API every 30 seconds. Scans are not transactional with external Drive changes; the following cycle reconciles any concurrent move.

Record the actual assistant phase through `POST /api/v1/rename/work` with the existing rename bearer token. Body: `{"phase":"reviewing","folder_id":"<verified ID>","folder_name":"2026_08_25","message":"Читаю бирки"}`. Allowed phases: paused, reviewing, matching, renaming, verifying, idle, error. Update at each phase change and at least every 10 minutes during analysis. Stop/pause must be explicitly recorded. More than 15 minutes without a heartbeat is displayed as awaiting_update, never fabricated active work. A live API queue overrides the display automatically.

Optional `review_ids` maps top-level folder IDs to arrays of unresolved Drive file IDs; preserve all other folders when replacing this map. Counts are intersected with current non-renamed images during each scan. "0 marked" does not mean an unreviewed folder has no ambiguous files.

Forecast uses observed wall-clock net progress (including review and pauses) over up to 7 days. It needs at least 3 observations and 2 hours, rejects decreases/rollbacks and never extrapolates one fast batch. When paused, only the indicative duration is available, not a completion date. This is an estimate at current pace; unresolved files may take longer.

Apps Script deployment must include `rename_monitor.gs` and the monitor routes from `rename_queue_api_v2.gs`; existing project and deployment, scopes and shared secret are reused. No new trigger, paid service or credential is required.
