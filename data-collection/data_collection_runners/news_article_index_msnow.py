from __future__ import annotations

import json
import re
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "collected_data" / "2_news_article_index" / "msnow.json"
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


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href = ""
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
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

    for month in MONTHS:
        try:
            for title, url in archive_links(2025, month):
                if not is_msnow_article_url(url):
                    continue
                try:
                    rows.append({"source": "msnow", "date": article_date(url), "title": title, "url": url})
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    print(f"{url}: {exc}")
                time.sleep(0.15)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{month}: {exc}")
        time.sleep(0.15)

    write_rows(rows)
    return 1 if failures else 0


def archive_links(year: int, month: str) -> list[tuple[str, str]]:
    parser = LinkParser()
    parser.feed(fetch_text(f"https://www.ms.now/archive/articles/{year}/{month}/"))
    return parser.links


def article_date(url: str) -> str:
    html = fetch_text(url)
    for pattern in (
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)',
        r'<time[^>]+datetime=["\']([^"\']+)',
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1)[:10]
    raise ValueError("missing date")


def is_msnow_article_url(url: str) -> bool:
    return (
        url.startswith("https://www.ms.now/")
        and "/archive/" not in url
        and "rcna" in url
        and "?share=" not in url
    )


def normalize_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.ms.now{url}"
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
