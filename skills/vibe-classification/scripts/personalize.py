#!/usr/bin/env python3
"""Build a personal copy of this skill with a TypeSafe key baked in.

    python3 personalize.py --key ts_...  [--out DIR]
    TYPESAFE_API_KEY=ts_... python3 personalize.py

Writes vibe-classification-personal.zip: this skill folder plus a `key` file that
jev.py reads. Upload that zip in claude.ai (Settings → Capabilities → Skills) in
place of the public one. The zip holds a live credential, so don't share it.
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
NAME = "vibe-classification"


def keep(rel, f):
    return (f.is_file() and rel.name != "key" and rel.suffix != ".zip"
            and "__pycache__" not in rel.parts and not any(p.startswith(".") for p in rel.parts))


def build(key, out_dir, skill_dir=SKILL_DIR):
    key = key.strip()
    if not key:
        raise SystemExit("personalize: no key given (use --key or TYPESAFE_API_KEY)")
    out = Path(out_dir) / f"{NAME}-personal.zip"
    # List the files before opening the zip, and skip zips: run from inside the
    # skill folder, the output would otherwise land in its own listing and nest
    # itself, which the skill uploader rejects.
    files = [f for f in sorted(skill_dir.rglob("*")) if keep(f.relative_to(skill_dir), f)]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{NAME}/{f.relative_to(skill_dir).as_posix()}")
        z.writestr(f"{NAME}/key", key + "\n")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--key", default=os.environ.get("TYPESAFE_API_KEY", ""))
    ap.add_argument("--out", default=".", help="directory to write the zip into")
    a = ap.parse_args()
    out = build(a.key, a.out)
    print(f"→ {out}  (contains your key: upload it, don't share it)")


if __name__ == "__main__":
    sys.exit(main())
