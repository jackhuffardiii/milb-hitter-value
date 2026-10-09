# MiLB Player Value (v2: pitchers)

Extends [MiLB Hitter Value (v1)](milb-hitter-value-spec.md) to pitchers, on one surplus-$ board shared with hitters. Everything in v1 not amended here carries over unchanged (data layer, park factors, matched-pair translations, A13 hazard, A15/A16 surplus and uncertainty, site structure). IDs continue v1's numbering.

Status: draft 2026-10-09. Decided via grill-me interview, 2026-10-09. Pre-registered before any pitcher model is fit (see Pre-registration).

## Problem

- **P3** v1 values only hitters, so it cannot answer the most common questionnaire comparison: hitter X or pitcher Y.
- **P4** v1 hitter WAR uses a fixed replacement level (20 runs per 600 PA). Its per-season total drifts from 639 (2014) to 549 (2026), while bWAR position-player WAR holds at 587 to 590 every season. On a combined board that drift would bias hitters against pitchers by era.

## v2 scope

- **S17** One comparable WAR and $ scale for hitters and pitchers: replacement level solved per season so position-player WAR sums to 590 and pitcher WAR to 410 per 2,430 MLB games (Baseball-Reference split; 2020 prorated to 60 games). Hitter WAR re-anchored and all hitter values restated in v2.
- **S18** Pitcher data layer: MiLB pitching 2005 to 2026 (2000 to 2004 history per Q17), MLB pitching 2005 to 2026, stints aggregated, rates recomputed from counts (Q4).
- **S19** Pitcher WAR: run values per event from the A14 BaseRuns partials for K, uBB, HBP, HR; non-HR balls in play valued at the league-season BIP mix plus observed 2B and 3B allowed at their run value above a single (contact term); park adjusted with B3 factors (pf_SO, pf_BB, pf_HR, pf_2B3B); SP and RP replacement levels per appearance; relief runs scaled by leverage, (1 + gmLI) / 2, with gmLI from bWAR; scaled to 410 per season. Unregressed: it measures value delivered.
- **S20** Pitcher MLEs: MLB-equivalent K%, BB%, HBP%, HR%, GB%, and ISO-on-contact allowed (extra bases per non-HR ball in play) via matched pairs (A5), regressed toward source league-season means by sample size.
- **S21** mERA (Majors-Equivalent Run Average): a predictive run-average stat on the ERA scale, built from MLE K%, BB%, GB%, and ISO-on-contact. Bayesian regression with level/league intercepts and level-varying slopes partially pooled across levels, fit to predict next-season MLE RA9. Likelihood (Gamma vs Normal) and varying vs fixed slopes chosen by s <= 2012 CV. Ported from the author's college pitching metric with the EV/LA contact grid replaced by ISO-on-contact, since no 2005 to 2017 row has EV/LA (A11).
- **S22** mERA ladder on the card: mERA at the pitcher's own level, translated to each level above it and to MLB with B4 chained factors. Display.
- **S23** Pitcher models, fit separately from hitters: A13 hazard for P(MLB) and ETA, E[WAR in first 6 MLB seasons | reached] with A12 selection and A16 variance model. Features: MLEs, mERA (gated, C15), age relative to level, highest level, throws, role (GS share, IP per game, pitches per outing), trajectory, progression pace, height and weight.
- **S24** P(MLB starter): logistic model on MiLB role features and MLEs, trained on 2016 to 2025 debuts; label is starts in a majority of MLB appearances over the first two MLB seasons. Card context only; not multiplied into value (realized role is already in the WAR target via S19).
- **S25** Eligibility: stat projection needs 150+ batters faced at A or above over the last 2 seasons (3 seasons if under 20 IP in the snapshot season) and rookie eligibility (under 50 MLB IP). Below that, a pitcher-specific draft prior (slot, bonus, HS vs college) in the A13 hazard form, flagged low confidence.
- **S26** Injury flag: injured-list placements in the snapshot season from Stats API transactions, shown on the card. Display only.
- **S27** Arsenal on pitcher cards, where tracked (AAA 2023+, Low-A FSL 2021+): per pitch family usage, velocity, spin, extension, whiff%. Display only.
- **S28** Tracking contact adjustment: for tracked pitchers, blend Savant xwOBA-on-contact allowed into the contact term by sample size before mERA and the model chain. Ships only if it passes C17.
- **S29** Two-way players: a player eligible in both pipelines (150+ PA and 150+ BF) gets both projections; board value is the sum, labeled "if both paths stick". Hitter-seasons with primary_pos_milb 'P' stay out of hitter training.
- **S30** Combined site: one leaderboard ranked by surplus $ with an All / Hitters / Pitchers filter and a role column; pitcher cards mirror hitter cards (stat lines, MLEs, mERA ladder, P(MLB), P(SP), ETA, WAR by season, surplus 10/50/90, drivers, arsenal, IL flag); methodology adds a pitcher section, the split sensitivity, and the drift test.
- **S31** 2026 offseason snapshot rerun for hitters and pitchers and published.

