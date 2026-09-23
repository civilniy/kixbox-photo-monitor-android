from datetime import datetime, timezone
import unittest

from engine import build_snapshot, linked_source_count, summarize_run


class EngineTests(unittest.TestCase):
    def test_linked_source_count_includes_label_and_product(self) -> None:
        plan = {
            "files": [
                {"destination": "out/a.jpg", "source": "in/product.jpg", "label_source": "in/label.jpg"}
            ]
        }
        results = [{"destination": "out/a.jpg", "state": "ready"}]
        self.assertEqual(linked_source_count(plan, results), 2)

    def test_partial_run_is_conservative(self) -> None:
        plan = {
            "run_id": "r1",
            "scan_folder": r"E:\\01 исходники\\2026_09_16",
            "records": [{}, {}, {}, {}],
            "files": [
                {"destination": "out/a.jpg", "source": "in/a.jpg", "label_source": "in/l.jpg"},
                {"destination": "out/b.jpg", "source": "in/b.jpg", "label_source": "in/l.jpg"},
            ],
        }
        run = summarize_run(plan, [{"destination": "out/a.jpg", "state": "ready", "summary": {}}], "2026-09-23T10:00:00+00:00")
        self.assertEqual(run["processed"], 2)
        self.assertEqual(run["state"], "processing")

    def test_forecast_uses_completed_calendar_days(self) -> None:
        runs = [
            {
                "folder": "batch",
                "source_total": 700,
                "processed": 700,
                "ready": 350,
                "manual": 0,
                "failed": 0,
                "state": "completed",
                "completed_at": "2026-09-22T10:00:00+00:00",
                "cost_usd": 35,
            }
        ]
        result = build_snapshot(runs, 1400, now=datetime(2026, 9, 23, tzinfo=timezone.utc))
        self.assertEqual(result["average_daily_source_7d"], 100)
        self.assertEqual(result["estimated_days_remaining"], 7)


if __name__ == "__main__":
    unittest.main()
