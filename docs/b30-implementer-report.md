# B30 implementer report

CV (GroupKFold(5) by player, s 2011-2020, 2442 rows, RMSE in log space): ridge 0.411, LightGBM 0.369, v2 baseline 1.192.
Chosen: LightGBM (monotone constraints on prev_war, war_3yr, career_war, arb_year; early-stopped iterations from CV).
Holdout (s >= 2021, 1626 rows, one look): model RMSE 0.382, median abs % err 20.7%; baseline RMSE 1.043, median abs % err 82.4%.
Final model refit on all seasons: data/models/arb.joblib. Metrics: data/b30_c24.json.

Choices
- Baseline uses prev-season WAR as the WAR forecast: arb share x max(prev_war x $/WAR(s), min(s)); $/WAR deflated at the inflation param.
- WAR = owar + pwar; prev_pt = PA + BF (log1p in the model); pitcher = BF > PA.
- Super Two (2y120d to 3y) included as arb year 1 (399 rows, flagged `super_two` in build(), not a feature).
- prev_log_salary_rel: previous-season salary when he was arb-eligible (service >= Super Two) and above 1.05 x min, else NaN; ridge gets 0 plus indicator.
- Multi-year proxy: drop rows with salary equal to last season's. Blank-position rows excluded.
- LightGBM uses numeric arb_year (monotone constraint); ridge uses one-hot.
- predict_arb floors at the league minimum; league_min(season) is a float for a scalar, array otherwise; seasons after 2026 grow at mlb_min_salary_growth_2027plus (checked through 2032 in tests).

Deviations: monotone constraints added so the spec's monotonicity test holds. run.py not touched (ORDER "b30" after "b29", MODULES "b30": "pipeline.b30_arb" still to register).
Tests: tests/test_b30.py (4); full suite 188 passed, 3 xfailed.
