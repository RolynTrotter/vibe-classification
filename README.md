# vibe-classification

A claude.ai chat skill that hands quick, instinctive judgments to
[TypeSafe](https://docs.typesafe.ai)'s Jev, a System One model that returns calibrated
yes/no probabilities, picks, and scores instead of text. It's for things like triaging an
inbox, deciding which of 30 search results are worth opening, tagging a list, or A/B-testing
the wording of a classification question before trusting it.

TypeSafe's own [agent skill](https://github.com/typesafe-ai/skills) teaches coding agents to
*build apps* on Jev. This one is for *chat*: Claude uses Jev directly, mid-conversation.

## Install

1. In claude.ai, turn on code execution (**Settings → Capabilities**) and add
   `api.typesafe.ai` to its allowed domains.
2. Get a zip with your key built in. Either:
   - clone this repo and run `python3 tools/build_skill.py --key <KEY>`, which gives you
     `dist/vibe-classification-personal.zip`, or
   - download the latest [release](https://github.com/RolynTrotter/vibe-classification/releases)
     zip, upload it, and in a chat say "personalize vibe-classification with my key: …".
     Claude builds the keyed zip for you to upload in its place.
3. Upload the personal zip under **Settings → Capabilities → Skills**. Don't share it,
   because it contains your key.

## Layout

| Path | What |
| --- | --- |
| `skills/vibe-classification/SKILL.md` | What Claude reads. Keep it short. |
| `skills/vibe-classification/scripts/jev.py` | The engine: spec in, compact decisions out. Stdlib only. |
| `skills/vibe-classification/scripts/personalize.py` | Bakes a key into a copy of the skill. |
| `tools/build_skill.py`, `tools/test_skill.py` | Build the zip, then test it unpacked. |
| `tests/` | Unit tests against a local fake of the API. They never need a key. |

```bash
python3 -m unittest discover tests
python3 tools/build_skill.py && python3 tools/test_skill.py
```

## Releasing

Bump `metadata.version` in `SKILL.md`, add a matching `CHANGELOG.md` entry, and merge
to `main`. `release.yml` tags `v<version>` and attaches the zip. A merge that doesn't
change the version releases nothing.
