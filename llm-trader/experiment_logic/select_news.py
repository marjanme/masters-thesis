from datetime import date

from experiment_logic.types import NewsItem, NewsMode


def select_visible_news(
    news_items: list[NewsItem],
    current_date: date,
    news_mode: NewsMode,
) -> list[NewsItem]:
    if news_mode == "none":
        return []

    if news_mode == "all_until_day":
        visible_news = [item for item in news_items if item.date <= current_date]
        return sorted(visible_news, key=lambda item: (item.date, item.news_id))

    raise ValueError(f"Unsupported news_mode: {news_mode!r}.")
