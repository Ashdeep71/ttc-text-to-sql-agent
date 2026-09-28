#!/bin/bash
# Loads data/processed/*.csv.gz into the ttc tables on first start.
# Runs after 01_schema.sql (tables) and 02_roles.sql, before 04_roles_password.sh.
set -eo pipefail

DATA_DIR="${DATA_DIR:-/data}"


TABLES=(delay_codes subway_delays bus_delays streetcar_delays)


for table in "${TABLES[@]}"; do
    file="$DATA_DIR/$table.csv.gz"

    if [ ! -f "$file" ]; then
        echo "03_load.sh: missing $file (run: uv run python -m transitquery.etl.run)" >&2
        exit 1
    fi

     IFS= read -r columns < <(gunzip -c "$file")

      echo "03_load.sh: loading ttc.$table"
    gunzip -c "$file" | psql -v ON_ERROR_STOP=1 \
        --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c "COPY ttc.$table ($columns) FROM STDIN WITH (FORMAT csv, HEADER true)"

    done


psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "ANALYZE"
echo "03_load.sh: done"
