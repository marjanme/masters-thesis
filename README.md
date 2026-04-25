# data-collection

Ta repozitorij pripravi vhodne podatke za projekt `llm-trader`.

Pipeline zbere metapodatke trgov, dnevne tržne verjetnosti, novičarske članke, izbere najbolj relevantne članke z embeddingi, prenese njihovo besedilo in na koncu izvozi datoteke v obliki, ki jo uporablja `llm-trader`.

## Struktura

```text
configs/
  market_event_slugs.txt

data_collection_runners/
  market_metadata.py
  market_daily_probabilities.py
  news_article_index_cnn.py
  news_article_index_msnow.py
  news_article_index_foxnews.py
  news_article_index_nypost.py
  selected_article_embeddings.py
  selected_article_text.py
  llm_trader_export.py

collected_data/
  0_market_metadata/
  1_market_daily_probabilities/
  2_news_article_index/
  3_selected_article_embeddings/
  4_selected_article_text/
  5_llm_trader_export/
```

`.cache/` je namenjen lokalnemu cacheu in ni del izhodnih podatkov.

## Zagon

Ukaze se požene iz root direktorija.

```bash
python3 data_collection_runners/market_metadata.py
python3 data_collection_runners/market_daily_probabilities.py
```

Nato se zbere indekse novic:

```bash
python3 data_collection_runners/news_article_index_cnn.py
python3 data_collection_runners/news_article_index_msnow.py
python3 data_collection_runners/news_article_index_foxnews.py
python3 data_collection_runners/news_article_index_nypost.py
```

Za izbor člankov mora lokalno teči Ollama z modelom `qwen3-embedding:8b`.

```bash
python3 data_collection_runners/selected_article_embeddings.py
python3 data_collection_runners/selected_article_text.py
python3 data_collection_runners/llm_trader_export.py
```

## Izhodi

Glavni končni izhod je:

```text
collected_data/
  5_llm_trader_export/
    markets.json
    daily_data.json
    news.json
```

Vmesni izhodi so namenjeni posameznim fazam:

- `0_market_metadata/data.json` vsebuje trge.
- `1_market_daily_probabilities/data.json` vsebuje dnevne verjetnosti.
- `2_news_article_index/*.json` vsebuje indekse člankov po virih.
- `3_selected_article_embeddings/data.json` vsebuje izbrane članke in embeddinge.
- `4_selected_article_text/data.json` vsebuje polna besedila izbranih člankov.

## Opombe

- Runnerji prepisujejo svoje izhodne datoteke.
- Dnevni podatki v končnem izvozu so omejeni na 20 dni pred razrešitvijo trga.
- `selected_article_embeddings.py` uporablja cache `.cache/embeddings.sqlite3`.
