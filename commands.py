"""One conservative Oracle SELECT or opted-in DML statement; native bind values only."""

import json
import math
import re
from validation import require, text, integer

WRITES = {"execute_sql"}
FORBIDDEN = set(
    "ALTER ANALYZE AUDIT BEGIN NEXTVAL CURRVAL CALL COMMENT COMMIT CREATE DECLARE DROP EXEC EXECUTE EXPLAIN GRANT INTO LOCK LOCKED PRAGMA RENAME RETURNING REVOKE ROLLBACK SAVEPOINT SET TRUNCATE UNION MINUS INTERSECT MODEL XMLTABLE JSON_TABLE DBMS UTL".split()
)
FUNCTIONS = set(
    "COUNT SUM MIN MAX AVG ABS CEIL FLOOR ROUND TRUNC MOD POWER SQRT LENGTH LOWER UPPER TRIM LTRIM RTRIM SUBSTR REPLACE CONCAT COALESCE NVL NVL2 NULLIF TO_CHAR TO_NUMBER TO_DATE TO_TIMESTAMP CAST EXTRACT ROW_NUMBER RANK DENSE_RANK OVER IN EXISTS AS VALUES SELECT FROM WHERE HAVING AND OR ON USING BY WHEN THEN ELSE NOT".split()
)


def check_sql(statement, write=False):
    text(statement, "statement", 32768, nonempty=True)
    require(
        not any(x in statement for x in (";", "--", "/*", "*/", "@", "\\", "{{", "}}")),
        "SQL scripts, comments, links and templates are forbidden.",
    )
    require(not re.search(r"\b[nqNQ]'", statement), "Alternative SQL quoting is unsupported.")
    tokens = []
    i = 0
    while i < len(statement):
        c = statement[i]
        if c in "'\"":
            quote = c
            i += 1
            quote_start = i
            while i < len(statement):
                if statement[i] == quote:
                    if i + 1 < len(statement) and statement[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                require(False, "Unclosed SQL quote.")
            require(
                quote != '"' or statement[quote_start : i - 1].upper() not in FORBIDDEN,
                "Unsupported quoted SQL identifier.",
            )
            tokens.append("STRING" if quote == "'" else "IDENTIFIER")
        elif c.isalpha() or c == "_":
            match = re.match(r"[A-Za-z_][A-Za-z0-9_$#]*", statement[i:])
            if match is None:
                require(False, "Invalid SQL token.")
                return statement
            tokens.append(match.group().upper())
            i += len(match.group())
        elif c.isspace():
            i += 1
        else:
            tokens.append(c)
            i += 1
    require(
        tokens and tokens[0] in ({"INSERT", "UPDATE", "DELETE", "MERGE"} if write else {"SELECT"}),
        "Unsupported SQL statement type.",
    )
    require(
        not (set(tokens) & FORBIDDEN) - ({"INTO", "SET", "NEXTVAL", "CURRVAL"} if write else set()),
        "Unsupported SQL clause.",
    )
    require("FOR" not in tokens, "Locking SQL is unsupported.")
    require(
        not set(tokens) & set("INSERT UPDATE DELETE MERGE".split()) or write,
        "DML requires execute_sql.",
    )
    for j, token in enumerate(tokens[:-1]):
        if tokens[j + 1] == "(" and re.fullmatch("[A-Z_][A-Z0-9_$#]*", token):
            table_columns = write and (
                j > 0
                and tokens[j - 1] == "INTO"
                or j > 2
                and tokens[j - 1] == "."
                and tokens[j - 3] == "INTO"
            )
            require(
                table_columns or token in FUNCTIONS and (j == 0 or tokens[j - 1] != "."),
                "Only unqualified approved builtin SQL functions are allowed.",
            )
    require(
        not any(t.startswith(("DBMS_", "UTL_")) for t in tokens), "Server packages are unsupported."
    )
    # Only positional Oracle binds; count mismatches are rejected by the driver.
    stripped = " ".join(tokens)
    require(not re.search(r":\s*[A-Z_]", stripped), "Use positional Oracle :1 binds.")
    return statement


def validate(name, args, config):
    require(name in {"query", "execute_sql"}, "Unknown Oracle action.")
    require(
        set(args) <= {"connection_ref", "statement", "parameters", "max_rows"},
        "Unknown action input.",
    )
    if name in WRITES:
        require("max_rows" not in args, "max_rows is query-only.")
    check_sql(args.get("statement"), name in WRITES)
    params = args.get("parameters", [])
    require(
        isinstance(params, list) and len(params) <= 100,
        "Parameters must be an array of at most 100 scalar values.",
    )
    for value in params:
        require(
            value is None
            or isinstance(value, str)
            or (type(value) is int and -(2**63) <= value < 2**63)
            or (type(value) is float and math.isfinite(value)),
            "Unsupported bind value.",
        )
        if isinstance(value, str):
            text(value, "parameter", 65536)
    require(
        len(json.dumps(params, allow_nan=False).encode()) <= 128 * 1024, "Parameters exceed limit."
    )
    if name in WRITES:
        require(
            config.get("allow_writes") is True,
            "Enable writes on this project connection.",
            code="write_disabled",
        )
    result = dict(args)
    result["parameters"] = params
    result["max_rows"] = integer(args.get("max_rows", 100), "max_rows", 1, 100)
    return result


def compile_command(name, args, config, **_):
    a = validate(name, args, config)
    return {
        "type": "oracle-sql",
        "statement": a["statement"],
        "staticParameters": json.dumps(a["parameters"], allow_nan=False),
        "parameters": [],
        "readOnly": name not in WRITES,
        "maxRows": a["max_rows"],
        "annotations": {
            "readOnlyHint": name not in WRITES,
            "destructiveHint": name in WRITES,
            "idempotentHint": False,
        },
    }, {}


def execute(name, args, config, context, call):
    value = call(*compile_command(name, args, config))
    if name in WRITES:
        row = value[0] if len(value) == 1 else None
        require(
            isinstance(row, dict) and type(row.get("rows_affected")) is int,
            "Invalid affected row result.",
            code="invalid_provider_response",
        )
        if not isinstance(row, dict):
            return {}
        return {"records": [], "count": row["rows_affected"], "applied": True}
    rows = value[0] if len(value) == 1 and isinstance(value[0], list) else value
    require(
        isinstance(rows, list)
        and len(rows) <= args.get("max_rows", 100)
        and all(isinstance(r, dict) for r in rows),
        "Invalid bounded result.",
        code="invalid_provider_response",
    )
    return {"records": rows, "count": len(rows), "applied": False}
