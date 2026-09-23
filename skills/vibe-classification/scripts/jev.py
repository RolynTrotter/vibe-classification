#!/usr/bin/env python3
"""Ask TypeSafe's Jev fast typed questions about one item or a whole list.

    python3 jev.py spec.json            # or pipe the spec on stdin
    python3 jev.py spec.json --show table --only relevant

The spec is JSON (see SKILL.md for the short version):

    {
      "ask": {                                   # question id -> question
        "relevant": "Is this page about sourdough starters?",             # yes/no
        "kind":  {"q": "What is this email?", "options": ["bill", "personal", "promo"]},
        "worth": {"q": "How worth reading is it?", "levels": ["skip", "skim", "read"]}
      },
      "items":   ["text", {"id": "a", "subject": "...", "body": "..."}],
      "items_file": "path",       # .jsonl / .json / .csv / .txt (one per line) / a directory
      "context": {...},           # optional state shared by every item
      "show": "decide",           # decide | table | json
      "only": "relevant",         # print just the items that pass: qid, qid=option, qid>=0.7
      "compare": true,            # A/B: report where questions (phrasings) disagree
      "threshold": 0.5,           # yes/no cut-off
      "max_chars": 12000          # truncate long items (Jev loses accuracy on big state)
    }

Questions can also be full TypeSafe question objects (anything with a "type"); those
pass through untouched. Standard library only, so it runs in any sandbox.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")
UNSURE_BAND = 0.2      # yes/no within threshold ± this is "unsure"
LOW_CONFIDENCE = 0.5   # choice/score confidence below this is "unsure"
NETWORK_HINT = ("Can't reach api.typesafe.ai. In claude.ai, add api.typesafe.ai to the "
                "allowed domains under Settings → Capabilities (code execution), then retry.")


class Fatal(Exception):
    """An error that will fail every item the same way, so stop the batch."""


# --- key ------------------------------------------------------------------------

def api_key():
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key and (SKILL_DIR / "key").is_file():
        key = (SKILL_DIR / "key").read_text().strip()
    if not key:
        raise Fatal("No TypeSafe key. Set TYPESAFE_API_KEY, or install a personal build of "
                    "the skill (scripts/personalize.py bakes the key in).")
    return key


# --- questions --------------------------------------------------------------------

def normalize_question(qid, q):
    if isinstance(q, str):
        return {"type": "noul", "instructions": q}
    if not isinstance(q, dict):
        raise Fatal(f"question {qid!r}: expected a string or an object")
    if "type" in q:
        return q
    text = q.get("q", q.get("ask", q.get("instructions")))
    if text is None:
        raise Fatal(f"question {qid!r}: needs \"q\" (the question text)")
    if "options" in q:
        opts = q["options"]
        if isinstance(opts, list):
            opts = {str(o): None for o in opts}
        return {"type": "choice", "instructions": text, "criteria": opts}
    if "levels" in q:
        return {"type": "score", "instructions": text, "criteria": list(q["levels"])}
    out = {"type": "noul", "instructions": text}
    if "yes" in q or "no" in q:
        out["criteria"] = {k: v for k, v in (("true", q.get("yes")), ("false", q.get("no"))) if v}
    return out


# --- items ------------------------------------------------------------------------

def load_items(spec):
    items = list(spec.get("items") or [])
    path = spec.get("items_file")
    if path:
        items += read_items_file(Path(path).expanduser())
    if not items:
        if "state" in spec:
            items = [spec["state"]]
        else:
            raise Fatal("nothing to ask about: give \"items\", \"items_file\" or \"state\"")
    return items


def read_items_file(p):
    if p.is_dir():
        return [{"id": f.name, "text": f.read_text(errors="replace")}
                for f in sorted(p.iterdir()) if f.is_file() and not f.name.startswith(".")]
    text = p.read_text(errors="replace")
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if p.suffix == ".json":
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    if p.suffix in (".csv", ".tsv"):
        return list(csv.DictReader(text.splitlines(), delimiter="\t" if p.suffix == ".tsv" else ","))
    return [line for line in text.splitlines() if line.strip()]


def item_id_and_state(i, item):
    if isinstance(item, dict):
        iid = str(item.get("id", i + 1))
        if "state" in item:
            return iid, item["state"]
        return iid, {k: v for k, v in item.items() if k != "id"}
    return str(i + 1), item


def truncate(state, limit):
    """Clip long strings; returns (state, was_clipped)."""
    if isinstance(state, str):
        return (state[:limit] + " …[truncated]", True) if len(state) > limit else (state, False)
    if isinstance(state, dict):
        clipped = False
        out = {}
        for k, v in state.items():
            out[k], c = truncate(v, limit)
            clipped |= c
        return out, clipped
    if isinstance(state, list):
        pairs = [truncate(v, limit) for v in state]
        return [v for v, _ in pairs], any(c for _, c in pairs)
    return state, False


def label(iid, state, width=48):
    if isinstance(state, dict):
        for k in ("title", "subject", "name", "url", "text", "body"):
            if isinstance(state.get(k), str):
                state = state[k]
                break
        else:
            state = json.dumps(state, ensure_ascii=False)
    s = " ".join(str(state).split())
    s = s if len(s) <= width else s[: width - 1] + "…"
    return f"{iid:>3} {s}" if iid.isdigit() else f"{iid} · {s}"


# --- HTTP -------------------------------------------------------------------------

def post(body, key, tries=5):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/v1/systemone", data=data, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    delay = 1.0
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                wait = e.headers.get("retry-after")
                time.sleep(float(wait) if wait and wait.replace(".", "").isdigit() else delay)
                delay *= 2
                continue
            if e.code == 401:
                raise Fatal("TypeSafe rejected the key (401). Check the key or rebuild the personal zip.")
            if e.code == 422:
                raise Fatal(f"TypeSafe says the request is malformed (422): {text[:600]}")
            if e.code in (403, 407) and "typesafe" not in text.lower():
                raise Fatal(f"{NETWORK_HINT} (HTTP {e.code}: {text[:200].strip()})")
            raise RuntimeError(f"HTTP {e.code}: {text[:300]}")
        except urllib.error.URLError as e:
            if attempt < tries - 1 and "timed out" in str(e.reason):
                time.sleep(delay)
                delay *= 2
                continue
            raise Fatal(f"{NETWORK_HINT} ({e.reason})")
    raise RuntimeError("gave up after retries")


# --- reading answers ----------------------------------------------------------------

def summarize(ans, threshold):
    """-> (display text, decision, unsure?, sort value)"""
    t = ans.get("type")
    if t == "noul":
        p = ans["noul"]
        unsure = abs(p - threshold) < UNSURE_BAND
        return f"{p:.2f}{'?' if unsure else ('✓' if p >= threshold else '✗')}", p >= threshold, unsure, p
    if t == "choice":
        c = ans["choice"]
        pr = ans.get("probabilities", {}).get(c, 0)
        unsure = ans.get("confidence", 1) < LOW_CONFIDENCE
        return f"{c} {pr:.2f}{'?' if unsure else ''}", c, unsure, pr
    if t == "score":
        s = ans["score"]
        legend = ans.get("legend", {})
        nearest = legend.get(str(round(s)), "")
        unsure = ans.get("confidence", 1) < LOW_CONFIDENCE
        short = nearest if len(nearest) <= 24 else nearest[:23] + "…"
        return f"{s:.1f} {short}{'?' if unsure else ''}".rstrip(), round(s), unsure, s
    return json.dumps(ans), None, True, 0


def passes(expr, answers, threshold):
    for op in (">=", "<=", "="):
        if op in expr:
            qid, val = expr.split(op, 1)
            a = answers.get(qid.strip())
            if a is None:
                return False
            if op == "=":
                return str(summarize(a, threshold)[1]) == val.strip()
            v = summarize(a, threshold)[3]
            return v >= float(val) if op == ">=" else v <= float(val)
    a = answers.get(expr.strip())
    if a is None:
        return False
    return bool(summarize(a, threshold)[1])


def is_unsure(expr, answers, threshold):
    qid = expr
    for op in (">=", "<=", "="):
        qid = qid.split(op, 1)[0]
    a = answers.get(qid.strip())
    return a is not None and summarize(a, threshold)[2]


# --- run ----------------------------------------------------------------------------

def run(spec):
    if not spec.get("ask"):
        raise Fatal("spec needs \"ask\": {question_id: question}")
    questions = {qid: normalize_question(qid, q) for qid, q in spec["ask"].items()}
    threshold = float(spec.get("threshold", 0.5))
    limit = int(spec.get("max_chars", 12000))
    key = api_key()

    rows = []
    for i, item in enumerate(load_items(spec)):
        iid, state = item_id_and_state(i, item)
        state, clipped = truncate(state, limit)
        full = {"context": spec["context"], "item": state} if "context" in spec else state
        rows.append({"id": iid, "state": state, "clipped": clipped,
                     "body": {"model": spec.get("model", MODEL), "state": full, "questions": questions}})

    def one(row):
        try:
            res = post(row["body"], key)
            row.update(answers=res.get("answers", {}), model=res.get("model"),
                       tokens=res.get("usage", {}).get("input_tokens", 0))
        except Fatal:
            raise
        except Exception as e:  # one bad item shouldn't sink the batch
            row.update(error=str(e), answers={}, tokens=0)
        return row

    t0 = time.time()
    one(rows[0])  # probe: a bad key, spec or network fails here, once, not N times
    with ThreadPoolExecutor(max_workers=int(spec.get("workers", 8))) as pool:
        list(pool.map(one, rows[1:]))
    return rows, questions, threshold, time.time() - t0


def render(spec, rows, questions, threshold, secs):
    show = spec.get("show", "decide")
    for r in rows:
        r.pop("body", None)
    if show == "json":
        return json.dumps([{k: r.get(k) for k in ("id", "answers", "error", "clipped")} for r in rows],
                          indent=1, ensure_ascii=False)

    out = []
    qids = list(questions)
    only = spec.get("only")
    if only:
        ok = [r for r in rows if not r.get("error")]
        unsure = [r for r in ok if is_unsure(only, r["answers"], threshold)]
        keep = [r for r in ok if r not in unsure and passes(only, r["answers"], threshold)]
        out.append(f"{len(keep)}/{len(rows)} pass {only}")
        out += [label(r["id"], r["state"], 70) for r in keep]
        if unsure:
            out.append(f"unsure ({len(unsure)}), judge these yourself:")
            out += [label(r["id"], r["state"], 70) for r in unsure]
        errs = [r for r in rows if r.get("error")]
        out += [f"  ! {r['id']}: {r['error']}" for r in errs]
        return "\n".join(out)

    model = next((r.get("model") for r in rows if r.get("model")), MODEL)
    tokens = sum(r.get("tokens", 0) for r in rows)
    out.append(f"{len(rows)} items · {len(qids)} q · {model} · {secs:.1f}s · {tokens:,} tok")
    for qid in qids:
        counts = {}
        for r in rows:
            a = r["answers"].get(qid)
            if a is None:
                continue
            _, d, unsure, _ = summarize(a, threshold)
            if unsure:
                name = "unsure"
            elif isinstance(d, bool):
                name = "yes" if d else "no"
            else:
                name = str(a.get("legend", {}).get(str(d), d))
            counts[name] = counts.get(name, 0) + 1
        out.append(f"  {qid}: " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))

    if spec.get("compare"):
        out += compare(rows, qids if spec["compare"] is True else spec["compare"], threshold)

    if show == "table":
        key = spec.get("sort", qids[0])
        rows = sorted(rows, key=lambda r: -summarize(r["answers"][key], threshold)[3]
                      if key in r["answers"] else 1)
        out.append("")
        out.append("| item | " + " | ".join(qids) + " |")
        out.append("|---|" + "---|" * len(qids))
        for r in rows:
            cells = [summarize(r["answers"][q], threshold)[0] if q in r["answers"] else "—" for q in qids]
            out.append(f"| {label(r['id'], r['state']).strip()} | " + " | ".join(cells) + " |")
    else:
        out.append("")
        for r in rows:
            cells = [f"{q} {summarize(r['answers'][q], threshold)[0]}" for q in qids if q in r["answers"]]
            out.append(f"{label(r['id'], r['state']):<52} " + "  ".join(cells))

    for r in rows:
        if r.get("error"):
            out.append(f"  ! {r['id']}: {r['error']}")
    clipped = [r["id"] for r in rows if r.get("clipped")]
    if clipped:
        out.append(f"  (truncated to {spec.get('max_chars', 12000)} chars: {', '.join(clipped[:10])}"
                   f"{'…' if len(clipped) > 10 else ''})")
    out.append("  ? = unsure (yes/no near the threshold, or low confidence)")
    return "\n".join(out)


def compare(rows, qids, threshold):
    out = [f"  compare {' vs '.join(qids)}:"]
    split = []
    for r in rows:
        ds = [summarize(r["answers"][q], threshold)[1] for q in qids if q in r["answers"]]
        if len(set(map(str, ds))) > 1:
            split.append(r)
    agree = len(rows) - len(split)
    out.append(f"    agree on {agree}/{len(rows)}" + (" — they disagree on:" if split else ""))
    for r in split:
        cells = "  ".join(f"{q} {summarize(r['answers'][q], threshold)[0]}" for q in qids if q in r["answers"])
        out.append(f"    {label(r['id'], r['state'], 40)}  {cells}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("spec", nargs="?", help="spec JSON file (default: stdin)")
    ap.add_argument("--items", help="items file or directory (overrides items_file)")
    ap.add_argument("--show", choices=["decide", "table", "json"])
    ap.add_argument("--only", help="print only passing items: qid | qid=option | qid>=0.7")
    ap.add_argument("--threshold", type=float)
    a = ap.parse_args(argv)
    try:
        raw = Path(a.spec).read_text() if a.spec and a.spec != "-" else sys.stdin.read()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        print(f"jev: can't read the spec: {e}", file=sys.stderr)
        return 2
    for k in ("show", "only", "threshold"):
        if getattr(a, k) is not None:
            spec[k] = getattr(a, k)
    if a.items:
        spec["items_file"] = a.items
    try:
        print(render(spec, *run(spec)))
    except Fatal as e:
        print(f"jev: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
