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


def build(key, out_dir, skill_dir=SKILL_DIR):
    key = key.strip()
    if not key:
        raise SystemExit("personalize: no key given (use --key or TYPESAFE_API_KEY)")
    out = Path(out_dir) / f"{NAME}-personal.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(skill_dir.rglob("*")):
            rel = f.relative_to(skill_dir)
            if f.is_dir() or rel.name == "key" or "__pycache__" in rel.parts \
                    or any(p.startswith(".") for p in rel.parts):
                continue
            z.write(f, f"{NAME}/{rel.as_posix()}")
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