## Explicitly out of scope

- **X8** A custom hitter/pitcher WAR split. The split follows the market-consistent Baseball-Reference convention; sensitivity is reported instead (C19).
- **X9** Injury history as a model feature. MiLB IL coverage before about 2015 is uneven, so train-era and scoring-era inputs would differ.
- **X10** A Stuff+ model on MiLB pitch-level data. Needs GBs of pitch-level pulls and would still be display or adjustment only under A11. Candidate for v3.
- **X11** An explicit SP/RP mixture valuation. Splits a small training set three ways.
- **X12** Recency sample weights. Drift is handled by A19.
- **X13** pybaseball. It adds nothing v2 lacks (no MiLB support; `bwar_pitch` wraps the same Baseball-Reference download v1 already does for `war_daily_bat`).
- **X14** Renaming the Netlify site. Stays at milb-hitter-value.netlify.app so existing links work.
- **X15** Major leaguers and a trade simulator. V3, after v2 ships: it needs v2's shared 590/410 scale and pitcher values, since prospects are the currency in most MLB trades. Split into V3a (MLB player value: projections, aging, contracts, arb, service time, reversing X6) and V3b (trade simulator: MLB trade rules, contender win curve, port of the NBA Tradeability Index `shop.py`/`cba.py` browser pattern). Contract and service-time data is the feasibility gate; check it before a V3 spec. Reuse: `~/Projects/mlb-trade-web/public/data/trades.json` already has every MLB trade since 2015 (2,393 trades, per-asset `fromTeamId`/`toTeamId`, cash/PTBNL rows, MLBAM `personId` keys matching this pipeline, refreshed daily by GitHub Actions), which can serve as the real-trade replay test set (NBA `validate_picks.py` method), scored on trades after the V3 declaration date. It has no contract or service-time data.

## Approach

- **A17** Comparability is the reason for S17. A shared league-wide anchor is what makes a 2-WAR pitcher worth the same as a 2-WAR hitter. 590/410 matches bWAR, which v1 already uses for validation (C1) and fielding (A4).
- **A18** mERA is an input, not a target. The 6-year WAR target stays unregressed so real contact management is paid for; mERA's job is forecasting. It is kept as a model feature only if it beats the raw components (C15).
- **A19** Era drift (K% up, velocity up, starter innings down, pitch clock) is absorbed by league-season-relative MLEs (A5), per-season WAR anchoring (S17), per-appearance SP/RP replacement (S19), censored modern rows in the hazard (A13), and P(SP) trained on modern debuts (S24). It is tested, not assumed: forward-chained CV (C18) and the 2018 to 2019 holdout (C20).
- **A20** The WAR model trains on the latest complete-window snapshots (s <= 2017 or the A12-style cutoff with under 2% censored, chosen on s <= 2012 data).
- **A21** Bayesian fit for mERA runs in Python alongside the pipeline (A8); library per Q22.

## Data

| ID | What | Source | Lives in |
|---|---|---|---|
| D13 | MiLB season pitching 2000 to 2024 (per team stint: BF, GS, IP, H, 2B, 3B, HR, TB, BB, HBP, SO, GO, AO, line/pop outs, pitches, swings, whiffs) | repo release `season_player_pitching` (confirmed 2026-10-09) | `data/raw/milb_pitching/` |
| D14 | MiLB season pitching 2025 to 2026 | MLB Stats API | `data/raw/statsapi/` |
| D15 | MLB pitching 2005 to 2026, incl. G and GS | MLB Stats API | `data/mlb_pitching.parquet` |
| D16 | bWAR pitching (leverage, validation) | Baseball-Reference `war_daily_pitch`, direct download | `data/raw/bwar_pitch.csv` |
| D17 | MiLB pitcher arsenal by pitch family, 2021 to 2026 | Baseball Savant minors CSV, grouped (existing `savant_family` pattern, player_type=pitcher) | `data/raw/savant_splits/` |
| D18 | Injured-list placements, snapshot season | Stats API transactions | `data/raw/statsapi/` |

## Success criteria

