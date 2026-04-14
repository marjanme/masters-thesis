from __future__ import annotations

import json
import time
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "collected_data" / "2_news_article_index" / "nypost.json"


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
                self.href = href
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
            for title, url in archive_links(current_date):
                if is_article_url(url, current_date):
                    rows.append(
                        {
                            "source": "nypost",
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


def archive_links(current_date: date) -> list[tuple[str, str]]:
    parser = LinkParser()
    parser.feed(fetch_text(f"https://nypost.com/{current_date:%Y/%m/%d}/"))
    return parser.links


def is_article_url(url: str, current_date: date) -> bool:
    return url.startswith(f"https://nypost.com/{current_date:%Y/%m/%d}/") and "/video/" not in url


def days(year: int):
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    while current < end:
        yield current
        current += timedelta(days=1)


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
