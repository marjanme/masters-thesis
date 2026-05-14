from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
MARKETS_PATH = ROOT / "collected_data" / "0_market_metadata" / "data.json"
INPUT_PATH = ROOT / "collected_data" / "4_selected_article_text" / "data.json"
OUTPUT_PATH = ROOT / "collected_data" / "5_semantic_news_filter" / "data.json"
CACHE_PATH = ROOT / ".cache" / "semantic_news_filter.sqlite3"
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_BASE_URL = "http://hivecore.famnit.upr.si:6666"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_PROGRESS_INTERVAL = 50
MIN_RELEVANCE_SCORE = 6
PROMPT_VERSION = "semantic_news_filter_v2"

STRUCTURED_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "relevance_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "reason": {"type": "string"},
    },
    "required": ["is_relevant", "relevance_score", "reason"],
}


def main() -> int:
    args = parse_args()
    market_questions = load_market_questions(MARKETS_PATH)
    articles = load_json(INPUT_PATH)
    total_references = limited_reference_count(articles, args.limit_articles, args.limit)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(CACHE_PATH)
    cache.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_relevance (
            cache_key TEXT PRIMARY KEY,
            result_json TEXT NOT NULL
        )
        """
    )

    client = OllamaClient(
        model_name=args.model_name,
        ollama_base_url=args.ollama_base_url,
        timeout_seconds=args.timeout_seconds,
        api_key=args.api_key or load_hivecore_api_key(),
    )

    rows: list[dict[str, Any]] = []
    attempted = 0
    article_count = 0
    failures = 0
    relevant = 0
    cache_hits = 0
    cache_misses = 0
    failure_examples: list[str] = []
    started_at = time.monotonic()

    print(
        "semantic_news_filter started: "
        f"input_articles={len(articles)} "
        f"planned_references={total_references} "
        f"progress_interval={args.progress_interval}",
        flush=True,
    )

    try:
        for article in articles:
            if args.limit_articles is not None and article_count >= args.limit_articles:
                break
            article_count += 1
            semantic_relevance = []
            for reference in article["selection_references"]:
                if args.limit is not None and attempted >= args.limit:
                    break

                attempted += 1
                market_id = "unknown"

                try:
                    market_id = require_string(reference, "market_id")
                    market_question = market_questions[market_id]
                    title_similarity_rank = require_int(reference, "rank")
                    result, cache_hit = classify_reference(
                        cache=cache,
                        client=client,
                        market_id=market_id,
                        market_question=market_question,
                        article=article,
                        title_similarity_rank=title_similarity_rank,
                    )
                    if cache_hit:
                        cache_hits += 1
                    else:
                        cache_misses += 1
                    semantic_relevance.append(result)
                    if result["included_by_default"]:
                        relevant += 1
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    if len(failure_examples) < 10:
                        article_url = article.get("url", "unknown url")
                        failure_examples.append(f"{article_url} [{market_id}]: {exc}")

                if should_report_progress(attempted, total_references, args.progress_interval):
                    print_progress(
                        attempted=attempted,
                        total_references=total_references,
                        article_count=article_count,
                        cache_hits=cache_hits,
                        cache_misses=cache_misses,
                        failures=failures,
                        relevant=relevant,
                        started_at=started_at,
                    )

            row = dict(article)
            row.pop("selection_references", None)
            row["semantic_relevance"] = semantic_relevance
            rows.append(row)

            if args.limit is not None and attempted >= args.limit:
                break
    finally:
        cache.close()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        "semantic_news_filter completed: "
        f"input_articles={len(articles)} "
        f"processed_articles={article_count} "
        f"attempted_references={attempted} "
        f"saved_articles={len(rows)} "
        f"cache_hits={cache_hits} "
        f"cache_misses={cache_misses} "
        f"included_by_default={relevant} "
        f"failures={failures} "
        f"elapsed={format_duration(time.monotonic() - started_at)} "
        f"output={OUTPUT_PATH}",
        flush=True,
    )
    for failure in failure_examples:
        print(f"semantic_news_filter failure: {failure}", flush=True)
    return 1 if failures else 0


def limited_reference_count(
    articles: list[dict[str, Any]],
    limit_articles: Optional[int],
    limit_references: Optional[int],
) -> int:
    selected_articles = articles[:limit_articles] if limit_articles is not None else articles
    total = sum(len(article.get("selection_references", [])) for article in selected_articles)
    if limit_references is not None:
        return min(total, limit_references)
    return total


def should_report_progress(attempted: int, total_references: int, progress_interval: int) -> bool:
    if attempted == total_references:
        return True
    return progress_interval > 0 and attempted % progress_interval == 0


def print_progress(
    attempted: int,
    total_references: int,
    article_count: int,
    cache_hits: int,
    cache_misses: int,
    failures: int,
    relevant: int,
    started_at: float,
) -> None:
    elapsed = time.monotonic() - started_at
    rate = attempted / elapsed if elapsed > 0 else 0
    remaining = total_references - attempted
    eta = remaining / rate if rate > 0 else None
    print(
        "semantic_news_filter progress "
        f"{attempted}/{total_references} "
        f"articles={article_count} "
        f"cache_hits={cache_hits} "
        f"cache_misses={cache_misses} "
        f"included_by_default={relevant} "
        f"failures={failures} "
        f"elapsed={format_duration(elapsed)} "
        f"eta={format_duration(eta) if eta is not None else 'unknown'}",
        flush=True,
    )


def format_duration(seconds: float) -> str:
    rounded_seconds = max(0, int(seconds))
    hours, remainder = divmod(rounded_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use an LLM to filter article relevance for each market.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL, help="HiveCore/Ollama model name.")
    parser.add_argument("--ollama-base-url", default=DEFAULT_OLLAMA_BASE_URL, help="HiveCore/Ollama base URL.")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Request timeout.")
    parser.add_argument("--api-key", default=None, help="HiveCore API key. Defaults to HIVECORE_API_KEY from .env.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of article-market pairs.")
    parser.add_argument("--limit-articles", type=int, default=None, help="Optional maximum number of articles.")
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="Print progress after this many article-market pairs.",
    )
    return parser.parse_args()


def classify_reference(
    cache: sqlite3.Connection,
    client: "OllamaClient",
    market_id: str,
    market_question: str,
    article: dict[str, Any],
    title_similarity_rank: int,
) -> tuple[dict[str, Any], bool]:
    key = cache_key(
        model_name=client.model_name,
        market_id=market_id,
        market_question=market_question,
        url=require_string(article, "url"),
        title=require_string(article, "title"),
        content=require_string(article, "content"),
    )
    cached = cache.execute("SELECT result_json FROM semantic_relevance WHERE cache_key = ?", (key,)).fetchone()
    if cached:
        return json.loads(cached[0]), True

    prompt = build_prompt(
        market_question=market_question,
        article_date=require_string(article, "date"),
        article_title=require_string(article, "title"),
        article_content=require_string(article, "content"),
    )
    raw_response = client.generate_response(prompt)
    parsed = parse_llm_response(raw_response)
    result = {
        "market_id": market_id,
        "title_similarity_rank": title_similarity_rank,
        "is_relevant": parsed["is_relevant"],
        "relevance_score": parsed["relevance_score"],
        "reason": parsed["reason"],
        "included_by_default": parsed["is_relevant"] and parsed["relevance_score"] >= MIN_RELEVANCE_SCORE,
    }

    cache.execute("INSERT INTO semantic_relevance VALUES (?, ?)", (key, json.dumps(result, ensure_ascii=False)))
    cache.commit()
    return result, False


def build_prompt(
    market_question: str,
    article_date: str,
    article_title: str,
    article_content: str,
) -> str:
    return (
        "You are filtering news articles for a prediction-market forecasting experiment.\n\n"
        "Task:\n"
        "Decide whether the article contains information that could help estimate the probability "
        "that the specific prediction market resolves YES.\n\n"
        "Prediction market question:\n"
        f"{market_question}\n\n"
        "Article date:\n"
        f"{article_date}\n\n"
        "Article title:\n"
        f"{article_title}\n\n"
        "Article content:\n"
        f"{article_content}\n\n"
        "Scoring guide:\n"
        "1 = completely unrelated.\n"
        "4 = broadly related topic, but not useful for forecasting this market.\n"
        "6 = partially useful for forecasting this market.\n"
        "8 = clearly relevant to forecasting this market.\n"
        "10 = directly about the event, outcome, candidate, decision, or metric in the market.\n\n"
        'Set "is_relevant" to true only when "relevance_score" is 6 or higher. '
        'Set "is_relevant" to false when "relevance_score" is 5 or lower.\n\n'
        "Return valid JSON in exactly this format:\n"
        "{\n"
        '  "is_relevant": true,\n'
        '  "relevance_score": 8,\n'
        '  "reason": "short explanation"\n'
        "}\n\n"
        'The value of "relevance_score" must be an integer from 1 to 10.\n'
        "Do not return any text outside the JSON object."
    )


class OllamaClient:
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

    def generate_response(self, prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "format": STRUCTURED_RESPONSE_SCHEMA,
            "options": {"temperature": 0},
        }
        response_payload = self._post("/api/chat", payload)
        message = response_payload.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama response is missing message.content.")
        return content

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
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
            raise RuntimeError(f"Ollama request failed with status {exc.code}: {response_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Ollama at {self.ollama_base_url}.") from exc

        response_object = json.loads(response_text)
        if not isinstance(response_object, dict):
            raise ValueError(f"Expected Ollama JSON object, got {type(response_object).__name__}.")
        return response_object


def parse_llm_response(raw_response: str) -> dict[str, Any]:
    response_text = strip_markdown_json_fence(raw_response)
    try:
        response_object = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc

    if not isinstance(response_object, dict):
        raise ValueError(f"LLM response must be a JSON object, got {type(response_object).__name__}.")

    is_relevant = response_object.get("is_relevant")
    if not isinstance(is_relevant, bool):
        raise ValueError("LLM field 'is_relevant' must be a boolean.")

    relevance_score = response_object.get("relevance_score")
    if not isinstance(relevance_score, int) or isinstance(relevance_score, bool):
        raise ValueError("LLM field 'relevance_score' must be an integer.")
    if relevance_score < 1 or relevance_score > 10:
        raise ValueError(f"LLM field 'relevance_score' must be between 1 and 10, got {relevance_score}.")

    reason = response_object.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("LLM field 'reason' must be a non-empty string.")

    return {
        "is_relevant": is_relevant,
        "relevance_score": relevance_score,
        "reason": reason.strip(),
    }


def strip_markdown_json_fence(raw_response: str) -> str:
    response_text = raw_response.strip()
    if not response_text.startswith("```"):
        return response_text

    lines = response_text.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return response_text


def cache_key(
    model_name: str,
    market_id: str,
    market_question: str,
    url: str,
    title: str,
    content: str,
) -> str:
    payload = {
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
        "market_id": market_id,
        "market_question": market_question,
        "url": url,
        "title": title,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_market_questions(path: Path) -> dict[str, str]:
    markets = {}
    for row in load_json(path):
        market_id = require_string(row, "market_id")
        markets[market_id] = require_string(row, "question")
    return markets


def load_json(path: Path) -> list[dict[str, Any]]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, list):
        raise ValueError(f"Expected JSON array in {path}.")
    for item in content:
        if not isinstance(item, dict):
            raise ValueError(f"Expected object rows in {path}.")
    return content


def require_string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {key}")
    return value.strip()


def require_int(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"missing integer {key}")
    return value


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
