from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import time
from array import array
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
MARKETS_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
NEWS_DIR = ROOT / "collected_data" / "2_news_article_index"
OUTPUT_PATH = ROOT / "collected_data" / "3_selected_article_embeddings" / "data.json"
CACHE_PATH = ROOT / ".cache" / "embeddings.sqlite3"
DEFAULT_MODEL = "bge-m3:latest"
DEFAULT_OLLAMA_BASE_URL = "http://hivecore.famnit.upr.si:6666"
DEFAULT_TIMEOUT_SECONDS = 120
SOURCES = ("cnn", "msnow", "foxnews", "nypost")


def main() -> int:
    args = parse_args()
    client = HiveCoreEmbeddingClient(
        model_name=DEFAULT_MODEL,
        ollama_base_url=DEFAULT_OLLAMA_BASE_URL,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        api_key=load_hivecore_api_key(),
    )

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(CACHE_PATH)
    cache.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings_v2 (
            model_name TEXT NOT NULL,
            text TEXT NOT NULL,
            vector BLOB NOT NULL,
            PRIMARY KEY (model_name, text)
        )
        """
    )

    rows: list[dict[str, object]] = []
    news = load_news()
    failures = 0

    try:
        markets = load_json(MARKETS_PATH)[: args.limit_markets]
        total_candidates = count_candidates(markets, news, args.limit_days)
        started_at = time.monotonic()
        for market in markets:
            market_embedding = embedding(cache, client, market["question"])
            current_dates = limited_window_days(market["resolution_date"], args.limit_days)
            for current_date in current_dates:
                for source in SOURCES:
                    candidates = news[source].get(current_date, [])
                    scored = []
                    for article in candidates:
                        try:
                            article_embedding = embedding(cache, client, article["title"])
                        except Exception as exc:  # noqa: BLE001
                            failures += 1
                            print(f"Skipping article embedding after error: {exc}", flush=True)
                            continue
                        scored.append((similarity(market_embedding, article_embedding), article, article_embedding))
                    scored.sort(key=lambda item: (-item[0], item[1]["title"], item[1]["url"]))
                    for rank, (score, article, article_embedding) in enumerate(scored[:5], start=1):
                        rows.append(
                            {
                                "market_id": market["market_id"],
                                "date": current_date,
                                "source": source,
                                "title": article["title"],
                                "url": article["url"],
                                "similarity": round(score, 6),
                                "embedding": article_embedding,
                                "rank": rank,
                            }
                        )
    finally:
        cache.close()

    output_path = args.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(
        "selected_article_embeddings completed: "
        f"markets={len(markets)} "
        f"candidate_rows={total_candidates} "
        f"selected_rows={len(rows)} "
        f"failures={failures} "
        f"elapsed={format_duration(time.monotonic() - started_at)}",
        flush=True,
    )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select relevant news articles using title embeddings.")
    parser.add_argument(
        "--limit-markets",
        type=int,
        default=None,
        help="Optional maximum number of markets to process.",
    )
    parser.add_argument(
        "--limit-days",
        type=int,
        default=None,
        help="Optional maximum number of days per market to process.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=OUTPUT_PATH,
        help="Output JSON path.",
    )
    return parser.parse_args()


def load_news() -> dict[str, dict[str, list[dict[str, str]]]]:
    news = {source: {} for source in SOURCES}
    for source in SOURCES:
        for row in load_json(NEWS_DIR / f"{source}.json"):
            news[source].setdefault(row["date"], []).append(row)
    return news


def count_candidates(
    markets: list[dict[str, object]],
    news: dict[str, dict[str, list[dict[str, str]]]],
    limit_days: int | None,
) -> int:
    total = 0
    for market in markets:
        for current_date in limited_window_days(str(market["resolution_date"]), limit_days):
            for source in SOURCES:
                total += len(news[source].get(current_date, []))
    return total


def embedding(cache: sqlite3.Connection, client: "HiveCoreEmbeddingClient", text: str) -> list[float]:
    row = cache.execute(
        "SELECT vector FROM embeddings_v2 WHERE model_name = ? AND text = ?",
        (client.model_name, text),
    ).fetchone()
    if row:
        return decode(row[0])

    vector = client.embedding(text)
    cache.execute("INSERT INTO embeddings_v2 VALUES (?, ?, ?)", (client.model_name, text, encode(vector)))
    cache.commit()
    return vector


class HiveCoreEmbeddingClient:
    def __init__(
        self,
        model_name: str,
        ollama_base_url: str,
        timeout_seconds: int,
        api_key: Optional[str],
    ) -> None:
        self.model_name = model_name
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key

    def embedding(self, text: str) -> list[float]:
        payload = {
            "model": self.model_name,
            "input": [text],
        }
        response_payload = self._post("/api/embed", payload)
        embeddings = response_payload.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise ValueError("HiveCore embedding response is missing embeddings.")
        first_embedding = embeddings[0]
        if not isinstance(first_embedding, list):
            raise ValueError("HiveCore embedding response has invalid embeddings[0].")
        return [float(value) for value in first_embedding]

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key is not None:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            url=f"{self.ollama_base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HiveCore embedding request failed with status {exc.code}: {response_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach HiveCore at {self.ollama_base_url}.") from exc

        response_object = json.loads(response_text)
        if not isinstance(response_object, dict):
            raise ValueError(f"Expected HiveCore JSON object, got {type(response_object).__name__}.")
        return response_object


def similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def window_days(resolution_date: str):
    end = date.fromisoformat(resolution_date)
    for offset in range(20, 0, -1):
        yield (end - timedelta(days=offset)).isoformat()


def limited_window_days(resolution_date: str, limit_days: int | None):
    days = list(window_days(resolution_date))
    return days if limit_days is None else days[:limit_days]


def encode(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def decode(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def load_hivecore_api_key() -> Optional[str]:
    env_value = os.environ.get("HIVECORE_API_KEY")
    if env_value is not None and env_value.strip():
        return env_value.strip()

    for env_path in candidate_env_paths():
        loaded_value = read_env_value(env_path, "HIVECORE_API_KEY")
        if loaded_value is not None and loaded_value.strip():
            return loaded_value.strip()

    return None


def candidate_env_paths() -> list[Path]:
    paths = [Path.cwd() / ".env", ROOT / ".env"]
    unique_paths: list[Path] = []
    for path in paths:
        if path not in unique_paths:
            unique_paths.append(path)
    return unique_paths


def read_env_value(env_path: Path, key: str) -> Optional[str]:
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
            continue

        name, value = stripped_line.split("=", 1)
        if name.strip() != key:
            continue

        return strip_env_quotes(value.strip())

    return None


def strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
