# TransitQuery

Ask questions about Toronto transit delays in plain English and get answers backed by SQL.

TransitQuery is a text-to-SQL agent over the TTC's public delay records for subway, bus and streetcar (about 1.24 million incidents, January 2014 to August 2026). An LLM writes PostgreSQL queries, and an MCP server checks and runs them against a read-only database. When a query fails, the agent reads the error and tries again.

> **Status: work in progress.** The data pipeline, the database and the SQL validator are built. The MCP server, the agent, the API and the evaluation suite are next. See [Roadmap](#roadmap).

## What it shows

- **Data engineering on messy real-world data.** The raw TTC files span 12 years, 35 files and 15 different column layouts. There are 111 spellings of the 4 subway lines, station names cut off at 22 characters, and a switch in 2025 from text categories to TTC codes. The cleaning pipeline turns all of it into four clean tables and logs every row it drops.
- **Two layers of safety for LLM-written SQL.** An application-level validator rejects anything that isn't a single read-only query. Separately, the database role can only read, so a write would fail even if the validator missed it.
- **Production practice.** The plan includes unit and integration tests, an evaluation set with execution accuracy and self-correction rate, Docker, CI/CD, and deployment to Azure.

## Architecture

```
            question
               │
     ┌─────────▼──────────┐        ┌──────────────────────┐
     │  LangGraph agent   │  MCP   │      MCP server      │
     │  (OpenAI model)    ├───────►│ list_tables          │
     │  generate → run →  │        │ describe_table       │
     │  retry on error    │        │ run_query            │
     └─────────▲──────────┘        │   └─ validator.py    │  ✅ built
               │                   └──────────┬───────────┘
     ┌─────────┴──────────┐                   │ transitquery_ro
     │  FastAPI  /ask     │        ┌──────────▼───────────┐
     └────────────────────┘        │   PostgreSQL 16      │  ✅ built
                                   │   schema: ttc        │
     Claude Desktop ──stdio──► MCP └──────────▲───────────┘
                                              │ COPY
                                   ┌──────────┴───────────┐
                                   │ ETL: download, clean │  ✅ built
                                   │ → data/processed/    │
                                   └──────────────────────┘
```

## The data

Source: [City of Toronto Open Data](https://open.toronto.ca/), published by the TTC ([subway](https://open.toronto.ca/dataset/ttc-subway-delay-data/), [bus](https://open.toronto.ca/dataset/ttc-bus-delay-data/), [streetcar](https://open.toronto.ca/dataset/ttc-streetcar-delay-data/)).

| Table | Rows | Key columns |
|---|---|---|
| `subway_delays` | 266,613 | `occurred_at`, `line_code`, `line_name`, `station`, `code`, `min_delay`, `min_gap`, `bound` |
| `bus_delays` | 803,323 | `occurred_at`, `route`, `location`, `incident`, `code`, `min_delay`, `min_gap`, `bound` |
| `streetcar_delays` | 169,614 | same as bus |
| `delay_codes` | 343 | `code`, `description`, `mode` |

Every delay table also has `hour`, `day_of_week`, `is_weekend`, `vehicle` and `source_file`. Timestamps are in America/Toronto time.

Things to know when querying:

- **Many incidents have zero delay.** About 65% of subway rows have `min_delay = 0`: an incident was logged but no train was held up. Questions about "delays" should filter on `min_delay > 0`.
- **Bus and streetcar changed how they record the reason in 2025.** Up to 2024 the reason is a text category in `incident` (such as `Mechanical`). From 2025 it's a TTC code in `code` (such as `MTDV`). The two don't map one-to-one, so they're kept in separate columns.
- **Stations use their current names.** For example, `DUNDAS` became `TMU` and `EGLINTON WEST` became `CEDARVALE`, both in 2024. Old records are mapped to the new names, and the original text stays in `station_raw`.

[`DATA_NOTES.md`](DATA_NOTES.md) lists all 23 known data issues and how each is handled. [`data/processed/README.md`](data/processed/README.md) has row counts and what each cleaning step removed.

## Getting started

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync --all-extras
cp .env.example .env        # then set TRANSITQUERY_RO_PASSWORD
```

### 1. Build the dataset (optional)

The cleaned data is already committed in `data/processed/`. To rebuild it from the source files:

```bash
uv run python -m transitquery.etl.run                   # download, clean, write data/processed/
uv run python -m transitquery.etl.run --skip-download   # reuse files already in data/raw/
uv run python -m transitquery.etl.run --min-year 2020   # keep less history
```

### 2. Start the database

The image is `postgres:16` with the setup scripts and processed data baked in. The data loads on the first start.

```bash
docker build -f db/Dockerfile -t transitquery-db .
docker run -d --name transitquery-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=<admin-password> \
  -e TRANSITQUERY_RO_PASSWORD=<readonly-password> \
  transitquery-db
```

The startup scripts in `db/init/` run in order:

| Script | What it does |
|---|---|
| `01_schema.sql` | Creates the tables in the `ttc` schema, with indexes and a comment on every column |
| `02_roles.sql` | Creates the read-only role `transitquery_ro` |
| `03_load.sh` | Loads each `*.csv.gz` with `COPY`, then runs `ANALYZE` |
| `04_roles_password.sh` | Sets the read-only role's password from the environment, so no secret is stored in git |

Check that the read-only role really can't write:

```bash
docker exec -it transitquery-db psql -U transitquery_ro -d postgres -h localhost \
  -c "DELETE FROM subway_delays"
# ERROR:  cannot execute DELETE in a read-only transaction
```

### 3. Run the tests

```bash
uv run pytest
```

## Safety model

LLM-written SQL passes two independent checks before it can touch the data.

**1. Validator** ([`src/transitquery/mcp_server/validator.py`](src/transitquery/mcp_server/validator.py)). It parses the query with `sqlglot` and:

- rejects anything that doesn't parse, and anything that isn't exactly one statement. This blocks stacked queries like `SELECT 1; DROP TABLE x`.
- requires a `SELECT` or a set operation such as `UNION`, then walks the whole tree. It rejects writes, schema changes, `COPY`, `SELECT … INTO`, `FOR UPDATE`, and data-changing CTEs.
- blocks risky functions: `pg_sleep`, `pg_read_file`, `pg_ls_dir`, `set_config`, `pg_terminate_backend`, `nextval`, and anything starting with `lo_` or `dblink`.
- adds `LIMIT 100` when there is no limit, and lowers any limit above 1000 to 1000.

Rejection messages are written for the LLM, so the agent can fix the query and retry.

**2. Database role** ([`db/init/02_roles.sql`](db/init/02_roles.sql)). `transitquery_ro` has:

- `SELECT` on the four tables only, granted by name, so tables added later aren't readable.
- no privileges from `PUBLIC`, and nothing in the `public` schema.
- `default_transaction_read_only = on`.
- `statement_timeout = 5s`, which cancels runaway queries.

Either check alone should stop a write.

## Project layout

```
transitquery/
├── src/transitquery/
│   ├── etl/            download.py, clean_{subway,bus,streetcar,codes}.py, normalize.py, common.py, run.py
│   └── mcp_server/     validator.py
├── db/                 Dockerfile, init/ (schema, roles, loader)
├── data/
│   ├── raw/            source files from Toronto Open Data (gitignored)
│   └── processed/      cleaned, gzipped CSVs, loaded into Postgres
├── notebooks/          01-cleaner.ipynb (data exploration)
├── tests/unit/         normalizers, cleaners, ETL run, validator
└── DATA_NOTES.md       known data issues and how each is handled
```

## Roadmap

- [x] ETL: download, clean and normalize all three modes
- [x] PostgreSQL schema with column comments, read-only role, preloaded Docker image
- [x] SQL validator with unit tests
- [ ] MCP server (`list_tables`, `describe_table`, `run_query`) over stdio and streamable HTTP, plus a Claude Desktop config
- [ ] LangGraph agent: generate SQL, run it, retry up to 3 times on error, then summarize the result
- [ ] FastAPI: `POST /ask`, `GET /health`, `GET /tables`
- [ ] Evaluation: 60–100 hand-written questions with reference SQL; report execution accuracy, self-correction rate and latency
- [ ] Docker Compose, GitHub Actions CI, deployment to Azure Container Apps, nightly evaluation run

The full plan is in [`../docs/DESIGN.md`](../docs/DESIGN.md).

## Tech stack

Python 3.12 · uv · pandas · PostgreSQL 16 · psycopg 3 · sqlglot · MCP Python SDK · LangGraph · langchain-openai · FastAPI · pytest · ruff · Docker · GitHub Actions · Azure Container Apps
