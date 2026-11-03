# Dengue in Peru: an Apache Spark analysis

Course project for **Ciencia de Datos Escalable** (MSc in Data Science).
It uses Spark's Structured APIs (DataFrame API and Spark SQL) to analyze dengue cases reported
in Peru and how they relate to population, water emergencies, health facility coverage and rainfall.

All data is public and official, most of it from Peru's
[National Open Data Platform](https://www.datosabiertos.gob.pe).

## Repository layout

```
.
├── data/
│   ├── catalog.yaml          # metadata: each dataset, its files, source URL and sha256
│   ├── raw/                  # data as downloaded, never modified (not committed)
│   └── processed/            # Spark outputs, e.g. Parquet (not committed)
├── notebooks/                # PySpark analysis (main deliverable)
├── scripts/
│   └── download_data.py      # downloads and verifies the data in data/catalog.yaml
├── docs/
│   ├── figures/              # charts saved by notebook 02 (also used by the report)
│   └── report/               # LaTeX source of the technical report (main.tex + sections/)
├── .env.example              # template for local secrets
└── requirements.txt
```

## Setup

1. **Java 25** (Spark 4.2 runs on Java 17, 21 or 25.0.3+), e.g.
   [Eclipse Temurin 25](https://adoptium.net/temurin/releases/?version=25). Check with `java -version`.
2. **Python 3.10+** and a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt   # PySpark already bundles Spark
   ```

3. **SENAMHI API key** (only for the weather station data): create an account at the
   [SENAMHI interoperability platform](https://observatorio.senamhi.gob.pe/investigadores/interoperabilidad),
   register your public IP, then `cp .env.example .env` and set `SENAMHI_API_KEY`.

## Data

`data/catalog.yaml` describes every dataset: publisher, source page, the files it is made of,
format, coverage, join keys and how datasets relate to each other.

Nothing under `data/raw/` is committed (the dengue file alone is 118 MB, above GitHub's 100 MB limit).
Rebuild it with:

```bash
python scripts/download_data.py                # download what is missing and verify sha256
python scripts/download_data.py --verify-only  # only check
```

`CHANGED` means the source published a new version of a file.

## Running the analysis

Run the notebooks in order (`jupyter lab`, or any editor using the `.venv` kernel):

1. `notebooks/01_data_preparation.ipynb`: reads `data/raw/`, cleans each source and writes Parquet
   tables to `data/processed/` (`dengue_cases`, `population`, `water_emergencies`,
   `health_facilities`, `weather_daily`).
2. `notebooks/02_analysis.ipynb`: answers the six analysis questions with the DataFrame API and
   saves its charts to `docs/figures/`.
3. `notebooks/03_execution_plans.ipynb`: shows how Spark executes the analysis. It writes Q2 in both the
   DataFrame API and Spark SQL (same result, same plan), reads two execution plans
   (`explain("formatted")`), and measures lazy evaluation, stages, tasks and shuffles through the Spark UI.

If `data/processed/` is already present (the package submitted for the course includes these curated
Parquet tables), notebooks 02 and 03 run directly, with no download and no SENAMHI API key. Notebook 01 is
only needed to rebuild those tables from `data/raw/`.

## Building the report

The technical report (in Spanish) is written in LaTeX: `docs/report/main.tex` includes one file per section
from `docs/report/sections/` and reads the charts from `docs/figures/`. It needs a TeX distribution with
`latexmk` and `biber` (e.g. TeX Live or MacTeX):

```bash
cd docs/report
latexmk          # writes build/main.pdf; only the LaTeX source is committed
```
