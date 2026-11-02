"""Bounded Oracle Dataset actions; intentionally single-table, explicit-column SQL."""

from __future__ import annotations

import math
import re
import time

from commands import compile_command
from validation import Failure, bounded_json, connection_values, integer, require, text

ACTIONS = frozenset(
    {
        "test_connection",
        "introspect_schema",
        "validate_query",
        "preview_query",
        "execute_template",
        "infer_output_schema",
    }
)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*\Z")
RESOURCE = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*\.[A-Za-z_][A-Za-z0-9_$#]*\Z")
TOKEN = re.compile(
    r"\s+|'(?:[^']|'')*'|:[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_$#]*|-?[0-9]+(?:\.[0-9]+)?|<=|>=|<>|!=|[=<>.,]"
)
TYPES = {"string", "integer", "number", "null"}


def catalog():
    return [
        {
            "connector_id": "oracle",
            "connector_type_id": "oracle",
            "database_kind": "oracle",
            "source_kind": "oracle",
            "display_name": "Oracle",
            "source_extension_id": "flowsteward.oracle",
            "source_extension_name": "Oracle",
            "source_provider": "Oracle",
            "query_language": "sql",
            "access_mode": "read_only",
        }
    ]


def _scope(dataset):
    require(isinstance(dataset, dict), "Dataset must be an object.")
    scope = dataset.get("resource_scope_jsonb", {})
    require(isinstance(scope, dict), "Dataset resource scope must be an object.")
    resources = scope.get("resources")
    require(
        isinstance(resources, list) and 0 < len(resources) <= 32,
        "Select 1–32 qualified dataset resources.",
    )
    result = {}
    for item in resources:
        require(isinstance(item, dict), "Invalid dataset resource.")
        name = item.get("resource_id")
        require(
            isinstance(name, str) and RESOURCE.fullmatch(name),
            "Resource requires unquoted SCHEMA.TABLE.",
        )
        columns = item.get("columns")
        require(
            columns is None or isinstance(columns, list) and len(columns) <= 100,
            "Invalid column allowlist.",
        )
        if columns is not None:
            require(
                all(isinstance(c, str) and IDENTIFIER.fullmatch(c) for c in columns),
                "Invalid allowed column.",
            )
        key = name.upper()
        require(key not in result, "Duplicate resource scope.")
        result[key] = None if columns is None else {c.upper() for c in columns}
    return result


def _query(args, *, execution):
    dataset = args.get("dataset")
    scope = _scope(dataset)
    template = args.get("query_template")
    require(isinstance(template, dict), "Saved query template is required.")
    require(template.get("query_language", "sql") == "sql", "Only SQL saved queries are supported.")
    require(
        isinstance(template.get("query_template_id"), str) and bool(template["query_template_id"]),
        "Saved query identifier is required.",
    )
    require(
        isinstance(dataset.get("dataset_id"), str)
        and bool(dataset["dataset_id"])
        and template.get("dataset_id") == dataset["dataset_id"],
        "Saved query belongs to another dataset.",
    )
    definition = template.get("query_definition_jsonb")
    require(
        isinstance(definition, dict) and set(definition) == {"sql"},
        "Saved SQL definition is required.",
    )
    sql = text(definition.get("sql"), "sql", 32768, nonempty=True)
    tokens, position = [], 0
    while position < len(sql):
        match = TOKEN.match(sql, position)
        if match is None:
            raise Failure("invalid_payload", "Unsupported saved SQL syntax.")
        token = match.group()
        if not token.isspace():
            tokens.append(token)
        position = match.end()
    cursor = 0

    def take():
        nonlocal cursor
        require(cursor < len(tokens), "Incomplete saved SQL.")
        token = tokens[cursor]
        cursor += 1
        return token

    def keyword(value):
        require(take().upper() == value, "Unsupported saved SQL grammar.")

    def column():
        value = take()
        require(IDENTIFIER.fullmatch(value) is not None, "Use explicit unquoted column names.")
        return value.upper()

    keyword("SELECT")
    projected = [column()]
    while cursor < len(tokens) and tokens[cursor] == ",":
        take()
        projected.append(column())
    require(len(projected) <= 100 and len(set(projected)) == len(projected), "Invalid projection.")
    keyword("FROM")
    owner = column()
    keyword(".")
    table = column()
    resource = owner + "." + table
    require(resource in scope, "Table is outside the dataset resource allowlist.")
    referenced_columns = set(projected)
    if cursor < len(tokens) and tokens[cursor].upper() == "WHERE":
        take()
        while True:
            referenced_columns.add(column())
            operator = take().upper()
            if operator == "IS":
                if cursor < len(tokens) and tokens[cursor].upper() == "NOT":
                    take()
                keyword("NULL")
            else:
                require(
                    operator in {"=", "<>", "!=", "<", ">", "<=", ">="}, "Unsupported comparison."
                )
                value = take()
                require(
                    value.startswith(("'", ":"))
                    or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) is not None
                    or value.upper() == "NULL",
                    "Use a literal or named bound value.",
                )
            if cursor < len(tokens) and tokens[cursor].upper() in {"AND", "OR"}:
                take()
                continue
            break
    if cursor < len(tokens) and tokens[cursor].upper() == "ORDER":
        take()
        keyword("BY")
        while True:
            referenced_columns.add(column())
            if cursor < len(tokens) and tokens[cursor].upper() in {"ASC", "DESC"}:
                take()
            if cursor >= len(tokens) or tokens[cursor] != ",":
                break
            take()
    require(cursor == len(tokens), "Only one single-table SELECT is supported.")
    allowed = scope[resource]
    require(
        allowed is None or referenced_columns <= allowed,
        "Column is outside the dataset column allowlist.",
    )
    schema = template.get("param_schema_jsonb", {})
    require(
        isinstance(schema, dict) and isinstance(schema.get("properties", {}), dict),
        "Invalid parameter schema.",
    )
    declarations = schema.get("properties", {})
    params = args.get("params", {})
    require(isinstance(params, dict), "Parameters must be an object.")
    names = [t[1:] for t in tokens if t.startswith(":")]
    require(set(names) <= set(declarations) and set(params) <= set(names), "Undeclared parameter.")
    values = []
    for name in names:
        declaration = declarations[name]
        require(isinstance(declaration, dict), "Invalid parameter declaration.")
        kinds = declaration.get("type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        require(
            bool(kinds) and all(k in TYPES for k in kinds),
            "Only string, integer, number and null binds are supported.",
        )
        if not execution and name not in params:
            continue
        require(name in params, "Missing query parameter.")
        value = params[name]
        valid = (
            value is None
            and "null" in kinds
            or isinstance(value, str)
            and "string" in kinds
            or type(value) is int
            and ("integer" in kinds or "number" in kinds)
            or type(value) is float
            and "number" in kinds
            and math.isfinite(value)
        )
        require(valid, "Query parameter does not match its declared scalar type.")
        values.append(value)
    # Rebuild only placeholder spans, preserving literal text verbatim.
    bind_index = 0
    compiled = []
    for match in TOKEN.finditer(sql):
        token = match.group()
        if token.startswith(":"):
            bind_index += 1
            token = ":" + str(bind_index)
        compiled.append(token)
    statement = "".join(compiled)
    return statement, values, resource, projected


