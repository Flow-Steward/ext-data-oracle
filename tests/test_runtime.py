import json
import pytest
import main
from commands import compile_command, validate
from validation import Failure, connection_values


def envelope(name="execute_sql"):
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            "group_id": None,
            "for_each_id": None,
            "step_id": "s",
            "step_execution_id": "e",
            "account_id": "a",
            "project_id": "p",
            "external_effect_id": "claim",
        },
        "action": {
            "action_id": name,
            "input": {
                "connection_ref": "c",
                "statement": "UPDATE things SET value=:1",
                "parameters": [None],
            },
            "target": {
                "connection": {
                    "connection_id": "c",
                    "connection_type": "oracle",
                    "config": {
                        "host": "example.com",
                        "service_name": "FREEPDB1",
                        "allow_writes": True,
                    },
                    "secrets": {"username": "u", "password": "p%40$literal"},
                }
            },
        },
    }


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM dual; DELETE FROM t",
        "BEGIN NULL; END",
        "SELECT * FROM t FOR UPDATE",
        "SELECT evil() FROM dual",
        "SELECT app.COUNT() FROM dual",
        'SELECT seq."NEXTVAL" FROM dual',
        "SELECT * FROM t@remote",
        "SELECT q'[;]' FROM dual",
        "SELECT 1 -- comment\n FROM dual",
        "WITH x AS (DELETE FROM t) SELECT * FROM x",
        "CREATE TABLE x(a int)",
    ],
)
def test_closed_read_sql(sql):
    with pytest.raises(Failure):
        validate("query", {"statement": sql}, {})


def test_bound_parameters_preserve_literal_and_numbers():
    command, args = compile_command(
        "query",
        {
            "statement": "SELECT :1, :2, :3, :4 FROM dual",
            "parameters": [4, 4.0, None, "x'; DELETE FROM t"],
        },
        {},
    )
    assert args == {}
    assert json.loads(command["staticParameters"]) == [4, 4.0, None, "x'; DELETE FROM t"]
    assert "DELETE" not in command["statement"]
    assert "4.0" in command["staticParameters"]


def test_write_claim_suppression_and_dispatch(monkeypatch):
    calls = []

    def fail(*a, **kw):
        calls.append(a)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(main.toolbox, "invoke", fail)
    p = envelope()
    p["runtime_context"]["test_mode"] = True
    assert main.handle(p)["error_code"] == "test_mode_suppressed"
    p = envelope()
    p["runtime_context"].pop("external_effect_id")
    assert main.handle(p)["error_code"] == "effect_claim_required"
    assert calls == []
    result = main.handle(envelope())
    assert result["retryable"] is False
    assert result["external_effect_status"] == "timeout_unknown"
    assert not result["definitely_no_external_effect"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("connectionString", "oracle://evil"),
        ("walletLocation", "/etc/x"),
        ("allowPrivate", True),
        ("service_name", "FREE?SSL=false"),
    ],
)
def test_connection_closed(field, value):
    p = envelope()["action"]["target"]["connection"]
    p["config"][field] = value
    with pytest.raises(Failure):
        connection_values(p)


def test_connection_ref_and_write_optin(monkeypatch):
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **kw: pytest.fail("network"))
    p = envelope()
    p["action"]["input"]["connection_ref"] = "other"
    assert main.handle(p)["error_code"] == "invalid_connection"
    p = envelope()
    p["action"]["target"]["connection"]["config"]["allow_writes"] = False
    assert main.handle(p)["error_code"] == "write_disabled"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t(v) VALUES (:1); COMMIT",
        "BEGIN DELETE FROM t; END",
        "TRUNCATE TABLE t",
        "UPDATE t SET v=1 RETURNING v INTO :1",
    ],
)
def test_dml_guard(sql):
    with pytest.raises(Failure):
        validate("execute_sql", {"statement": sql, "parameters": [1]}, {"allow_writes": True})


@pytest.mark.parametrize("field", ["account_id", "project_id", "step_execution_id"])
def test_scoped_host_context_required(monkeypatch, field):
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **kw: pytest.fail("network"))
    p = envelope()
    p["runtime_context"].pop(field)
    assert not main.handle(p)["ok"]


def test_successful_query_and_dml_results(monkeypatch):
    p = envelope("query")
    p["action"]["input"] = {
        "connection_ref": "c",
        "statement": "SELECT :1 FROM dual",
        "parameters": [7],
        "max_rows": 3,
    }
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **kw: [[{"VALUE": 7}]])
    assert main.handle(p)["result"] == {"records": [{"VALUE": 7}], "count": 1, "applied": False}
    monkeypatch.setattr(
        main.toolbox, "invoke", lambda *a, **kw: [{"status": "success", "rows_affected": 2}]
    )
    assert main.handle(envelope())["result"] == {"records": [], "count": 2, "applied": True}


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t(v) VALUES (:1)",
        "UPDATE t SET v=:1 WHERE id=1",
        "DELETE FROM t WHERE id=:1",
        "MERGE INTO t USING (SELECT :1 AS v FROM dual) s ON (t.id=s.v) WHEN MATCHED THEN UPDATE SET t.v=s.v",
    ],
)
def test_supported_dml_uses_native_bound_parameters(sql):
    tool, args = compile_command(
        "execute_sql", {"statement": sql, "parameters": [1]}, {"allow_writes": True}
    )
    assert not tool["readOnly"]
    assert json.loads(tool["staticParameters"]) == [1]
    assert args == {}
