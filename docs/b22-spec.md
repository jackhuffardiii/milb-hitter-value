# B22 spec (handed to the implementer 2026-10-10; check its work against this)

Do not commit. Write docs/b22-implementer-report.md when done (numbers, choices, deviations).
Pitcher models (S23, S25, C18), the pitcher twin of `pipeline/b6_models.py`. Read b6 fully first: same hazard (A13), WAR mean
selection (A12), spread (A16), Platt rule (C4), drivers (A6).

## Code shape
- New `pipeline/b22_pitch_models.py`; run.py "b22" after "b21" (b22 must run after b21 and before b8/b9 later steps).
- Reuse b6's generic pieces unchanged: person_period, curve, hazard_cv_check, _lgb_cv, _lin_cv, _oof, _make, select_spread,
  _spread_fit, _spread_scale, _zval, QS, T_MAX, Z_GRID, horizon/p_within. Where b6 is hitter-specific (XFN, _war_mask reading
  war_target.parquet, _spread_F / SPREAD_FEATS, drivers using XFN), generalize with the smallest change (e.g. a `war_target`
  argument, X/spread functions carried on the model dict or added to XFN under new keys). HARD CONSTRAINT: hitter outputs stay
  identical. Before editing b6, copy data/predictions.parquet, data/drivers.parquet, data/b6_metrics.json to $TMPDIR; after,
  `run.py b6` and assert `.equals` (json: same content). b6 takes ~1 min.

## Data
- data/pitch_features.parquet (B20). group stat / prior. Labels debut_year, reached_mlb, debuted, eta_years, war_6yr; WAR
  training mask from data/pitch_war_target.parquet (censored, pre2005), same logic as b6 `_war_mask`.
- S28 contact adjustment (C17 passed): data/pitch_contact.parquet has xb_contact_adj (raw AAA XB/BIP scale). For stat rows whose
  season s has >= 100 AAA BIP (BIP = BF - SO - BB - HBP - HR over AAA rows of data/milb_pitching_seasons.parquet, excluding the
  Mexican League) and an xb_contact_adj, multiply reg_XB and blend_reg_XB by xb_contact_adj / XB_obs (XB_obs = (2B + 2*3B)/BIP
  over the same AAA rows). Report how many rows change, by season (only 2022+ exist). Keep the unadjusted values in
  reg_XB_raw / blend_reg_XB_raw for the card.
- Design matrices: stat = `pitch_X(df)` from pipeline/b20_pitch_features.py, NO extra columns (mERA failed C15).
  prior = pitcher analog of b6 prior_X: round_num, pick_overall, log1p(signing_bonus), international, age, level_num,
  log1p(BF_s), years_since_draft, hs_draftee.
- Spread features (stat): age, age_vs_level, level_num, pro_years, blend_GS_share (+ pred, as b6). Prior: prior X + pred.

## Fits (mirror b6 main)
- Selection on stat s <= 2012 GroupKFold(5) CV only: hazard linear vs LightGBM (person-period log loss), WAR ridge vs LightGBM
  (OOF Spearman, reached non-censored non-pre2005). Prior: linear only.
- backtest: train s <= 2012, WAR s <= 2012, predict 2013-17. fit2017: train s <= 2017, WAR s <= 2014, predict 2018-19.
  final: train s <= 2025, WAR s <= 2014, predict s >= 2018 (incl. 2026 score rows). WAR cutoff 2014, not b6's 2015: A12's
  "under 2% censored" rule gives 2014 for pitchers (pitch_war_target censored share among reached stat rows: 2014 .9%, 2015 3.0%).
- Spread kind chosen in the backtest fit, reused by later fits (b6 pattern). Report C11 coverage like b6.
- Models: data/models/pitch_{kind}_{fit}.joblib (kind stat/prior), same dict keys as b6 models (incl. "z") so B8's value() can
  load them by name with a prefix.
- **No holdout metrics.** Do NOT compute or print any metric on 2013-17 or 2018-19 predictions (B23 is the single pitcher
  holdout look, run by the main session). Only s <= 2012 CV numbers go in b22_metrics.json.

## C18 drift check -> b22_metrics.json["c18"]
- On stat s <= 2012 with the chosen model types: (a) GroupKFold(5) OOF, (b) forward-chained: train s <= 2009, test 2010-12
  (player-disjoint not required). Report P(MLB) log loss on fully observed not-debuted rows (9-year reach, as hazard_cv_check)
  and WAR Spearman (reached rows) for both. Report only; no decision rides on it.

## Reach-rate flag (B20) -> b22_metrics.json["reach_vs_hitters"]
- Train-era (s <= 2017) stat, not debuted: reach rate for pitchers vs hitters (data/features.parquet) by highest_level x
  age_vs_level tercile (terciles cut on the pooled rows), with n. One line of interpretation in the report.

## Outputs
- data/pitch_predictions.parquet: b6 predictions columns (+ fit, group, chosen_*), pitcher rows.
- data/pitch_drivers.parquet: b6 drivers format for stat backtest rows and stat 2026 score rows (final fit).
- data/b22_metrics.json: cv_stat, chosen_stat, spread (+ C11), calibration_check (CV-based, as b6), c18, reach_vs_hitters,
  contact_adjusted_rows.
- tests/test_b22.py: predictions unique per (player_id, season, fit); p_mlb in [0,1], debuted rows p=1; war_q10 <= war_q50 <=
  war_q90; every 2026 stat/prior row scored by the final fit; model files load with key "z" of length 199; metrics json has
  c18 with both schemes and no holdout keys.
- Full suite stays green (166 passed, 3 xfailed before B22).
