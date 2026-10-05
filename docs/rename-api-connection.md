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
