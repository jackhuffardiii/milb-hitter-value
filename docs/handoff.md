# Handoff log

Each build step appends its section below.

## B1 - Data layer (S1, S2, S3, D1, D3, D4, D5, D6, Q4)

Run: `python run.py b1` (module `pipeline/b1_data.py`; tests `.venv/bin/pytest tests/test_b1.py -q`). Runtime: ~1 min cold (all raw cached under `data/raw/`), ~20 s warm. Raw: `data/raw/milb_batting/{year}_{level}.csv` (repo), `data/raw/statsapi/*.json` (sha1 of path+params). Shared helpers in `pipeline/common.py`: `api_get`, `download`, `pmap` (8 threads), `add_rates` (Q4), `COUNTS`, path constants. `add_rates(df)` needs columns H,2B,3B,HR,AB,BB,HBP,SF,SO,PA.
Rates: AVG=H/AB, OBP=(H+BB+HBP)/(AB+BB+HBP+SF), SLG=TB/AB, ISO=SLG-AVG, BABIP=(H-HR)/(AB-SO-HR+SF), K_pct=SO/PA, BB_pct=BB/PA; zero denominator -> NaN.

### data/milb_player_seasons.parquet
Grain: player_id x season x level x league_id (stints at different teams in one league summed). 126,067 rows, 2005-2019 and 2021-2026 (no 2020). Level codes: aaa, aa, a+ (High-A), a (Low-A), a- (short-season A, 2005-2019 only), rk (Rookie incl. DSL/FCL/ACL). Pitchers who batted are included (see primary_pos_milb == 'P').
- player_id int (MLBAM), season int, level str, league_id int, league_name str (abbr e.g. PCL, INT)
- teams str (team abbreviations joined by `|`), team_ids str (joined by `|`)
- G, PA, AB, H, 2B, 3B, HR, BB, IBB, HBP, SO, SF, SH, SB, CS, GO, AO, pitches_faced int
- swings, whiffs float: repo only (NaN for 2025-2026, API does not provide them; also NaN in some older repo cells)
- AVG, OBP, SLG, ISO, BABIP, K_pct, BB_pct float (recomputed)
- age float: (July 1 of season - birth_date)/365.25; NaN when birth_date missing (1 row, 1 player)
- bats str (L/R/S, from players), primary_pos_milb str (position token with most games across the player-season's position strings, e.g. "C/1B" counts both), source str ('repo' for <=2024, 'statsapi' for 2025-26)

### data/players.parquet
One row per player_id in any output (milb, mlb, fielding, draft): 38,303 rows. player_id int, full_name, birth_date datetime, bats, throws, primary_pos (MLB's primary position abbr), mlb_debut_date datetime, draft_year Int64. 2 players have no birth_date (1 MiLB row has NaN age).

### data/draft.parquet
One row per pick, 2005-2026, 24,122 rows. draft_year, round (str; supplemental rounds have codes), pick_overall, pick_in_round, player_id Int64 (null if pick has no person), full_name, team_id, signing_bonus (float, NaN when absent), pick_value (slot value), school, school_class, school_state, school_country, draft_type (e.g. JR), position. One exact duplicate 2008 pick (127) is dropped.

### data/mlb_seasons.parquet
Grain player_id x season x team_id (MLB, sportId 1, 2005-2026; 2026 is a full season as of build date). Same counting columns as above (swings/whiffs all NaN), league_id, league_name (AL/NL), team_abv, position (API position of the split), age, and recomputed rates. 25,758 rows. Includes pitchers' batting lines.

### data/mlb_fielding_games.parquet
Grain player_id x season x position (summed over teams). position (abbr, includes P), games, games_started, innings float. 52,548 rows.

### Data quirks
- API hitting stats are per player per team only when queried with `teamId` (without it, traded players come back merged under one team), so the pull is per team per sportId per season.
- 2024 repo-vs-API check (per player x team x level, 5,185 rows each, all join, PA totals identical 784,285): all counting stats (G,PA,AB,H,2B,3B,HR,BB,SO,SB) equal on 99.98% of rows; only BB differs on 1 row. Detail in `data/b1_api_validation_2024.json`. 2024 API pull is not used in outputs.
- Repo has no 2006 `rk` file; 2006 rookie level is absent. No 2020 MiLB season; repo `a-` stops after 2019.
- OBP can be below AVG when SF>0 (formula-correct, 480 rows); the test checks SF==0 rows only.
- 11 rows have age 45-50 (e.g. aged AAA veterans); real, kept.
- Repo "win" (winter league) files are ignored.
- Repo rate columns are ignored (Q4).

### Spec deviations
none (note: the spec's 15-45 age bound is violated by 11 genuine rows; test allows up to 50).

## B1 addendum (for B3)

`pipeline/b1_data.py` now also writes `data/milb_stints.parquet`: the pre-aggregation MiLB frame, one row per player x season x level x team (stint), columns player_id, season, level, league_id, team_id, source, plus COUNTS (G, PA, AB, H, 2B, 3B, HR, BB, IBB, HBP, SO, SF, SH, SB, CS, GO, AO, pitches_faced, swings, whiffs). No other B1 behavior changed; B1 tests pass.

## B3 - Park factors (S5 park part, Q8, D2)

Run: `python run.py b3` (module `pipeline/b3_park.py`; tests `.venv/bin/pytest tests/test_b3.py -q`). Needs `data/milb_stints.parquet` (B1). Runtime: ~1 s warm; cold is ~2,500 cached-by-hash Stats API calls (8 threads), roughly 10-15 min. Also writes `data/b3_k.json` (k values).

Method (all cells use the API; no PBP was needed, nothing downloaded/deleted for Q11): `GET /teams/stats?stats=statSplits&sitCodes=h|a&group=hitting|pitching&season&sportId&gameType=R` returns team home and away splits for MiLB sportIds 11,12,13,14,15 (to 2019),16 and MLB 1, 2005-2026 (no MiLB 2020), including 2005. Hitting gives the team's batting at home/away, pitching gives its pitching-allowed at home/away (PA = battersFaced). Home counts = hitting-home + pitching-home, road = hitting-away + pitching-away.
Components per PA: `1B`, `2B3B`, `HR`, `BB` (= BB - IBB + HBP, i.e. uBB+HBP), `SO`, `R` (runs/PA); `BABIP` is per ball in play ((H-HR)/(AB-SO-HR+SF)).
- raw_<comp> = home rate / road rate, normalized so the PA-weighted league-season mean is 1.0 (league_id from `/teams?sportId&season`).
- pf_<comp> (regressed) = effective-n-weighted mean of raw over season-1..+1 of the same team in the same league AND venue (venue_id from `/teams`; a venue or league change breaks the window; MiLB 2019 and 2021 are treated as adjacent), shrunk to 1 by n/(n+k) where n is the window's summed effective sample (home PA x road PA / (home PA + road PA) per season), then renormalized again to PA-weighted mean 1 per league-season (pooling drifts the mean).
- k per component = n_mean*(1-r)/r with r = observed year-to-year correlation of raw factors (MiLB AAA-A, same team/league/venue, adjacent seasons), r floored at 0.05 and capped at 0.95. Values (k in effective PA; r_yy): 1B 3609 (0.42), 2B3B 2181 (0.54), HR 1202 (0.68), BB 17151 (0.13, so BB factor is nearly 1), SO 2049 (0.56), BABIP 1414 (0.55), R 1630 (0.61).
- Player: per stint factor (1+pf)/2; PA-weighted over the player-season-level-league stints.

### data/park_factors.parquet
Grain sport ('milb'|'mlb') x season x team_id; 5,493 rows. level (aaa, aa, a+, a, a-, rk, mlb), league_id, venue_id, method (always 'api'), PA_home, PA_road (hitting+pitching-allowed PA in home / road games), raw_{1B,2B3B,HR,BB,SO,BABIP,R}, pf_{same}. Join MLB on (season, team_id) where sport=='mlb'; every mlb_seasons (season, team_id) is present (660 MLB team-seasons, incl. 2020).

### data/milb_player_park.parquet
Grain player_id x season x level x league_id (same keys and row count as milb_player_seasons, 126,067). ppf_{comps} (player factor, 1 = neutral), share_PA_with_factor (PA share of stints with a factor; 1.0 everywhere, rk and a- included).

### Quirks
- AAA before 2019 includes the Mexican League (sportId 11 then, third league, 16 teams) and it is absent in 2018, so AAA league-season means are per league_id.
- 2005 Rookie splits are partial (about half the PA of later years); rk is best effort (Rookie team lists change a lot, many short windows).
- 2020: MLB only (60 games, regressed with 2019/2021 neighbors; for MLB 2020 counts as adjacent to both).
- Toledo/Oklahoma City 2024 HR pf ~0.71-0.75 are the extremes; Coors HR pf > 1.05 in most seasons.

### Spec deviations
- S5 / D2 / Q11: park factors come from Stats API team home/road splits, not PBP (repo PBP ends May 2025 and cannot cover 2025-26). Because the API covered every level-season, no PBP was used, downloaded or deleted (cells by method: 5,493 api, 0 pbp). D2's "PBP 2005 to 2025" row is therefore unused; B11 still needs PBP for batted-ball data.

## B2 - Simplified WAR + target (S4, A2, A3, A4, C1, D7, Q2)

Run: `python run.py b2` (module `pipeline/b2_war.py`; tests `.venv/bin/pytest tests/test_b2.py -q`). Runtime: seconds warm (44 cached team-season API calls cold). Needs B1 outputs and `data/park_factors.parquet` (B3). Validation data `data/raw/bwar.csv` (35 MB, gitignored with data/raw, fetched once from baseball-reference with a normal UA; if blocked, `main()` prints a skip message and the C1 test is skipped).

Method: pooled no-intercept OLS of team runs on 1B, 2B, 3B, HR, uBB+HBP (BB-IBB+HBP), outs (AB-H+SF+SH) over 660 MLB team-seasons 2005-2026 (Stats API `teams/stats?stats=season`, hitting and pitching); coefficients rescaled per season so predicted league runs = actual. wOBA weight = (run value - out value) times wOBA_scale, where scale makes league wOBA = league OBP (so scale ~1.5, not FanGraphs' 1.2; weights are on the OBP scale). wOBA denominator AB+BB-IBB+SF+HBP. bat_runs = (wOBA-lg_wOBA)/wOBA_scale*PA. park_runs = -(ppf_R-1)*lg_R_per_PA*PA, ppf_R = PA-weighted (1+pf_R)/2 (missing pf_R treated neutral). pos_runs per spec (C +12.5, SS 7.5, 2B/3B/CF 2.5, LF/RF -7.5, 1B -12.5, DH -17.5, per 162 games, prorated); DH games = max(0, G - non-P fielding games); the fielding file has no generic "OF" rows so the -2.5 fallback is never used. repl_runs = 20*PA/600. RPW = 9*(lgR/lgIP)*1.5+3 (9.1-10.4). owar = (bat+park+pos+repl)/RPW. Pitchers dropped when P games > 50% of fielding games.

### data/linear_weights.parquet
Grain season (22 rows). rv_{1B,2B,3B,HR,uBB_HBP,out} run values; w_{1B,2B,3B,HR,uBB_HBP} wOBA weights; wOBA_scale; lg_wOBA (= league OBP); lg_R_per_PA; RPW.

### data/mlb_war.parquet
Grain player_id x season (13,977 rows, non-pitchers with PA>0, teams summed). PA int, wOBA, lg_wOBA, wOBA_scale, bat_runs, park_runs, pos_runs, repl_runs, RPW, owar (all float), primary_pos (position with most non-P fielding games; "DH" if none). bat_runs is not park-adjusted; add park_runs.

### data/war_target.parquet
Grain player_id (2,549 rows): debut_season (year of players.mlb_debut_date), war_6yr (sum of owar over debut_season..+5, 2020 included), n_seasons_observed, censored (debut_season+5 > 2026), pre2005 (debut < 2005; sums incomplete, exclude from training). One row per player with a debut date. Debuts with no hitting PA in the window (pitchers, pinch-runner/defensive-sub debuts, and pre-2005 debuts whose window predates the data) get war_6yr = 0, n_seasons_observed = 0 (B6-fix; before it these were absent, leaving 224 train_era players NaN: 222 pre-2005 debuts whose 6-year window ended before 2005, plus 2 PA-less debuts). pre2005 rows are incomplete: exclude from training. Non-censored 2005-2017 debuts (n=1,291): median war_6yr 0.36, 38% below zero (low-PA replacement-level-ish seasons have slightly negative oWAR), exactly 0 never; mean 3.2, p75 4.5, max 39.6.

### Validation (C1), 300+ PA non-pitchers, n=5,747
r vs bWAR WAR = 0.8505 (threshold 0.85, passes barely); r vs bWAR (runs_bat+runs_position+runs_replacement)/our RPW = 0.9773. The gap is fielding and baserunning/DP: largest negative residuals are glove-first players (Betts 2016, Gardner 2010, Simmons 2017, Kiermaier 2015, Duran 2024), largest positive are bad-defense sluggers (Dunn 2009, Kemp 2010, McCutchen 2016). Mean residual by position is within +-0.4 WAR (C +0.40, CF -0.35).

### Quirks / deviations
Per-600-PA league bat_runs among non-pitchers is ~+1.9 runs pre-2020 (pitcher bats excluded), ~0 after universal DH. No spec deviations. 2020 oWAR uses the 60-game season with the same per-162 positional proration (so positional/replacement runs are scaled by games/PA correctly).

## B4 - MLE translation (S5 translation part, S6, A5)

Run: `python run.py b4` (module `pipeline/b4_mle.py`; tests `.venv/bin/pytest tests/test_b4.py -q`). ~10 s. Also writes `data/b4_k.json` (k values).

Method: affiliated A, A+, AA, AAA non-pitcher rows only (Mexican League id 125 and Rookie/a- excluded; pitchers excluded via primary_pos_milb / players.primary_pos). Rates per PA: K=SO/PA, BB=(BB-IBB+HBP)/PA, ISO=(TB-H)/AB, BABIP per BIP=(AB-SO-HR+SF). Park-neutral = rate / ppf (K by ppf_SO, BB by ppf_BB, BABIP by ppf_BABIP, ISO by (1-w)*ppf_2B3B + w*ppf_HR, w = league-season share of ISO bases from HR, 3HR/(2B+2*3B+3HR)). MLB: team-stint pf_ half-home (1+pf)/2, same ISO blend per season, denominator-weighted to player-season.
Pairs: same player-season, >=50 PA at lower row (player x level x league) and at the upper level (aggregated over leagues; MLB aggregated over teams). w = harmonic mean of PAs (all components use this weight; pair also needs both rates non-NaN). raw_factor = sum(w*upper)/sum(w*lower). Shrinkage: league-season -> level-season -> level-all: factor = (W*raw + k*parent)/(W+k), W = summed pair weight, k = mean(W)*(1-r)/r with r = corr of adjacent-season deviations from parent (2019/2021 adjacent), r capped .95; if r<=0.05 or <15 adjacent pairs, fixed k=20000 pair-weight (only ISO level-season). Chain: MLE = neutral * own league-season factor * level-season factors of each higher level through aaa->mlb of the SAME season (zero-pair cells, e.g. no data, fall back to the parent through W=0). Regression (S6): reg = (n*MLE + k*prior)/(n+k), n = PA (K, BB), AB (ISO), BIP (BABIP); k = 60, 120, 160, 820 (FanGraphs stabilization points); prior = denominator-weighted mean MLE of that level-season (all affiliated leagues).
k values (k, r): league->level-season K 7347 (.54), BB 27704 (.24), ISO 6485 (.57), BABIP 25069 (.26); level-season->level-all K 56722 (.28), BB 21889 (.50), ISO 20000 (fixed, r .03), BABIP 170221 (.12).

### data/translation_factors.parquet
Grain from_level (a, a+, aa, aaa; factor goes to the next level, aaa goes to mlb) x league_id x season x component (K, BB, ISO, BABIP). 1,216 rows. league_id = -1 means pooled over leagues (level-season rows have season>0; level-all rows have season = 0). n_pairs int, pair_weight float (sum of harmonic-mean weights), raw_factor (NaN when no pairs), factor (shrunk; level-all factor = raw). Pooled all-years factors: aaa->mlb K 1.248, BB 0.753, ISO 0.728, BABIP 0.873. Per-league-season n_pairs (K): min/median a 38/56, a+ 20/40, aa 21/44, aaa 46/75.5; level-season: a 92/122, a+ 106/131, aa 106/131, aaa 107/166.

### data/mle.parquet
Grain player_id x season x level x league_id (affiliated A..AAA, non-pitcher; 64,369 rows). PA, AB, BIP, neutral_{K,BB,ISO,BABIP}, mle_*, reg_* (NaN where denominator is 0). No wOBA proxy.

### data/mle_player_season.parquet
Grain player_id x season: PA (total across levels), highest_level, mle_* and reg_* (denominator-weighted across rows).

### Out-of-sample (AAA s >=200 PA, MLB s+1 >=200 PA, n=986): RMSE raw AAA rate vs reg_ MLE
K .0557 vs .0449, BB .0370 vs .0237, ISO .0661 vs .0522, BABIP .0543 vs .0446 (MLE wins 4/4). Caveat: factors are fit on all years including s+1 level-all pairs (minor leakage); MLE beating raw is largely the level-bias correction.

### Quirks
2020 has no MiLB; 2026 factors come from 2026 pairs (full season in data). Player with several leagues at one level pairs each league row with the aggregated upper level.

### Spec deviations
none.

## B5 - Model-ready table (A10, S7 features, S8 prior population, Q5, Q7, A2, A3)

Run: `python run.py b5` (module `pipeline/b5_features.py`; tests `.venv/bin/pytest tests/test_b5.py -q`). Seconds. Needs B1-B4 outputs.

Snapshot: one row per non-pitcher (milb_player_seasons primary_pos_milb != P and players.primary_pos != P) x season s in 2005-2026 with affiliated MiLB play in s (Mexican League 125 excluded) and career MLB AB through s < 130 (mlb_seasons, 2005+ only). group 'stat' = A/A+/AA/AAA PA over s and s-1 >= 150 AND complete reg_ MLE for s (4 rates non-NaN); else 'prior'. split: train_era s<=2017, censored 2018-2025, score 2026. Counts: train_era 19,898 stat / 22,408 prior; censored 10,868 / 12,407; score 1,598 / 1,483.

### data/features.parquet (grain player_id x season, 76k rows; unique key)
- ids: player_id int, season int, name str, team str (teams of highest-level row, `|`-joined), group str (stat|prior), split str.
- level/age: highest_level str (rk,a-,a,a+,aa,aaa), level_num float (rk 0, a- 0.5, a 1, a+ 2, aa 3, aaa 4), age float (July 1 of s), age_vs_level float (age minus PA-weighted mean age of all affiliated hitters at that level-season), bats str, milb_pos str (primary position at highest level), level_group str (stat only: low = a/a+, high = aa/aaa).
- volume: PA_s (all affiliated levels in s), PA_highest (PA at highest level in s), career_milb_pa (affiliated MiLB PA through s, data starts 2005), pro_years (s - first MiLB season in data + 1; left-censored at 2005).
- MLE (stat only; NaN for prior): reg_{K,BB,ISO,BABIP} (B4 reg_ rates, season s), blend_{...} (Marcel: PA*w with w=3 for s and 2 for s-1, s-1 term dropped when absent; 2021 has no s-1 since no 2020), delta_{...} = s minus s-1 (NaN if no s-1).
- position (stat only): p_C, p_SS, p_CF (transition probabilities), exp_pos_runs (sum P * POS_RUNS per 162, imported from b2_war).
- draft (all rows, from latest draft record with draft_year <= s): round_num (numeric; non-numeric rounds NaN), pick_overall, signing_bonus, draft_year, years_since_draft, international bool (no draft record on or before s).
- labels: reached_mlb bool (has players.mlb_debut_date, any year), debut_year, eta_years (max(0, debut_year - s); NaN if not reached), war_6yr (war_target; NaN if not reached or absent from war_target = pitcher-only/no-PA debuts). After the B6-fix every reached row has war_6yr (pre-2005 debuts carry 0 and must be excluded via war_target.pre2005). war_6yr window starts at debut season, and is censored/pre2005 flagged only in war_target (not copied here).

### data/position_transition.parquet
Grain level_group (low|high) x milb_pos x mlb_pos (C,1B,2B,3B,SS,LF,CF,RF,DH): n (count), p (Laplace alpha=1, sums to 1 per level_group x milb_pos). milb_pos '_ALL' = marginal row, used as fallback for MiLB positions with no training snapshots. Built from all snapshots s<=2017 (stat and prior with highest level a..aaa) of players who reached MLB with debut >= 2005; MLB position = most fielding games (incl. DH rows, non-P) in debut..debut+2 seasons, DH if none. Leakage note: matrix is fit on the same train_era snapshots (minor; 9 positions).
Highest-level rates for stat train_era reached_mlb: a .21, a+ .21, aa .32, aaa .60. High-level SS -> SS .751, C -> C .948, CF -> CF .436 (LF .306, RF .222).

### Spec deviations
none.

## B6 - Models (S7, S8, A6, A7, A3)

Run: `python run.py b6` (module `pipeline/b6_models.py`; tests `.venv/bin/pytest tests/test_b6.py -q`). ~45 s. Needs B5 + war_target. Env note: Mac wheel of lightgbm needs libomp; none installed system-wide, so the venv copy was patched (`install_name_tool -add_rpath .venv/.../sklearn/.dylibs lightgbm/lib/lib_lightgbm.dylib` then `codesign --force --sign -`). Redo after a fresh venv, or `brew install libomp`. Added to requirements.txt: scikit-learn, lightgbm, shap, joblib, scipy.

Reusable API (B11): `fit_stat(train_df, cfg)`, `predict_stat(models, df)` (df = features.parquet rows; returns p_mlb, war_mean, war_q10/50/90, eta_mean, eta_q10/q90, ev_war, low_confidence, index = df index), `fit_prior`, `predict_prior`, `drivers(models, df, 'p_mlb'|'war')`. Fitted models: `data/models/{stat,prior}_{backtest,final}.joblib` (dict: p_mlb, war, eta estimators, *_q quantile models keyed 0.1/0.5/0.9, cols, cfg). Swap ISO/BABIP inputs by editing reg_/blend_/delta_ columns of the frame passed to predict_stat.

Design: features = STAT_NUM + one-hot STAT_CATS (bats, highest_level; raw milb_pos dummies removed, position enters only via exp_pos_runs, p_C, p_SS, p_CF), PA counts log1p'd; no draft features. Linear: median impute (+missing indicators) + standardize; LightGBM num_leaves 15, lr .03, min_child 50, n_estimators = mean best_iter (early stopping on 20% group holdout inside each GroupKFold(5) fold) x1.1. Training sets: WAR rows = reached, war_target.censored False, pre2005 False; ETA rows = reached. Selection data = stat train_era s<=2012; same choice used for both fits. 'backtest' fit trains s<=2012, predicts stat+prior 2013-2017; 'final' trains s<=2017, predicts censored 2018-2025 + score 2026.

### data/predictions.parquet (grain player_id x season x fit; 43,365 rows: backtest 7,592 stat + 9,417 prior; final 12,466 stat + 13,890 prior)
player_id, season, group (stat|prior), fit (backtest|final), p_mlb, war_mean, war_q10/q50/q90 (sorted), eta_mean, eta_q10/q90 (>=0), ev_war = p_mlb*war_mean, low_confidence (True for prior), chosen_p_mlb / chosen_war / chosen_eta ('linear'|'lightgbm' for stat; prior always 'linear'). Prior WAR/ETA ranges are mean + empirical residual quantiles.
### data/drivers.parquet (stat rows only: backtest 2013-2017 and final 2026 score)
player_id, season, fit, target (p_mlb: log-odds contribution; war: wins), feature, feature_value (raw, imputed), contribution, rank (1-5 by |contribution|). Long format.
### data/b6_metrics.json
cv_stat (OOF log loss / RMSE / Poisson deviance per candidate + lgb n_estimators), chosen_stat, holdout_stat and holdout_prior (2013-2017 backtest fit: logloss, brier, auc, calibration deciles, war_rmse, eta_rmse, spearman_ev_vs_realized, spearman_war_reached_only, war_q10_q90_coverage), cv_prior.

### Quirks / spec deviations
- S8: signing_bonus is NaN for all draft years <= 2016 (B1 bonus coverage), so log_bonus is dropped by the imputer in prior training; prior models effectively use round, pick, international, age, level, PA, years since draft.
- After dropping position dummies LightGBM wins all three targets (WAR RMSE 4.109 vs ridge 4.125). Age and age_vs_level dominate WAR drivers for 19-year-olds (+4 wins); 2026 top-15 war_mean is ~8-12.
- Recency recalibration of P(MLB) (C4): OOF predictions on the training fit, Platt (logit) chosen over isotonic by group-CV log loss on the last 3 training seasons only (backtest 2010-12, final 2015-17); applied in predict_stat(calibrate=True). Holdout deciles 6-8 remain under-predicted by 5.6-6.5 points (was 7.4-8.0), so tests/test_b6.py C4 test is xfail. Prior model left uncalibrated (deciles within 3 points). Drivers for p_mlb are of the uncalibrated model.

## B7 - Top-100 collection and backtest (S9, C2, C3, C4, D8, Q3, Q6, Q12)

Run: `python run.py b7` (module `pipeline/b7_backtest.py`; tests `.venv/bin/pytest tests/test_b7.py -q`). Seconds. Needs features, predictions (fit=='backtest'), war_target, b6_metrics, milb_player_seasons, and committed `data/manual/top100.csv`. top100.csv was built once by `pipeline/b7_scrape_top100.py` (curl of the MLB.com article, parses embedded markdown) then `python -m pipeline.b7_top100 /tmp/raw100.json` (name matching); neither is part of `run.py`.

### data/manual/top100.csv (committed)
Grain list_year (2014-2018, 100 rows each) x rank. list_year, source, source_url, rank, name, pos, org, is_hitter (any slash-component of pos not P/RHP/LHP/SP/RP; Ohtani, McKay count as hitters), player_id (MLBAM, blank unless matched), match_status (matched|ambiguous|unmatched|pitcher). Source is 'pipeline' (MLB Pipeline preseason Top 100) for ALL years: BA full lists are paywalled (baseball-reference/baseballamerica 403, only partial team-blog snippets), so per Q6 the substitute is used; the methodology page must say so. 2017 list has a duplicated "32." in the source (Maitan, De Leon): De Leon assigned 33; 2015 #100 rendered "100 ." Matching (Q12): normalized names (accents, Jr./suffixes, nickname map, first+last when middle names) against players.parquet, restricted to features snapshots at list_year-1 then list_year-2; multiple candidates are narrowed by milb_pos compatibility; else left blank. Org is not used (features carry MiLB team names, not parent org).
Hitter match counts (matched/ambiguous/unmatched): 2014 51/0/0, 2015 51/1/1, 2016 58/0/3, 2017 57/0/1, 2018 54/0/2. Not matched: 2015 Michael Taylor WAS (ambiguous), 2015 Justin O'Conner, 2016 Brett Phillips, 2016 Javy Guerra (players.parquet has these as primary_pos P, so no feature rows), 2016 "Raul Mondesi" (KC; is Adalberto Mondesi 609275, but the list name collides with other Mondesis, left unmatched), 2017 Kevin Maitan (no snapshot in 2015/2016 in features), 2018 Shohei Ohtani (no MiLB), 2018 Brendan McKay (pitcher-coded).

### data/backtest_players.parquet
Grain list_year x rank (matched ranked hitters having a backtest prediction at season list_year-1; 269 rows). list_year, rank, player_id, name, model_rank_within_list (by ev_war among these rows), list_rank_within_matched, gap (list_rank_within_matched - model rank; >0 model higher on player), ev_war, p_mlb, war_mean, realized (war_6yr if reached else 0), reached bool, censored bool (debut_season+5>2026), pre2005 bool.

### data/backtest.json
sources (url per year), C2 {primary_excl_censored, sensitivity_incl_censored: per_year Spearman model vs BA, top_n 10/25 reached shares and mean realized, pooled with 2000-resample player bootstrap 90% CI of difference}, C3 {baseline vs model log loss and Spearman, both censoring variants}, C4 deciles with pass flags (|gap|<=0.05), disagreements (10 largest each way), realized_definition. Primary excludes censored and pre2005 rows (5 of 269 ranked rows).

### Results
C2 (primary, n=264): pooled Spearman model 0.217 vs list 0.379, diff -0.161, 90% CI [-0.291, -0.032]; the model loses to the Pipeline rank. Per year (model/list): 2014 .418/.556, 2015 .156/.160, 2016 .085/.253, 2017 .184/.483, 2018 .305/.408. Almost every ranked hitter reached MLB (shares 1.0), so the reach-share comparison is uninformative; top-25 mean realized WAR is slightly lower for the model in most years. Sensitivity (incl. censored) nearly identical (pooled .228 vs .382). C3: model beats baseline on log loss (0.408 vs 0.536) but NOT on Spearman (0.170 vs 0.191); n=7,488 stat rows. C4: deciles 6, 7, 8 fail (gaps -6.5, -5.6, -5.7 points), the rest pass. Biggest model-vs-list gaps: model high on Willie Calhoun, Jake Bauers, Bobby Bradley (realized ~0); model low on Moncada, Buxton, Swanson, Luis Robert, Juan Soto (28.3 WAR), Vlad Jr.; the model sees age/level/stats only so young high-ceiling prospects are undervalued.

### Quirks / spec deviations
- D8/Q6/S9: lists are MLB Pipeline, not BA, for all years (BA paywalled); list years are 2014-2018 (preseason after holdout snapshots 2013-2017) while the spec table says 2013 to 2017.
- C3 baseline: logistic and ridge on s<=2012 stat rows, OPS from summed counting stats at highest level in s. Baseline Spearman beats the model's on realized WAR (model's ev has Spearman 0.170 on the stat holdout, matching b6_metrics).

## B11 - Batted-ball layer (S13, S14, C8, D2, D11, Q11, Q13, Q14)

Run: `python run.py b11` (module `pipeline/b11_batted.py`; tests `tests/test_b11.py`). Registered between b6 and b7. Needs B1-B6 outputs. First run ~11.5 min (downloads); rerun from cache ~50 s. Rerunnable after a B6 refit (rescore step reads current features/predictions/models and asserts it reproduces predictions.parquet).

Source: Baseball Savant minors Statcast CSV, one request per day 2021-04-01..2026-09-30 (Apr-Sep), balls-in-play filter, cached as data/raw/savant/{day}.parquet (1,100 files). Download ~514 MB (HTTP bodies), 4 concurrent, 0.2 s sleep. game_pk -> level via Stats API schedule (sportId 11 = aaa, 14 = a), only those kept. Events from Savant `events` (errors/FC/DP = out), bunts excluded, rows need launch_speed and launch_angle.

### data/bip.parquet (625,625 rows; one per tracked BIP)
batter int, season, level (aaa|a), game_pk, home_team, launch_speed, launch_angle, spray_angle (deg, pull negative both hands, LHB flipped), stand, outcome (out|1B|2B|3B|HR), source ('savant'), p_out/p_1B/p_2B/p_3B/p_HR (out-of-fold by batter, GroupKFold 5, per-level LightGBM multiclass on EV/LA/spray; sums to 1).
BIP by level x season (a / aaa): 2021 22,273 / 0; 2022 25,273 / 41,496; 2023 25,037 / 110,421; 2024 26,389 / 107,803; 2025 27,252 / 107,151; 2026 26,177 / 106,353.

### data/batted_ball.parquet (S13, display only; player_id x season x level, 6,182 rows)
n_bip_tracked, share_bip_tracked (tracked / (AB-SO+SF)), avg_ev, ev90, hard_hit_pct (EV>=95), avg_la, la_sd, sweet_spot_pct (LA 8-32), barrel_pct (piecewise-linear approximation of the Statcast barrel table, see `barrel()`).

### S14 / C8 (data/b11_c8.json)
xBABIP = sum(P1B+P2B+P3B)/sum(1-PHR) over tracked BIP; xISO = sum(P2B+2P3B+3PHR)/n_tracked * (AB-SO+SF)/AB (scaled to actual AB via tracked share). Park-neutral by construction; blended with B4 neutral_ISO/BABIP per row: adj = w*x + (1-w)*obs, w = n/(n+k), n = tracked BIP attributed to the row. k fit on AAA 2022->2023, 2023->2024 (>=200 PA, >=50 tracked BIP): k_ISO = 50, k_BABIP = 100 (grid in json).
(a) AAA year-ahead RMSE vs next-season neutral rate, observed -> adjusted: 2024->2025 (held out, n=185) ISO .0517 -> .0506, BABIP .0466 -> .0423 PASS; 2023->2024 (n=203) ISO .0512 -> .0480, BABIP .0437 -> .0408; 2025->2026 (n=179) ISO .0532 -> .0524, BABIP .0477 -> .0424.
(b) AAA s (2022-2025, >=200 PA, >=50 tracked BIP) -> MLB s+1 (>=150 PA), n=225, reg_ MLE baseline -> S14-adjusted: ISO .0502 -> .0494, BABIP .0433 -> .0440 (adjusted worse) FAIL.
s14_pass = False (null result, not tuned). predictions_final.parquet = B6 fit=='final' rows unchanged with s14_applied False everywhere and *_base columns NaN; drivers_final likewise. The rescore path (adjusted features, B6 predict, drivers) is implemented and exercised only through the no-change reproduction check; it activates automatically if a rerun passes.

### data/predictions_final.parquet / data/drivers_final.parquet
Same grain/columns as predictions/drivers (fit=='final') plus s14_applied bool, {p_mlb,war_mean,war_q10,war_q50,war_q90,eta_mean,ev_war}_base (NaN unless applied); drivers add feature_base/feature_value_base/contribution_base.

### Quirks / Spec deviations
- D2/Q11: repo PBP not used; all batted balls come from Savant (D11/Q13) 2021-2026, Low-A is FSL parks only, AAA full from 2023 (2022 partial, ~41k BIP), none for AAA 2021.
- Only AAA and Low-A tracked; 2026 rows are 2026 Apr-Sep.

## B13 - Baserunning in oWAR (S4, C1)

Run: `python run.py b2` (same module `pipeline/b2_war.py`). owar = (bat + park + bsr + pos + repl)/RPW, bsr_runs = wSB + gidp_runs. New columns in `data/mlb_war.parquet`: wSB, gidp_runs, bsr_runs (float). `data/linear_weights.parquet` gains runCS, lg_wSB, lg_GIDP_per_PA. `war_target` recomputes from the new owar (raw sum, no floor). Downstream (b5/b6/b7/b11) is not rerun.
- wSB (FanGraphs form): runSB 0.2, runCS = -(2*lgR/lg_outs + 0.075), lg_wSB = (lgSB*runSB + lgCS*runCS)/lg(1B+BB+HBP-IBB), wSB = SB*runSB + CS*runCS - lg_wSB*(1B+BB+HBP-IBB). League totals from the Stats API team totals (same as linear weights).
- GIDP runs (approximation): -0.37*(GIDP - lg_GIDP_per_PA*PA). True DP opportunities (runner on 1st, <2 outs) need MLB play-by-play, which is not pulled.
- GIDP source: mlb_seasons lacks it; b2 `_gidp()` calls `api_get("stats", stats="season", group="hitting", sportId=1, season, teamId, playerPool="All", limit=5000)`, the exact B1 params: 660/660 team-seasons cache hits (100%), zero new network calls.
- C1 (300+ PA, n=5,747): r vs bWAR WAR 0.8505 -> 0.8631; r vs (runs_bat+runs_br+runs_dp+runs_position+runs_replacement)/RPW 0.9773 (old def, no br/dp) -> 0.9689 (new def); r bsr_runs vs bWAR (runs_br+runs_dp) = 0.7627.
- Known data issue (B1, not fixed): mlb_seasons totals for 2024 and 2025 are 2-4% short of Stats API team totals (2024 H 38,994 vs 39,823; SB 3,546 vs 3,617). League wSB over all hitters sums to 0 for every other season, but 5.9 runs in 2024, 1.0 in 2025. This also means bat_runs in those seasons use incomplete player rows. Non-pitcher wSB sums are > 0 pre-2022 because pitcher hitters (negative wSB) are dropped.
- Spec deviations: none (GIDP is the documented approximation).

## B12 - S15 features and C9 selection (S15, C9, Q15, Q16, D12, A12 evaluation)

Run: `python run.py b1 b3 b4 b5 b12` (b12 = `pipeline/b12_select.py`, also `python -m pipeline.b12_select`, ~2 min, registered after b5). Tests: `tests/test_b1.py`, `test_b5.py`, `test_b12.py`; `tests/conftest.py` adds the repo root to sys.path so tests can import `pipeline.*`.

### B1 additions (`pipeline/b1_data.py`)
- `milb_player_seasons.parquet` and `milb_stints.parquet` gain (float, summed, NaN where the source lacks them): FO, PO, LO (fly/pop/line outs), ground_hits, fly_hits, pop_hits, line_hits, GiDP. Repo (2005-2024) has all of them (coverage 100%). 2025-26 (Stats API): GiDP from `groundIntoDoublePlay`, GO/AO as before, the rest NaN.
- `swings`, `whiffs` now filled for 2026 from the repo's refreshed 2026 files (`data/raw/milb_batting/2026_{lv}.csv`), joined player_id x team_id x level; join rate 100% of API rows and PA (5,528 of 5,528 repo rows matched); 98.5% of 2026 A-AAA rows have swings > 0. 2025 stays NaN (repo stopped 2025-05-01, API has no swings). Repo cells with swings == 0 mean untracked, so B5 treats swings <= 0 as missing.
- `milb_player_seasons` gains pos_g_SS, pos_g_CF, pos_g_C: sum of G over stint rows whose position string lists that position (approximation: "SS/2B" counts all its G for both).
- `players.parquet` gains height_in (float; from "6' 2\"" = 74; values outside 55-90 set NaN) and weight_lb (float; outside 100-400 NaN). Current values (Q15 look-ahead, stated on methodology page). 38,285 / 38,282 non-null of 38,303.

### B5 features (`pipeline/b5_features.py`; `S15_GROUPS` dict, `S15_KEPT` list for B6r)
All S15 columns are populated only for group 'stat' (NaN for prior). Contact/batted/speed aggregate A..AAA rows of season s over leagues; "blend_" = 3:2 weighted blend of s with s-1 (weights 3*valid PA, 2*valid PA_prev; a missing side gets weight 0, so 2021 and 2026 use the single season; 2025 snapshot is NaN for contact because 2025 has no swings).
- contact: contact_rate = 1 - whiffs/swings; swing_rate = swings/pitches_faced; blend_contact_rate, blend_swing_rate. Non-null for 2005-2024 and 2026, all NaN for 2025 (Q16).
- batted: gb_rate, fb_rate, ld_rate, pu_rate = (GO+ground_hits, FO+fly_hits, LO+line_hits, PO+pop_hits)/sum of the four (NaN 2025-26, no detailed types); gofb = GO/AO (all years); blend_ versions of each. Not park-adjusted.
- speed: sb_att_rate = (SB+CS)/(1B+BB+HBP-IBB) clipped to 1; sb_success = SB/(SB+CS); triple_rate = 3B/(2B+3B). Season s only.
- posmix: pos_share_SS, pos_share_CF, pos_share_C = pos_g_X / G at the highest level in s (clipped to 1; positions can sum above 1, approximation above).
- pace: games_at_current_level (career G at highest level reached through s, all levels incl. rk, ladder rk<a-<a<a+<aa<aaa), ascent_pace = career G below that level / max(1, levels climbed since the first season's lowest level) (lower = faster), levels_climbed_s (distinct levels above the starting level played in s), repeated_level (float 0/1: highest level in s == highest in s-1 and >= 200 PA there; 0 if no s-1 row).
- body: height_in, weight_lb, bmi = 703*lb/in^2.

### C9 selection (`data/b12_c9.json`; train-era stat rows s <= 2012, n = 12,306; GroupKFold(5) by player; holdout 2013-2017 untouched)
Baseline = current B6 stat features; P(MLB) = B6 LightGBM (early stopped), WAR-hat = ridge (A12 candidate; B6 itself not changed, A12 selection still B6r), ev = p * WAR-hat, realized = war_6yr if reached else 0, non-censored non-pre2005. Rule: keep if log loss or Spearman improves and neither loses more than 0.002 / 0.005.
| group | logloss | ev Spearman | keep |
|---|---|---|---|
| baseline | 0.4253 | 0.1559 | |
| contact | 0.4256 | 0.1554 | no |
| batted | 0.4283 | 0.1540 | no |
| speed | 0.4219 | 0.1538 | yes |
| posmix | 0.4248 | 0.1575 | yes |
| pace | 0.4207 | 0.1540 | yes |
| body | 0.4112 | 0.1688 | yes |
| all kept | 0.3967 | 0.1686 | yes |
Kept groups: speed, posmix, pace, body (13 features, `S15_KEPT`). Contact and batted are dropped (also would be NaN for 2025-26 snapshots). Body gain is partly the Q15 look-ahead (current size of players who reached MLB is better recorded). B6 models were not refit; B6r imports `S15_KEPT` from `pipeline.b5_features`. `pipeline/b12_select.py` has `_X(df, cols)` building baseline `stat_X` plus extras (log1p on games_at_current_level and ascent_pace).

Spec deviations (D12, Q16): no game-feed pull; 2026 swings/whiffs come from repo season files (refreshed 2026-10-01), 2025 contact/swing are NaN, 2026 contact uses 2026 alone (no 2-year blend, same as 2021). No other deviations.


## B1-fix - MLB per-team hitting pull omitted traded-away stints (S3)

Cause: `stats?group=hitting&sportId=1&teamId=T&playerPool=All` does not return every stint of a player traded away from T (2024: 11 players, e.g. De La Cruz's MIA stint; 2025 similar; 2005-2023 and 2026 were complete). League hit totals were short (2024 H 38,994 vs 39,823 API team totals; 2025 38,686 vs 40,138). Fix (`pipeline/b1_data.py::_fill_missing_stints`): per MLB season, compare each player's summed team-row PA with the league-wide `stats` row (one row per player, summed across teams); for mismatches, replace their rows with `people/{id}/stats?stats=season&sportId=1` per-team splits. Cached by `api_get`; no existing cache entries were stale (new calls only). `mlb_seasons.parquet` gains `GiDP`; `b2_war._gidp` now reads it (previously re-read the per-team cache, which had the same hole). MiLB 2025-26 API pull was checked and is complete (matches `teams/stats` totals for every sport/season).
League totals H/HR/BB/SO/SB after: 2023 40,839/5,868/15,819/41,843/3,503 (unchanged); 2024 39,823/5,453/14,929/41,197/3,617 (H was 38,994); 2025 40,138/5,650/15,379/40,645/3,440 (H was 38,686); 2026 39,849/5,575/16,337/40,700/3,289 (unchanged).
Tests: `tests/test_b1.py::test_mlb_matches_api_team_totals` (2005-2026, within 0.5% of `teams/stats` sums for H, HR, BB, SO, SB) and `test_milb_api_matches_team_totals` (2025-26 per level). Not fixed: `mlb_fielding_games` uses the same per-team fielding pull and may have the same hole (games by position only; not used by value models beyond positional).
Spec deviations: none.


## B12-fix - drop weight/bmi look-ahead (S15, Q15)

weight_lb and bmi leak post-snapshot information (MLB players' listed weights are updated over careers; reached players avg 206 lb vs 196 for non-reached). `S15_GROUPS["body"]` and `S15_KEPT` are now height_in only; weight_lb and bmi stay in features.parquet for display, never model inputs. `python run.py b12` rerun (also on the B1-fix data); the C9 table in the B12 section above is superseded by:
| group | logloss | ev Spearman | keep |
|---|---|---|---|
| baseline | 0.4253 | 0.1559 | |
| contact | 0.4254 | 0.1554 | no |
| batted | 0.4283 | 0.1540 | no |
| speed | 0.4219 | 0.1537 | yes |
| posmix | 0.4248 | 0.1575 | yes |
| pace | 0.4209 | 0.1541 | yes |
| body (height only) | 0.4261 | 0.1581 | yes (Spearman +0.0023, logloss -0.0008 within tol) |
| all kept (11 features) | 0.4142 | 0.1561 | yes |
Body gain from 0.0133 Spearman / 0.0145 logloss collapses to noise once weight/bmi are removed, confirming look-ahead; height kept per the rule. Holdout untouched.


## B6r - refit with A12 selection and S15 features; B11, B7 rerun (A12, S15, C2, C3, C4)

Run: `python run.py b6 b11 b7` (~2 min). Code: `stat_X(df, extra=())` in `pipeline/b6_models.py` is the single design-matrix builder (log1p on `LOG_EXTRA` = games_at_current_level, ascent_pace); models use `_X(df) = stat_X(df, S15_KEPT)` (11 features: speed, posmix, pace, height_in); `b12_select._X` delegates to `stat_X` (moved from b12 to avoid a b6<->b12 import cycle). A12: WAR mean model chosen by OOF Spearman vs realized war_6yr among reached non-censored non-pre2005 rows, GroupKFold(5), s<=2012 (`b6_metrics.json` cv_stat.war.spearman_*). P(MLB)/ETA selection unchanged (log loss / Poisson deviance); recency Platt/isotonic calibration unchanged; quantile LightGBMs unchanged.
CV (s<=2012): P(MLB) logloss linear 0.4630 / lightgbm 0.4142 -> lightgbm. WAR Spearman ridge 0.3354 / lightgbm 0.3084 (RMSE 4.170 / 4.140) -> ridge (linear). ETA deviance 0.9112 / 0.8347 -> lightgbm.
Holdout 2013-2017 (stat, n=7,592): logloss 0.4028, AUC 0.8849, ev Spearman 0.2162, WAR reached-only Spearman 0.3712; C4 fails deciles 7 (-5.7) and 8 (-5.1 points). C3 (n=7,488 excl. censored): model logloss 0.3886 vs 0.5360 naive, Spearman 0.2162 vs 0.1926. C2 pooled (n=264): model 0.248 vs Pipeline list 0.386, diff -0.138, 90% CI [-0.259, -0.018] (model worse than the list). B11 C8: a_pass true, b_pass false, s14_pass false (S14 not applied).
Driver sign check (2026 top 15 by ev_war), ridge WAR: age and age_vs_level carry opposite-signed contributions and p_C / pos_share_C offset each other (-1.97 / +1.76); blend_K and reg_K offset (e.g. -3.11 / +1.99): collinear linear terms, individually baseball-implausible, net sensible. Do not read single linear drivers in isolation.


## B8 - Surplus value model and grouped drivers (S10, A6, A7, A1, D9, Q10, Q2)

Run: `python run.py b8` (module `pipeline/b8_value.py`; tests `tests/test_b8.py`; ~10 s). Needs predictions_final, predictions (backtest rows), features, war_target, mlb_war, models/*.joblib, `data/manual/dollar_params.csv` (committed; each row has source_url and source_note). Small B6 edit: `drivers()` caps `top` at the number of contribution columns (top=999 returns every feature).

### data/manual/dollar_params.csv
$/WAR 2026 = $11.23M (FanGraphs Feb 2026, 2025-26 class; the 2026-27 class is unpublished so this is an assumption for 2026-27), inflation 0.58%/yr (realized CAGR of FanGraphs annual overall $/WAR 2020-2026, see revision below), MLB minimum $780,000 for 2026 (2022-26 CBA, Baseball-Reference), 2027+ minimum = 2026 grown at 0.58% (assumption), arb 40/60/80% (Tango rule of thumb; observed averages nearer 25/40/62), discount rate 8% (spec assumption, no source). CBA expires December 2026 so 2027+ economics are assumptions.

### data/war_profile.parquet
control_year 1..6, mean_owar (mean owar in control year k over reached non-censored 2005-2017 debuts, n=2,966, missing seasons count 0), share (mean_owar / sum, sums to 1; ratio of means, not mean of per-player ratios, because per-player war_6yr near zero is unstable). Shares: .076, .151, .192, .198, .195, .189.

### data/valuations.parquet (grain player_id x season x fit; 2026 final rows 3,081 + backtest 2013-2017 rows 17,009)
player_id, season, fit (final|backtest), group, low_confidence, p_mlb, war_mean, war_q10/q50/q90, eta_mean, p_debut_2027..2035 (Poisson(eta_mean) truncated at j=8, renormalised; columns are calendar years for the 2026 snapshot; for backtest rows column p_debut_2027+j means snapshot+1+j), surplus_if_mlb, surplus_q10/q50/q90 (conditional on reaching, USD), ev_surplus = p_mlb * surplus_if_mlb, s14_applied. Present values at the row's snapshot season (cash flow in calendar year Y discounted by 1.08^(Y - snapshot)). Raw WAR, no floor, so q10 can be negative. Never-reaching players cost nothing in this model. Backtest rows use $/WAR and minimum salary deflated back from 2026 at the $/WAR growth rate (0.58%/yr): APPROXIMATE era parameters. surplus_if_mlb uses war_mean; q columns use the same ETA distribution.

### data/drivers_grouped.parquet (final 2026 and backtest rows, stat and prior groups)
player_id, season, fit, group, target (p_mlb log-odds | war wins), family, contribution (sum over the family's features incl. missing-indicators; sums over families equal the full contribution total within 1e-6, asserted), phrase (plain-English description of the family's inputs, same for both targets), rank (by |contribution| within row x target). Families: Age (age, age_vs_level), Strikeouts, Walks, Power, Contact quality, Position, Speed, Development pace (incl. level_num, highest_level, pro_years, PA counts, games_at_current_level, ascent_pace, levels_climbed_s, repeated_level), Body (height_in, bats), Draft pedigree (prior group only: round, pick, bonus, international; Development pace there = level, log PA, years since draft), Other (asserted empty for stat). p_mlb contributions are of the uncalibrated model (SHAP for LightGBM, coef x standardized value for ridge). "Level avg" in phrases = mean of that rate over same-season stat rows at the same highest level.
Family sign check (2026 stat rows): Strikeouts contribution positive despite above-average blend_K: 1 of 785 (p_mlb), 2 of 785 (war). Age family non-positive for players younger than level average: 204 of 1,022 (p_mlb), 267 of 1,022 (war), and positive for older-than-level: 54 of 576 (p_mlb), 274 of 576 (war). These violations are mostly 25-year-olds only slightly young for level: the Age family includes absolute age, which is penalized separately from age_vs_level in the ridge, so the family net depends on both. Not corrected.

### Spec deviations
none (assumptions in dollar_params.csv are labeled; $/WAR base is the 2025-26 class figure because 2026-27 is not yet published).


### B8 revision (A6, A7, D9)
- Intervals (A7): B6 WAR 10/50/90 are no longer LightGBM quantiles. `binned_resid` in `pipeline/b6_models.py` takes GroupKFold(5) OOF predictions of the chosen WAR model (ridge) on the WAR training rows, bins by quintile of the OOF prediction, and stores residual 10/50/90 quantiles per bin with the fitted model (`mod["war_resid"]`); predicted war_qXX = war_mean + residual of the row's bin. Same for the prior ridge. ETA keeps LightGBM quantiles (stat) / residual quantiles (prior). b6, b11, b7, b8 rerun (B11/B7 unchanged in conclusions). Holdout 2013-2017 q10-q90 coverage: stat 0.8006, prior 0.8472. War_q50 is NOT within 1 WAR of war_mean: war_q50 - war_mean averages -1.3 (max abs 2.3 on 2026 stat rows) because WAR outcomes are right-skewed (bin median residuals -0.5/+0.4 to -2.3 vs mean 0; the ridge predicts a mean). So surplus_q50 < surplus_if_mlb is expected (median vs mean), and war_mean always lies inside [q10, q90]. Tests assert ordering, mean inside the interval, |q50-mean| < 3.
- Phrases (A6): `input_dir` (+1 above / -1 below the pooled training-row mean of the family's lead input, 0 neutral) and `suppressed` added to drivers_grouped. Reference = mean over train-era stat rows of that fit (final s<=2017, backtest s<=2012) of blend_K/BB/ISO/BABIP and sb_att_rate: "MLB-equivalent ISO .124 vs .078 prospect avg". Age phrase is neutral: "Age 21.4; 5.4 yrs younger than AAA avg". `missingindicator_delta_*` now belong to Development pace (they flag no prior season, not a rate). A direction survives only if it agrees with the family contribution for that target; otherwise the phrase gets "; net effect also reflects trend/regressed values" and input_dir 0 (`suppressed` True). Cause of disagreements: reg_/blend_/delta_ ridge terms are collinear with opposite signs (e.g. reg_K +1.05, blend_K -1.61), so the family net can differ from the lead input. 2026 final stat rows suppressed (war / p_mlb of 1,598): Strikeouts 158 / 63, Walks 151 / 63, Power 258 / 99, Contact quality 227 / 213, Speed 75 / 208. Zero residual disagreements by construction.
- $/WAR growth (D9): 0.58%/yr = (11.23/10.85)^(1/6)-1 from FanGraphs' overall free-agent $/WAR series (2026 edition table, https://blogs.fangraphs.com/what-are-teams-paying-for-a-win-in-free-agency-2026-edition/): 2020 10.85, 2021 6.70, 2022 11.24, 2023 10.34, 2024 12.08, 2025 11.92, 2026 11.23 ($M). Only the 2026 edition's table could be retrieved (2023-2025 edition URLs 404). 2022 to 2026 is ~0%. Used for both $/WAR and the 2027+ minimum.
- Sensitivity, top-10 ev_surplus ($M, 2026 final): base 0.58%: Jenkins 39.6, Rodriguez 39.0, Willits 38.1, Curley 36.7, Walcott 35.2, Adams 34.8, De Vries 34.7, Salas 34.4, Made 32.2, Walton 32.2. At 3%: Jenkins 43.1, Willits 42.9, Rodriguez 42.9, Curley 40.6, Walcott 38.5, De Vries 38.0, Adams 37.8, Salas 37.5, Southisene 36.6, Walton 35.7. At 7%: Willits 52.2, Rodriguez 50.2, Jenkins 49.3, Curley 47.9, Southisene 45.1, Walcott 44.6, De Vries 44.2, Adams 43.3, Salas 43.2, Walton 42.4.


## B9 - Static site (S11, S13, C5, C7, U1, U2)

Run: `python run.py b9` (module `pipeline/b9_site.py`; tests `tests/test_b9.py`; ~15 s warm). Rerun after any upstream rerun; it only reads parquet/json and the cached Stats API `/teams` responses (parent org). Serve with `python3 -m http.server` from `site/`; deploy `site/` to Netlify as is (committed, including `site/data/`). Vanilla HTML/CSS/JS, no external scripts, charts are inline SVG built in `site/app.js`.

### Outputs (`site/`, about 9 MB, 3,081 players)
- `index.html`, `player.html?id=`, `method.html`, `app.css`, `app.js` (one script; `body[data-page]` picks the page).
- `data/leaderboard.json`: `{season, run_date, rows[]}`; row: id, name, org (MLB parent club via Stats API parentOrgName of the team_ids of the highest-level 2026 row), team, level, age, pos (MiLB), mlb_pos (mode of position_transition), group, low_conf, p_mlb, war, eta, ev/q10/q90 (millions USD; q are conditional on reaching), rank (by ev_surplus).
- `data/players/{id}.json`: bio, hist (last 3 seasons), chain (per 2026 level: K/BB/ISO/BABIP as [raw, park-neutral, MLE, regressed], park factors), blend (model inputs, stat group only), p_mlb, war{mean,q10,q50,q90}, eta{mean,q10,q90,debut{year:p}}, surplus{if_mlb,q10,q50,q90,ev} ($M), drivers{p_mlb,war}[{family,c,phrase,sup}] (sup = `suppressed`, rendered italic/neutral), batted (2025-26 tracked rows), pos_probs.
- `data/method.json`: C1 (computed from mlb_war vs bWAR), park examples, translation factors, CV/model choice, holdout (stat, prior), C2, C3, C4, disagreements, C8, C9, dollar_params, war_profile, sensitivity (top-10 ev at $/WAR growth base, 3%, 7%, computed by calling `b8_value.value` with overridden growth), coverage, run_date. The methodology prose is generated in JS from these numbers, so reruns update it.

### Notes
- Card EV = p_mlb x surplus_if_mlb (tested). Medians are labeled "median"; the mean is the central estimate (right-skewed outcomes).
- Pages verified at 375 px: no horizontal page scroll (tables scroll in their own region). Headless Chrome cannot render below ~500 px, so mobile screenshots in `docs/screens/*_375.png` are 375 px iframes.
- Spec deviations: none.


## B10 - 2026 snapshot run, smell test, publish (S12, C5, C6, Q9)

Run: `python run.py` (all steps, from cached raw data). `run.py` now prints per-step times. Full rebuild 2026-10-06: b1 22, b3 1, b2 1, b4 9, b5 1, b12 44, b6 63, b11 55, b7 2, b8 4, b9 22; total 223 s. Outputs byte-identical to the committed `site/` (rebuild is deterministic). `pytest`: 96 passed, 1 xfailed.

### C6 smell test (2026 top 50 vs MLB Pipeline Top 100, mlb.com/prospects/top100, read 2026-10-06)
- Pipeline list has 76 hitters (24 pitchers out of scope, X1). Matched by name to the leaderboard: 73. Not on the board: Tyler Bell, Derek Curiel (rookie-level/insufficient A+ sample). Luis Hernández (#25) matches two board players with the same name, rejected per Q12 (the 17-year-old prior-group row, board #917, is likely him).
- 33 of our top 50 are on Pipeline's list. Spearman of our rank vs Pipeline rank among matched hitters: 0.32 (p = 0.005).
- Consensus at the top: of Pipeline's top 10 hitters (Made, Arias, De Vries, De Paula, Willits, Gonzalez, Walcott, Rodriguez, Emerson, Jenkins), 8 are in our top 13. Exceptions: Josuar Gonzalez (#7 -> 44, A ball, p_mlb 0.84) and Grady Emerson (#12 -> 359).
- Disagreements, explained by drivers:
  1. 2025 draftees with little pro time fall to the S8 prior, which tops out near 3 WAR and has no scouting input: Emerson (#12 -> 359), Cholowsky (#14 -> 387), Lackey (#18 -> 362), Booth (#36 -> 352), Burress (#37 -> 578), Lombard (#65 -> 418). Draft pedigree drives their p_mlb; the WAR prior is flat. This is the largest systematic gap.
  2. International teenagers at rookie level get the population prior (Q1, no bonus data): Renteria (#73 -> 1,258), Gomez (#76 -> 1,390).
  3. College bats young for AA with strong walk rates rank well above Pipeline: Rincon (#96 -> 15; BB% 10.5 vs 5.9 avg, 1.8 yrs young for AA), Houston (#54 -> 14), Curley (unranked -> 4; BB% 10.6). Unranked top-25 hitters (Curley, Adams, Walton, Voit, Jesús Báez, Genao, Munroe, Primera) fit this profile.
  4. Very young for level: Southisene (#58 -> 11; 4.5 yrs young for AA), Ebel (#93 -> 20; 3.7 yrs young for A+). The Age family is the largest driver for both.
  5. Strikeouts pull down raw-tools players: Ethan Holliday (#23 -> 248; K% 46.2 in 152 PA at A), Ike Irish (#95 -> 398; average age for A+, bat-first position).
- Verdict: passes. The consensus elite are at the top, every large gap traces to a card driver, and the systematic gaps (recent draftees, international teenagers, age weighting) match the model's stated limits (S8, Q1, X7).

### Publish (Q9)
Code on GitHub; `site/` deployed to Netlify as a static folder (no build command).

Spec deviations: none.


## B14 - Fielding runs in WAR (S4, X2, A4, C1; user decision 2026-10-06)

Run: `python run.py` (209 s). `pipeline/b2_war.py::_fielding()` reads Baseball-Reference `runs_field` (DRS-based) from the cached `data/raw/bwar.csv`, summed over stints per mlb_ID x year; joined on player_id x season (100% of mlb_war rows match; missing would be 0). `mlb_war.parquet` gains `fld_runs` (float, runs). Column `owar` keeps its name but is now full WAR: (bat + park + bsr + fld + pos + repl) / RPW. bwar.csv is now a required input to b2 (was validation only); its 2026 PA total matches mlb_seasons exactly, so the cached file is complete. `validate()` adds `off` = owar - fld_runs/RPW.
- C1 (300+ PA, n=5,775): r vs bWAR 0.8631 -> 0.9508 (partly shared by construction); offense-only vs bWAR offensive components 0.9689 (the independent check, unchanged). Simmons 2017: fld_runs 36, gap to bWAR 1.7 (batting runs), was ~5.
- Model effect (target now includes defense, so old and new metrics measure different targets): train CV WAR Spearman ridge 0.3354 -> 0.2946 (ridge still chosen over LightGBM 0.2552). Holdout stat: ev Spearman 0.2162 -> 0.1652, WAR reached-only Spearman 0.3712 -> 0.3082, q10-q90 coverage 0.8006 -> 0.7719. P(MLB) unchanged. C3 still passes (Spearman 0.1652 vs naive 0.1456). C2 pooled: model 0.266 vs Pipeline 0.374, diff -0.109, 90% CI [-0.234, 0.010] (was -0.138, CI excluded 0). C9 table moves by < 0.002 per group, same keep decisions (S15_KEPT unchanged).
- Reading: fielding is harder to predict from minor league batting lines, so accuracy against the defense-inclusive target is lower, but the model now trails the Pipeline list by less on that target. 2026 board: projected CF +0.50 WAR and SS +0.36 on average, other positions ~0; top 15 unchanged in membership except Voit (17 -> 14); Kepley 31 -> 16, Quintero 34 -> 23.
- Spec updated (S4, X2, A4) as a recorded user decision.


## v1.1 revision (audit 2026-10-06; plan docs/fix-plan.md; spec S16, A13-A16, C10-C12, Q17, Q18)

Run: `python run.py` (all steps; `--refresh` re-pulls people and current-season API answers, otherwise the cache is permanent). Full rebuild from cache 2026-10-06: b1 19, b3 1, b2 1, b4 7, b5 1, b12 31, b6 29, b11 48, b7 3, b8 5 (b9 22); `pytest`: 105 passed, 2 xfailed (C4, C10). Order of work R0-R10, one commit each (R7 had no code change).

### R1 data (b1, common, run.py)
- `data/milb_history.parquet` (new; Q17): player_id x season x level x league_id, G, PA for MiLB 2000-2004 from the Stats API per team (sportIds 11-16; repo has no pre-2005 files). Career history only, never snapshots. AAA rows include the Mexican League (league 125, filtered in b5).
- `draft.parquet` now 1990-2026 (47,354 picks); `players.parquet` gains `pulled_on` (oldest people-cache date) and grows to 53,504 players (1990+ draftees).
- `common.api_get` caches as before; `cache_file(path, **params)` exposes the cache path; with `common.REFRESH` (set by `run.py --refresh`) answers that can change (paths starting `people`, or season == 2026) are re-fetched once per run.
- b5 draft record is now the latest with draft_year <= s. `international` means "no draft record (1990+) on or before s" (international signee or undrafted FA). Train-era rows flagged international that were actually 2000-04 draftees: 4,806 before the fix.

### R2 WAR (b2; A14)
- Run values per season = partial derivatives of BaseRuns at league totals (A = H + uBB + HBP - HR + .5 IBB, B = 1.02(1.4 TB - .6 H - 3 HR + .1(uBB + HBP)), C = outs, D = HR), scaled so league runs match, then the out value is set above average (absolute out - R/O; league linear weights sum to 0, RE24 convention). Ratios vs 1B: 2B 1.38-1.40, 3B 1.77-1.81, HR 2.22-2.31, BB .80; wOBA scale ~1.2 (was 1.57, HR/1B 2.78 under the old pooled OLS).
- C1 (n=5,775): r offense-only vs bWAR offense 0.9689 -> 0.9798; full r 0.9587 (partly shared by construction, fielding is bWAR's).

### R3 translations (b4; S6, C10)
- Pairs: same-season (>= 50 PA both) plus cross-season (L in s >= 300 PA -> L+1 in s+1 >= 300 PA), 11,735 + 4,810. Cross-season upper rates are divided by repeater aging drift by age bucket (<=21.5, 23.5, 25.5, older; `b4_k.json` aging_drift).
- Regression prior is now the source league-season mean MLE (was level-season). Because the chain factor is multiplicative this equals "regress at source, then translate"; it differs little from v1.
- C10 (in `b4_k.json`, `level_step()`): fails 6 of 12 cells (v1 same-season only: 10 of 12; cross-only: 7 of 12 with AAA->MLB ISO 0.855 from MLB survivor selection, so same+cross kept). Remaining gaps: BB +.0023 to +.0035 at every step, AA->AAA ISO +.0073 and BABIP +.0097. Note: movers are selected on a good season s, which biases C10 toward a negative gap, so the true harshness is if anything larger. The pre-registered +-1 SE band fails ~1/3 of cells even for an unbiased translation; recorded, not changed. Pooled AAA->MLB factors: K 1.239, BB .764, ISO .757, BABIP .886.

### R4 features (b5, b12; S16, S7, Q17, C9)
- `features.parquet` gains `debuted` (debut_year <= s; 3,000 train-era, 1,259 censored, 147 score rows) and `p_C_bt, p_SS_bt, p_CF_bt, exp_pos_runs_bt` (transition matrix fit on s<=2012 for the backtest fit; `b6.for_fit(df, 'backtest')` swaps them in). `eta_years` = debut - s (>= 1) for reached players not yet in MLB, NaN for debuted rows.
- `position_transition.parquet` gains `cutoff` (2012 | 2017). B9 uses cutoff 2017.
- pro_years, career_milb_pa and pace features use 2000-04 history (median pro_years now 4 in every train season; was 1, 2, 3, 4 for 2005-08).
- C9 rerun (s<=2012, debuted rows out, BABIP out): baseline logloss .3968 / ev Spearman .0855 (lower than v1's .14 because debuted rows were easy positives). Kept: contact, speed, posmix, body; dropped: batted, pace. `S15_KEPT` updated; contact's gain is within noise but the rule keeps it.

### R5 models (b6; A13, A16, A12, S16, C11)
- Hazard: person-period rows (snapshot x t = 1..9, s + t <= 2026, stop at debut); features = model features + t, t dummies, t x age_vs_level, t x level_num. CV (s<=2012, 77,290 person-years) logloss linear .0984 vs LightGBM .0989 -> linear. P(MLB) = 1 - S(9); `p_debut_t1..t9` = P(debut = s + t). CV calibration (fully observed rows, GroupKFold) within 4 points in every decile for every fit -> no Platt. Tail (`calibration_check.*.tail`): predicted .90-.98 reach ~6 points less often than predicted; all 118 rows predicted > .99 reached.
- WAR: ridge (CV Spearman .238 vs LightGBM .198). Training rows: reached, not debuted, uncensored, not pre2005, s <= 2012 (backtest) or s <= 2015 (fit2017, final).
- Spread (A16): log(|OOF residual| + .05) modeled from SPREAD_FEATS + the WAR prediction (OOF in training); candidates const / ridge / LightGBM by CV pinball (q10/50/90): stat LightGBM, prior ridge. Distribution = mean + war_scale x z, z = 199 centered standardized residual quantiles (`mod['z']`). C11 (CV): stat passes (subgroups .76-.83); prior fails only in the AA/AAA cell (n=18, 12 covered). Residual shape is right-skewed (z q10/50/90 -1.4/-.8/+2.1): CV top quintile realized mean 5.4 vs median 1.4 WAR. Median is miscalibrated in the bottom predicted quintile (16% below q50).
- Fits: backtest (train s<=2012 -> 2013-17), fit2017 (s<=2017 -> 2018-19, C12), final (hazard s<=2025 with censoring, WAR s<=2015 -> 2018-2026). Debuted rows: p_mlb 1, p_debut 0, eta 0.
- `predictions.parquet` columns: player_id, season, group, fit, p_mlb, p_debut_t1..t9, eta_mean (conditional on reaching), eta_q10, eta_q90, war_mean, war_scale, war_q10/50/90, ev_war, debuted, low_confidence, chosen_hazard, chosen_war. `b6_metrics.json`: cv_stat, chosen_stat, spread, calibration_check, holdout{stat|prior}_{backtest|fit2017}{all|player_disjoint}.
- Drivers: P(MLB) = hazard log-odds contributions averaged over t = 1..9 (t terms dropped, interactions folded into their base feature).

### R6 value (b8; S10, A15, S16)
- `contract_surplus(war_draws, debut_year, snapshot, share, prm)`: per control year max(value - salary, 0), discounted; years <= snapshot are sunk. `value()` averages over the 199 z draws and the hazard debut-year probabilities; ev_surplus = sum_t p_debut_t x E[surplus] = p_mlb x surplus_if_mlb; surplus_qXX are quantiles over draws. Debuted players: p = 1, debut_year from features.
- New family "Swing and miss" (contact features); "Contact quality" (BABIP) removed.
- 2026 board: EV rose most for players young for level (+$3.9M mean, vs +$0.9M for the oldest tercile); debuted players +$4.3M. Top 5: Willits, Walcott, De Vries, Made, Jenkins (in MLB).

### R8 backtest (b7, b7_scrape_top100, b7_top100; C12, D8)
- top100.csv adds Pipeline 2019 and 2020 (52 and 61 hitters matched; 2014-18 rows unchanged; matcher now replaces only scraped years; "pete" nickname added). Unmatched: 2019 Victor Victor Mesa; 2020 Brendan McKay (pitcher-coded), "Alex Kiriloff" (source misspelling, left unmatched per Q12), Jasson Dominguez.
- backtest.json adds C12, C2.player_disjoint, C3.player_disjoint, C3.v1_population_spearman_model, holdout_looks; backtest_players.parquet adds war_thru_2026, debuted, holdout.

### R9 single evaluation (2013-17: 5th look; 2018-19: first look)
- C3 passes: logloss .371 vs .447 naive; EV Spearman .106 vs .087 (n=6,552). On v1's population (debuted rows included) Spearman is .160 (v1 .165): the drop vs v1 is the population, not the model. Player-disjoint: .170 vs .147.
- C2 (2014-18 lists, n=264): model .243 vs Pipeline .370, diff -.127, 90% CI [-.249, -.004] (loses). Player-disjoint n=146: diff -.238.
- C4 fails: 2013-17 deciles 7-9 under-predict by 6.0, 5.4, 10.3 points; 2018-19 deciles 6, 8, 9 by 7.3, 6.9, 6.0. CV was within 4 points, so this reads as drift toward higher reach rates. Not recalibrated (pre-registered rule is CV-based).
- C12: P(MLB) logloss .391, AUC .866 (n=2,729); EV Spearman vs WAR through 2026 ties the naive baseline (2018 .074 vs .078; 2019 .085 vs .083); 2018 complete windows (fast risers, n=258) WAR Spearman .335 vs .262. Lists 2019-20 vs WAR through 2026 (n=113): model .300 vs Pipeline .113, diff +.187, CI [.016, .357]: shorter horizon that rewards quick arrival, small n.
- Pre-registered directions: lower-level MLEs rose vs AAA (yes); HR-heavy WAR fell (yes, HR/1B weight 2.78 -> 2.3); debuted EV rose (yes, +$4.3M); prospect ETA shortened (yes, 3.52 effective v1 -> 2.64, more than the expected ~0.5); EV rose most for young-for-level (yes); A/A+ P(MLB) moved toward post-2021 rates (a .253 -> .255, a+ .265 -> .287; AAA fell .51 -> .37, unexpected: v1 learned AAA reach rates partly from already-debuted rows); holdout Spearman within +-0.03 (no: -.06, explained by the population change above).

### R10 site (b9, app.js; C6, C7)
- leaderboard rows add `in_mlb`; cards add `in_mlb {debut, control_years_left}`, `eta` null for debuted, `blend` without BABIP plus `contact`, `people_pulled_on`. method.json adds C10, C12, holdout (new layout), holdout_looks, babip (audit ablation constants), model_choice.spread / calibration_check, people_pulled_on. Methodology prose rewritten for v1.1 (results, revision, translations, models, value, assumptions, limits).
- C7: no horizontal page scroll at 375 px on index, card, method (checked in the browser pane).
- C6 rerun vs MLB Pipeline Top 100 (mlb.com/prospects/top100, read 2026-10-06): 76 hitters, 73 matched (Luis Hernández ambiguous; Tyler Bell, Derek Curiel unmatched). 34 of our top 50 are on the list (v1 32); Spearman of our rank vs Pipeline rank .393 (v1 .356). Pipeline top 10 hitters: Made 4, Arias 6, De Vries 3, De Paula 34, Willits 1, Josuar Gonzalez 43, Walcott 2, Rodriguez 9, Emerson 138 (prior; v1 316), Jenkins 5. Draft-prior gap narrowed (Lackey 303 -> 176, Booth top prior). Largest disagreements: international teenagers on the population prior (Gomez, Renteria); Aidan Miller 37 -> 626 (2026 was 14 PA on an AA rehab stint after reaching AAA in 2025; the linear hazard reads a 14-PA season like a washout, -4.3 log-odds from Development pace; no injury data); Holliday and Carlson (A ball, K% heavy). Model higher: Ebel, Davalan, Southisene, Cannarella (young for level or strong K/BB). Verdict: passes, with the injury-season failure documented.

### Open items for v1.2 (not done; would be post-hoc after the R9 look)
- Injury-shortened seasons: use two-season volume or career-max level so a rehab season does not read as a washout (Miller).
- P(MLB) drift: a recency term or era-aware calibration, judged on CV with 2018+ censored data.
- C10 BB and AA->AAA residual harshness.

### Spec deviations
- C10 and C11 (prior) fail as reported above; C4 still fails. No deviation from the R0 decisions except: the spread model also uses the WAR prediction as an input (needed for C11; decided on CV before the R9 look).
