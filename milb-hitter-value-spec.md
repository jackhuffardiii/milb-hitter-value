# MiLB Hitter Value (v1)

A stats-based projection system that puts a surplus dollar value on every A through AAA hitter, with a full audit trail from minor league line to dollars. It exists so I can cite a concrete, defensible number when an MLB questionnaire or job application asks me to value a player.

Status: approved 2026-10-06. Decided via grill-me interview, 2026-10-06. S13, S14 added after PBP tracking coverage check. v1.1 revision (audit 2026-10-06, user decisions, plan in docs/fix-plan.md): S16, A13-A16, C10-C12, Q17, R0-R10; S6, S7, S8, S10, A7, A12 amended. Pre-registered before any rerun.

## Problem

- **P1** I have no defensible, public way to value a minor league hitter. Questionnaires ask for exactly this, and an answer without a method behind it reads as a guess.
- **P2** The source repo (armstjc/milb-data-repository) has raw MiLB stats but no ages, no MLB outcomes, and no translations. Its 2025 season files stopped updating on 2025-05-01, and some rate columns are internally impossible (2024 AA Jake Thompson: .324 AVG, .075 OBP).

## Users

- **U1** Me, citing player cards and the methodology in MLB questionnaires, job applications, and portfolio links.
- **U2** Front office reviewers reading the site cold. They must be able to trace any number back to its inputs.

## v1 scope

- **S1** Data layer: repo season batting files 2005 to 2024 (all levels), MiLB 2025 to 2026 pulled from the MLB Stats API, mid-season stints aggregated, all rate stats recomputed from counting stats.
- **S2** Player bio and acquisition: birthdate, bats, MLB debut date from the Stats API people endpoint; draft round, pick, and signing bonus from the draft endpoint.
- **S3** MLB outcomes: MLB season batting and games by position, 2005 to 2026, from the Stats API.
- **S4** Simplified in-house WAR: wOBA-based batting runs, park adjusted, plus baserunning runs (wSB from SB/CS, and GIDP runs vs league rate), fielding runs (Baseball-Reference runs_field, DRS-based, 2005 to 2026), positional adjustment and replacement level. Validated against bWAR. Baserunning added 2026-10-06 (user decision); extra-bases-taken baserunning not included (needs MLB play-by-play). Fielding added 2026-10-06 (user decision; reverses X2).
- **S5** Environment adjustments: park factors from MLB Stats API team home/road splits (MiLB and MLB, 2005 to 2026; 3-year window, regressed by reliability-derived k), and league-season translation factors from matched pairs, chained level to level up to MLB. Changed from PBP during B3: PBP ends May 2025 and could not cover the 2026 snapshot.
- **S6** MLEs: MLB-equivalent K%, BB%, ISO, BABIP for every player-season, regressed by sample size.
- **S7** Three models trained on 2005 to 2017 snapshots: P(reach MLB), E[WAR in first 6 MLB seasons | reached], and ETA (years to debut | reached). Features: MLEs, age relative to level, highest level, projected MLB position, year-over-year trajectory.
- **S8** Prior for players with no A-or-above sample (Rookie, DSL, pre-2021 A-): P(MLB) and E[WAR] from draft slot and bonus, flagged low confidence.
- **S9** Backtest on held-out 2013 to 2017 snapshots: model vs preseason top-100 ranks published the following spring (lists 2014 to 2018; headline), plus a naive age-vs-level + OPS baseline across the full population.
- **S10** Surplus $ model: market $/WAR with annual inflation, league minimum for 3 pre-arb years, arb at 40/60/80% of value, 8% discount rate, cash flows starting at projected ETA.
- **S11** Static site: leaderboard, one card per player (stats, MLEs, P(MLB), E[WAR], ETA, surplus $ with 10/50/90 range, top drivers), and a methodology page with the backtest and bWAR validation.
- **S12** 2026 offseason snapshot run and published.
- **S13** Batted-ball context on player cards: avg and 90th pct exit velocity, hard-hit rate, launch angle, barrel rate, where tracked (AAA 2023+, Low-A FSL parks 2021+). Display only; no effect on the projection.
- **S14** Batted-ball input adjustment: for tracked AAA and Low-A FSL hitters, replace observed ISO and BABIP with expected values from EV/LA, blended toward observed by sample size, before they enter the MLE and model chain. Ships only if it passes C8.
- **S16** Players who already debuted but are still rookie-eligible (under 130 MLB AB) are kept on the board with P(MLB) = 1 and a real control clock: control year 1 is their debut season, years before the snapshot+1 are sunk, remaining WAR = E[WAR] x unused control-year shares. Their MLB samples are not inputs. They never appear in training rows (debut_year <= s is excluded), so P(MLB) and ETA learn only from players not yet in MLB. Added v1.1.
- **S15** Extra model features, added 2026-10-06: (1) contact rate (1 - whiffs/swings) and swing rate; (2) batted-ball mix GB%, FB%, LD%, PU% from repo out and hit types; (3) speed: SB attempt rate per time on first, triples rate; (4) position mix: share of games at SS, CF, C; (5) progression pace in games: games at current level, career games below current level per level climbed (ascent pace), levels climbed this season, repeated level (pace partly encodes org scouting judgment; stated on the methodology page); (6) height and weight. Each kept only if it improves train-era CV (C9).

