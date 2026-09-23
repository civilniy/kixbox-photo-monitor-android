from datetime import datetime, timezone
import unittest

from engine import build_credits, build_snapshot, linked_source_count, summarize_run


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

    def test_openai_credits_can_be_merged_into_drive_snapshot(self) -> None:
        result = build_credits(
            costs_by_day={"2026-09-23": 10.0},
            daily=[{"date": "2026-09-23", "ready": 20}],
            processed_source=100,
            ready_total=50,
            remaining_source=100,
            credit_topups_usd=100.0,
            opening_balance_usd=7.45,
            now=datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(result["balance_usd"], 97.45)
        self.assertEqual(result["opening_balance_usd"], 7.45)
        self.assertEqual(result["topups_usd"], 100.0)
        self.assertEqual(result["cost_per_ready_usd"], 0.2)
        self.assertEqual(result["projected_cost_remaining_usd"], 10.0)

    def test_balance_can_use_organization_costs(self) -> None:
        result = build_credits(
            costs_by_day={"2026-09-23": 9.0},
            balance_costs_by_day={"2026-09-23": 10.0},
            daily=[],
            processed_source=0,
            ready_total=0,
            remaining_source=0,
            credit_topups_usd=100.0,
            opening_balance_usd=0.0,
            now=datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(result["costs_total_usd"], 10.0)
        self.assertEqual(result["project_costs_total_usd"], 9.0)
        self.assertEqual(result["balance_usd"], 90.0)

    def test_actual_cabinet_balance_wins_over_delayed_costs(self) -> None:
        result = build_credits(
            costs_by_day={"2026-09-23": 808.46},
            daily=[],
            processed_source=15113,
            ready_total=8080,
            remaining_source=0,
            credit_topups_usd=992.0,
            opening_balance_usd=7.45,
            actual_balance_usd=71.35,
        )
        self.assertEqual(result["balance_usd"], 71.35)
        self.assertEqual(result["costs_total_usd"], 928.10)
        self.assertEqual(result["project_costs_total_usd"], 808.46)
        self.assertEqual(result["balance_source"], "cabinet")
        self.assertEqual(result["cost_per_ready_usd"], 0.1149)


if __name__ == "__main__":
    unittest.main()
