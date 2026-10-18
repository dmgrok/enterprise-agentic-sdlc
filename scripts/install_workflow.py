"""Install this checkout's compiled recipe and resource, or check for drift."""

import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def install(root=ROOT, check=False):
    mappings = [("workflows/governed-intent.md", ".github/workflows/governed-intent.md"),
                ("workflows/governed-intent.lock.yml", ".github/workflows/governed-intent.lock.yml"),
                ("resources/intent-template.json", ".github/aw/kit/intent-template.json")]
    for source, destination in mappings:
        target = root / destination
        if check:
            if not target.is_file() or target.read_bytes() != (root / source).read_bytes():
                raise ValueError("Installed workflow drift: " + destination)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / source, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    install(check=args.check)
    print("Installed workflow matches" if args.check else "Installed governed workflow in .github/workflows")
