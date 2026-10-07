# Audit fix plan (v1.1)

Source: audit of 2026-10-06 (findings #1-#12 plus hygiene, H). Decisions settled with the user in a grill-me interview on 2026-10-06.
Executed by Claude in this repo, one step at a time in the order below. Each step gets one commit with its tests, and `docs/handoff.md` is updated after each.
The site is not public, so everything ships as a single release at the end (R10).

## Decisions

| ID | Decision | Fixes |
|---|---|---|
| D-1 | Players who have already debuted stay on the board with P(MLB) = 1. Control year 1 is their real debut season, and their remaining WAR = war_mean x the control-year shares they haven't used yet. Their MLB samples (< 130 AB) are not model inputs. | #1 |
| D-2 | Training rows with debut_year <= s are excluded from every model. ETA is redefined as debut - s >= 1, so there is no off-by-one. | #1, #2 |
| D-3 | Pre-registration: every modeling decision is made on s <= 2012 GroupKFold CV. The fix list and expected directions go into the spec before any rerun. Then one look at 2013-17 (disclosed as the 5th look; A12 was chosen after seeing the holdout) and one look at a fresh 2018-19 holdout. | #3 |
| D-4 | BABIP leaves the models and the driver families. Raw and park-neutral BABIP stay on cards as display only. | user concern |
| D-5 | Each rate is regressed toward its source league-season mean in raw units first, then translated (the current order makes the reg_ features mostly encode level). | #4, BABIP finding |
| D-6 | Translation factors use same-season pairs plus cross-season pairs (L in s -> L+1 in s+1, >= 300 PA each), with aging removed using repeater drift by age bucket. | #4 |
| D-7 | Surplus is floored at 0 in each control year and integrated over the player's WAR distribution. One WAR draw per player is spread across years by the profile (years fully correlated; slightly understates non-tender value). | #5 |
| D-8 | Per-player spread: ridge for the mean plus a variance model predicting the OOF residual scale from the features. Distribution = mean + scale x pooled standardized residual quantiles. | #5 |
| D-9 | A discrete-time hazard model of debut replaces both the P(MLB) and ETA models. Censored 2018-2025 snapshots count for the years they have observed. P(MLB) = 1 - S(9 years); the ETA distribution comes from the same curve. | #6, #2 |
| D-10 | The final E[WAR \| reached] model trains on s <= 2015 (under 2% censored) instead of s <= 2017. | #11 |
| D-11 | Batting run values = BaseRuns partial derivatives at league totals, per season. | #7 |
| D-12 | Career-history features use backfilled 2000-04 MiLB seasons. Snapshots still start in 2005. | #9 |

## Steps

Dependency order: data -> WAR -> MLE -> features -> models -> value -> evaluation -> site. Every step that changes model inputs is judged on s <= 2012 CV only; the holdout is opened only in R9.

### R0 Pre-registration (spec only, no code)
- Record D-1..D-12 in `milb-hitter-value-spec.md` as dated user decisions. New IDs: A13 hazard model, A14 BaseRuns weights, A15 per-year floor, A16 variance model, S16 handling of debuted players, Q17 2000-04 backfill.
- Add success criteria:
  - **C10 level-step test.** For players with a full season at L in s and a full season at L+1 in s+1, the mean MLE change minus the change for repeaters at L (same age bucket) is within +-1 SE for K, BB and ISO at every step (A->A+, A+->AA, AA->AAA).
  - **C11 subgroup coverage.** WAR 10-90 coverage is 0.80 +- 0.05 on s <= 2012 CV within each of: age-vs-level tercile, level group, and predicted-WAR quintile.
  - **C12 fresh holdout (2018-19).** P(MLB) log loss and calibration deciles; Spearman of EV against WAR accumulated through 2026 within each snapshot year; 2018 six-year WAR on the complete-window subset only, labeled fast risers.
  - **C4** is restated for the hazard model.
- Write down the expected direction of each change (e.g. lower-level MLEs rise; HR-heavy hitters' WAR falls; already-debuted players' EV rises). Commit before R1.

### R1 Data and hygiene (b1, common)
- D-12: pull 2000-04 MiLB batting. First check whether the repo release has 2000-04 files; if not, use the Stats API per team per sportId, as the 2025-26 pull does. If neither source covers it, stop and ask (the fallback is masking the features as missing). The data is used only for career history; `milb_player_seasons` gains a `history_only` flag, or the backfill goes to a separate file.
- #10: extend `DRAFT_YEARS` back to the earliest year the draft endpoint serves (target 1990), so pre-2005 draftees stop being labeled `international`. Rename the flag's meaning to "no draft record" on the methodology page; undrafted US free agents still land there.
- H: make cache freshness explicit. `api_get(..., refresh=True)` for endpoints whose answers change (people/debut dates, current-season stats); `run.py --refresh` re-pulls them. Record the pull date in `players.parquet` and the site JSON.
- H: B5 draft record = latest with draft_year <= s (match the code to the docstring). Rename `spearman_ba` to `spearman_list`.
- Tests: pre-2005 draftees are not `international`; the cache refresh re-fetches people.

### R2 WAR (b2)
- D-11: BaseRuns per season from league totals (A = H + BB + HBP - HR - .5 IBB, B = (1.4 TB - .6 H - 3 HR + .1 (BB + HBP - IBB)) x 1.02, C = AB - H, D = HR). Run value per event = partial derivative at league totals; rescale so league runs match actual, as now. Keep the wOBA scale-to-OBP convention.
- Check: HR/1B and 3B/1B ratios fall within 10% of the standard wOBA ratios (about 2.3 and 1.8) every season.
- Rerun C1. Report the offense-only r as the headline and label the full-WAR r as partly shared by construction (#12).

### R3 MLE translations (b4)
- D-5: reg_ = translate(raw regressed toward the source league-season mean, using the stabilization k). The regression prior no longer depends on level after translation.
- D-6: cross-season pairs with aging correction. Repeater drift per age bucket (<=21, 22-23, 24-25, 26+), estimated from same-level s -> s+1 pairs, is divided out of the cross-season upper rate. Pair weights and the shrinkage hierarchy are unchanged.
- Gate: C10. If it fails, report it and try cross-season pairs only before moving on (that was the second choice in D-6).
- Rerun the B4 out-of-sample RMSE table.

### R4 Features (b5)
- D-2: drop debut_year <= s rows from training splits. Keep them in score rows with a `debuted` flag.
- D-4: remove reg_/blend_/delta_BABIP from `STAT_NUM`. Keep BABIP columns in features for display.
- #8: build the position transition matrix per fit cutoff (backtest <= 2012, final <= 2017) and compute p_C/p_SS/p_CF/exp_pos_runs per fit. Either store both column sets or compute them in b6. Fix the doc so it says stat-group rows only.
- D-12: recompute pro_years, career_milb_pa and the pace features on the 2000-04 + 2005+ history.
- Rerun B12/C9 on the new baseline (CV only) to confirm the kept S15 groups. Update S15_KEPT if the decisions change.

### R5 Models (b6)
- D-9 hazard model. Person-period rows: one per snapshot x year t = 1..9 after s while not yet debuted and t is observed (s + t <= 2026). Target: debut in s + t. Features: the stat features plus t (one-hot). Candidates: logistic (with t interactions) vs LightGBM, chosen by s <= 2012 CV log loss on person-periods.
  - Outputs: P(MLB) = 1 - prod(1 - h_t) for t = 1..9, and P(debut = s + t).
  - Censored 2018-2025 snapshots enter the final fit only, and only for observed years.
  - Calibration (C4) checked on CV. Platt is applied to the hazard only if CV shows a gap.
  - The prior group (S8) gets the same hazard form with prior features.
- D-10: final WAR ridge trains on s <= 2015. The backtest WAR fit stays s <= 2012.
- D-8 variance model: fit a model of log |OOF residual| (ridge or small LightGBM, chosen by CV pinball loss at q10/q50/q90). Pooled standardized-residual quantile table. Gate: C11. Replaces `binned_resid`.
- Drivers: P(MLB) drivers come from the hazard model. Family attribution is unchanged except that "Contact quality" is removed.

### R6 Value (b8)
- The arrival distribution comes from the hazard probabilities directly (Poisson and the +1 removed).
- D-7: sample N = 2,000 WAR draws per player from D-8, allocate by control-year share, compute max(value - salary, 0) per year, discount and average. EV = sum over arrival years of P(debut year) x E[floored surplus].
- D-1: debuted players get p = 1 and control years starting at the debut season. Years before 2027 are sunk; they get the remaining shares x war_mean draws.
- Tests: EV >= 0 for every player; for two players with equal mean, the wider spread gives EV at least as high; for a debuted player, EV equals the remaining-years surplus.
- Rerun the $/WAR growth sensitivity table.

### R7 Batted-ball layer (b11)
- Rerun as is. S14's BABIP half no longer feeds a model input; the C8 report says so. S14 stays off unless C8 passes.

### R8 Backtest code (b7)
- Add C12: a 2018-19 population, the WAR-through-2026 target, and the 2018 complete-window subset.
- The bootstrap CIs stay. The top-100 comparison stays on 2014-18 lists (2019-20 Pipeline lists can be added for C12 if they can be collected the same way; optional, decided at R8).

### R9 The single evaluation
- Run the full pipeline once. Report C2, C3, C4, C10, C11 and C12 exactly as they come out, with no tuning afterward.
- Compare each result to the R0 expected directions. Explain any surprise; do not fix it.

### R10 Site and methodology (b9, app.js)
- Cards: debuted players get a badge ("in MLB, rookie-eligible") plus remaining control years; the P(MLB) curve and ETA come from the hazard model; there is no BABIP driver; spread and floor are explained.
- Methodology disclosures:
  - Holdout history (5 looks; A12 was holdout-driven).
  - Fresh 2018-19 results.
  - BABIP ablation (log loss +0.0009, r = .11 with next-year MLB BABIP).
  - C1 partly circular.
  - Era-shift handling.
  - 2000-04 backfill.
  - The "no draft record" definition.
  - Cache pull date.
- Rerun C6 (smell test) on the new board and C7 (phone width).
- Rebuild and commit `site/`.

## Finding -> step map

| Finding | Step |
|---|---|
| #1 already-debuted players | R4, R5, R6, R10 |
| #2 ETA off-by-one | R5, R6 |
| #3 holdout reuse | R0, R9, R10 |
| BABIP | R3, R4, R10 |
| #4 MLE harshness | R3 |
| #5 ceiling and floor | R5, R6 |
| #6 era shift | R5 |
| #7 linear weights | R2 |
| #8 transition-matrix leak | R4 |
| #9 left-censored history | R1, R4 |
| #10 international flag | R1 |
| #11 truncated WAR training | R5 |
| #12 C1 circularity | R2, R10 |
| H cache, docstrings, naming | R1 |

## Left unchanged
- `HARNESS.md` (untracked, user's file): not touched.
- The bWAR fetch user agent: left as is (one cached download); noted here only.
- X1-X7 scope exclusions are unchanged.
