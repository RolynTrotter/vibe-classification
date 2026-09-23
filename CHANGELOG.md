# Changelog

`metadata.version` in `skills/vibe-classification/SKILL.md` is the version. Bump it
and add an entry here, and merging to `main` cuts the release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com); versioning is [semver](https://semver.org).

## [0.1.0] — 2026-09-23

First release.

### Added

- The `vibe-classification` skill: `scripts/jev.py` asks Jev yes/no, pick-one, and
  score questions over one item or a list. It prints compact decisions by default, a
  ranked table with `show: table`, only the passing items with `only`, and phrasing
  disagreements with `compare`.
- Requests carry their own User-Agent. Cloudflare in front of the API rejects
  Python's default with a 403, which was first misread as a network block.
- `scripts/personalize.py` builds a personal zip with your TypeSafe key baked in.
- Release automation: merging a version bump to `main` tags `v<version>` and attaches
  the skill zip.
