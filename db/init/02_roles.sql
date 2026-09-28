-- transitquery_ro: the read-only user the MCP server connects as.
-- Its password is set by 04_roles_password.sh, so no secret is stored in git.

CREATE ROLE transitquery_ro LOGIN;

-- Remove the permissions Postgres gives every user by default (PUBLIC),
-- then grant back only what the read-only user needs.
-- current_database() avoids hard-coding the name (it's whatever POSTGRES_DB is).
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO transitquery_ro', current_database());
END
$$;

-- The tables live in ttc (01_schema.sql); nobody but the admin gets anything in public.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA ttc TO transitquery_ro;

-- Listed by name, so tables added later aren't readable by default.
GRANT SELECT ON ttc.subway_delays, ttc.bus_delays, ttc.streetcar_delays, ttc.delay_codes TO transitquery_ro;

-- Applied to every session this user opens.
ALTER ROLE transitquery_ro SET search_path = ttc;                     -- queries can say just "subway_delays"
ALTER ROLE transitquery_ro SET default_transaction_read_only = on;   -- second lock, on top of SELECT-only grants
ALTER ROLE transitquery_ro SET statement_timeout = '5s';             -- cancel runaway queries
ALTER ROLE transitquery_ro SET timezone = 'America/Toronto';         -- show times and EXTRACT(hour) in local time
