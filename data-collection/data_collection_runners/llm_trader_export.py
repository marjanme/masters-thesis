from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MARKETS_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
DAILY_PATH = ROOT / "collected_data" / "1_market_daily_probabilities" / "data.json"
SEMANTIC_NEWS_PATH = ROOT / "collected_data" / "5_semantic_news_filter" / "data.json"
OUTPUT_DIR = ROOT / "collected_data" / "6_llm_trader_export"
MIN_RELEVANCE_SCORE = 6


def main() -> int:
    markets = load_json(MARKETS_PATH)
    windows = {row["market_id"]: window(row["resolution_date"]) for row in markets}

    write_json(
        OUTPUT_DIR / "markets.json",
        [
            {
                "market_id": row["market_id"],
                "question": row["question"],
                "resolution_date": row["resolution_date"],
                "resolved_yes": row["resolved_yes"],
            }
            for row in markets
        ],
    )
    write_json(
        OUTPUT_DIR / "daily_data.json",
        [
            row
            for row in load_json(DAILY_PATH)
            if row["market_id"] in windows and row["date"] in windows[row["market_id"]]
        ],
    )
    write_json(OUTPUT_DIR / "news.json", news_rows(load_json(SEMANTIC_NEWS_PATH)))
    return 0


def news_rows(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for article in articles:
        for reference in article["semantic_relevance"]:
            if not include_reference(reference):
                continue
            key = (reference["market_id"], article["date"], article["url"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "news_id": news_id(
                        reference["market_id"],
                        article["date"],
                        article["source"],
                        reference["title_similarity_rank"],
                        len(rows) + 1,
                    ),
                    "market_id": reference["market_id"],
                    "date": article["date"],
                    "title": article["title"],
                    "content": article["content"],
                    "title_similarity_rank": reference["title_similarity_rank"],
                    "semantic_is_relevant": reference["is_relevant"],
                    "semantic_relevance_score": reference["relevance_score"],
                    "semantic_relevance_reason": reference["reason"],
                }
            )

    return sorted(rows, key=lambda row: (row["market_id"], row["date"], row["news_id"]))


def include_reference(reference: dict[str, Any]) -> bool:
    return bool(reference["is_relevant"]) and int(reference["relevance_score"]) >= MIN_RELEVANCE_SCORE


def news_id(market_id: str, current_date: str, source: str, rank: int, ordinal: int) -> str:
    return f"{market_id}_{current_date.replace('-', '')}_{source}_r{rank}_{ordinal:06d}"


def window(resolution_date: str) -> set[str]:
    end = date.fromisoformat(resolution_date)
    return {(end - timedelta(days=offset)).isoformat() for offset in range(20, 0, -1)}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, rows: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
