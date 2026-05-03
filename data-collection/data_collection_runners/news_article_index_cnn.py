from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from urllib import request
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "collected_data" / "2_news_article_index" / "cnn.json"
CNN_SITEMAP_INDEX = "https://edition.cnn.com/sitemap/article.xml"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
CNN_HOSTS = {"cnn.com", "www.cnn.com", "edition.cnn.com"}
CNN_NON_ARTICLE_PATHS = {"video", "videos", "gallery", "galleries", "audio"}


def main() -> int:
    rows: list[dict[str, str]] = []
    failures = 0

    for sitemap_url in cnn_sitemaps(2025):
        try:
            for url in article_urls(sitemap_url):
                if not is_cnn_article_url(url):
                    continue
                try:
                    rows.append(
                        {
                            "source": "cnn",
                            "date": cnn_date(url),
                            "title": html_title(url),
                            "url": url,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    print(f"{url}: {exc}")
                time.sleep(0.15)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{sitemap_url}: {exc}")
        time.sleep(0.15)

    write_rows(rows)
    return 1 if failures else 0


def cnn_sitemaps(year: int) -> list[str]:
    root = ET.fromstring(fetch_text(CNN_SITEMAP_INDEX))
    urls = [node.text.strip() for node in root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS) if node.text]
    return sorted(url for url in urls if re.search(rf"/{year}/\d\d\.xml$", url))


def article_urls(sitemap_url: str) -> list[str]:
    root = ET.fromstring(fetch_text(sitemap_url))
    return [node.text.strip() for node in root.findall(".//sm:url/sm:loc", SITEMAP_NS) if node.text]


def is_cnn_article_url(url: str) -> bool:
    parsed = urlparse(url)
    parts = {part.lower() for part in parsed.path.split("/") if part}
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc in CNN_HOSTS
        and re.match(r"^/\d{4}/\d{2}/\d{2}/", parsed.path) is not None
        and not parts.intersection(CNN_NON_ARTICLE_PATHS)
    )


def cnn_date(url: str) -> str:
    match = re.match(r"^/(\d{4})/(\d{2})/(\d{2})/", urlparse(url).path)
    if not match:
        raise ValueError("missing date path")
    return "-".join(match.groups())


def html_title(url: str) -> str:
    req = request.Request(
        url,
        headers={"User-Agent": "data-collection-2/1.0", "Accept": "text/html,application/xhtml+xml"},
    )
    with request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        buffer = bytearray()

        while len(buffer) < 2_000_000:
            chunk = response.read(8192)
            if not chunk:
                break
            buffer.extend(chunk)

            lowered = bytes(buffer).lower()
            title_end = lowered.find(b"</title>")
            if title_end == -1:
                continue
            title_start = lowered.rfind(b"<title", 0, title_end)
            if title_start == -1:
                continue
            title_start = lowered.find(b">", title_start, title_end)
            if title_start == -1:
                continue
            title = unescape(bytes(buffer)[title_start + 1 : title_end].decode(charset, errors="replace"))
            return " ".join(title.split())

    raise ValueError("missing title")


def fetch_text(url: str, accept: str = "application/xml,text/xml,text/html,*/*") -> str:
    req = request.Request(url, headers={"User-Agent": "data-collection-2/1.0", "Accept": accept})
    with request.urlopen(req, timeout=60) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def write_rows(rows: list[dict[str, str]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        unique.setdefault(row["url"], row)
    rows = sorted(unique.values(), key=lambda row: (row["date"], row["title"], row["url"]))
    OUTPUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
