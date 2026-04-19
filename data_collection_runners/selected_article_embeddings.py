from __future__ import annotations

import json
import math
import sqlite3
from array import array
from datetime import date, timedelta
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
MARKETS_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
NEWS_DIR = ROOT / "collected_data" / "2_news_article_index"
OUTPUT_PATH = ROOT / "collected_data" / "3_selected_article_embeddings" / "data.json"
CACHE_PATH = ROOT / ".cache" / "embeddings.sqlite3"
MODEL = "qwen3-embedding:8b"
SOURCES = ("cnn", "msnow", "foxnews", "nypost")


def main() -> int:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(CACHE_PATH)
    cache.execute("CREATE TABLE IF NOT EXISTS embeddings (text TEXT PRIMARY KEY, vector BLOB NOT NULL)")

    rows: list[dict[str, object]] = []
    news = load_news()

    try:
        for market in load_json(MARKETS_PATH):
            market_embedding = embedding(cache, market["question"])
            for current_date in window_days(market["resolution_date"]):
                for source in SOURCES:
                    candidates = news[source].get(current_date, [])
                    scored = []
                    for article in candidates:
                        article_embedding = embedding(cache, article["title"])
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

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


def load_news() -> dict[str, dict[str, list[dict[str, str]]]]:
    news = {source: {} for source in SOURCES}
    for source in SOURCES:
        for row in load_json(NEWS_DIR / f"{source}.json"):
            news[source].setdefault(row["date"], []).append(row)
    return news


def embedding(cache: sqlite3.Connection, text: str) -> list[float]:
    row = cache.execute("SELECT vector FROM embeddings WHERE text = ?", (text,)).fetchone()
    if row:
        return decode(row[0])

    vector = ollama_embedding(text)
    cache.execute("INSERT INTO embeddings VALUES (?, ?)", (text, encode(vector)))
    cache.commit()
    return vector


def ollama_embedding(text: str) -> list[float]:
    req = request.Request(
        "http://localhost:11434/api/embed",
        data=json.dumps({"model": MODEL, "input": [text]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [float(value) for value in payload["embeddings"][0]]


def similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def window_days(resolution_date: str):
    end = date.fromisoformat(resolution_date)
    for offset in range(20, 0, -1):
        yield (end - timedelta(days=offset)).isoformat()


def encode(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def decode(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
