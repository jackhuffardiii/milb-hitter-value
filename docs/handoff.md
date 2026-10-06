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

Design: features = STAT_NUM + one-hot STAT_CATS (bats, highest_level, milb_pos), PA counts log1p'd; no draft features. Linear: median impute (+missing indicators) + standardize; LightGBM num_leaves 15, lr .03, min_child 50, n_estimators = mean best_iter (early stopping on 20% group holdout inside each GroupKFold(5) fold) x1.1. Training sets: WAR rows = reached, war_target.censored False, pre2005 False; ETA rows = reached. Selection data = stat train_era s<=2012; same choice used for both fits. 'backtest' fit trains s<=2012, predicts stat+prior 2013-2017; 'final' trains s<=2017, predicts censored 2018-2025 + score 2026.

### data/predictions.parquet (grain player_id x season x fit; 43,365 rows: backtest 7,592 stat + 9,417 prior; final 12,466 stat + 13,890 prior)
player_id, season, group (stat|prior), fit (backtest|final), p_mlb, war_mean, war_q10/q50/q90 (sorted), eta_mean, eta_q10/q90 (>=0), ev_war = p_mlb*war_mean, low_confidence (True for prior), chosen_p_mlb / chosen_war / chosen_eta ('linear'|'lightgbm' for stat; prior always 'linear'). Prior WAR/ETA ranges are mean + empirical residual quantiles.
### data/drivers.parquet (stat rows only: backtest 2013-2017 and final 2026 score)
player_id, season, fit, target (p_mlb: log-odds contribution; war: wins), feature, feature_value (raw, imputed), contribution, rank (1-5 by |contribution|). Long format.
### data/b6_metrics.json
cv_stat (OOF log loss / RMSE / Poisson deviance per candidate + lgb n_estimators), chosen_stat, holdout_stat and holdout_prior (2013-2017 backtest fit: logloss, brier, auc, calibration deciles, war_rmse, eta_rmse, spearman_ev_vs_realized, spearman_war_reached_only, war_q10_q90_coverage), cv_prior.

### Quirks / spec deviations
- S8: signing_bonus is NaN for all draft years <= 2016 (B1 bonus coverage), so log_bonus is dropped by the imputer in prior training; prior models effectively use round, pick, international, age, level, PA, years since draft.
- Linear WAR ridge is chosen (ties LightGBM within CV noise) and leans on age heavily for young players (age coefficient contributes +3 to +4.5 WAR for 19-year-olds); its ranges (q10 ~ -0.4) come from the quantile LightGBMs.
- C4 calibration: see final report; holdout deciles 6-8 are under-predicted by 5-8.5 points (reach rate in 2013-2017 snapshots exceeds the 2005-2012 training rate).
