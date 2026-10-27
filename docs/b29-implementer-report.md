# B29 implementer report (MLB WAR projections, C23)

Files: pipeline/b29_projections.py, tests/test_b29.py; data/mlb_projections.parquet, data/b29_aging.json, data/b29_c23.json. run.py not touched (register "b29" after "b28" + MODULES entry). Not committed.
Run: `.venv/bin/python -m pipeline.b29_projections`. Full suite: 193 passed, 3 xfailed.

## C23 (base seasons 2014-2018, 2021-2024; next season; 0 WAR if he did not play) - PASSES on both kinds
| kind | n | method | r | RMSE |
|---|---|---|---|---|
| hitter | 5810 | ours | .659 | 1.271 |
| hitter | | plain Marcel | .647 | 1.331 |
| hitter | | last-season WAR | .629 | 1.465 |
| pitcher | 7210 | ours | .629 | 0.850 |
| pitcher | | plain Marcel | .625 | 0.878 |
| pitcher | | last-season WAR | .612 | 0.964 |

Residual SD of ours (actual - projection) by projected-PT tercile (b29_c23.json "residual_sd_by_pt_tercile", shape per the coordinator addendum):
hitters [0.78, 1.14, 1.70], cuts 271 / 426 PA; pitchers [0.40, 0.68, 1.24], cuts 118.7 / 199.5 outs. Terciles are assigned with np.searchsorted(cuts, pt). The edge over Marcel is small (r +.001 to +.012); the RMSE gain is the clearer part.

## Aging curves (WAR per 600 PA / 450 outs, age -> age+1, 3-age smoothed; full table in b29_aging.json)
| age | hitter | starter | reliever |
|---|---|---|---|
| 23 (<=23) | +0.02 | +0.03 | +0.06 |
| 25 | -0.12 | -0.07 | -0.04 |
| 28 | -0.40 | -0.32 | -0.27 |
| 31 | -0.70 | -0.29 | -0.48 |
| 34 | -0.79 | -0.32 | -0.53 |
| 37 | -1.04 | -0.73 | -0.91 |
| 38 (>=38) | -1.13 | -0.63 | -1.00 |
Decline starts early (about -0.4 WAR/yr by 28), partly because the delta method conditions on playing both years (survivor and regression-to-mean effects are baked in). Starter curve is noisy at 31-37 (few pairs).

## Choices
- Base season = 2026 (data complete, sums to 590/410). Age = days from birth to July 1 / 365.25, floored for the bucket. Curves for the backtest use only pairs with s+1 <= base (no leakage); final curve uses pairs through 2026.
- Curve group of a pair is set by starter status (GS/G > .5) in season s; hitters one group. Curve applied as rate + cumulative delta / UNIT, times flat PT.
- Plain Marcel: rate x (1 + .006*(29-a)) under 29, (1 + .003*(29-a)) from 29, with a = floor(age at base) + 1; same rate and PT as ours.
- Side assignment: two_way if window PA >= TWO_WAY_MIN_PA and BF >= TWO_WAY_MIN_BF (only Ohtani; position players who pitch a few outs stay hitters); else the side with more PA vs BF in 2024-26 (career if no window). Two-way WAR is summed; pt_YYYY = PA for hitter/two_way, outs for pitcher.
- Backtest includes every player with base PT > 0 on each side (incl. position players with a few outs), per the spec.

## Deviations / notes
- Extra columns pa_YYYY and outs_YYYY (both sides' PT) so a two-way player keeps both; pt_YYYY follows the spec.
- 9 contracted players have no MLB rows in 2024-26 (prospects): war 0, pt 0 (not given a Marcel 200-PA league-average line). B31 should handle them from the MiLB projections.
- Dropped one 1-PA 2018 row with NaN owar in load_hist (it made the naive correlation NaN).
- Players with no birth_date are dropped from curves/backtest (about 0.3%); all 1169 contracted ids have ages.
- Output has 1169 rows (contracts file has 23 duplicate player_id rows from multi-team listings; deduped).
