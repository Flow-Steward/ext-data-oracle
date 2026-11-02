"""Dataset contract exercised through the real host entrypoint; no Oracle account needed."""

import copy
import json

import pytest

import main
from test_runtime import envelope


def dataset_envelope(action="execute_template"):
    payload = envelope(action)
    payload["action"].pop("target")
    payload["action"]["input"] = {
        "connection_config": {"host": "example.com", "service_name": "FREEPDB1"},
        "secret_refs": {"values": {"username": "u", "password": "secret"}},
        "dataset": {
            "dataset_id": "d",
            "resource_scope_jsonb": {
                "resources": [{"resource_id": "APP.THINGS", "columns": ["ID", "VALUE"]}]
            },
        },
        "query_template": {
            "query_template_id": "q",
            "dataset_id": "d",
            "query_language": "sql",
            "query_definition_jsonb": {"sql": "SELECT ID, VALUE FROM APP.THINGS WHERE ID=:id"},
            "param_schema_jsonb": {"type": "object", "properties": {"id": {"type": "integer"}}},
            "output_schema_jsonb": {
                "type": "object",
                "properties": {"ID": {"type": "integer"}, "VALUE": {"type": "string"}},
            },
        },
        "params": {"id": 7},
        "limits": {"max_runtime_rows": 3, "max_preview_rows": 2, "timeout_seconds": 4},
    }
    return payload


def test_dataset_named_parameters_and_empty_schema(monkeypatch):
    calls = []

    def provider(config, secrets, command, arguments, **kwargs):
        calls.append((command, kwargs))
        assert command["readOnly"] is True
        assert command["maxRows"] == 3
        assert command["statement"] == "SELECT ID, VALUE FROM APP.THINGS WHERE ID=:1"
        assert json.loads(command["staticParameters"]) == [7]
        assert 0 < kwargs["timeout_seconds"] <= 4
        return [[]]

    monkeypatch.setattr(main.toolbox, "invoke", provider)
    payload = dataset_envelope()
    response = main.handle(payload)
    assert response["ok"], response
    assert response["result"]["rows"] == []
    assert (
        response["result"]["output_schema"]
        == payload["action"]["input"]["query_template"]["output_schema_jsonb"]
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT PASSWORD FROM APP.THINGS",
        "SELECT ID FROM OTHER.THINGS",
        "SELECT * FROM APP.THINGS",
        "SELECT ID FROM APP.THINGS UNION SELECT PASSWORD FROM APP.USERS",
        "SELECT (SELECT PASSWORD FROM APP.USERS) FROM APP.THINGS",
        'SELECT "PASSWORD" FROM APP.THINGS',
        "SELECT CAST(PASSWORD AS VARCHAR2(20)) FROM APP.THINGS",
        "SELECT ID FROM APP.THINGS WHERE PASSWORD='x'",
        "SELECT ID FROM APP.THINGS WHERE ID=:missing",
        "SELECT ID FROM APP.THINGS; DELETE FROM APP.THINGS",
    ],
)
def test_dataset_scope_denies_before_provider(monkeypatch, sql):
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **k: pytest.fail("provider called"))
    payload = dataset_envelope()
    payload["action"]["input"]["query_template"]["query_definition_jsonb"]["sql"] = sql
    assert not main.handle(payload)["ok"]


def test_dataset_all_actions_catalog_and_limits(monkeypatch):
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **k: [[{"ID": 7, "VALUE": "ok"}]])
    for action in (
        "validate_query",
        "preview_query",
        "execute_template",
        "infer_output_schema",
        "test_connection",
    ):
        result = main.handle(dataset_envelope(action))
        assert result["ok"], (action, result)
    payload = dataset_envelope()
    payload["action"]["input"]["params"]["id"] = True
    assert not main.handle(payload)["ok"]
    payload = dataset_envelope()
    payload["action"]["input"]["limits"]["max_runtime_rows"] = 101
    assert not main.handle(payload)["ok"]
    for query in ("supported_connectors", "runtime_health"):
        payload = dataset_envelope()
        payload["mode"] = "query"
        payload["query"] = {"query_id": query}
        assert main.handle(payload)["ok"]


def test_dataset_introspection_is_bounded_and_column_scoped(monkeypatch):
    def provider(config, secrets, command, arguments, **kwargs):
        assert "ALL_TAB_COLUMNS" in command["statement"]
        assert json.loads(command["staticParameters"]) == ["APP", "THINGS"]
        return [
            [
                {"COLUMN_NAME": "ID", "DATA_TYPE": "NUMBER", "NULLABLE": "N"},
                {"COLUMN_NAME": "PASSWORD", "DATA_TYPE": "VARCHAR2", "NULLABLE": "Y"},
            ]
        ]

    monkeypatch.setattr(main.toolbox, "invoke", provider)
    result = main.handle(dataset_envelope("introspect_schema"))
    assert result["ok"], result
    assert result["result"]["schema_snapshot"]["schema_version"] == "dataset_schema_snapshot.v1"
    assert result["result"]["resources"] == result["result"]["schema_snapshot"]["resources"]
    columns = result["result"]["schema_snapshot"]["resources"][0]["columns"]
    assert [c["name"] for c in columns] == ["ID"]
    assert columns[0]["value_type"] == "number"


def test_dataset_byte_budget_and_scope_identity(monkeypatch):
    monkeypatch.setattr(main.toolbox, "invoke", lambda *a, **k: [[{"VALUE": "x" * 2000}]])
    payload = dataset_envelope()
    payload["action"]["input"]["limits"]["max_bytes"] = 1024
    assert not main.handle(payload)["ok"]
    bad = copy.deepcopy(payload)
    bad["action"]["input"]["query_template"]["dataset_id"] = "elsewhere"
    assert not main.handle(bad)["ok"]


def test_initial_admin_schema_discovery_needs_no_saved_template(monkeypatch):
    def provider(config, secrets, command, arguments, **kwargs):
        assert command["readOnly"] is True
        assert command["maxRows"] == 100
        assert "ALL_TAB_COLUMNS" in command["statement"]
        assert json.loads(command["staticParameters"]) == ["U"]
        return [
            [
                {
                    "OWNER": "U",
                    "TABLE_NAME": "THINGS",
                    "COLUMN_NAME": "ID",
                    "DATA_TYPE": "NUMBER",
                    "NULLABLE": "N",
                }
            ]
        ]

    monkeypatch.setattr(main.toolbox, "invoke", provider)
    payload = dataset_envelope("introspect_schema")
    payload["action"]["input"].pop("dataset")
    payload["action"]["input"].pop("query_template")
    response = main.handle(payload)
    assert response["ok"], response
    assert response["result"]["schema_snapshot"]["resources"][0]["resource_id"] == "U.THINGS"