- **C13** Per-season WAR totals: position players 590 and pitchers 410 (prorated for 2020), within 1 WAR, every season 2005 to 2026.
- **C14** Pitcher WAR correlates with bWAR pitching at r >= 0.75 on MLB pitcher-seasons with 100+ IP; RP subset (40+ IP, under 5 GS) reported. Gaps explained by the FIP-vs-RA9 difference, documented.
- **C15** mERA gate: kept as a model feature only if adding it to the raw MLE components improves s <= 2012 GroupKFold OOF P(MLB) log loss or WAR Spearman without worsening the other. Otherwise display only and the null result is reported. Varying slopes kept only if they beat fixed slopes on held-out next-season MLE RA9.
- **C16** Pitcher level-step test (C10 analog): K%, BB%, GB% MLE changes for L to L+1 movers vs same-level repeaters within +-1 SE at A->A+, A+->AA, AA->AAA.
- **C17** S28 gate: on AAA 2023 to 2025, blended contact predicts next-season contact allowed (ISO-on-contact) with lower RMSE than observed. If it fails, S28 is dropped and the null result is reported.
- **C18** Drift check: forward-chained CV (train s <= 2009, test 2010 to 2012) vs random GroupKFold on s <= 2012, both reported for P(MLB) log loss and WAR Spearman.
- **C19** Split sensitivity: combined 2026 top 50 at 57/43 and 61/39, overlap and rank changes reported on the methodology page.
- **C20** Single holdout evaluation for pitchers: 2013 to 2017 (C2 to C4 analogs vs MLB Pipeline top-100 pitchers from D8 and a naive age-vs-level + K-BB% baseline) and 2018 to 2019 (C12 analog). Reported whichever way it goes. Combined board also reports one Spearman across hitters and pitchers.
- **C21** Hitter restatement: hitter holdout metrics re-reported after S17 (2013 to 2017 look #6, 2018 to 2019 look #2), with no hitter modeling change.
- **C22** C5, C6, C7 apply to pitcher cards and the combined board.

## Open questions and assumptions

- **Q19** gmLI column in `war_daily_pitch`: name and coverage verified in B17. If missing, relievers get no leverage credit and the methodology page says so.
- **Q20** SP/RP replacement gap fixed at the FanGraphs convention (about .380 vs .470 win%); only the overall level is solved per season.
- **Q21** mERA target rows need 100+ BF in the next season; pairs weighted by BF.
- **Q22** Bayesian library for mERA (e.g. PyMC, a new pinned dependency) vs an empirical-Bayes approximation in existing dependencies. Decided in B19 before any fit; varying slopes require a real hierarchical fit.
- **Q23** The two-way sum overstates players whose careers resolve to one path. Stated on the card and methodology page.
- **Q24** Restating hitters changes every published hitter value, including figures already cited externally. Hold citations until v2 publishes.
- **Q25** Matched-pair translation pairs for pitchers use the same BF thresholds scaled from v1's PA thresholds (300 PA -> 300 BF).

## Pre-registration

Written before any pitcher model is fit. All pitcher choices (mERA likelihood and slopes, feature gates, model selection, A20 cutoff) are made on s <= 2012 CV. The 2013 to 2017 and 2018 to 2019 pitcher holdouts are opened once, in B23.

Expected directions:
- Re-anchoring: 2021 to 2026 hitter WAR rises (v1 sums 545 to 591), 2014 to 2015 falls (638 to 639); training-era hitter targets fall about 4% on average; 2026 hitter-vs-hitter rank order nearly unchanged (Spearman with v1.1 EV >= 0.98).
- The age-vs-level + K-BB% baseline is hard to beat; the model's margin over it is expected to be smaller than v1's hitter margin over age + OPS.
- mERA (C15) and the tracking contact adjustment (C17) may fail their gates; either outcome is reported.
- Forward-chained CV (C18) scores worse than random folds; the gap measures drift.
- Pitcher P(MLB) at a given level and age is lower than hitters', and the 10-90 WAR range is wider.

## Build order

- **B15** Pre-registration commit (this spec), then S17: per-season replacement in B2, hitter chain rerun through B8, C13 (hitters), C21. (M)
- **B16** Pitcher data layer: D13, D14, D15, D18, stints aggregated, rates recomputed, sanity checks. (M)
- **B17** Pitcher WAR, D16 download, C13 (pitchers), C14. (M)
- **B18** Pitcher translations and MLEs (S20), C16. (M)
- **B19** mERA fit (S21), library decision (Q22), ladder (S22), C15 slope test. (M)
- **B20** Pitcher features, P(SP) (S24), C15 feature gate. (M)
- **B21** Tracking layer: arsenal (D17, S27), contact adjustment and C17. (S)
- **B22** Pitcher models and prior (S23, S25), C18. (M)
- **B23** Single pitcher holdout evaluation (C20). (S)
- **B24** Surplus $ for pitchers, two-way sum (S29), combined board, C19. (S)
- **B25** Site and methodology (S26, S30). (M)
- **B26** 2026 snapshot run, smell test (C6) on the combined top 50, publish (S31). (S)
