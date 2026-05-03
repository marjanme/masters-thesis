# llm-trader

Ta repozitorij vsebuje majhen eksperiment za preverjanje, kako LLM oceni verjetnost, da se napovedni trg razreši v `YES`.

Projekt ne pripravlja podatkov sam. Predpostavlja, da so vhodni podatki že pripravljeni v JSON datotekah. Njegova naloga je samo:

1. naložiti vhodne podatke,
2. za vsak dan sestaviti poziv za LLM,
3. poklicati model,
4. razčleniti odgovor,
5. shraniti rezultate.

## Kaj je en eksperiment

En eksperiment pomeni, da za en izbrani trg in eno izbrano konfiguracijo model zaporedno obdeluje vse dnevne podatke za ta trg.

Konfiguracija določa pogoje eksperimenta. Pove:

- katero navodilo dobi model,
- ali model vidi trenutne tržne verjetnosti,
- ali je v pozivu omenjeno, kdo so drugi udeleženci trga,
- ali model vidi novice.

Primer konfiguracije:

```json
{
  "configuration_id": "1",
  "instruction_id": "1",
  "show_market_probabilities": true,
  "other_traders": "llms",
  "news_mode": "all_until_day"
}
```

Ta primer pomeni, da model:

- dobi navodilo z ID `1`,
- vidi trenutni verjetnosti `YES` in `NO`,
- dobi informacijo, da so drugi udeleženci trga LLM agenti,
- vidi vse novice do trenutnega dne.

## Potek eksperimenta

Glavna vstopna točka je `run_experiment.py`.

Pri izbranem `market_id` in `configuration_id` program:

1. naloži vse datoteke iz `input_data/`,
2. izbere trg, konfiguracijo in navodilo, na katero kaže konfiguracija,
3. zbere vse dnevne vrstice za ta trg po časovnem vrstnem redu,
4. za vsak dan izbere vidne novice,
5. zgradi poziv,
6. pokliče izbran LLM backend,
7. razčleni vrnjeni JSON,
8. zapiše rezultate v `results/`.

Jedrna logika je v:

- `experiment_logic/load_data.py`
- `experiment_logic/select_news.py`
- `experiment_logic/build_prompt.py`
- `experiment_logic/llm_client.py`
- `experiment_logic/parse_llm_response.py`
- `experiment_logic/experiment_runner.py`

## Vhodni podatki

Vsi vhodni podatki so v mapi `input_data/`:

- `markets.json`: definicija trga (`market_id`, vprašanje, datum razrešitve)
- `daily_data.json`: dnevne tržne verjetnosti za posamezni trg in datum
- `news.json`: novice, povezane s trgom in datumom
- `instructions.json`: možna navodila za LLM
- `configurations.json`: možne eksperimentalne konfiguracije

Program pri nalaganju preveri:

- obvezna polja,
- neprazne nize,
- veljavne datume,
- verjetnosti med `0` in `1`,
- da velja `probability_yes + probability_no = 1`,
- enolične identifikatorje,
- veljavne reference med datotekami.

## Primer izvedbe

Primer zagona:

```bash
python3 run_experiment.py --market-id 1 --configuration-id 1 --provider mock
```

Primer zagona z Ollama-kompatibilnim endpointom na HiveCore in privzetim modelom `qwen3.5:4b`:

```bash
python3 run_experiment.py --market-id 1 --configuration-id 1 --provider ollama
```

Pri tem zagonu program:

1. prebere trg z ID `1`,
2. prebere konfiguracijo z ID `1`,
3. poišče navodilo, ki pripada tej konfiguraciji,
4. za vsak dan iz `daily_data.json` za trg `1` sestavi poziv,
5. v poziv po pravilih konfiguracije vključi verjetnosti in novice,
6. pridobi napoved modela,
7. vse rezultate shrani v izhodno datoteko.

Vsak zagon ustvari mapo oblike:

```text
results/<market_id>_<configuration_id>_<YYYYMMDD_HHMMSS>/predictions.json
```

Izhod vsebuje za vsak dan:

- datum,
- kratko utemeljitev modela,
- `p_yes` in `p_no`,
- uporabljeni poziv,
- celoten pogovor z modelom.
