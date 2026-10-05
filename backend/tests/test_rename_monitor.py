import unittest
from datetime import datetime, timezone, timedelta
from rename_monitor import build_snapshot

class RenameMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,5,16,tzinfo=timezone.utc)
        self.raw={'generated_at':self.now.isoformat(),'folders':[{'id':'a','name':'2026_08_22','total':234,'renamed':228,'review':6},{'id':'b','name':'2026_08_23','total':264,'renamed':259,'review':5},{'id':'c','name':'2026_08_24','total':372,'renamed':355,'review':17}]}
    def test_weighted_totals_and_review_not_complete(self):
        d=build_snapshot(self.raw,now=self.now)
        self.assertEqual((d['total'],d['renamed'],d['remaining'],d['review']),(870,842,28,28))
        self.assertEqual(d['progress_percent'],96.78)
        self.assertEqual(d['folders_complete'],0)
    def test_new_retouch_increases_denominator(self):
        self.raw['folders'][0]['total']+=20
        d=build_snapshot(self.raw,now=self.now)
        self.assertEqual(d['remaining'],48)
        self.assertLess(d['progress_percent'],96.78)
    def test_empty_is_not_completed(self):
        self.raw['folders']=[{'id':'a','name':'empty','total':0,'renamed':0}]
        d=build_snapshot(self.raw,now=self.now)
        self.assertEqual(d['progress_percent'],0);self.assertEqual(d['folders_complete'],0)
    def test_inconsistent_counts_fail(self):
        self.raw['folders'][0]['renamed']=300
        with self.assertRaises(ValueError):build_snapshot(self.raw,now=self.now)
    def test_old_heartbeat_never_shows_active(self):
        d=build_snapshot(self.raw,{'phase':'reviewing','folder_id':'a','updated_at':(self.now-timedelta(hours=1)).isoformat()},self.now)
        self.assertEqual(d['work']['phase'],'awaiting_update');self.assertIsNone(d['estimated_completion_at'])
    def test_fast_batch_does_not_produce_forecast(self):
        self.raw['history']=[{'at':(self.now-timedelta(minutes=i)).isoformat(),'renamed':842-i*100} for i in [2,1,0]]
        d=build_snapshot(self.raw,now=self.now);self.assertIsNone(d['estimated_hours_remaining'])
    def test_forecast_requires_active_recent_work(self):
        self.raw['history']=[{'at':(self.now-timedelta(hours=i)).isoformat(),'renamed':842-i*100} for i in [3,2,0]]
        paused=build_snapshot(self.raw,{'phase':'paused'},self.now)
        self.assertAlmostEqual(paused['estimated_hours_remaining'],.28);self.assertIsNone(paused['estimated_completion_at'])
        active=build_snapshot(self.raw,{'phase':'matching','folder_id':'a','updated_at':self.now.isoformat()},self.now)
        self.assertIsNotNone(active['estimated_completion_at']);self.assertEqual(active['folders'][0]['state'],'working')
    def test_decrease_does_not_create_misleading_eta(self):
        self.raw['history']=[{'at':(self.now-timedelta(hours=i)).isoformat(),'renamed':v} for i,v in [(3,400),(2,900),(0,842)]]
        self.assertIsNone(build_snapshot(self.raw,now=self.now)['pace_per_hour'])
