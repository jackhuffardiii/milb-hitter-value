# B29 spec: MLB player WAR projections (v3 S33, C23). Handed to an implementer 2026-10-10.

Do not commit. Report to docs/b29-implementer-report.md. Knobs come from `pipeline/config.py` (v3 block); do not hard-code them.

## Inputs
- data/mlb_war.parquet (hitters: player_id, season, PA, owar), data/mlb_pitch_war.parquet (pitchers: player_id, season, outs,
  G, GS, pwar). Both sum to 590/410 per season (our scale). Ages from data/players.parquet / data/pitch_players.parquet
  (birth_date; age on July 1 of the season, same convention as b4/b16).
- Population to project: every player_id in data/mlb_contracts_2026.parquet (the 2026 40-man rosters). A player with both
  hitting and pitching rows (Ohtani) gets both projections, summed per season.

## Method (pipeline/b29_projections.py, function `project(hist, base_season)` reusable for the backtest)
- Rate: Marcel over the last three seasons up to base_season with config.MARCEL_WEIGHTS: rate = (sum w*WAR + R*m) /
  (sum w*PT + R), PT = PA (hitters) or outs (pitchers), R = config.REGRESS_PA / REGRESS_OUTS, m = that kind's league WAR per
  PA (per out) over the same seasons among players with PT > 0. A missing season contributes 0 WAR and 0 PT.
- Playing time: config.PT_HIT / PT_PITCH (starter = GS/G > .5 over the window). Held flat across projection years.
- Aging: our own delta-method curve, separately for hitters, starters, relievers: for consecutive seasons (s, s+1) of the
  same player with PT > 0 both years, change in WAR per 600 PA (hitters) or per 450 outs (pitchers), weighted by the
  harmonic mean of PT, by age (bucketed: <=23, each age 24-37, >=38), seasons 2006-2025 excluding pairs touching 2020.
  Smooth with a 3-age moving average. Apply cumulatively from base_season age to each projection year. Report the curve.
- Output: data/mlb_projections.parquet: player_id, kind (hitter, pitcher, two_way), age_2026, starter (bool),
  war_{2027..2032}, pt_{2027..2032}. data/b29_aging.json: the curves.

## C23 backtest -> data/b29_c23.json
- For base seasons 2014-2024 (skip 2019 as base for 2020 and 2020 as base), project base+1 for every player with
  base-season PT > 0 and compare with actual next-season WAR (0 if he did not play). Report per kind: Pearson r and RMSE
  for (a) ours, (b) plain Marcel (same rate and PT, Marcel's textbook aging: +0.6%/yr rate change before 29 applied to WAR
  rate, -0.3%/yr after), (c) naive last-season WAR. Also report the residual SD of ours by projected-PT tercile (B31 uses it
  for uncertainty). No tuning on this; C23 passes if ours is not worse than plain Marcel on both r and RMSE.

## run.py and tests
- ORDER: "b29" after "b28"; MODULES entry.
- tests/test_b29.py: one row per contracted player_id; war and pt finite; pt >= 0; aging curve keys present; c23 json has
  all three methods for both kinds; known check: a top player (e.g. Aaron Judge 592450 or Juan Soto 665742) projects
  2027 WAR above 3.
- Full suite must stay green (`.venv/bin/python -m pytest -q`).