def _rows(value, limit):
    rows = (
        value[0]
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list)
        else value
    )
    require(
        isinstance(rows, list) and len(rows) <= limit and all(isinstance(r, dict) for r in rows),
        "Invalid bounded Oracle result.",
        code="invalid_provider_response",
    )
    return rows


def _type(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    return "string"


def _metadata_type(source_type):
    normalized = source_type.upper()
    if normalized in {"NUMBER", "FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE", "DECIMAL"}:
        return "number"
    if normalized == "INTEGER":
        return "integer"
    if normalized == "DATE" or normalized.startswith("TIMESTAMP"):
        return "datetime"
    if normalized in {"RAW", "LONG RAW", "BLOB", "BFILE"}:
        return "binary"
    return "string"


def handle(name, args, invoke):
    require(name in ACTIONS, "Unknown dataset action.")
    require(
        set(args)
        <= {"connection_config", "secret_refs", "dataset", "query_template", "params", "limits"},
        "Unknown dataset action input.",
    )
    refs = args.get("secret_refs", {})
    require(isinstance(refs, dict), "Invalid resolved credentials.")
    secrets = refs.get("values", refs.get("refs", refs))
    config, secrets = connection_values(
        {"config": args.get("connection_config"), "secrets": secrets}
    )
    limits = args.get("limits", {})
    require(
        isinstance(limits, dict)
        and set(limits) <= {"max_preview_rows", "max_runtime_rows", "timeout_seconds", "max_bytes"},
        "Unknown query limits.",
    )
    preview_limit = integer(limits.get("max_preview_rows", 20), "max_preview_rows", 1, 100)
    runtime_limit = integer(limits.get("max_runtime_rows", 100), "max_runtime_rows", 1, 100)
    byte_limit = integer(limits.get("max_bytes", 400 * 1024), "max_bytes", 1024, 400 * 1024)
    timeout = integer(
        limits.get("timeout_seconds", config["request_timeout_seconds"]), "timeout_seconds", 1, 30
    )
    deadline = time.monotonic() + min(timeout, config["request_timeout_seconds"])

    def call(statement, parameters, limit):
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Dataset deadline exceeded.", code="timeout")
        command, arguments = compile_command(
            "query", {"statement": statement, "parameters": parameters, "max_rows": limit}, config
        )
        value = invoke(config, secrets, command, arguments, timeout_seconds=remaining)
        require(time.monotonic() < deadline, "Dataset deadline exceeded.", code="timeout")
        rows = _rows(value, limit)
        bounded_json(rows, byte_limit)
        return rows

    if name == "test_connection":
        call("SELECT 1 AS VALUE FROM dual", [], 1)
        return {"status": "ok", "connector_id": "oracle"}
    if name == "introspect_schema":
        resources: dict[str, dict] = {}
        truncated = False
        scope = _scope(args["dataset"]) if "dataset" in args else None
        plans = list(scope) if scope is not None else [None]
        remaining_columns = 100
        for resource in plans:
            if remaining_columns == 0:
                truncated = True
                break
            statement = "SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE, NULLABLE FROM ALL_TAB_COLUMNS WHERE OWNER=:1"
            parameters = [resource.split(".")[0] if resource else secrets["username"].upper()]
            if resource:
                statement += " AND TABLE_NAME=:2"
                parameters.append(resource.split(".")[1])
            statement += " ORDER BY OWNER, TABLE_NAME, COLUMN_ID"
            rows = call(statement, parameters, remaining_columns)
            truncated = truncated or len(rows) == remaining_columns
            remaining_columns -= len(rows)
            for row in rows:
                column = row.get("COLUMN_NAME")
                owner = row.get("OWNER", resource.split(".")[0] if resource else None)
                table = row.get("TABLE_NAME", resource.split(".")[1] if resource else None)
                require(
                    all(
                        isinstance(v, str) and IDENTIFIER.fullmatch(v)
                        for v in (column, owner, table)
                    ),
                    "Invalid metadata identifiers.",
                    code="invalid_provider_response",
                )
                key = owner.upper() + "." + table.upper()
                require(
                    (scope is None and owner.upper() == secrets["username"].upper())
                    or key == resource,
                    "Metadata escaped resource scope.",
                    code="invalid_provider_response",
                )
                if (
                    scope is not None
                    and scope[key] is not None
                    and column.upper() not in scope[key]
                ):
                    continue
                item = resources.setdefault(
                    key,
                    {
                        "resource_id": key,
                        "name": table,
                        "resource_type": "table",
                        "selectable": True,
                        "columns": [],
                        "indexes": [],
                        "metadata": {},
                    },
                )
                source_type = text(row.get("DATA_TYPE"), "metadata data type", 256, nonempty=True)
                item["columns"].append(
                    {
                        "name": column,
                        "data_type": source_type,
                        "source_type": source_type,
                        "type": source_type,
                        "value_type": _metadata_type(source_type),
                        "nullable": row.get("NULLABLE") == "Y",
                    }
                )
        return {
            "schema_snapshot": {
                "schema_version": "dataset_schema_snapshot.v1",
                "source_kind": "oracle",
                "resources": list(resources.values()),
                "truncated": truncated,
                "metadata": {
                    "connector_id": "oracle",
                    "resource_count": len(resources),
                    "truncated": truncated,
                    "column_limit": 100,
                },
            },
            "resources": list(resources.values()),
            "resource_count": len(resources),
            "truncated": truncated,
        }
    execution = name != "validate_query"
    statement, values, resource, projected = _query(args, execution=execution)
    compile_command("query", {"statement": statement, "parameters": values, "max_rows": 1}, config)
    if not execution:
        return {"valid": True, "read_only": True, "referenced_resources": [resource]}
    limit = runtime_limit if name == "execute_template" else preview_limit
    rows = call(statement, values, limit)
    require(
        all(set(row) <= set(projected) for row in rows),
        "Unexpected provider output columns.",
        code="invalid_provider_response",
    )
    schema = args["query_template"].get("output_schema_jsonb")
    if not isinstance(schema, dict) or not schema:
        schema = {
            "type": "object",
            "properties": {
                column: {"type": _type(rows[0].get(column)) if rows else "null"}
                for column in projected
            },
        }
    if name == "infer_output_schema":
        return {"output_schema": schema}
    result = {
        "rows": rows,
        "row_count": len(rows),
        "output_schema": schema,
        "truncated": len(rows) == limit,
    }
    bounded_json(result, byte_limit)
    return result
