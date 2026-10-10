"""B30 checks: arbitration salary model (C24)."""
import json

import numpy as np
import pandas as pd
import pytest

from pipeline.b30_arb import OUT, league_min, predict_arb
from pipeline.b6_models import MODELS

if not (MODELS / "arb.joblib").exists():
    pytest.skip("B30 not run", allow_module_level=True)


def rows(**kw):
    base = dict(season=2026, prev_war=2.0, war_3yr=5.0, career_war=8.0, arb_year=2, is_pitcher=0, is_starter=0,
                prev_log_salary_rel=np.nan, prev_pt=500)
    return pd.DataFrame([{**base, **kw}])


def test_monotone_in_war_and_arb_year():
    war = predict_arb(pd.concat([rows(prev_war=w) for w in np.arange(-1, 8, 0.5)]))
    assert (np.diff(war) >= 0).all() and war[-1] > war[0]
    ay = predict_arb(pd.concat([rows(arb_year=k) for k in (1, 2, 3)]))
    assert (np.diff(ay) >= 0).all() and ay[-1] > ay[0]


def test_never_below_minimum():
    p = predict_arb(pd.concat([rows(prev_war=-3, war_3yr=-5, career_war=-5, arb_year=1, season=s) for s in (2015, 2026)]))
    assert (p >= league_min(np.array([2015, 2026]))).all()


def test_c24_has_holdout_for_model_and_baseline():
    h = json.loads(OUT.read_text())["holdout"]
    assert {"rmse_log", "median_abs_pct_err"} <= set(h["model"]) and {"rmse_log", "median_abs_pct_err"} <= set(h["baseline"])


def test_future_seasons_and_scalar_minimum():
    assert league_min(2026) == 780000 and league_min(2032) > league_min(2031) > 780000
    p = predict_arb(pd.concat([rows(season=s) for s in (2027, 2032)]))
    assert (p >= league_min(np.array([2027, 2032]))).all() and p[1] > p[0]
