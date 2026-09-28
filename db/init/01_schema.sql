CREATE TABLE subway_delays(
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    hour smallint NOT NULL,
    day_of_week text NOT NULL,
    is_weekend boolean NOT NULL, 
    line_code text NOT NULL,
    line_name text NOT NULL, 
    station text,
    station_raw text,
    code text,
    min_delay integer NOT NULL,
    min_gap integer,
    bound text,
    vehicle integer,
    source_file text NOT NULL
    
);

CREATE INDEX ON subway_delays(occurred_at);
CREATE INDEX ON subway_delays(station);
CREATE INDEX ON subway_delays(line_code);
CREATE INDEX ON subway_delays(code);

COMMENT ON TABLE subway_delays IS
  'One row per TTC subway delay incident, January 2014 to present. Source: City of Toronto Open Data. Cleaned: station and line names standardized, duplicates removed.';

COMMENT ON COLUMN subway_delays.id IS 'Row number, assigned on load. No meaning in the source data.';
COMMENT ON COLUMN subway_delays.occurred_at IS 'When the incident happened, in Toronto local time (America/Toronto).';
COMMENT ON COLUMN subway_delays.hour IS 'Hour of day, 0-23, Toronto local time. Rush hour is usually 7-9 and 16-18 on weekdays.';
COMMENT ON COLUMN subway_delays.day_of_week IS 'Day name: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.';
COMMENT ON COLUMN subway_delays.is_weekend IS 'True on Saturday and Sunday.';
COMMENT ON COLUMN subway_delays.line_code IS
  'Subway line number: ''1'' Yonge-University, ''2'' Bloor-Danforth, ''3'' Scarborough RT (closed July 2023), ''4'' Sheppard. Incidents at interchange stations list several lines, e.g. ''1/2''. To include those, use line_code LIKE ''%1%''.';
