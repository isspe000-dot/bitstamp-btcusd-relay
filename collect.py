"""Publish a BTC/USD 06:59 KST report using finalized one-minute candles."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from time import sleep
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KST = timezone(timedelta(hours=9), "KST")
BITSTAMP = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
KRAKEN = "https://api.kraken.com/0/public/OHLC"
PRICE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def now_utc():
    return datetime.now(timezone.utc)


def candle_open(day):
    return datetime.combine(day, time(6, 59), KST)


def positive_close(value):
    if not isinstance(value, str) or not PRICE.fullmatch(value) or Decimal(value) <= 0:
        raise ValueError("close is not a positive decimal string")
    return value


def exact_close(rows, target):
    matches = [close for stamp, close in rows
               if (type(stamp) is int or isinstance(stamp, str)) and str(stamp) == str(target)]
    if len(matches) != 1:
        raise ValueError(f"expected one finalized candle for {target}, found {len(matches)}")
    return positive_close(matches[0])


def bitstamp_close(payload, target):
    data = payload["data"]
    if data.get("pair", data.get("market")) != "BTC/USD":
        raise ValueError("unexpected Bitstamp market")
    return exact_close(((row["timestamp"], row["close"]) for row in data["ohlc"]), target)


def kraken_close(payload, target):
    if payload["error"]:
        raise ValueError("Kraken API returned an error")
    rows = payload["result"]["BTC/USD"]
    # Kraken includes its uncommitted candle as the last element.
    return exact_close(((row[0], row[4]) for row in rows[:-1]), target)


def fetch_json(url):
    request = Request(url, headers={"User-Agent": "kst-btcusd-relay/1", "Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def fetch_candle(endpoint, params, extract, target, attempts=1):
    url = f"{endpoint}?{urlencode(params)}"
    for attempt in range(attempts):
        if attempt:
            sleep(2)
        requested_at = now_utc()
        try:
            close = extract(fetch_json(url), target)
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"{endpoint} target={target} attempt={attempt + 1} {error}", file=sys.stderr)
        else:
            return {
                "status": "verified",
                "source_url": url,
                "requested_at_utc": requested_at.isoformat(),
                "timestamp_unix": target,
                "close_usd": close,
                "error": None,
            }
    return {
        "status": "unavailable",
        "source_url": url,
        "requested_at_utc": requested_at.isoformat(),
        "timestamp_unix": None,
        "close_usd": None,
        "error": error,
    }


def collect_day(day):
    opened = candle_open(day)
    closed = opened + timedelta(minutes=1)
    target = int(opened.timestamp())
    bitstamp = fetch_candle(
        BITSTAMP, {"step": 60, "limit": 4, "end": target + 60, "exclude_current_candle": "true"},
        bitstamp_close, target, attempts=2,
    )
    verified = bitstamp["status"] == "verified"
    comparison = None
    if not verified:
        comparison = fetch_candle(
            KRAKEN, {"pair": "XBTUSD", "assetVersion": 1, "interval": 1, "since": target - 60},
            kraken_close, target,
        )
    cutoff = datetime.combine(day, time(7, 5), KST)
    return {
        "date_kst": day.isoformat(),
        "candle_open_kst": opened.isoformat(),
        "candle_closed_kst": closed.isoformat(),
        "expected_timestamp_unix": target,
        "bitstamp": bitstamp,
        "backfilled": (datetime.fromisoformat(bitstamp["requested_at_utc"]) >= cutoff
                       if verified else None),
        "kraken_comparison": comparison,
    }


def write_json(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", type=date.fromisoformat, help="Report date in KST (YYYY-MM-DD)")
    parser.add_argument("--output-dir", type=Path, default=Path("public"))
    args = parser.parse_args()
    started = now_utc()
    today = started.astimezone(KST).date()
    day = args.as_of_date or today
    if started < candle_open(day) + timedelta(minutes=1):
        parser.error("the report date's 06:59 KST candle has not closed")
    report = {
        "schema_version": 1,
        "market": "BTC/USD",
        "interval_seconds": 60,
        "as_of_date_kst": day.isoformat(),
        "started_at_utc": started.isoformat(),
        "previous": collect_day(day - timedelta(days=1)),
        "current": collect_day(day),
    }
    write_json(args.output_dir / "reports" / f"{day}.json", report)
    if day == today:
        write_json(args.output_dir / "latest.json", report)
    for label in ("previous", "current"):
        record = report[label]
        print(f"{label} {record['date_kst']} Bitstamp={record['bitstamp']['status']} "
              f"close={record['bitstamp']['close_usd']} backfilled={record['backfilled']}")
    return 0 if all(report[label]["bitstamp"]["status"] == "verified"
                    for label in ("previous", "current")) else 3


if __name__ == "__main__":
    sys.exit(main())
