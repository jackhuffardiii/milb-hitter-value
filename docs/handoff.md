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
