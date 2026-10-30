"""B31: weekly digest boundary regression without changing the daily view."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from wisp import telemetry


class GrowthTelemetryTest(unittest.TestCase):
    def test_day_five_event_gets_its_own_weekly_hour(self):
        now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "decisions.jsonl"
            path.write_text(json.dumps({
                "ts": (now - timedelta(hours=120)).isoformat(),
                "result": "ANSWERED",
            }) + "\n")
            with patch.object(telemetry, "datetime") as clock:
                clock.now.return_value = now
                clock.fromisoformat.side_effect = datetime.fromisoformat
                weekly = telemetry.digest(168, path, path)
                daily = telemetry.digest(24, path, path)
            self.assertEqual(weekly["turns"], 1)
            self.assertEqual(len(weekly["per_hour"]), 168)
            self.assertEqual(weekly["per_hour"][47], 1)
            self.assertEqual(daily["turns"], 0)
            self.assertEqual(daily["per_hour"], [0] * 24)
