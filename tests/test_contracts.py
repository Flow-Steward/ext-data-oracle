from pathlib import Path
import yaml

R = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.safe_load((R / name).read_text())


def test_contracts_and_effects():
    m = load("extension.yaml")
    assert (
        m["extension_id"]
        == load("extension-descriptor.yaml")["extension_id"]
        == "flowsteward.oracle"
    )
    assert m["features"] == ["tool", "action"]
    assert m["egress"] == {"connection_fields": ["oracle.host"]}
    assert {o["operation_id"] for o in load("contracts/operation_manifest.yaml")["operations"]} == {
        "query",
        "execute_sql",
    }
    assert {o["action_id"] for o in load("ui/actions/actions.yaml")["actions"]} == {
        "query",
        "execute_sql",
    }
    assert {o["operation_id"] for o in m["external_effects"]} == {"execute_sql"}
    c = load("contracts/connection_types.yaml")["connection_types"][0]
    assert c["connection_type_id"] == "oracle"
    assert not c["capabilities"]["workflow_trigger"]
    assert c["config_schema"]["additionalProperties"] is False
    assert c["config_schema"]["properties"]["allow_writes"]["default"] is False


def test_canonical_apache_license_is_unmodified():
    import hashlib

    assert (
        hashlib.sha256((R / "LICENSE").read_bytes()).hexdigest()
        == "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd"
    )
