---
name: vibe-classification
description: Fast gut-call judgments via TypeSafe's Jev, a System One model that returns calibrated yes/no probabilities, one-of-N choices, or scores instead of text. Use to triage or tag a list (emails, messages, tickets, notes), check whether documents, search results or webpages are relevant before spending effort reading them, filter or rank candidates, or put a quick vibe label on anything that fits a closed set of answers. Also use when the user wants to draft, test, or A/B the wording of a classification question, or mentions Jev, TypeSafe, or System One.
compatibility: Python 3 (stdlib only). Needs network access to api.typesafe.ai and a TypeSafe API key (baked in by scripts/personalize.py, or TYPESAFE_API_KEY).
metadata:
  version: "0.1.1"
  source: "https://github.com/RolynTrotter/vibe-classification"
---

# vibe-classification

Jev answers narrow questions about text, fast and cheap, with calibrated probabilities.
Use it for the instinctive calls: *is this relevant, which bucket, how much*. Do the
thinking yourself; hand Jev the sorting.

## Run

```bash
python3 scripts/jev.py <<'EOF'
{"ask": {
   "relevant": "Does this page explain how to revive a sourdough starter?",
   "kind":  {"q": "What kind of email is this?", "options": ["bill", "personal", "newsletter", "spam"]},
   "urgency": {"q": "How soon does the reader need to act?", "levels": ["no action", "this month", "this week", "today"]}},
 "items": ["text…", {"id": "inv-443", "subject": "…", "body": "…"}]}
EOF
```

- A string is a yes/no question. `options` is a pick-one, and `levels` is an ordered score (2–10 levels).
- For yes/no, add `"yes": "…", "no": "…"` to spell out the boundary.
- Instead of `items`, pass `"items_file": path` (.jsonl, .json, .csv, .txt with one item per line, or a folder of files).
- Add `"context": {…}` for facts every item needs, such as who the reader is or what the goal is.
- `"only": "relevant"` (or `kind=bill`, `urgency>=2`) prints just the items that pass. Use it when you'll act on the result yourself.
- `"show": "table"` gives a ranked markdown table to show the user. `"show": "json"` gives raw answers.
- A `?` marks an unsure answer. Look at those items yourself instead of trusting the tag.

## Framing (Jev reads literally)

- Ask one judgment per question and say exactly what you mean. If you'd need to explain the
  intent, put that explanation in the question or the criteria.
- Keep math, dates, counts and exact matches in code. Turn numbers into words or buckets
  first (e.g. "closed well above open, long upper wick"), not raw OHLC values.
- Send only what the question needs. Trim boilerplate, and extract page text before sending it.
- When nothing may fit, add a `none`/`other` option.

## Two modes

**In the background** (your own filtering, e.g. "which of these 30 results are worth
opening?"): write the question and run it. Don't stop to ask. Act on `only`, and mention it
briefly if at all.

**With the user**, when they'll rely on the labels or the question is fuzzy: offer 2–3
phrasings as options (use the choice widget if you have one). Run them side by side on about
5 items with `"compare": true`, where each phrasing gets its own question id. Show where they
disagree, let the user pick or tweak one, then run the full list. Skip this if the first draft
is obviously fine.

## Setup trouble

- *No key* / *401*: the user needs the personal build. Ask for their key once, then run
  `python3 scripts/personalize.py --key KEY --out /mnt/user-data/outputs` and hand them the
  zip to upload in place of this skill.
- *Can't reach api.typesafe.ai*: the user must add `api.typesafe.ai` to the allowed domains
  in Settings → Capabilities (code execution).
- API details: https://docs.typesafe.ai/llms.txt