## Explicitly out of scope

- **X1** Pitchers. v2.
- **X2** Minor league fielding as a model input (only crude PO/A/E exists before Statcast). MLB fielding runs moved into S4 on 2026-10-06: Baseball-Reference publishes them for every season, so the original "no free source before 2016" premise was wrong.
- **X3** In-season or weekly refresh, and any live backend.
- **X4** International signing bonus data. No free source.
- **X5** Similarity comps on player cards. Candidate for v2.
- **X6** Real service-time modeling (options, Super Two, manipulation).
- **X7** Scouting grades or prospect ranks as model inputs. Ranks are the benchmark, so they stay out of the features.

## Approach

- **A1** Value means surplus $ over team control. It is the front office framing and maps directly to questionnaire prompts.
- **A2** Target is P(MLB) x E[WAR in first 6 MLB seasons]. Seasons stand in for control years; simple and stated openly.
- **A3** Train on 2005 to 2017 snapshots only. Later classes have censored MLB outcomes and would look like failures.
- **A4** Own simplified WAR instead of bWAR/fWAR. bWAR supplies the fielding component only (from 2026-10-06); its total WAR is a validation check.
- **A5** MLEs via matched pairs (same player, adjacent levels, same or consecutive season), chained to MLB, at league-season grain plus park. Handles PCL parks and era shifts (2021 restructure, ABS, pitch clock, ball changes) without separate era logic.
- **A6** Models: logistic/linear baselines and LightGBM, pick per model by backtest. SHAP values give per-player drivers for the card.
- **A7** Uncertainty: P(MLB) shown directly; WAR range from quantile models or empirical residuals, carried through to a 10/50/90 surplus $ range.
- **A8** Python: pandas + DuckDB, parquet intermediates, scikit-learn + LightGBM. Pipeline writes JSON; static HTML/JS site renders it.
- **A9** Offseason snapshot, rerun by hand. No scheduler.
- **A11** Tracking data improves inputs, not the model. No 2005 to 2017 training row has EV/LA, and 2021+ players have no 6-year outcomes until about 2030, so EV/LA cannot be a model feature. S14 sharpens the ISO/BABIP the trained model already uses.
- **A12** WAR model selection ranks candidates by Spearman of predicted vs realized WAR among reached players (train-era CV), not RMSE, because valuation is a ranking problem. Changed 2026-10-06 after B7: RMSE selection picked a LightGBM whose noisy ranks lost to the naive baseline; train-era CV favored ridge.
- **A13** P(MLB) and ETA come from one discrete-time hazard model of debut: one row per snapshot x year t = 1..9 after s while not yet debuted and observed (s + t <= 2026). P(MLB) = 1 - prod(1 - h_t); P(debut = s + t) from the same curve. Censored 2018-2025 snapshots enter the final fit for their observed years, so post-2021 data shapes the early hazards. ETA >= 1 by construction. Replaces the separate P(MLB) classifier, Poisson ETA, and Platt recalibration (calibration applied only if CV shows a gap). v1.1.
- **A14** Batting run values per season are the partial derivatives of BaseRuns at league totals (replaces team-run OLS, which overweighted HR and 3B). Still our own WAR (A4). v1.1.
- **A15** Surplus is floored at 0 per control year (demote/release in pre-arb, non-tender in arb) and integrated over the player's WAR distribution; one draw per player spread across years by the control-year profile. v1.1.
- **A16** WAR uncertainty: ridge mean plus a variance model of the OOF residual scale from the features; distribution = mean + scale x pooled standardized residual quantiles (replaces prediction-quintile residual bins, which gave equal spread to equal means). v1.1.
- **A10** Projected MLB position from a historical transition matrix (MiLB position mix to MLB primary position), so shortstops slide down the spectrum at realistic rates.

## Data

