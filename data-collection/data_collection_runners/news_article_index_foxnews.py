from __future__ import annotations

import json
import time
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "collected_data" / "2_news_article_index" / "foxnews.json"
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


class SitemapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and "sitemap-grid-link" in (values.get("class") or "").split():
            href = values.get("href")
            if href:
                self.href = normalize_url(href)
                self.parts = []

    def handle_data(self, data: str) -> None:
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            title = " ".join(unescape(" ".join(self.parts)).split())
            if title:
                self.links.append((title, self.href))
            self.href = ""


def main() -> int:
    rows: list[dict[str, str]] = []
    failures = 0

    for current_date in days(2025):
        try:
            for title, url in sitemap_links(current_date):
                rows.append(
                    {
                        "source": "foxnews",
                        "date": current_date.isoformat(),
                        "title": title,
                        "url": url,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{current_date.isoformat()}: {exc}")
        time.sleep(0.15)

    write_rows(rows)
    return 1 if failures else 0


def sitemap_links(current_date: date) -> list[tuple[str, str]]:
    parser = SitemapParser()
    parser.feed(fetch_text(f"https://www.foxnews.com/html-sitemap/{current_date.year}/{MONTHS[current_date.month - 1]}/{current_date.day}"))
    return parser.links


def days(year: int):
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    while current < end:
        yield current
        current += timedelta(days=1)


def normalize_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.foxnews.com{url}"
    return url


def fetch_text(url: str) -> str:
    req = request.Request(
        url,
        headers={"User-Agent": "data-collection-2/1.0", "Accept": "text/html,application/xhtml+xml"},
    )
    with request.urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def write_rows(rows: list[dict[str, str]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        unique.setdefault(row["url"], row)
    rows = sorted(unique.values(), key=lambda row: (row["date"], row["title"], row["url"]))
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
