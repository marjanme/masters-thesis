from __future__ import annotations

import json
import re
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "collected_data" / "3_selected_article_embeddings" / "data.json"
OUTPUT_PATH = ROOT / "collected_data" / "4_selected_article_text" / "data.json"
HINTS = {
    "cnn": ("article", "article__content", "article-body", "body-text", "main-content"),
    "nypost": ("article", "entry-content", "single__content", "article-body", "post-content"),
    "msnow": ("article", "article-body", "article-content", "body", "content"),
    "foxnews": ("article", "article-body", "article-content", "paywall", "main-content"),
}


def main() -> int:
    rows: list[dict[str, Any]] = []
    failures = 0

    for url, references in grouped_references().items():
        first = references[0]
        try:
            html = fetch_html(url)
            rows.append(
                {
                    "source": first["source"],
                    "date": first["date"],
                    "title": title(html) or first["title"],
                    "url": url,
                    "content": content(first["source"], html),
                    "selection_references": [
                        {"market_id": row["market_id"], "rank": row["rank"]} for row in references
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{url}: {exc}", flush=True)
        time.sleep(0.5)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 1 if failures else 0


def grouped_references() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in json.loads(INPUT_PATH.read_text(encoding="utf-8")):
        grouped.setdefault(row["url"], []).append(row)
    return grouped


def fetch_html(url: str) -> str:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 data-collection-2/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with request.urlopen(req, timeout=120) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def content(source: str, html: str) -> str:
    body = article_body(jsonld_objects(html))
    if body:
        return body
    paragraphs = Paragraphs(HINTS[source])
    paragraphs.feed(html)
    text = paragraphs.text()
    if not text:
        raise ValueError("missing content")
    return text


def jsonld_objects(html: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    pattern = r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    for raw in re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL):
        try:
            objects.extend(flatten(json.loads(unescape(raw.strip()))))
        except json.JSONDecodeError:
            pass
    return objects


def flatten(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for child in value for item in flatten(child)]
    if isinstance(value, dict) and isinstance(value.get("@graph"), list):
        return [item for child in value["@graph"] for item in flatten(child)]
    return [value] if isinstance(value, dict) else []


def article_body(objects: list[dict[str, Any]]) -> str:
    bodies = [clean(item["articleBody"]) for item in objects if isinstance(item.get("articleBody"), str)]
    return max(bodies, key=len) if bodies else ""


def title(html: str) -> str:
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\'](.*?)["\']',
        r"<title[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return clean(unescape(match.group(1)))
    return ""


class Paragraphs(HTMLParser):
    def __init__(self, hints: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.hints = hints
        self.stack: list[bool] = []
        self.skip = 0
        self.active = False
        self.parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
            self.stack.append(False)
            return
        blob = f"{tag} {' '.join(value or '' for _key, value in attrs)}".lower()
        inside = (self.stack[-1] if self.stack else False) or tag in {"article", "main"} or any(hint in blob for hint in self.hints)
        self.stack.append(inside)
        if tag == "p" and inside:
            self.active = True
            self.parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag == "p" and self.active:
            text = clean("".join(self.parts))
            if len(text) >= 40 and text not in self.paragraphs:
                self.paragraphs.append(text)
            self.active = False
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.active and not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


if __name__ == "__main__":
    raise SystemExit(main())
