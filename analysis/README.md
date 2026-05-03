# Analiza

Ta mapa vsebuje statistične analize rezultatov projekta `llm-trader`.

Pričakovani vhodni podatki:

```text
../llm-trader/results/*/predictions.json
```

Glavni zvezek:

```text
notebooks/preliminary_statistical_analysis.ipynb
```

Namestitev okolja:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m ipykernel install --user --name llm-trader-analysis --display-name "Python (llm-trader-analysis)"
```

Zagon JupyterLab:

```bash
jupyter lab
```
