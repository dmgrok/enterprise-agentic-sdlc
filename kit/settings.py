"""Human-owned YAML policy; strict parsing and existing runtime contract validation."""

from pathlib import Path
import yaml

from kit.contracts import validate
from kit.ghaw import governed_config
from kit.profile import Loader


def load(path):
    value = yaml.load(Path(path).read_text(), Loader=Loader)
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "workflow", "guidelines", "runtime"}
            or value["schema_version"] != "0.1"
            or not isinstance(value["guidelines"], str) or not value["guidelines"].strip()
            or not isinstance(value["workflow"], dict)
            or set(value["workflow"]) != {"controller_url", "model"}):
        raise ValueError("Invalid agent policy configuration")
    validate("control-policy", value["runtime"])
    runtime = value["runtime"]
    if runtime["warn_spend_microusd"] >= runtime["max_spend_microusd"]:
        raise ValueError("Spend warning must be below the hard limit")
    governed_config(value["workflow"]["controller_url"], value["workflow"]["model"])
    return value
