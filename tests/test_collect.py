from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import collect


DAY = date(2026, 11, 8)
TARGET = 1794088740
RUN = datetime(2026, 11, 7, 22, 3, tzinfo=timezone.utc)


def bitstamp(*rows):
    return {"data": {"pair": "BTC/USD", "ohlc": [
        {"timestamp": str(stamp), "close": price} for stamp, price in rows
    ]}}


def kraken(*rows):
    return {"error": [], "result": {"BTC/USD": [
        [stamp, None, None, None, price] for stamp, price in rows
    ], "last": TARGET}}


class CandleTests(unittest.TestCase):
    def test_utc_conversion_and_exact_bitstamp_match(self):
        self.assertEqual(int(collect.candle_open(DAY).timestamp()), TARGET)
        payload = bitstamp((TARGET + 60, "1"), (TARGET, "2.50"), (TARGET - 60, "3"))
        self.assertEqual(collect.bitstamp_close(payload, TARGET), "2.50")

    def test_rejects_missing_duplicate_and_invalid_close(self):
        invalid = [bitstamp((TARGET + 60, "9")), bitstamp((TARGET, "9"), (TARGET, "10"))]
        invalid.extend(bitstamp((TARGET, value)) for value in ("0", "0.000", "-1", "NaN", "Infinity"))
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                collect.bitstamp_close(payload, TARGET)

    def test_kraken_rejects_uncommitted_and_wrong_minute(self):
        with self.assertRaises(ValueError):
            collect.kraken_close(kraken((TARGET - 60, "2"), (TARGET, "3")), TARGET)
        self.assertEqual(collect.kraken_close(kraken((TARGET, "2"), (TARGET + 60, "3")), TARGET), "2")


class ReportTests(unittest.TestCase):
    def run_collector(self, folder, clock, fetch, *args):
        with (patch("collect.now_utc", return_value=clock),
              patch("collect.fetch_json", side_effect=fetch) as request,
              patch("collect.sleep"),
              patch("sys.argv", ["collect.py", "--output-dir", str(folder), *args]),
              redirect_stdout(StringIO()), redirect_stderr(StringIO())):
            status = collect.main()
        return status, request

    def successful_bitstamp(self, url):
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["step"], ["60"])
        self.assertEqual(query["exclude_current_candle"], ["true"])
        return bitstamp((int(query["end"][0]) - 60, "90000.01"))

    def test_writes_both_exact_days_and_flags_previous_as_backfill(self):
        with tempfile.TemporaryDirectory() as folder:
            status, request = self.run_collector(folder, RUN, self.successful_bitstamp)
            self.assertEqual(status, 0)
            self.assertEqual(request.call_count, 2)
            latest = Path(folder, "latest.json").read_text(encoding="utf-8")
            self.assertEqual(latest, Path(folder, "reports", f"{DAY}.json").read_text(encoding="utf-8"))
        report = json.loads(latest)
        self.assertEqual(report["previous"]["expected_timestamp_unix"], TARGET - 86400)
        self.assertEqual(report["current"]["bitstamp"]["timestamp_unix"], TARGET)
        self.assertEqual(report["current"]["bitstamp"]["requested_at_utc"], RUN.isoformat())
        self.assertTrue(report["previous"]["backfilled"])
        self.assertFalse(report["current"]["backfilled"])
        self.assertIsNone(report["current"]["kraken_comparison"])

    def test_kraken_value_stays_separate_on_bitstamp_failure(self):
        responses = [bitstamp((TARGET - 86400, "1")), OSError("offline"),
                     bitstamp((TARGET + 60, "3")), kraken((TARGET, "2"), (TARGET + 60, "3"))]
        with tempfile.TemporaryDirectory() as folder:
            status, request = self.run_collector(folder, RUN, responses)
            current = json.loads(Path(folder, "latest.json").read_text(encoding="utf-8"))["current"]
        self.assertEqual(status, 3)
        self.assertEqual(request.call_count, 4)
        self.assertIsNone(current["bitstamp"]["close_usd"])
        self.assertIsNone(current["backfilled"])
        self.assertEqual(current["kraken_comparison"]["close_usd"], "2")

    def test_manual_backfill_preserves_latest(self):
        with tempfile.TemporaryDirectory() as folder:
            latest = Path(folder, "latest.json")
            latest.write_text("existing", encoding="utf-8")
            status, _ = self.run_collector(folder, RUN, self.successful_bitstamp, "--as-of-date", "2026-11-07")
            self.assertEqual(status, 0)
            self.assertEqual(latest.read_text(encoding="utf-8"), "existing")
            report = json.loads(Path(folder, "reports", "2026-11-07.json").read_text(encoding="utf-8"))
            self.assertTrue(report["current"]["backfilled"])

    def test_late_current_candle_is_backfilled(self):
        with tempfile.TemporaryDirectory() as folder:
            status, _ = self.run_collector(folder, RUN + timedelta(minutes=2), self.successful_bitstamp)
            current = json.loads(Path(folder, "latest.json").read_text(encoding="utf-8"))["current"]
        self.assertEqual(status, 0)
        self.assertTrue(current["backfilled"])

    def test_before_close_makes_no_requests_and_publishes_nothing(self):
        fetch = Mock(side_effect=self.successful_bitstamp)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(SystemExit) as caught:
                self.run_collector(folder, RUN - timedelta(minutes=4), fetch)
            self.assertEqual(caught.exception.code, 2)
            fetch.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
