# KIXBOX upload stage

The existing rename queue moves reviewed photos into each day's `Переименовано`.
The new, separate stage moves those same Drive file IDs into `готово к выгрузке`.
It preserves names, file contents, and IDs. Duplicate names are permitted because
Drive keeps them as separate files; it never copies or overwrites images.

## Install

1. Add `apps-script/upload_stage.gs` to the existing Apps Script project
   `162PgD7RzSJh5gO-Zz-tshw44AEoA-VhYIOkoI0u0FgJVqwlPLxxVYhuc`.
2. Replace that project's `rename_queue_api_v2.gs` with the version in this branch.
   This adds four authenticated actions; the rename boundary remains unchanged.
3. Update the existing Web App deployment to a new version, retaining its `/exec`
   URL, execute-as-owner setting, access setting, and `RENAME_API_TOKEN`.
   Updating GitHub or deploying Render does not update Apps Script.
4. Deploy this branch's `backend/rename_api.py` to the existing Render service.
   No additional environment variables or Google OAuth token are required.
5. On the existing authorized server run `queue/upload_client.py` with the
   private plan file and `--run`. The client checks API availability before staging.

Apps Script cannot be updated with the existing rename token: it authenticates
the application, not Google's project/deployment management API. An authorized
Apps Script editor session or existing project-management OAuth access is required
for steps 1–3. No such API credential was found during preparation.

## API

All routes require the existing `Authorization: Bearer RENAME_API_TOKEN`:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/rename/upload/plan` | Validate and persist an immutable upload plan |
| POST | `/api/v1/rename/upload/run` | Move up to 25 files for the supplied `request_id` |
| GET | `/api/v1/rename/upload/status` | Read progress |
| GET | `/api/v1/rename/upload/registry` | Read before/after metadata and results |

Plan fields are `request_id`, fixed `destination`, and `operations` containing
`id`, exact existing `name`, source `parent`, and `reviewed: true`.

The script verifies that every source is named `Переименовано` and descends from
the fixed `02 готовые` root. The target ID and its project parent are fixed.
It refuses unfinished rename queues or replacement of unfinished upload queues.
It verifies JPEG type, name, parents, MD5, and size before and after moving.
It records intent before writes and uses readback after ambiguous responses.
All upload and rename mutations share the existing Apps Script lock.

Source metadata, immutable identity and folder mapping are hashed. An operation
whose file changed stops for review. A timeout can be resumed with the same
request ID; completed IDs are never moved again.

## Validation

- `node tests/test_upload_stage.cjs`: 11 behavioral scenarios, including committed
  writes with lost responses, repeated batches, separate same-name photos,
  forbidden sources/targets, changed content/names/parents, and modified plans.
- `python tests/test_upload_routes.py`: authenticated dispatch, request identity,
  invalid input and exclusion of an active rename worker.
- Existing rename API tests should also pass with the route additions.

Prepared batch on 2026-10-12: 527 unique JPEG IDs from 37 source folders.
The private manifest is kept on the existing server, outside this repository.
No production transfer has run during code preparation.
