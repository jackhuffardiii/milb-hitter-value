# B22 implementer report (2026-10-10)

Not committed. Spec: docs/b22-spec.md.

## Changes
- `pipeline/b6_models.py`: smallest generalization. Added `WAR_TARGET` (default `war_target.parquet`) as an argument to `_war_mask`, `select_stat` and `fit`. `select_stat` also takes `kind` and builds X from `XFN[kind]`. Added `SPREAD = {"stat": SPREAD_FEATS}`; `_spread_F` uses `SPREAD[kind]` when there is an entry, otherwise `XFN[kind]` (for prior that is still prior_X). `low_confidence` is now `kind.endswith("prior")`.
- Hitter outputs are unchanged. I backed up predictions.parquet, drivers.parquet and b6_metrics.json to $TMPDIR, reran `run.py b6`, and compared: predictions `.equals` True, drivers `.equals` True, json content equal True.
- `pipeline/b22_pitch_models.py` (new) registers `pitch_stat` (B20 `pitch_X`, no extra columns) and `pitch_prior` in b6's `XFN`, and `pitch_stat` spread features in `SPREAD`. To use b6's `predict`/`drivers` on pitcher models, B8 has to `import pipeline.b22_pitch_models` first.
- `run.py`: b22 is registered right after b21.
- `tests/test_b22.py`: the spec'd checks.

## Selection (stat s<=2012 GroupKFold(5) CV)
| | linear | LightGBM | chosen |
|---|---|---|---|
| hazard person-period log loss (79,474 periods) | 0.11171 | 0.11179 (230 trees) | linear |
| WAR OOF Spearman (2,687 rows) | 0.240 | 0.210 (91 trees) | linear |

Prior: linear (fixed).

## Spread (A16, chosen in backtest fit) and C11
- stat: CV pinball const .638 / ridge .582 / **lightgbm .578**. Overall coverage .805, every cell in [.75, .85]. **C11 passes.**
- prior: const .712 / **ridge .661** / lightgbm .666. Overall coverage .812. **C11 fails** only in the level_group "high" cell (.583). That cell has just 36 of 1,493 prior WAR rows, so it is a small sample. Hitter prior also fails C11.

## Calibration check (C4, s<=2012 CV)
- stat_backtest: max decile gap .013, no Platt (10,766 rows).
- prior_backtest: max gap .020, no Platt (14,927 rows).

## C18 (report only, chosen types, stat s<=2012)
| scheme | P(MLB) log loss (n) | WAR Spearman (n) |
|---|---|---|
| GroupKFold(5) OOF | 0.4403 (10,766) | 0.244 (2,687) |
| forward: train s<=2009, test 2010-12 | 0.4543 (4,158) | 0.184 (1,099) |

Forward chaining is somewhat worse on both metrics. That suggests some era drift, or the WAR sample is too small to say: n = 1,099, with the WAR model trained on only about 1.6k rows.

## Contact adjustment (S28): rows changed
Uses the regenerated pitch_contact.parquet, where xb_contact_adj = f(xwOBAcon) alone. The b22 run started after the file's 01:37 rewrite.

| 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| 187 | 282 | 264 | 265 | 304 |

Total 1,302 stat rows. Unadjusted values are kept in `reg_XB_raw` / `blend_reg_XB_raw`. These columns are only in the in-memory frame. pitch_features.parquet is not rewritten, so the card has to recompute them or B22 has to persist them; this is flagged under Gaps.

## Reach rate, pitchers vs hitters (train-era stat, not debuted)
Pooled age_vs_level tercile cuts: -8.5 / -1.19 / 0.34 / 12.2.

| level | tercile | pitcher rate (n) | hitter rate (n) |
|---|---|---|---|
| a | young | .422 (894) | .439 (1013) |
| a | mid | .226 (1373) | .191 (1235) |
| a | old | .105 (1709) | .076 (1670) |
| a+ | young | .410 (1141) | .440 (1177) |
| a+ | mid | .231 (2104) | .206 (1834) |
| a+ | old | .105 (1989) | .063 (1893) |
| aa | young | .528 (1679) | .533 (1673) |
| aa | mid | .277 (1860) | .237 (1678) |
| aa | old | .144 (1587) | .085 (1580) |
| aaa | young | .399 (2205) | .370 (1896) |
| aaa | mid | .210 (815) | .190 (778) |
| aaa | old | .147 (661) | .133 (588) |

Interpretation: young-for-level players reach at about the same rate in both groups. Pitchers who are average or old for their level reach more often than hitters, by up to 1.7x for old pitchers at AA and A+. Age-for-level is a weaker penalty for pitchers, which is consistent with relief roles giving older arms a path.

## Deviations / gaps
1. **Calibration check is backtest only.** b22_metrics.json `calibration_check` has only `stat_backtest` and `prior_backtest`. The fit2017 and final CV checks cover rows from s 2013-17, which conflicts with the spec's "only s<=2012 CV numbers" and the no-2013-19-metric rule. Their Platt decision still runs inside `fit` and is stored in each model's `recal_info`. No Platt was applied in the backtest fits; I did not inspect whether fit2017 or final applied one.
2. **XB_obs = 0:** 2 player-seasons across all years have >= 100 AAA BIP and zero extra-base hits, so the ratio is undefined. Those rows are left unadjusted.
3. **XB_obs source:** taken from B21's `aaa_contact()` (same definition: AAA rows, Mexican League excluded, (2B + 2*3B)/BIP). It is not recomputed.
4. **Prior "age_vs_level" in the hazard:** b6's `_hx` uses age x t when age_vs_level is absent, so the pitcher prior gets the age interaction, as the hitter prior does.
5. **`*_raw` columns are not persisted** (see contact adjustment above). If the card needs them, B22 could write them to pitch_predictions, or the card can recompute them.
6. **C18 GroupKFold** trains each fold's hazard on all not-debuted fold rows. All s<=2012 rows are fully observed, so this is the same as hazard_cv_check's setup. The forward-chained hazard trains on s<=2009 with debut outcomes through 2018, so it overlaps the test window in calendar time. The spec allows this.
7. No metric was computed on any 2013-19 prediction.

## Verification
- `run.py b22`: 33 s.
- `pytest -q`: 171 passed, 3 xfailed (166 before, plus 5 new).
- `run.py b6` rerun: hitter outputs identical.
- Other files in the tree that I did not touch: pipeline/b8_value.py (modified) and pipeline/b23_pitch_holdout.py (new).
