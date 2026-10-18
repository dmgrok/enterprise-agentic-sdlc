# Contributing

Keep authority outside the agent. A proposed integration must preserve all three
operating axes and explain whether a control is implemented, fixture-tested,
compiler-verified or proven against a live runtime.

## Run verification

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python -m kit.profile .
.venv/bin/python examples/control_demo.py
.venv/bin/python examples/http_demo.py
```

Tests use synthetic data and require local process signals and loopback sockets.
No model credentials or paid provider calls are needed. After changing workflow
sources, regenerate with the compiler pinned in `runtime.json` and check for
drift with `scripts/compile.py --check`.

Update JSON Schemas and negative tests with protocol changes. Keep README Mermaid
diagrams aligned with executable paths, and distinguish deployment requirements
from verified behavior. Do not commit keys, credential files, control databases,
private source material or provider responses. Use conventional commit messages
and describe relevant checks in pull requests.

## Update a diagram

Edit the Mermaid sources in `docs/diagrams/`, render their SVGs with the pinned
tools, and inspect the result before committing. See the
[diagram guide](docs/diagrams/README.md). The README embeds the generated SVGs;
CI also renders every source to catch Mermaid syntax errors.
