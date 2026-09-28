#!/bin/bash
# Sets transitquery_ro's password from the environment, so the password never
# appears in a committed file. Numbered 04 so it runs after 02_roles.sql creates
# the role (the image sorts names ignoring punctuation, so "02_roles_password"
# would run before "02_roles.sql").
set -e

: "${TRANSITQUERY_RO_PASSWORD:?Set TRANSITQUERY_RO_PASSWORD for the read-only database user}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v pw="$TRANSITQUERY_RO_PASSWORD" <<-'EOSQL'
    ALTER ROLE transitquery_ro PASSWORD :'pw';
EOSQL
