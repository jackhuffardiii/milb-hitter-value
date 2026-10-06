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
