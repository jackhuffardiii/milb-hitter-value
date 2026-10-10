# B20 implementer report (2026-10-10, unreviewed: verify every number)

Files: pipeline/b20_pitch_features.py (new; `pitch_X` for B22), tests/test_b20.py (8 tests), b5_features.py (`draft_features(snap, hs=False)`), run.py (b20 after b19). Nothing committed.

Claimed verification: hitter features.parquet `.equals` after `run.py b5` (68,662 x 75); `run.py b20` 13 s; pytest 160 passed, 3 xfailed.

Rows (split x group): train_era prior 26,011 / stat 21,467; censored 14,362 / 13,421; score 1,804 / 2,074.

Reach rate, train_era stat rows (pitchers vs hitters): a .218 vs .206 (n 3,977); a+ .226 vs .209 (5,260); aa .357 vs .321 (5,437); aaa .627 vs .604 (6,793). Note: the pre-registration expected pitcher P(MLB) at a level to be LOWER than hitters'; raw reach rates point the other way (check age-matched before calling it).

hs_draftee: school_class is NaN for ~86% of draft rows, so it falls back to school text (`\bHS\b|High School` -> 1, other non-empty -> 0). 31,931 college, 7,723 HS, 39,485 no record.

P(SP): n 1,413, base rate .253, OOF log loss .390 (constant .565), AUC .854. Stat rows only.

C15 (n 10,766; stat, s <= 2012, not debuted):
| candidate | logloss | ev Spearman | d_ll gain | d_sp gain | keep |
|---|---|---|---|---|---|
| baseline | .44907 | .10938 | | | |
| mera_cv_blend | .44839 | .10825 | +.00067 | -.00113 | true |
| mera_cv | .44660 | .10736 | +.00246 | -.00202 | true |
kept_feature = "mera_cv": picked by the implementer's own score (d_ll/.002 + d_sp/.005), not a spec rule. Weak keep given mERA's mild in-window leakage. Main session decides.

Spot check: Gerrit Cole 2012 (AAA, stat, R, round 1, blend_GS_share > .95, debut 2013, hs_draftee 0 from the 2011 UCLA record).

Choices it made: role features include rookie-ball rows; pitches_per_G NaN if any stint lacks pitches; levels_climbed_s NaN for 2005 pitchers whose prior MiLB year predates 2005; il_count / il_max_days on 2026 rows only; age_vs_level includes position players' mop-up BF; P(SP) debut year from pitch_players.
