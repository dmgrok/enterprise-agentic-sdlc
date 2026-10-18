"""Conservative profile for this spike's single supported workflow shape."""

import argparse
import json
from pathlib import Path
import re

import yaml


class Loader(yaml.SafeLoader):
    pass


# YAML 1.2 treats `on` as a string. Do not mutate SafeLoader's shared registry.
Loader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError("Duplicate YAML key: " + str(key))
        result[key] = loader.construct_object(value_node)
    return result


Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_frontmatter(path):
    parts = path.read_text().split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("Missing frontmatter")
    value = yaml.load(parts[1], Loader=Loader)
    if not isinstance(value, dict):
        raise ValueError("Frontmatter must be a mapping")
    return value


def inspect(config):
    failures = []

    def require(passed, rule):
        if not passed:
            failures.append(rule)

    # Unsupported capabilities fail closed; do not pretend to resolve gh-aw imports.
    allowed = {"description", "on", "permissions", "engine", "strict", "timeout-minutes",
               "max-ai-credits", "max-daily-ai-credits", "max-turns", "check-for-updates",
               "network", "tools", "safe-outputs", "concurrency"}
    require(not (set(config) - allowed), "unsupported-frontmatter")
    require(config.get("strict") is True, "strict-mode")
    require(config.get("check-for-updates") is True, "update-check")
    require(config.get("permissions") == {"contents": "read"}, "read-only-permissions")
    require(config.get("engine") == "copilot", "spike-engine")
    require(config.get("concurrency") == {"job-discriminator": "${{ github.run_id }}"}, "dispatch-concurrency")
    triggers = config.get("on", {})
    require(isinstance(triggers, dict) and set(triggers) == {"workflow_dispatch"}, "manual-only")
    for name, cap in (("timeout-minutes", 10), ("max-ai-credits", 20),
                      ("max-daily-ai-credits", 100), ("max-turns", 10)):
        require(type(config.get(name)) is int and 0 < config[name] <= cap, name)
    require(config.get("network") == {"allowed": ["defaults", "github", "copilot"]}, "network-allowlist")
    require(config.get("tools") == {"github": {"min-integrity": "merged", "toolsets": ["repos"]},
                                    "edit": None, "bash": ["cat", "mkdir"]}, "approved-tools")
    outputs = config.get("safe-outputs", {})
    require(isinstance(outputs, dict) and set(outputs) == {"staged", "create-pull-request", "threat-detection"}, "safe-output-types")
    if isinstance(outputs, dict):
        require(outputs.get("staged") is True, "staged-only")
        require(outputs.get("threat-detection") == {"max-ai-credits": 20}, "detection-budget")
        require(outputs.get("create-pull-request") == {
            "draft": True, "title-prefix": "[kit] Intent: ", "allowed-files": ["work/**"]}, "artifact-output-scope")
    return failures


def main():
    parser = argparse.ArgumentParser(description="Check the restricted slice-1 profile; not an org settings audit")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    failures = []
    try:
        root = args.root
        manifest = yaml.load((root / "aw.yml").read_text(), Loader=Loader)
        if manifest["files"] != ["workflows/draft-intent.md"]:
            failures.append("unsupported-package-workflows")
        if json.loads((root / ".github/workflows/aw.json").read_text()) != {"strict": True}:
            failures.append("repository-strict-mode")
        paths = sorted((root / "workflows").glob("*.md"))
        if [str(p.relative_to(root)) for p in paths] != manifest["files"]:
            failures.append("unlisted-workflows")
        for path in paths:
            failures.extend(str(path.relative_to(root)) + ": " + x for x in inspect(read_frontmatter(path)))
        for resource in manifest.get("resources", []):
            if resource != {"source": "resources/intent-template.json", "destination": ".github/aw/kit/intent-template.json"}:
                failures.append("unsupported-resource")
            elif not (root / resource["source"]).is_file():
                failures.append("missing-resource")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        failures.append("profile-input: " + str(exc))
    print(json.dumps({"decision": "blocked" if failures else "pass", "failures": failures}, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
