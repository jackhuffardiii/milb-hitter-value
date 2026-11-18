# MiLB Hitter Value

A stats-based projection system that puts a surplus dollar value on every A through AAA hitter, with an audit trail from minor league stat line to dollars: MLB-equivalent rates, P(reach MLB), expected WAR over six control years, ETA, and surplus $ with a 10/50/90 range.

- Spec: [milb-hitter-value-spec.md](milb-hitter-value-spec.md)
- Build log, output schemas, and results: [docs/handoff.md](docs/handoff.md) (v1.1 audit fixes: [docs/fix-plan.md](docs/fix-plan.md))
- Site: none of its own since 2026-11-18. `run.py b34` writes the site data (`site/data/`) into the Trade Web (`~/Projects/mlb-trade-web`), which hosts the rankings, player pages, Trade Machine and methodology ([trade-web-merge-spec.md](trade-web-merge-spec.md))

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py          # every step; `run.py b9` runs one; `--refresh` re-pulls bios/debuts and 2026 API data
.venv/bin/python -m pytest -q
```

Raw data (`data/raw/`, MLB Stats API, Baseball Savant, Baseball-Reference, milb-data-repository) and intermediates are not committed; the first run downloads and caches them. Hand-maintained inputs live in `data/manual/`.
