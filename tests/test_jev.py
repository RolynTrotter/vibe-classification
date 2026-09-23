"""Unit tests for scripts/jev.py against the local fake API.

    python3 -m unittest discover tests
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/vibe-classification/scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import fake_jev  # noqa: E402

SRV, URL = fake_jev.start()
os.environ["TYPESAFE_BASE_URL"] = URL
os.environ["TYPESAFE_API_KEY"] = "test-key"
import jev  # noqa: E402  (reads TYPESAFE_BASE_URL at import)


def run(spec, *args):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec, f)
    with redirect_stdout(out), redirect_stderr(err):
        code = jev.main([f.name, *args])
    os.unlink(f.name)
    return code, out.getvalue(), err.getvalue()


EMAILS = [
    {"id": "a", "subject": "Invoice due YES", "body": "bill LEVEL3"},
    {"id": "b", "subject": "Lunch?", "body": "personal"},
    {"id": "c", "subject": "Weekly digest MAYBE", "body": "newsletter LEVEL1"},
]
ASK = {
    "act": "Does the reader need to act on this?",
    "kind": {"q": "What kind of email?", "options": ["bill", "personal", "newsletter"]},
    "urgency": {"q": "How soon?", "levels": ["none", "month", "week", "today"]},
}


class Questions(unittest.TestCase):
    def test_shorthand_expands_to_api_types(self):
        n = jev.normalize_question
        self.assertEqual(n("x", "Is it?"), {"type": "noul", "instructions": "Is it?"})
        self.assertEqual(n("x", {"q": "Is it?", "yes": "Y"})["criteria"], {"true": "Y"})
        self.assertEqual(n("x", {"q": "Which?", "options": ["a", "b"]})["criteria"], {"a": None, "b": None})
        self.assertEqual(n("x", {"q": "How?", "levels": ["lo", "hi"]})["type"], "score")
        raw = {"type": "noul", "instructions": "raw"}
        self.assertIs(n("x", raw), raw)
        with self.assertRaises(jev.Fatal):
            n("x", {"options": ["a"]})


class Batch(unittest.TestCase):
    def setUp(self):
        fake_jev.Handler.calls.clear()

    def test_decide_output(self):
        code, out, _ = run({"ask": ASK, "items": EMAILS})
        self.assertEqual(code, 0)
        self.assertIn("3 items · 3 q · jev-fake", out)
        self.assertIn("act: ", out)
        self.assertRegex(out, r"a · Invoice due YES\s+act 0.90✓  kind bill 0.85  urgency 3.0 today")
        self.assertIn("act 0.10✗", out)
        self.assertIn("act 0.50?", out)
        self.assertEqual(len(fake_jev.Handler.calls), 3)

    def test_only_filters(self):
        _, out, _ = run({"ask": ASK, "items": EMAILS, "only": "act"})
        self.assertTrue(out.startswith("1/3 pass act"))
        self.assertIn("a · Invoice", out)
        self.assertNotIn("Lunch", out)
        self.assertIn("unsure (1), judge these yourself:\nc · Weekly digest", out)
        _, out, _ = run({"ask": ASK, "items": EMAILS}, "--only", "kind=newsletter")
        self.assertIn("1/3 pass", out)
        self.assertIn("Weekly digest", out)
        _, out, _ = run({"ask": ASK, "items": EMAILS}, "--only", "urgency>=1")
        self.assertIn("2/3 pass", out)

    def test_table_is_sorted(self):
        _, out, _ = run({"ask": ASK, "items": EMAILS, "show": "table", "sort": "urgency"})
        rows = [l for l in out.splitlines() if l.startswith("| ") and "item" not in l]
        self.assertEqual([r.split("·")[0].strip("| ").strip() for r in rows], ["a", "c", "b"])

    def test_compare_reports_disagreements(self):
        spec = {"ask": {"v1": "Is it urgent?", "v2": {"q": "Must they act?", "options": ["YES", "no"]}},
                "items": ["plain", "YES please"], "compare": ["v1", "v1"]}
        _, out, _ = run(spec)
        self.assertIn("agree on 2/2", out)
        spec = {"ask": {"v1": "Is it urgent?", "v2": "Should it be read today?"},
                "items": ["x"], "compare": True}
        _, out, _ = run(spec)
        self.assertIn("compare v1 vs v2", out)

    def test_label_uses_first_text_field(self):
        self.assertEqual(jev.label("AAA", {"candle": "long lower wick", "n": 3}), "AAA · long lower wick")
        self.assertEqual(jev.label("2", {"n": 3}), '  2 {"n": 3}')

    def test_json_and_context(self):
        _, out, _ = run({"ask": {"q": "YES?"}, "items": ["hi"], "context": {"who": "Rolyn"},
                         "show": "json"})
        data = json.loads(out)
        self.assertEqual(data[0]["answers"]["q"]["type"], "noul")
        self.assertEqual(fake_jev.Handler.calls[0]["state"], {"context": {"who": "Rolyn"}, "item": "hi"})

    def test_items_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "l.txt").write_text("one YES\n\ntwo\n")
            (d / "l.jsonl").write_text('{"id": "x", "text": "YES"}\n')
            (d / "l.csv").write_text("id,text\nr1,YES\nr2,no\n")
            docs = d / "docs"
            docs.mkdir()
            (docs / "p1.md").write_text("YES")
            (docs / ".hidden").write_text("junk")
            for path, n in (("l.txt", 2), ("l.jsonl", 1), ("l.csv", 2), ("docs", 1)):
                _, out, _ = run({"ask": {"q": "?"}}, "--items", str(d / path))
                self.assertIn(f"{n} items", out, path)

    def test_truncates_long_items(self):
        _, out, _ = run({"ask": {"q": "?"}, "items": ["x" * 50], "max_chars": 10})
        self.assertIn("truncated to 10 chars: 1", out)
        self.assertTrue(fake_jev.Handler.calls[0]["state"].endswith("…[truncated]"))

    def test_retries_rate_limit(self):
        fake_jev.Handler.limited = False
        code, out, _ = run({"ask": {"q": "?"}, "items": ["RATELIMIT YES"]})
        self.assertEqual(code, 0)
        self.assertIn("0.90✓", out)
        self.assertEqual(len(fake_jev.Handler.calls), 2)


class Failures(unittest.TestCase):
    def setUp(self):
        fake_jev.Handler.calls.clear()

    def test_bad_key_stops_after_one_call(self):
        os.environ["TYPESAFE_API_KEY"] = "wrong"
        try:
            code, _, err = run({"ask": {"q": "?"}, "items": ["a", "b", "c", "d"]})
        finally:
            os.environ["TYPESAFE_API_KEY"] = "test-key"
        self.assertEqual(code, 1)
        self.assertIn("401", err)
        self.assertEqual(len(fake_jev.Handler.calls), 1)

    def test_malformed_question_is_fatal(self):
        code, _, err = run({"ask": {"q": {"type": "bogus", "instructions": "?"}}, "items": ["a", "b"]})
        self.assertEqual(code, 1)
        self.assertIn("422", err)

    def test_missing_key(self):
        os.environ.pop("TYPESAFE_API_KEY")
        try:
            code, _, err = run({"ask": {"q": "?"}, "items": ["a"]})
        finally:
            os.environ["TYPESAFE_API_KEY"] = "test-key"
        self.assertEqual(code, 1)
        self.assertIn("No TypeSafe key", err)

    def test_unreachable_gives_network_hint(self):
        old = jev.BASE_URL
        jev.BASE_URL = "http://127.0.0.1:9"
        try:
            code, _, err = run({"ask": {"q": "?"}, "items": ["a"]})
        finally:
            jev.BASE_URL = old
        self.assertEqual(code, 1)
        self.assertIn("allowed domains", err)

    def test_nothing_to_ask(self):
        self.assertEqual(run({"ask": {"q": "?"}})[0], 1)
        self.assertEqual(run({"items": ["a"]})[0], 1)


if __name__ == "__main__":
    unittest.main()
