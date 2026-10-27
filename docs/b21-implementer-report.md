# B21 implementer report

Objective: pitcher Savant tracking (arsenal, contact adjustment) and the C17 gate. Not committed.

## Changes
- pipeline/b9_site.py: `savant_family(season, fam, player_type="batter")`. Batter URL and cache name unchanged; pitcher cache `p_{season}_{fam}.csv`. No other b9 edits.
- pipeline/b21_pitch_tracking.py (new), run.py (ORDER and MODULES), tests/test_b21.py (5 tests).
- Outputs: data/pitch_arsenal.parquet (22,612 rows, 2021-26), data/pitch_contact.parquet (7,745 rows, 2022-26), data/b21_c17.json. New cache files: `p_{2021..2026}_{Fastball,Breaking,Offspeed}.csv`, `p_{2022..2026}_contact.csv`.
- Savant's pitcher CSV has the same columns as the batter one; player_id is the pitcher. No adaptation needed. Under the BBT filter `bip` equals `pa`, and `xwoba` is xwOBA on contact.

## C17 (n = 237 pitcher-seasons, 191 pitchers; s in 2023-24, AAA-dominant both years, >= 100 AAA BIP both years, tracked)
| predictor | OOF weighted RMSE |
|---|---|
| A observed XB/BIP | 0.05725 |
| B blended (XB, xwOBAcon) | 0.05649 |
| C shrunk-only control | 0.05729 |

- Gate (B < A): PASS, but by only 0.0008 (1.3%). B also beats C, so the gain is not just shrinkage.
- Full-sample fit: k = 800 (top of the grid, so the blend leans on tracking; a larger k might do slightly better), f = 0.00262 + 0.2556 * xwOBAcon. Control C picks k = 50.
- n is small and the margin is thin. No confidence interval was computed.

## Choices and deviations
- BIP for XB, the 100-BIP filter and w is box-score AAA BIP (BF - SO - BB - HBP - HR), not Savant BIP. Sample also requires a Savant xwOBAcon row for s, any tracked count.
- "AAA-dominant" = AAA BF / all non-Mexican-League BF >= 0.8. Target ISO and weight use next-season AAA rows only; weight = AB - SO + SF.
- k is chosen inside each training fold by in-sample weighted RMSE after a linear calibration; calibration is fit on the training fold and applied to the held-out fold.
- `xb_contact_adj` uses the full-sample f and k. Pitcher-seasons with no AAA BIP get pure f(xwOBAcon). It is not wired into B18/B20/B22.
- Arsenal usage = pitches / total_pitches per family. Per-player family usage sums to < 1 for some (median 0.998, mean 0.94) because unclassified pitch codes belong to no family.
- Arsenal medians: Fastball velocity 92.2, Breaking 82.1, Offspeed 85.3.

## Verification
`.venv/bin/python run.py b21` (76 s uncached) and `.venv/bin/python -m pytest -q`: 165 passed, 3 xfailed (160 + 5 new).
