# Changing the methodology

Every methodology choice you are likely to tweak is one line in `pipeline/config.py`. Dollar assumptions are rows in
`data/manual/dollar_params.csv`. Change the value, rerun from the step named below, run the tests, and log the change in
`docs/handoff.md` (what changed, why, before/after numbers).

```bash
.venv/bin/python run.py --from b6
```

`--from bX` runs bX and every later step in `run.py`'s ORDER. Single steps still work (`run.py b8 b9`).
b19 (mERA, about 40 minutes of PyMC) is skipped automatically when its inputs and code are unchanged (fingerprint in
`data/b19_cache.json`); delete that file to force a refit.

| What you want to change | Where | Rerun from | Tests that guard it |
|---|---|---|---|
| Hitter / pitcher WAR split (590/410) | `config.POS_WAR_PER_2430`, `PITCH_WAR_PER_2430` | `--from b2` | test_b2, test_b17 (season sums), test_b24 (C19) |
| SP vs RP replacement gap | `config.SP_RP_GAP` | `--from b17` | test_b17 |
| Translation pair thresholds | `config.MIN_PAIR`, `MIN_PAIR_CROSS` | `--from b18` (pitchers) / `--from b4` (hitters) | test_b4, test_b18 (C10, C16) |
| Regression to the mean | `config.K_STAB_HIT`, `K_STAB_PITCH` | same as above | test_b4, test_b18 |
| Stat vs prior group cutoffs | `config.STAT_MIN_PA`, `STAT_MIN_BF`, `STAT_SHORT_OUTS` | `--from b20` / `--from b5` | test_b5, test_b20 |
| Season blend weights (3:2) | `config.BLEND_WEIGHTS` | `--from b20` / `--from b5` | test_b5, test_b20 |
| Pitcher population, rookie eligibility | `config.PITCHER_MIN_BF`, `ROOKIE_MAX_MLB_OUTS` | `--from b20` | test_b20 |
| Training windows | `config.SELECT_CUTOFF`, `FIT2017_CUTOFF`, `FINAL_CUTOFF`, `WAR_CUTOFF_*` | `--from b22` / `--from b6` | test_b6, test_b22 |
| Tracked contact: xwOBA-only vs blend | `config.CONTACT_XWOBA_ONLY`, `CONTACT_MIN_AAA_BIP` | `--from b21` | test_b21, test_b22 |
| Two-way thresholds | `config.TWO_WAY_MIN_PA`, `TWO_WAY_MIN_BF` | `--from b24` | test_b24 |
| $/WAR, inflation, minimum, arbitration shares, discount | `data/manual/dollar_params.csv` | `--from b8` | test_b8, test_b24 |
| v3 projection: Marcel weights, regression, playing time | `config.MARCEL_WEIGHTS`, `REGRESS_PA`, `REGRESS_OUTS`, `PT_HIT`, `PT_PITCH`, `C23_MAX_RATE_BIAS` | `--from b29` | test_b29 (C23 in data/b29_c23.json), test_b31 |
| v3 projection horizon | `config.PROJ_FIRST`, `PROJ_YEARS` | `--from b29` | test_b29, test_b31 |
| v3 arbitration model holdout split | `config.ARB_HOLDOUT_FIRST` | `--from b30` (re-opens its holdout) | test_b30 |
| v3 trade rules: 40-man limit, tax line | `config.ROSTER_MAX`, `CBT_THRESHOLD_2027` | `--from b32` | test_b31 |
| v3 option/arb/pre-arb year rules | `contract_years()` in `pipeline/b31_mlb_value.py` | `--from b31` | test_b31 |
| Add a feature to the pitcher model | `PITCH_NUM` in `pipeline/b20_pitch_features.py` (`pitch_X`) | `--from b20`; gate it like C15 (`b20.evaluate`) | test_b20, test_b22 |
| Add a feature to the hitter model | `S15_KEPT` / `stat_X` in b5/b6 (gate with b12) | `--from b5` | test_b5, test_b12 |

Rules that keep a change honest (from the spec, still binding):
- Choose on s <= 2012 grouped CV only. The 2013-17 and 2018-19 holdouts have been opened (hitters 6 and 2 times, pitchers
  once); a change judged on them is tuned to them. Say so if you look.
- Feature groups go in or out whole, through a gate (C15 pattern: improve one metric, worsen neither).
- `run.py` rebuilds are deterministic: after a no-op change, `git status site/` shows nothing.
- `SELECT_CUTOFF` and `FIT2017_CUTOFF` also define the holdout windows (s+1 .. 2017 and 2018-19 in b6/b22). The
  holdout scorers keep their own pre-registered windows (`HOLDOUTS` in b7_backtest.py and b23_pitch_holdout.py); moving a
  cutoff means re-defining a holdout, so change those deliberately and say so.
- b19's PyMC fit is seeded but not bit-reproducible across refits (parallel chains, compiled BLAS): mERA moves by about
  .01 and the C15 log-loss gain by about .001 between refits. The cache is what keeps a rebuild byte-identical. mERA is
  display only (C15 failed), so a refit never moves P(MLB), WAR or dollars.
