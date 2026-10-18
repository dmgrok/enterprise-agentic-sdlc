"""Local-only JSON Schema resolution; never retrieve remote schema references."""

import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1] / "schemas"


def validate(name, value):
    if name not in {"telemetry", "control-policy", "intent", "evidence", "binding"}:
        raise ValueError("Unknown contract")
    schema = json.loads((ROOT / (name + ".schema.json")).read_text())
    Draft202012Validator(schema).validate(value)


def check_schemas():
    for path in ROOT.glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