COMMENT ON COLUMN subway_delays.line_name IS 'Readable line name, e.g. ''Line 1 Yonge-University''.';
COMMENT ON COLUMN subway_delays.station IS
  'Standardized station name, uppercase, current official name (e.g. ''BLOOR-YONGE'', ''ST GEORGE'', ''QUEEN''''S PARK''). Renamed stations use the new name: DUNDAS is ''TMU'', EGLINTON WEST is ''CEDARVALE'', DOWNSVIEW is ''SHEPPARD WEST''. NULL when the location is not a station (a yard, a whole line, or between two stations); see station_raw.';
COMMENT ON COLUMN subway_delays.station_raw IS 'Location exactly as written in the source data, before cleaning.';
COMMENT ON COLUMN subway_delays.code IS 'TTC delay reason code, e.g. ''MUSC''. Join to delay_codes.code for a description.';
COMMENT ON COLUMN subway_delays.min_delay IS
  'Minutes of delay caused. 0 means an incident was logged but caused no delay (about 65% of rows). When asking about delays, filter min_delay > 0.';
COMMENT ON COLUMN subway_delays.min_gap IS 'Minutes between this train and the train ahead of it, including the delay.';
COMMENT ON COLUMN subway_delays.bound IS 'Direction of travel: ''N'', ''S'', ''E'', ''W''. NULL when not recorded or unclear.';
COMMENT ON COLUMN subway_delays.vehicle IS 'Train number. NULL when not recorded.';
COMMENT ON COLUMN subway_delays.source_file IS 'Name of the source file, for tracing.';


-- ============ bus_delays ============

CREATE TABLE bus_delays(
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    hour smallint NOT NULL,
    day_of_week text NOT NULL,
    is_weekend boolean NOT NULL,
    route integer NOT NULL,
    location text,
    incident text,
    code text,
    min_delay integer NOT NULL,
    min_gap integer,
    bound text,
    vehicle integer,
    source_file text NOT NULL
);

CREATE INDEX ON bus_delays(occurred_at);
CREATE INDEX ON bus_delays(route);
CREATE INDEX ON bus_delays(incident);
CREATE INDEX ON bus_delays(code);

COMMENT ON TABLE bus_delays IS
  'One row per TTC bus delay incident, January 2014 to present. Source: City of Toronto Open Data. Cleaned: routes and directions standardized, duplicates removed.';

COMMENT ON COLUMN bus_delays.id IS 'Row number, assigned on load. No meaning in the source data.';
COMMENT ON COLUMN bus_delays.occurred_at IS 'When the incident happened, in Toronto local time (America/Toronto).';
COMMENT ON COLUMN bus_delays.hour IS 'Hour of day, 0-23, Toronto local time. Rush hour is usually 7-9 and 16-18 on weekdays.';
COMMENT ON COLUMN bus_delays.day_of_week IS 'Day name: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.';
COMMENT ON COLUMN bus_delays.is_weekend IS 'True on Saturday and Sunday.';
COMMENT ON COLUMN bus_delays.route IS 'Bus route number, e.g. 52 for 52 Lawrence West. Branch letters are removed (52A and 52B are both 52).';
COMMENT ON COLUMN bus_delays.location IS
  'Where it happened, free text in uppercase, e.g. ''KENNEDY STATION'' or ''QUEEN AND LESLIE''. Not fully standardized: use ILIKE ''%KENNEDY%'' rather than exact matches.';
COMMENT ON COLUMN bus_delays.incident IS
  'Plain-English reason category, e.g. ''Mechanical'', ''Diversion'', ''Security''. Filled for 2014-2024 only; NULL from 2025 on, when the TTC switched to codes (see code).';
COMMENT ON COLUMN bus_delays.code IS
  'TTC delay reason code, e.g. ''EFO''. Filled from 2025 on only; NULL before. Join to delay_codes.code for a description. For reasons across all years, use incident for 2014-2024 and code for 2025 on.';
COMMENT ON COLUMN bus_delays.min_delay IS 'Minutes of delay caused. 0 means an incident was logged but caused no delay.';
COMMENT ON COLUMN bus_delays.min_gap IS 'Minutes between this bus and the bus ahead of it, including the delay.';
COMMENT ON COLUMN bus_delays.bound IS 'Direction of travel: ''N'', ''S'', ''E'', ''W'', or ''BOTH'' (both directions affected). NULL when not recorded or unclear.';
COMMENT ON COLUMN bus_delays.vehicle IS 'Bus number. NULL when not recorded.';
COMMENT ON COLUMN bus_delays.source_file IS 'Name of the source file, for tracing.';


-- ============ streetcar_delays ============

CREATE TABLE streetcar_delays(
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    hour smallint NOT NULL,
    day_of_week text NOT NULL,
    is_weekend boolean NOT NULL,
    route integer NOT NULL,
    location text,
    incident text,
    code text,
    min_delay integer NOT NULL,
    min_gap integer,
    bound text,
    vehicle integer,
    source_file text NOT NULL
);

CREATE INDEX ON streetcar_delays(occurred_at);
CREATE INDEX ON streetcar_delays(route);
CREATE INDEX ON streetcar_delays(incident);
CREATE INDEX ON streetcar_delays(code);

COMMENT ON TABLE streetcar_delays IS
  'One row per TTC streetcar delay incident, January 2014 to present. Source: City of Toronto Open Data. Cleaned: routes and directions standardized, duplicates removed.';

COMMENT ON COLUMN streetcar_delays.id IS 'Row number, assigned on load. No meaning in the source data.';
COMMENT ON COLUMN streetcar_delays.occurred_at IS 'When the incident happened, in Toronto local time (America/Toronto).';
COMMENT ON COLUMN streetcar_delays.hour IS 'Hour of day, 0-23, Toronto local time. Rush hour is usually 7-9 and 16-18 on weekdays.';
COMMENT ON COLUMN streetcar_delays.day_of_week IS 'Day name: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.';
COMMENT ON COLUMN streetcar_delays.is_weekend IS 'True on Saturday and Sunday.';
COMMENT ON COLUMN streetcar_delays.route IS
  'Streetcar route number, e.g. 504 for 504 King, 501 for 501 Queen. 300-series are night routes. Branch letters are removed (504A is 504).';
COMMENT ON COLUMN streetcar_delays.location IS
  'Where it happened, free text in uppercase, e.g. ''DUNDAS WEST STATION'' or ''QUEEN AND RONCESVALLES''. Not fully standardized: use ILIKE ''%RONCESVALLES%'' rather than exact matches.';
COMMENT ON COLUMN streetcar_delays.incident IS
  'Plain-English reason category, e.g. ''Mechanical'', ''Held By'', ''Investigation''. Filled for 2014-2024 only; NULL from 2025 on, when the TTC switched to codes (see code).';
COMMENT ON COLUMN streetcar_delays.code IS
  'TTC delay reason code, e.g. ''MTDV''. Filled from 2025 on only; NULL before. Join to delay_codes.code for a description. For reasons across all years, use incident for 2014-2024 and code for 2025 on.';
COMMENT ON COLUMN streetcar_delays.min_delay IS 'Minutes of delay caused. 0 means an incident was logged but caused no delay.';
COMMENT ON COLUMN streetcar_delays.min_gap IS 'Minutes between this streetcar and the one ahead of it, including the delay.';
COMMENT ON COLUMN streetcar_delays.bound IS 'Direction of travel: ''N'', ''S'', ''E'', ''W'', or ''BOTH'' (both directions affected). NULL when not recorded or unclear.';
COMMENT ON COLUMN streetcar_delays.vehicle IS 'Streetcar number. NULL when not recorded.';
COMMENT ON COLUMN streetcar_delays.source_file IS 'Name of the source file, for tracing.';


-- ============ delay_codes ============

CREATE TABLE delay_codes(
    code text PRIMARY KEY,
    description text NOT NULL,
    mode text NOT NULL
);

COMMENT ON TABLE delay_codes IS
  'Lookup table: what each TTC delay code means. Join on code from subway_delays, bus_delays or streetcar_delays. A few codes in the delay tables are not listed here (the TTC never published them), so use a LEFT JOIN.';

COMMENT ON COLUMN delay_codes.code IS 'Delay code, e.g. ''MUSC''. Unique across all modes.';
COMMENT ON COLUMN delay_codes.description IS 'What the code means, uppercase, e.g. ''SI SPEED CONTROL'' for MUSC.';
COMMENT ON COLUMN delay_codes.mode IS
  'Which system the code belongs to: ''subway'', ''bus'' or ''streetcar''. Scarborough RT codes are listed as ''subway''. Streetcar delays sometimes use bus codes.';