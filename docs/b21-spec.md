# B21 spec (handed to the implementer 2026-10-10; check its work against this)

Do not commit. Write your report to docs/b21-implementer-report.md when done (numbers, choices, anything that deviated).
Network: Bash calls that download need `allowed_domains: ["baseballsavant.mlb.com"]`. Be polite: sleep 0.2 s between uncached requests, cache every response under data/raw/savant_splits/.

## Task 0: generalize `savant_family` (pipeline/b9_site.py:79)
- Add `player_type="batter"`. Batter URL and cache name `{season}_{fam}.csv` stay byte-identical (hitter cache must keep hitting).
- Pitcher cache name `p_{season}_{fam}.csv`. Keep the 25,000-row cap assert.
- Hitter site output must not change: no other edits to b9.

## Task 1: arsenal (D17, S27, display only) -> data/pitch_arsenal.parquet
- New `pipeline/b21_pitch_tracking.py`. Seasons 2021-2026, families from `PITCH_FAMILY`.
- One row per player_id x season x family: pitches, usage (= pitches / total_pitches), velocity, spin_rate, release_extension, whiff (= whiffs / swings, NaN if no swings).
- Savant minors CSVs mix all tracked levels (AAA 2023+, Florida State League 2021+); keep it that way and label it "tracked games" in a column-free way (docstring). Display only: never a model feature.

## Task 2: contact adjustment (S28) and C17 gate -> data/pitch_contact.parquet, data/b21_c17.json
- xwOBA on contact allowed per pitcher-season: one Savant minors query per season, player_type=pitcher, group_by=name, all pitch types, batted balls only (reuse the BBT filter string b9/b11 already use for hfBBT), cache `p_{season}_contact.csv`. Seasons 2022-2026. Columns kept: player_id, season, xwoba (= xwOBAcon), bip.
- Contact term = XB/BIP, the B18 definition (`XB=(2B+2*3B)/BIP`, pipeline/b18_pitch_mle.py:35), from data/milb_pitching_seasons.parquet summed over AAA rows only.
- C17 sample: AAA-dominant pitcher-seasons (>= 80% of affiliated MiLB BF at AAA) for s in 2023-2024 with an AAA-dominant s+1 and >= 100 BIP in both seasons. Target: next-season ISO on contact = (2B + 2*3B + 3*HR) / (AB - SO + SF) from box stats, weight = next-season contact count.
- Blended term: w * XB_obs + (1 - w) * f(xwOBAcon), w = BIP / (BIP + k). f = weighted linear fit of XB_obs on xwOBAcon; k picked from a small grid (e.g. 50, 100, 200, 400, 800). f and k are fit inside each training fold only.
- Evaluation: GroupKFold(5) by player. Each predictor (A: observed XB_obs; B: blended) gets an OOF weighted linear calibration to the target, then weighted RMSE. Also report a control C: XB_obs shrunk to the fold's league mean with the same k grid (no tracking). Gate = spec C17 as written: B's RMSE < A's -> pass. Report C regardless and say plainly if B beats A but not C (that means the gain is shrinkage, not tracking).
- Write blended `xb_contact_adj` for every tracked pitcher-season with xwOBAcon (fit f, k on the full C17 sample) to pitch_contact.parquet. Do not wire it into b18/b20/b22; the main session decides after C17.
- Report n, both RMSEs, control, chosen k, f coefficients.

## run.py and tests
- ORDER: "b21" after "b20"; MODULES entry.
- tests/test_b21.py: unique keys in arsenal and contact; usage in [0, 1] and sums to ~1 per player-season; whiff in [0, 1]; velocity plausible (Fastball median 88-96); c17 json has n, rmse_observed, rmse_blended, rmse_shrunk_control, boolean pass; hitter `savant_family(2024, "Fastball")` still reads the existing cached file (no network).
- Full suite must stay green: `.venv/bin/python -m pytest -q` (160 passed, 3 xfailed before B21).
