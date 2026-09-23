#!/usr/bin/env python3
"""Check the built zip is uploadable and works once unpacked somewhere else.

    python3 tools/build_skill.py && python3 tools/test_skill.py

A skill zip fails silently in three ways: its shape (one top folder, one SKILL.md),
its frontmatter (the uploader's name/description rules), and missing files. So this
unzips the real artifact into a temp dir and runs it there, against a fake API.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "vibe-classification"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from build_skill import version  # noqa: E402
import fake_jev  # noqa: E402

V = version()
ZIP = ROOT / "dist" / f"{NAME}-{V}.zip"
failed = 0


def check(cond, msg, detail=""):
    global failed
    print(f"  {'✓' if cond else '✗'} {msg}" + ("" if cond or not detail else f" — {detail}"))
    failed += not cond


if not ZIP.exists():
    sys.exit(f"✗ no {ZIP.relative_to(ROOT)}: run tools/build_skill.py first")

print(f"\n{NAME} v{V}: packaging")
names = zipfile.ZipFile(ZIP).namelist()
files = [n for n in names if not n.endswith("/")]
skill_mds = [f for f in files if f.endswith("SKILL.md")]
check(skill_mds == [f"{NAME}/SKILL.md"], "exactly one SKILL.md, in the top folder", skill_mds)
check({n.split("/")[0] for n in names} == {NAME}, "one top-level folder named for the skill")
check(not any(Path(f).name.startswith(".") for f in files), "no dotfiles")
check(f"{NAME}/key" not in files, "no key in the public zip")
for need in ("scripts/jev.py", "scripts/personalize.py"):
    check(f"{NAME}/{need}" in files, f"bundles {need}")

print("\nfrontmatter")
md = zipfile.ZipFile(ZIP).read(f"{NAME}/SKILL.md").decode()
fm = re.match(r"^---\n(.*?)\n---\n", md, re.S)
fm = fm.group(1) if fm else ""
field = lambda k: (re.search(rf"^{k}:\s*(.*)$", fm, re.M) or [None, ""])[1].strip()
name, desc = field("name"), field("description")
check(name == NAME, "name matches the folder", name)
check(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64, "name is lowercase-hyphenated, ≤64")
check(not re.search(r"anthropic|claude", name, re.I), "name avoids reserved words")
check(0 < len(desc) <= 1024, "description is 1–1024 chars", f"{len(desc)} chars")
check(not re.search(r"[<>]", name + desc), "no angle brackets in name/description")
body_lines = len(md.splitlines())
check(body_lines <= 120, "SKILL.md stays short (≤120 lines)", f"{body_lines} lines")

print("\nrun from the unzipped bundle")
srv, url = fake_jev.start()
with tempfile.TemporaryDirectory() as tmp:
    zipfile.ZipFile(ZIP).extractall(tmp)
    skill = Path(tmp) / NAME
    env = {**os.environ, "TYPESAFE_BASE_URL": url, "TYPESAFE_API_KEY": "test-key"}
    spec = json.dumps({"ask": {"act": "Act on it?", "kind": {"q": "Kind?", "options": ["bill", "spam"]}},
                       "items": ["bill YES", "spam"]})
    r = subprocess.run([sys.executable, str(skill / "scripts/jev.py")], input=spec, env=env,
                       capture_output=True, text=True, cwd=tmp)
    check(r.returncode == 0, "jev.py runs", r.stderr.strip())
    check("act 0.90✓  kind bill" in r.stdout, "answers a yes/no and a choice", r.stdout)

    env.pop("TYPESAFE_API_KEY")
    r = subprocess.run([sys.executable, str(skill / "scripts/personalize.py"), "--key", "test-key",
                        "--out", tmp], env=env, capture_output=True, text=True)
    # Run it twice from inside the skill folder with the default --out: the second
    # run must not pick up the first run's zip, and neither may nest itself.
    for _ in range(2):
        subprocess.run([sys.executable, "scripts/personalize.py", "--key", "test-key"],
                       env=env, capture_output=True, text=True, cwd=skill)
    inside = skill / f"{NAME}-personal.zip"
    nested = [n for n in zipfile.ZipFile(inside).namelist() if n.endswith(".zip")] if inside.exists() else ["<missing>"]
    check(not nested, "personalize run from inside the folder doesn't zip itself", nested)
    inside.unlink(missing_ok=True)
    personal = Path(tmp) / f"{NAME}-personal.zip"
    check(r.returncode == 0 and personal.exists(), "personalize.py builds a keyed zip", r.stderr.strip())
    if personal.exists():
        z = zipfile.ZipFile(personal)
        check(z.read(f"{NAME}/key").decode().strip() == "test-key", "the key is inside")
        check(f"{NAME}/SKILL.md" in z.namelist(), "and it is still a whole skill")
        other = Path(tmp) / "p"
        z.extractall(other)
        r = subprocess.run([sys.executable, str(other / NAME / "scripts/jev.py")], input=spec, env=env,
                           capture_output=True, text=True)
        check(r.returncode == 0 and "2 items" in r.stdout, "keyed build runs with no env key", r.stderr.strip())
srv.shutdown()

print(f"\n✗ {failed} check(s) failed" if failed else "\n✓ zip is uploadable and runs")
sys.exit(1 if failed else 0)