| ID | What | Source | Lives in |
|---|---|---|---|
| D1 | MiLB season batting 2005 to 2024 | repo release `season_player_batting` | `data/raw/milb_batting/` |
| D2 | Repo PBP: not used. Measured coverage only (tracking starts 2021). Superseded by D11 during B11. | n/a | n/a |
| D3 | MiLB season batting 2025 to 2026 | MLB Stats API | `data/raw/statsapi/` |
| D4 | Player bio (birthdate, bats, debut) | Stats API `/people` | `data/players.parquet` |
| D5 | Draft picks and bonuses | Stats API `/draft/{year}` | `data/draft.parquet` |
| D6 | MLB batting + games by position 2005 to 2026 | Stats API | `data/mlb_seasons.parquet` |
| D7 | bWAR (validation only) | Baseball-Reference `war_daily_bat` | `data/raw/bwar.csv` |
| D8 | Preseason top-100 lists 2014 to 2018 (MLB Pipeline; BA paywalled) | hand collected from mlb.com, matched to MLBAM IDs | `data/manual/top100.csv` |
| D9 | $ model parameters with citations | public sources at build time | `data/manual/dollar_params.csv` |
| D11 | MiLB Statcast balls in play 2021 to 2026 (AAA, Low-A FSL), server-filtered to batted balls | Baseball Savant minors CSV, per day | `data/raw/savant/` (one parquet per day) |
| D12 | MiLB swings/whiffs 2026 (contact rate) | repo season files refreshed 2026-10-01; 2025 unavailable (repo stopped 2025-05, API lacks swings) | merged into `data/milb_player_seasons.parquet` |
| D10 | Published outputs | pipeline | `site/data/*.json` |

## Success criteria

- **C1** Simplified WAR correlates with bWAR at r >= 0.85 on MLB player-seasons with 300+ PA. Gaps explained by fielding/baserunning, documented.
- **C2** Backtest runs end to end on 2013 to 2017 holdout and reports Spearman vs realized 6-year WAR for both the model and BA rank. v1 ships whether the model wins or loses; the result is stated plainly.
- **C3** Model beats the naive age + OPS baseline on log loss for P(MLB) and on Spearman for E[WAR], full holdout population.
- **C4** P(MLB) calibration within 5 points per decile on holdout.
- **C5** Every number on a player card traces to inputs shown on that card. One command rebuilds data, models, and site JSON from scratch.
- **C6** 2026 top 50 passes a manual smell test against current public top-100 lists, with disagreements explained by drivers.
- **C8** S14 gate: on AAA 2023 to 2025, expected ISO/BABIP predict next-season ISO/BABIP better (lower RMSE) than observed, and AAA batted-ball metrics predict MLB results for 2023 to 2025 arrivals at least as well as AAA outcomes. If it fails, S14 is dropped and the methodology page reports the null result.
- **C9** S15 gate: each feature group is kept only if adding it improves train-era (s <= 2012) GroupKFold OOF metrics: P(MLB) log loss or ev Spearman, without worsening the other. Decided before any holdout rerun; the 2013 to 2017 holdout is evaluated once afterward.
- **C10** Level-step test (v1.1): for players with a full season (>= 300 PA, one level) at L in s and at L+1 in s+1, mean MLE change minus mean change of same-level repeaters (same age bucket) is within +-1 SE for K, BB, ISO at A->A+, A+->AA, AA->AAA.
- **C11** WAR 10-90 coverage 0.80 +- 0.05 on s <= 2012 CV within each age-vs-level tercile, level group, and predicted-WAR quintile (v1.1).
- **C12** Fresh holdout 2018-19 snapshots (v1.1), evaluated once: P(MLB) log loss and calibration deciles; Spearman of EV vs WAR accumulated through 2026 within each snapshot year; 2018 six-year WAR on the complete-window subset only, labeled fast risers.
- **C7** Site is static, works at phone width, no horizontal scroll.

## Open questions and assumptions

- **Q1** International signees with no A-or-above sample get a population prior (no bonus data). They will cluster at a generic value.
- **Q2** "First 6 MLB seasons" approximates team control. September call-ups and demotions break the match.
- **Q3** Naive age + OPS baseline included alongside the top-100 benchmark.
- **Q4** All rate stats recomputed from counting stats; repo rate columns ignored.
- **Q5** Unit of analysis is one row per player per offseason snapshot. CV grouped by player so a player never appears in both train and test.
- **Q6** Benchmark: MLB Pipeline preseason top 100, all five years. Baseball America full lists are paywalled (403 on public archives). The methodology page states this.
- **Q7** Eligibility for stat projection: 150+ PA at A or above across the last two seasons, and still rookie-eligible (under 130 MLB AB). Everyone else falls to the S8 prior or is excluded.
- **Q8** MLB park factors for batting runs computed the same way as MiLB ones (home/road splits from Stats API), not borrowed from bWAR.
- **Q9** Hosting: static site deployed to Netlify after B10 (user decision, 2026-10-06).
- **Q10** $/WAR and arb percentages are pinned to cited public figures at build time; no number is fixed in this spec.
- **Q11** No PBP downloads. Savant serves batted balls only (~0.7 MB/day vs 5.3 GB of pitch-level PBP), cached per day so interrupted runs resume.
- **Q12** Name to MLBAM ID matching for top-100 lists rejects ambiguous matches instead of guessing; unmatched names are listed.

