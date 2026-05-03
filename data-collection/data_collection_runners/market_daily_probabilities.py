from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
OUTPUT_PATH = ROOT / "collected_data" / "1_market_daily_probabilities" / "data.json"
CLOB_URL = "https://clob.polymarket.com"


def main() -> int:
    rows: list[dict[str, object]] = []
    failures = 0

    for market in read_markets(INPUT_PATH):
        try:
            rows.extend(fetch_daily_rows(market))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{market['market_id']}: {exc}")
        time.sleep(0.15)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 1 if failures else 0


def fetch_daily_rows(market: dict[str, str]) -> list[dict[str, object]]:
    start_date = date.fromisoformat(market["start_date"])
    end_date = date.fromisoformat(market["resolution_date"])
    prices = latest_prices_by_day(
        token_id=market["yes_token_id"],
        start_date=start_date,
        end_date=end_date,
    )
    rows: list[dict[str, object]] = []

    for current_date in date_range(start_date, end_date):
        price = prices.get(current_date)
        if price is None:
            print(f"{market['market_id']}: missing {current_date.isoformat()}")
            continue
        probability_yes = round(price, 6)
        rows.append(
            {
                "market_id": market["market_id"],
                "date": current_date.isoformat(),
                "probability_yes": probability_yes,
                "probability_no": round(1.0 - probability_yes, 6),
            }
        )

    return rows


def latest_prices_by_day(token_id: str, start_date: date, end_date: date) -> dict[date, float]:
    prices: dict[date, tuple[int, float]] = {}
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    # CLOB history is fetched in small chunks to avoid brittle long-range requests.
    while start <= end:
        stop = min(start + timedelta(days=7) - timedelta(seconds=1), end)
        params = {
            "market": token_id,
            "startTs": str(int(start.timestamp())),
            "endTs": str(int(stop.timestamp())),
            "fidelity": "1440",
        }
        payload = get_json(f"{CLOB_URL}/prices-history?{parse.urlencode(params)}")
        history = payload.get("history") if isinstance(payload, dict) else None
        if not isinstance(history, list):
            raise ValueError("missing price history")

        for point in history:
            if not isinstance(point, dict):
                continue
            timestamp = point.get("t")
            price = point.get("p")
            if not isinstance(timestamp, (int, float)) or not isinstance(price, (int, float)):
                continue
            current_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
            previous = prices.get(current_date)
            # Keep the last observed price for each UTC day.
            if previous is None or timestamp > previous[0]:
                prices[current_date] = (int(timestamp), float(price))

        start = stop + timedelta(seconds=1)
        time.sleep(0.15)

    return {current_date: price for current_date, (_timestamp, price) in prices.items()}


def read_markets(path: Path) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("expected input array")
    return [read_market(row) for row in rows]


def read_market(row: object) -> dict[str, str]:
    if not isinstance(row, dict):
        raise ValueError("expected object row")
    return {
        "market_id": require_string(row, "market_id"),
        "start_date": require_string(row, "start_date"),
        "resolution_date": require_string(row, "resolution_date"),
        "yes_token_id": require_string(row, "yes_token_id"),
    }


def get_json(url: str) -> object:
    req = request.Request(url, headers={"User-Agent": "data-collection-2/1.0"})
    with request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def require_string(row: dict[object, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {key}")
    return value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
