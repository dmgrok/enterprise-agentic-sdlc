"""Generate the narrowly supported governed-intent recipe and its exact profile."""

from urllib.parse import urlsplit


HOOK = '''import json, os, sys
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError
body = {"repository": os.environ["KIT_REPOSITORY"],
        "github_run_id": int(os.environ["KIT_GITHUB_RUN_ID"]),
        "attempt": int(os.environ["KIT_GITHUB_ATTEMPT"]), "revision": os.environ["KIT_REVISION"]}
import re
run = os.environ["KIT_RUN"]
if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run):
    sys.exit("Invalid controller run identifier")
request = Request(os.environ["KIT_URL"] + "/runs/" + run + "/" + os.environ["KIT_PHASE"],
                  data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["KIT_TOKEN"]})
try:
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        result = json.load(response)
    if result.get("allowed") is not True or result.get("revision") != body["revision"]:
        sys.exit("Controller denied this revision")
except (HTTPError, URLError, ValueError, TimeoutError):
    sys.exit("Controller admission unavailable or denied")
'''


def governed_config(url="https://controller.example.invalid", model="gpt-4.1"):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port):
        raise ValueError("Controller URL must be an HTTPS origin without credentials, path or port")
    url = url.rstrip("/")
    if not isinstance(model, str) or not model or len(model) > 100 or "${{" in model:
        raise ValueError("An explicit provider model is required")

    def hook(phase):
        return {"name": "Controller " + phase, "env": {
            "KIT_URL": url, "KIT_TOKEN": "${{ secrets.KIT_AGENT_TOKEN }}",
            "KIT_RUN": "${{ inputs.controller_run }}", "KIT_PHASE": phase,
            "KIT_REPOSITORY": "${{ github.repository }}", "KIT_GITHUB_RUN_ID": "${{ github.run_id }}",
            "KIT_GITHUB_ATTEMPT": "${{ github.run_attempt }}", "KIT_REVISION": "${{ github.sha }}"},
            "run": "python3 - <<'PY'\n" + HOOK + "PY\n"}
    return {
        "description": "Governed intent drafting through external admission, gateway accounting and final output checks.",
        "on": {"manual-approval": "kit-agent-start", "workflow_dispatch": {"inputs": {
            "brief": {"description": "Problem statement", "required": True, "type": "string"},
            "controller_run": {"description": "Pre-enrolled controller run ID", "required": True, "type": "string"}}}},
        "permissions": {"contents": "read"}, "strict": True,
        "concurrency": {"job-discriminator": "${{ github.run_id }}"},
        "timeout-minutes": 10, "max-ai-credits": 20, "max-daily-ai-credits": 100,
        "max-turns": 10, "check-for-updates": True,
        "engine": {"id": "copilot", "harness": {"max-retries": 0}, "env": {
            "COPILOT_PROVIDER_BASE_URL": url + "/v1",
            "COPILOT_PROVIDER_API_KEY": "${{ secrets.KIT_AGENT_TOKEN }}",
            "COPILOT_PROVIDER_TYPE": "openai", "COPILOT_MODEL": model,
            "COPILOT_PROVIDER_MAX_OUTPUT_TOKENS": "2048"}},
        "network": {"allowed": ["defaults", "github", parsed.hostname]},
        "tools": {"github": {"min-integrity": "merged", "toolsets": ["repos"]},
                  "edit": None, "bash": ["cat", "mkdir"]},
        "pre-agent-steps": [hook("admission")],
        "post-steps": [{"name": "Export proposed intent for independent quality collection",
                        "uses": "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
                        "with": {"name": "kit-intent-${{ github.run_id }}-${{ github.run_attempt }}",
                                 "path": "work/", "if-no-files-found": "error", "retention-days": 7}}],
        "jobs": {"safe_outputs": {"pre-steps": [hook("output-check")]}},
        "safe-outputs": {"staged": True, "threat-detection": {"max-ai-credits": 20},
                         "create-pull-request": {"draft": True, "title-prefix": "[kit] Intent: ", "allowed-files": ["work/**"]}},
    }


def inspect_governed(config):
    try:
        env = config["engine"]["env"]
        base = env["COPILOT_PROVIDER_BASE_URL"]
        if not isinstance(base, str) or not base.endswith("/v1"):
            return ["governed-provider-url"]
        expected = governed_config(base[:-3], env["COPILOT_MODEL"])
        return [] if config == expected else ["governed-recipe-drift"]
    except (KeyError, TypeError, ValueError):
        return ["invalid-governed-recipe"]
