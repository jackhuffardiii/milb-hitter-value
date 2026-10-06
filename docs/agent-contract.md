# Build agent contract

Every build agent follows this. Read it and `milb-hitter-value-spec.md` before writing code.

## Spec is the contract
- Your build step (B#) and the spec IDs it lists are the requirements. Cite the IDs you implement in each module docstring and in your commit message.
- If the data or an API contradicts the spec, do not improvise a new design. Implement what is possible, then record the contradiction under "Spec deviations" in `docs/handoff.md` and in your final report, naming the IDs affected.
- Do not edit `milb-hitter-value-spec.md` or `milb-hitter-value-plan.html`.

## Layout
- `pipeline/b<N>_<name>.py`: one module per build step, each exposing `main()`. Shared helpers only in `pipeline/common.py` (add to it, do not duplicate).
- `run.py`: runs every step's `main()` in build order. Register your step there. `python run.py` must rebuild everything from scratch (C5); `python run.py b3` runs one step.
- `data/raw/`: downloaded/cached source files. `data/*.parquet`: intermediates. `data/manual/`: hand-maintained inputs (the only committed data). `site/`: published output.
- `tests/test_b<N>.py`: plain pytest asserts on the real outputs of your step. Smallest checks that fail if your logic breaks.

## Environment
- Python 3.12, virtualenv at `.venv` (create with `python3 -m venv .venv` if missing). Dependencies pinned in `requirements.txt` (exact versions). Add only what you need.
- Standard stack: pandas, pyarrow, duckdb, requests, scikit-learn, lightgbm, shap, pytest.

## External data
- MLB Stats API (`https://statsapi.mlb.com/api/v1/...`): cache every raw response under `data/raw/` so reruns do not refetch; retry with backoff; at most 8 concurrent requests.
- Never push, publish, or post anything. Read-only network access to data sources only.

## Git
- One commit per build step, made at the end, after tests pass: `B<N>: <summary> (<spec IDs>)`, ending with the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Only touch your step's files, `pipeline/common.py`, `run.py`, `requirements.txt`, `tests/`, and `docs/handoff.md`.

## Handoff
Append a section to `docs/handoff.md` for your step: every output file with grain and columns (name, type, meaning), how to run it, runtime, known data quirks, and "Spec deviations" (or "none"). The next agent reads only this file and the spec, so make it sufficient.

## Final report
Return: files changed, the verification command you ran with its actual output (trimmed), the commit hash, deviations, and anything the next step must know.
