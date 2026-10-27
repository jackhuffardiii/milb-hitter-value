# B30 spec: arbitration salary model (v3 S35, C24). Handed to an implementer 2026-10-10.

Do not commit. Report to docs/b30-implementer-report.md. Knobs from `pipeline/config.py`; no hard-coding.

## Data
- data/mlb_salaries.parquet (B27): season, player_id (matched rows only), pos, service_years (2010+), salary.
- Our WAR: data/mlb_war.parquet (owar, PA), data/mlb_pitch_war.parquet (pwar, outs, G, GS).
- Training rows: matched player-seasons 2011-2026 with 3 <= service_years(s) < 6 at the start of season s (service_years in
  the Cot's sheet for season s is service time entering s), salary > 1.05 x that season's league minimum (drops pre-arb
  renewals and minor-league contracts), and not on a multi-year contract (exclude a row when the same player's salary is
  identical in s-1 and s+1 and not equal to his s-1 arb-predicted path: simplest robust proxy = exclude rows whose salary
  equals the previous season's salary exactly). Arb year k = floor(service_years) - 2 (1, 2, 3). Super Two
  (2.12 <= service < 3) included as arb year 1 if salary qualifies, flagged.
- League minimum by season: 2026 $780K from data/manual/dollar_params.csv; earlier years from the CBA schedule
  (2010 400K, 2011 414K, 2012 480K, 2013 490K, 2014 500K, 2015-16 507.5K, 2017 535K, 2018 545K, 2019 555K, 2020 563.5K,
  2021 570.5K, 2022 700K, 2023 720K, 2024 740K, 2025 760K, 2026 780K). Put the table in pipeline/b30_arb.py.

## Model (pipeline/b30_arb.py)
- Target: log(salary / league minimum of s).
- Features: prior-season WAR (s-1), WAR over s-3..s-1, career WAR through s-1, arb year (one-hot), pitcher flag, starter flag
  (pitchers, GS/G > .5 in s-1), prior-season log(salary/min) when he was already arb-eligible (else 0 + indicator), PT in s-1.
- Candidates: ridge vs LightGBM (LGB params like b6), chosen by GroupKFold(5) by player on s < config.ARB_HOLDOUT_FIRST,
  metric = RMSE in log space. Baseline for comparison: the v2 rule (arb share 40/60/80% x max(WAR x $/WAR of s, min)) using
  $/WAR deflated like b8 (2026 base, inflation param).
- Holdout: one look on s >= config.ARB_HOLDOUT_FIRST: RMSE (log) and median absolute % error for model and baseline.
- Final fit on all training seasons for use by B31.
- Public function: `predict_arb(df) -> salary dollars`, df columns: season, prev_war, war_3yr, career_war, arb_year,
  is_pitcher, is_starter, prev_log_salary_rel (NaN if none), prev_pt. Loads data/models/arb.joblib.

## Outputs, run.py, tests
- data/models/arb.joblib, data/b30_c24.json (cv per candidate, chosen, baseline cv, holdout model vs baseline, n rows).
- ORDER: "b30" after "b29"; MODULES entry.
- tests/test_b30.py: model loads; predict_arb monotone in prev_war (higher WAR -> higher salary, other things equal) and in
  arb_year; predictions >= league minimum; c24 json has holdout numbers for model and baseline.
- Full suite green.
