"""Compile in a temporary consumer repository, leaving the host vault untouched."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def normalize_setup_comments(content, commit):
    # gh-aw adds a redundant SHA label only when GitHub metadata is reachable.
    # Canonicalize that exact display comment; preserve every executable byte.
    ref = re.escape("github/gh-aw-actions/setup@" + commit)
    return re.sub(r"(?m)^((?:[ ]*uses: |#   - )" + ref + r")(?: # " + re.escape(commit) + r")?$",
                  lambda match: match[1] + " # " + commit, content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", required=True, help="Path to gh-aw binary, not the gh wrapper")
    parser.add_argument("--check", action="store_true", help="Fail on committed lock drift")
    args = parser.parse_args()
    compiler = str(Path(args.compiler).resolve())
    runtime = json.loads((ROOT / "runtime.json").read_text())
    architecture = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    asset = platform.system().lower() + "-" + str(architecture)
    expected = runtime["compiler_sha256"].get(asset)
    if expected is None or hashlib.sha256(Path(compiler).read_bytes()).hexdigest() != expected:
        raise SystemExit("Unrecognised compiler artifact or checksum mismatch: " + asset)
    version = subprocess.check_output([compiler, "version"], text=True).strip()
    if version != "gh aw version v" + runtime["gh_aw_version"]:
        raise SystemExit("Compiler version mismatch: " + version)
    with tempfile.TemporaryDirectory(prefix="enterprise-sdlc-compile-") as folder:
        consumer = Path(folder)
        subprocess.run(["git", "init", "--quiet", str(consumer)], check=True)
        workflows = consumer / ".github/workflows"
        workflows.mkdir(parents=True)
        shutil.copy2(ROOT / ".github/workflows/aw.json", workflows / "aw.json")
        for path in (ROOT / "workflows").glob("*.md"):
            shutil.copy2(path, workflows / path.name)
        for path in (ROOT / "workflows").glob("*.lock.yml"):
            shutil.copy2(path, workflows / path.name)
        installed = consumer / ".github/aw/kit"
        installed.mkdir(parents=True)
        shutil.copy2(ROOT / "resources/intent-template.json", installed / "intent-template.json")
        subprocess.run([compiler, "compile", "--strict", "--action-mode", "action",
                        "--action-tag", runtime["actions_commit"]], cwd=consumer, check=True)
        for generated in workflows.glob("*.lock.yml"):
            generated.write_text(normalize_setup_comments(generated.read_text(), runtime["actions_commit"]))
            target = ROOT / "workflows" / generated.name
            if args.check:
                if not target.exists() or target.read_bytes() != generated.read_bytes():
                    if target.exists():
                        delta = difflib.unified_diff(target.read_text().splitlines(), generated.read_text().splitlines(),
                                                     fromfile="committed/" + target.name,
                                                     tofile="generated/" + generated.name, lineterm="")
                        print("\n".join(list(delta)[:100]))
                    raise SystemExit("Lock drift: " + target.name)
            else:
                shutil.copy2(generated, target)
    print("Lock files match" if args.check else "Lock files generated")


if __name__ == "__main__":
    main()
