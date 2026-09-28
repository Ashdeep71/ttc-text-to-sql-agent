"""Checks AI-written SQL before it reaches the database.

This is the application-level safety layer. The database-level layer is the
read-only transitquery_ro role (db/init/02_roles.sql); either one alone should
stop a write, and together they back each other up.
"""



import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


class ValidationError(ValueError):
    """The SQL was rejected. The message is written for the LLM, so it can fix the query."""




FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,
    exp.Copy, exp.Command,
    exp.Into,           # like SELECT ... INTO new_table
    exp.Lock,           # SELECT ... FOR UPDATE
)

FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "set_config", "pg_reload_conf",
    "pg_terminate_backend", "pg_cancel_backend",
    "nextval", "setval",
}
FORBIDDEN_FUNCTION_PREFIXES = ("lo_", "dblink")


def _function_name(node: exp.Func) -> str:
    """sqlglot keeps unknown functions (like pg_sleep) as Anonymous nodes with the name as text."""
    name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
    return name.lower()


def _parse_single_statement(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except ParseError as error:
        raise ValidationError(f"Could not parse the SQL: {error}") from error
    if len(statements) != 1:
        raise ValidationError(f"Send exactly one SQL statement (got {len(statements)}).")
    return statements[0]



def _check_is_read_only(tree: exp.Expression, sql: str) -> None:
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        first_word = sql.split()[0].upper()
        raise ValidationError(f"Only SELECT queries are allowed (this starts with {first_word}).")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise ValidationError(f"{node.key.upper()} is not allowed; queries must only read data.")


def _check_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise ValidationError(f"The function {name}() is not allowed.")




def _apply_limit(tree: exp.Expression) -> exp.Expression:
    """Add LIMIT 100 if there is none; lower anything above 1000 to 1000."""
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(DEFAULT_LIMIT)
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(value, exp.Literal) and value.is_int and int(value.name) <= MAX_LIMIT:
        return tree                                   # a sensible LIMIT already
    return tree.limit(MAX_LIMIT)                      # too big, not a number, or FETCH FIRST





def validate(sql: str) -> str:
    """Return the SQL that is safe to run (with a LIMIT), or raise ValidationError."""
    if not sql or not sql.strip():
        raise ValidationError("The SQL is empty.")
    tree = _parse_single_statement(sql)
    _check_is_read_only(tree, sql)
    _check_functions(tree)
    return _apply_limit(tree).sql(dialect="postgres")



