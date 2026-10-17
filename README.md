# TransitQuery

Ask questions about Toronto transit delays in plain English and get answers backed by SQL.

TransitQuery is a text-to-SQL agent over the TTC's public delay records for subway, bus and streetcar (about 1.24 million incidents, January 2014 to August 2026). A LangGraph agent has an OpenAI model write PostgreSQL, runs it through an MCP server that validates it and executes it against a read-only database, and retries with the error when a query fails.

```
$ uv run python -m transitquery.agent "Which subway station had the most delays in winter 2025?"
[attempt 1] 1 rows
  SELECT station, COUNT(*) AS incidents
  FROM subway_delays
  WHERE min_delay > 0
    AND station IS NOT NULL
    AND occurred_at >= '2024-12-01' AND occurred_at < '2025-03-01'
  GROUP BY station ORDER BY incidents DESC LIMIT 1

BLOOR-YONGE had the most delays in winter 2025, with 141 incidents.
```

None of the three filters is in the question. They come from what the agent is told about this data (see [How the agent works](#how-the-agent-works)).

## Results

21 hand-written questions with reference SQL, scored by comparing query results ([details](#evaluation)). Model: `gpt-5.4-mini-2026-03-17`.

| | Accuracy | Easy | Medium | Hard | Latency p50 / p95 |
|---|---|---|---|---|---|
| **With domain hints** | **100% (21/21)** | 6/6 | 8/8 | 7/7 | 2.0 s / 2.4 s |
| Schema only (ablation) | 76% (16/21) | 3/6 | 7/8 | 6/7 | 2.2 s / 2.7 s |

Every miss without hints was a definition error, not a SQL error. The model counted zero-minute incidents as delays, counted weekends as rush hour, or ranked a NULL station first. The hints are twelve short facts about this data, and they close that gap.

Scope of these numbers: one run of 21 questions. No first query failed in either run, so the eval didn't exercise the retry loop. The unit tests cover retry and stop-at-3 behaviour with a fake model. Reports are in [`eval/reports/`](eval/reports/).

## What it shows

- **An LLM agent with self-correction.** A LangGraph graph loads the schema once, writes SQL with structured output, runs it, and on an error sends the failed query and the database's message back to the model, up to 3 attempts.
- **Evaluation, not just demos.** An execution-match scorer, accuracy by difficulty, latency percentiles, and an ablation that measures what the prompt's domain knowledge is worth.
- **Two layers of safety for LLM-written SQL.** A `sqlglot` validator rejects anything but a single read-only query. Separately, the database role can only read, so a write fails even if the validator misses it. Integration tests check each layer on its own.
- **Data engineering on messy real-world data.** The raw TTC files span 12 years, 35 files and 15 different column layouts. There are 111 spellings of the 4 subway lines, station names cut off at 22 characters, and a switch in 2025 from text categories to TTC codes. The cleaning pipeline turns all of it into four tables and logs every row it drops.
- **Tools over MCP.** The same server answers Claude Desktop and the agent.

## Architecture

```
            question
               │
     ┌─────────▼──────────┐        ┌──────────────────────┐
     │  LangGraph agent   │  MCP   │      MCP server      │
     │  (OpenAI model)    ├───────►│ list_tables          │
     │  generate → run →  │        │ describe_table       │
     │  retry on error    │        │ run_query            │
     └─────────▲──────────┘        │   └─ validator.py    │
               │                   └──────────┬───────────┘
     ┌─────────┴──────────┐                   │ transitquery_ro (read-only)
     │ CLI / eval runner  │        ┌──────────▼───────────┐
     │ (FastAPI planned)  │        │   PostgreSQL 16      │
     └────────────────────┘        │   schema: ttc        │
                                   └──────────▲───────────┘
     Claude Desktop ──stdio──► MCP server     │ COPY
                                   ┌──────────┴───────────┐
                                   │ ETL: download, clean │
                                   │ → data/processed/    │
                                   └──────────────────────┘
```

## How the agent works

```
START → load_schema → generate_sql → execute ──ok──────────────► summarize → END
                           ▲            │
                           └──error─────┤ attempts < 3
                                        └──error, attempts = 3──► fail → END
```

| Node | What it does |
|---|---|
| `load_schema` | Calls `list_tables` and `describe_table` once per process and caches the result. The schema is static. |
| `generate_sql` | The model returns `{reasoning, sql}` as structured output. The prompt holds the schema with every column's comment, the domain hints and five worked examples. On a retry it also holds the failed query and its error. |
| `execute` | Calls `run_query` on the MCP server and records the attempt in a trace. |
| `summarize` | Writes a one-to-three-sentence answer from the returned rows only. |
| `fail` | After 3 failed attempts, returns the last error instead of guessing. |

The domain hints ([`agent/prompts.py`](src/transitquery/agent/prompts.py)) are definitions a model can't infer from column names. For example, a "delay" means `min_delay > 0`, rush hour is weekdays 7–9 and 16–18, winter 2025 means December 2024 to February 2025, and bus reasons are text up to 2024 and codes from 2025.

The agent talks to the MCP server with the MCP SDK's own client. `langchain-mcp-adapters` only supports MCP 1.x, and the graph calls the tools in a fixed order, so it doesn't need them wrapped as LangChain tools.

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

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, and an OpenAI API key for the agent.

```bash
uv sync --all-extras
cp .env.example .env        # then set TRANSITQUERY_RO_PASSWORD, OPENAI_API_KEY and OPENAI_MODEL
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
docker run -d --name transitquery-db -p 5433:5432 \
  -e POSTGRES_PASSWORD=<admin-password> \
  -e TRANSITQUERY_RO_PASSWORD=<readonly-password> \
  transitquery-db
```

The container is published on host port **5433** so it doesn't clash with a locally installed Postgres on 5432. The app reads the port from `TRANSITQUERY_DB_PORT` in `.env`.

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

### 3. Ask the agent

```bash
uv run python -m transitquery.agent "What were the top 5 bus routes by total delay minutes in 2024?"
```

The agent starts the MCP server itself over stdio. To use a server that's already running, set `TRANSITQUERY_MCP_URL=http://127.0.0.1:8001/mcp`. It prints each attempt's SQL, then the answer, the number of attempts and the latency.

### 4. Run the evaluation

```bash
uv run python -m transitquery.eval.runner                    # model from OPENAI_MODEL
uv run python -m transitquery.eval.runner --model <name>     # compare another model
uv run python -m transitquery.eval.runner --no-hints         # ablation: schema only
uv run python -m transitquery.eval.runner --only hard        # a subset, by id prefix
```

Each run writes a Markdown and a JSON report to `eval/reports/`. `--min-accuracy 0.8` makes it exit with an error below that score, for use in CI.

### 5. Run the MCP server on its own

The server exposes three tools to any MCP client:

| Tool | Returns |
|---|---|
| `list_tables()` | Each table with its description and approximate row count |
| `describe_table(name)` | Columns with type, nullability and meaning, plus 5 sample rows |
| `run_query(sql)` | `{columns, rows, row_count, truncated, executed_sql}`, or an error message the model can use to fix the query |

```bash
uv run python -m transitquery.mcp_server                                # stdio (for Claude Desktop)
uv run python -m transitquery.mcp_server --transport streamable-http    # HTTP on 127.0.0.1:8001/mcp
```

Settings come from `.env` in the project root (see [`src/transitquery/config.py`](src/transitquery/config.py)). Server settings start with `TRANSITQUERY_`, for example `TRANSITQUERY_DB_PORT` or `TRANSITQUERY_STATEMENT_TIMEOUT_MS`. The server finds `.env` by absolute path, so it works whatever directory it's started from.

`truncated` is true only when the server's own LIMIT cut the result short. A LIMIT you wrote yourself doesn't count.

### 6. Connect Claude Desktop

In Claude Desktop, open **Settings → Developer → Edit Config** and add the server under `mcpServers`, keeping any keys already in the file:

```json
{
  "mcpServers": {
    "transitquery": {
      "command": "C:\\path\\to\\transitquery\\.venv\\Scripts\\python.exe",
      "args": ["-m", "transitquery.mcp_server"]
    }
  }
}
```

On macOS or Linux the command is `/path/to/transitquery/.venv/bin/python`. Pointing at the project's own Python means `uv` doesn't need to be on Claude's PATH. No password goes in this file, because the server reads it from `.env`.

Quit Claude Desktop completely (from the system tray icon or menu bar, not just by closing the window) and reopen it. `transitquery` should show as running under Settings → Developer. Then try:

- *Which subway station had the most delays in winter 2025?*
- *What are the top 5 causes of bus delays by total minutes?*
- *Delete all subway delays.* (This is refused.)

If the server doesn't start, run the same command in a terminal to see the error. If it waits silently, it's working: it's waiting for a client. Claude Desktop also writes a log, `mcp-server-transitquery.log`, in its `logs` folder.

### 7. Run the tests

```bash
uv run pytest                      # everything
uv run pytest tests/unit           # no database or API needed
uv run pytest tests/integration    # needs the transitquery-db container running
```

The unit tests cover the ETL, the validator, the eval scorer, and the agent's retry loop with a fake model. The integration tests call the MCP tools end to end against the real database. They also test the read-only role directly, without the validator, and check that the statement timeout cancels an expensive query. If the database isn't reachable, they're skipped rather than failed.

## Evaluation

[`eval/questions.yaml`](eval/questions.yaml) has 21 questions, tagged by mode (subway, bus, streetcar, all), difficulty and feature: aggregation, ranking, time windows, joins to delay codes, era-dependent columns, nested aggregation and a cross-mode `UNION`.

Answers are scored by **execution match**: the gold SQL and the agent's SQL both run through the same validator and read-only database, and their results are compared. Many different queries are correct, so comparing SQL text would undercount. The rules ([`eval/compare.py`](src/transitquery/eval/compare.py)) avoid marking a right answer wrong for its shape:

- Each gold column must match some predicted column by value. Names don't matter, and extra columns are fine. Gold queries select only the columns that are the answer.
- With a top-level `ORDER BY`, row order matters, and a longer ranking passes if it starts with the gold rows.
- Without one, rows are compared as a multiset.
- Numbers are compared at 1 decimal place.

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

On top of the role, [`db.py`](src/transitquery/mcp_server/db.py) runs every query in its own `READ ONLY` transaction with a per-query timeout, and always rolls that transaction back, even when the query succeeds.

Either check alone should stop a write. The integration tests check each one separately.

## Project layout

```
transitquery/
├── src/transitquery/
│   ├── etl/            download.py, clean_{subway,bus,streetcar,codes}.py, normalize.py, common.py, run.py
│   ├── mcp_server/     server.py (the 3 tools), validator.py, db.py (read-only execution)
│   ├── agent/          graph.py (LangGraph), prompts.py (schema, hints, examples), client.py (MCP)
│   ├── eval/           compare.py (scoring), runner.py
│   └── config.py       settings from .env
├── eval/               questions.yaml, reports/
├── db/                 Dockerfile, init/ (schema, roles, loader)
├── data/
│   ├── raw/            source files from Toronto Open Data (gitignored)
│   └── processed/      cleaned, gzipped CSVs, loaded into Postgres
├── notebooks/          01-cleaner.ipynb (data exploration)
├── tests/
│   ├── unit/           ETL, validator, eval scorer, agent retry loop
│   └── integration/    MCP tools, read-only role and timeout against the real database
└── DATA_NOTES.md       known data issues and how each is handled
```

## Roadmap

- [x] ETL: download, clean and normalize all three modes
- [x] PostgreSQL schema with column comments, read-only role, preloaded Docker image
- [x] SQL validator with unit tests
- [x] MCP server (`list_tables`, `describe_table`, `run_query`) over stdio and streamable HTTP, plus a Claude Desktop config
- [x] Integration tests against the real database
- [x] LangGraph agent: generate SQL, run it, retry up to 3 times on error, then summarize the result
- [x] Evaluation: execution-match scorer, accuracy, self-correction rate, latency, and a no-hints ablation
- [ ] Grow the eval to 60–100 questions, including ones designed to make the first query fail
- [ ] FastAPI: `POST /ask`, `GET /health`, `GET /tables`
- [ ] Docker Compose, GitHub Actions CI, deployment to Azure Container Apps, nightly evaluation run

## Tech stack

Python 3.12 · uv · pandas · PostgreSQL 16 · psycopg 3 · sqlglot · MCP Python SDK · LangGraph · LangChain · OpenAI · pytest · ruff · Docker
