# B20 spec (handed to the implementer 2026-10-10; check its work against this)

Do not commit without review. If pymc is imported anywhere, import the pipeline module first (PYTENSOR_FLAGS).

## Task 1: `pipeline/b20_pitch_features.py` -> data/pitch_features.parquet
One row per pitcher x season s, 2005-2026. Mirror `pipeline/b5_features.py`.
- Population: affiliated MiLB pitching in s (league_id != 125) AND (pitch_players.primary_pos in {P, TWP} or MiLB BF in s >= 150).
- Rookie-eligible at end of s (S25): career MLB outs through s < 150.
- Snapshot: highest_level, level_num (b5 LVL), age, throws, BF_s, BF_highest, career_milb_bf (incl. milb_pitch_history), pro_years, age_vs_level (BF-weighted season-level mean age of all affiliated pitchers).
- Role (S23): GS_share, outs_per_G, pitches_per_G for s, plus 3:2 BF-weighted blends with s-1 (blend_*).
- Group (S25): stat if A..AAA BF over s and s-1 >= 150 (s, s-1, s-2 if under 60 A..AAA outs in s) AND complete reg_K, reg_BB, reg_GB, reg_XB for s; else prior. Non-stat rows: MLE and mERA features NaN.
- MLE features: reg_K, reg_BB, reg_HBP, reg_HR, reg_GB, reg_XB; Marcel blend_* (3:2 by MLE BF) and delta_* (s minus s-1), b5's pattern.
- mERA: mera_cv, mera_cv_blend, mera, mera_blend from pitch_mera_player_season (stat rows only).
- Pace: levels_climbed_s, repeated_level. Body: height_in (feature), weight_lb (display, Q15).
- Draft: refactor b5's inline draft block into `draft_features(snap)` in b5_features.py, used by both; hitter features.parquet must be `.equals` before/after `run.py b5`. Add hs_draftee from draft school_class (NaN without a record).
- il_2026: count and max il_days for 2026 rows (display only).
- Labels: reached_mlb, debuted, eta_years, war_6yr (pitch_war_target), split train_era (<= 2017) / censored (<= 2025) / score (2026).
- run.py: "b20" after "b19".

## Task 2: P(SP) (S24), column p_sp, data/b20_psp.json
- Label: debut year D in 2016-2025; is_starter = sum(GS)/sum(G) over MLB seasons D and D+1 > 0.5. Row = latest stat snapshot with s < D.
- Features: blend_GS_share, blend_outs_per_G, blend_pitches_per_G, reg_K, reg_BB, reg_GB, age, level_num; StandardScaler + median imputer + LogisticRegression(C=1).
- Report GroupKFold(5) OOF log loss, AUC, base rate, n. Fit on all, write p_sp to stat rows. Display only, never a model feature.

## Task 3: C15 mERA gate, data/b20_c15.json
- Mirror b12_select.evaluate on group == stat, s <= 2012, not debuted. `pitch_X(df, extra=())` in b20 (B22 reuses it): level_num, age, age_vs_level, pro_years, log1p(BF_s, BF_highest, career_milb_bf), blend_reg_* (6), delta_reg_K, delta_reg_BB, blend role (3), levels_climbed_s, height_in, one-hot throws and highest_level.
- P(MLB) b6 `_lgb_cv`; WAR ridge `_linear("war")` on reached, non-censored, non-pre2005 training-fold rows; GroupKFold(5) by player.
- Baseline vs + ["mera_cv_blend"] and vs + ["mera_cv"]. Keep if log loss or EV Spearman improves without the other worsening beyond LL_TOL .002 / SP_TOL .005. Only mera_cv columns (never final mera).
- Docstring states the mild leakage: mera_cv was fit on target seasons <= 2012, the same window.

## Tests: tests/test_b20.py
Unique keys; complete reg_ on stat rows; no rookie-ineligible rows; prior rows NaN MLE/mERA; p_sp in [0, 1] on stat rows only; c15 json has both candidates with boolean keep; split values; one known prospect spot check.
