#!/usr/bin/env python3
"""Package the skill for upload to claude.ai.

    python3 tools/build_skill.py            check versions, build dist/vibe-classification-<v>.zip
    python3 tools/build_skill.py --check    only check versions agree
    python3 tools/build_skill.py --key KEY  also build dist/vibe-classification-personal.zip
                                            (or set TYPESAFE_API_KEY and pass --key "")

The version lives in SKILL.md's frontmatter (metadata.version). CHANGELOG.md's top
entry must match it: bumping both and merging to main is what cuts a release.
The public zip never contains a key.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "vibe-classification"
SKILL = ROOT / "skills" / NAME
DIST = ROOT / "dist"

sys.path.insert(0, str(SKILL / "scripts"))
import personalize  # noqa: E402


def version():
    m = re.search(r'^\s+version:\s*"([^"]+)"', (SKILL / "SKILL.md").read_text(), re.M)
    if not m:
        sys.exit("✗ no metadata.version in SKILL.md")
    return m.group(1)


def check():
    v = version()
    m = re.search(r"^##\s*\[?v?(\d[^\]\s]*)", (ROOT / "CHANGELOG.md").read_text(), re.M)
    found = m.group(1) if m else None
    if found != v:
        sys.exit(f"✗ CHANGELOG.md top entry is {found}, SKILL.md says {v}. Bump both.")
    print(f"✓ version {v} in sync (SKILL.md, CHANGELOG.md)")
    return v


def ignore(_dir, names):
    return [n for n in names if n.startswith(".") or n == "__pycache__" or n == "key" or n.endswith(".zip")]


def build(v):
    out = DIST / NAME
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(SKILL, out, ignore=ignore)
    zip_path = DIST / f"{NAME}-{v}.zip"
    zip_path.unlink(missing_ok=True)
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", DIST, NAME)
    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        print(f"  {f.relative_to(out)}")
    print(f"→ {zip_path.relative_to(ROOT)}  (upload this)")
    return zip_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--key", nargs="?", const="", default=None)
    a = ap.parse_args()
    v = check()
    if a.check:
        return
    DIST.mkdir(exist_ok=True)
    build(v)
    if a.key is not None:
        key = a.key or os.environ.get("TYPESAFE_API_KEY", "")
        p = personalize.build(key, DIST)
        print(f"→ {p.relative_to(ROOT)}  (contains your key: upload it, don't share it)")


if __name__ == "__main__":
    main()