- **Q13** Confirmed 2026-10-06: Baseball Savant minors CSV serves AAA and FSL batted balls for 2021 to 2026 with real event outcomes.
- **Q14** Cards flag when S14 was applied, since tracking coverage depends on organization (FSL affiliates only at Low-A).
- **Q15** Height and weight are current values from the people endpoint, not as of each snapshot. Mild look-ahead leak; stated on the methodology page.
- **Q17** Career-history features (pro_years, career PA, pace) use backfilled 2000-2004 MiLB seasons; snapshots still start in 2005. Draft records are pulled back to the earliest year served so pre-2005 draftees are not flagged as having no draft record. v1.1.
- **Q18** Holdout history (v1.1): 2013-2017 was evaluated four times before v1.1 (B7, B6r, B8 revision, B14) and A12 was chosen after a holdout result. All v1.1 decisions are made on s <= 2012 CV; 2013-17 gets one more (5th) look and 2018-19 its first, both reported as they come out. Expected directions are pre-registered in docs/fix-plan.md.
- **Q16** 2025 contact and swing rates are unavailable. The 2026 snapshot uses 2026 values alone (no 2-year blend), the same treatment as 2021. No game-feed pull (~3 GB) for one prior season.

## Build order

- **B1** Data layer: D1, D3, D4, D5, D6 pulled, stints aggregated, rates recomputed, sanity checks. Runnable: one command produces the clean player-season table. (M)
- **B2** Simplified WAR + bWAR validation (C1). (M)
- **B3** Park factors from PBP (D2), MiLB and MLB. (M)
- **B4** Matched-pair translations and MLEs. (L)
- **B5** Position transition matrix and feature table. (S)
- **B6** P(MLB), E[WAR], ETA models plus S8 prior. (M)
- **B11** Batted-ball layer: S13 metrics from repo PBP (D2) and Savant (D11), expected ISO/BABIP fit, C8 tests. Runs after B6, before B7. (M)
- **B13** Baserunning runs in oWAR (S4): wSB and GIDP runs, rerun bWAR validation. (S)
- **B12** S15 features: B1 keeps out/hit types and height/weight; game-feed pitch calls for 2025 to 2026; B5 features; C9 selection. (M)
- **B6r** Refit B6 with A12 selection and kept S15 features; rerun B11 and B7 once. (S)
- **B7** Top-100 collection (D8) and backtest (C2 to C4). (M, mostly manual)
- **B8** Surplus $ model. (S)
- **B9** Static site and methodology page. (M)
- **B10** 2026 snapshot run, smell test (C6), publish. (S)

## v1.1 revision (audit 2026-10-06)

Amendments: S6 regresses each rate toward its source league-season mean before translating, and translation pairs add cross-season pairs (L in s -> L+1 in s+1, >= 300 PA each) with aging removed by repeater drift. S7 drops BABIP features (train-era ablation: log loss +0.0009, Spearman -0.0015; MLE BABIP r = .11 with next-year MLB BABIP); BABIP stays on cards as display. S7 position transition matrix is fit per fit cutoff (no holdout leak). S8 prior uses the A13 hazard form. S10 uses A13 arrival probabilities and A15. A7 per A16. A12 final WAR model trains on s <= 2015 (under 2% censored).

Pre-registered expected directions: lower-level MLEs rise relative to AAA; HR-heavy hitters' WAR targets fall slightly; already-debuted players' EV rises (p = 1) while their remaining control years fall; prospect ETAs shorten by about half a year vs v1 B8; EV rises most for high-spread (young, low-level) players under the floor; P(MLB) at A/A+ for 2026 moves toward the post-2021 base rate; holdout Spearman changes are expected within +-0.03 and are reported whichever way they go.

- **R0** Pre-registration (this section). **R1** Data/hygiene (Q17, cache refresh). **R2** A14. **R3** S6/C10. **R4** features (S16 exclusion, BABIP, transition leak, Q17). **R5** A13, A16, A12 cutoff. **R6** S10/A15/S16. **R7** B11 rerun. **R8** C12 code. **R9** single evaluation. **R10** site and methodology disclosures.
