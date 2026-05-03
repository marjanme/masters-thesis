from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "market_event_slugs.txt"
OUTPUT_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
GAMMA_URL = "https://gamma-api.polymarket.com"


def main() -> int:
    slugs = read_slugs(CONFIG_PATH)
    rows: list[dict[str, str]] = []
    failures = 0

    for slug in slugs:
        try:
            rows.append(fetch_market_row(slug))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{slug}: {exc}")
        time.sleep(0.15)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 1 if failures else 0


def read_slugs(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def fetch_market_row(slug: str) -> dict[str, str]:
    payload = get_json(f"{GAMMA_URL}/events?{parse.urlencode({'slug': slug, 'closed': 'true'})}")
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("expected exactly one closed event")

    event = payload[0]
    markets = event.get("markets")
    if not isinstance(markets, list):
        raise ValueError("missing markets")

    for market in markets:
        if not isinstance(market, dict):
            continue
        try:
            outcomes = parse_string_list(market.get("outcomes"))
            prices = parse_float_list(market.get("outcomePrices"))
            token_ids = parse_string_list(market.get("clobTokenIds"))
        except ValueError:
            continue
        if len(outcomes) != len(prices) or len(outcomes) != len(token_ids):
            continue
        yes_index = find_index(outcomes, "Yes")
        no_index = find_index(outcomes, "No")
        if yes_index is None or no_index is None:
            continue
        if prices[yes_index] >= 0.99 and prices[no_index] <= 0.01:
            return {
                "market_id": safe_market_id(slug),
                "question": require_string(market, "question"),
                "start_date": parse_date(require_string(market, "startDate")),
                "resolution_date": parse_date(optional_string(market, "closedTime") or require_string(market, "endDate")),
                "yes_token_id": token_ids[yes_index],
            }

    raise ValueError("no resolved yes/no market found")


def get_json(url: str) -> object:
    req = request.Request(url, headers={"User-Agent": "data-collection-2/1.0"})
    with request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected list of strings")
    return value


def parse_float_list(value: object) -> list[float]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("expected list")
    return [float(item) for item in value]


def find_index(values: list[str], target: str) -> int | None:
    for index, value in enumerate(values):
        if value.casefold() == target.casefold():
            return index
    return None


def require_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {key}")
    return value.strip()


def optional_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def parse_date(value: str) -> str:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if value.endswith("+00"):
        value += ":00"
    if " " in value and "T" not in value:
        value = value.replace(" ", "T", 1)
    if "." in value:
        prefix, suffix = value.rsplit(".", 1)
        timezone_index = next((index for index, char in enumerate(suffix) if char in "+-"), len(suffix))
        fraction = suffix[:timezone_index]
        timezone = suffix[timezone_index:]
        value = f"{prefix}.{fraction.ljust(6, '0')}{timezone}"
    return datetime.fromisoformat(value).date().isoformat()


def safe_market_id(slug: str) -> str:
    return slug.replace("-", "_")


if __name__ == "__main__":
    raise SystemExit(main())
