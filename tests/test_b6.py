"""B6 checks on real outputs: predictions.parquet, drivers.parquet, b6_metrics.json."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def p():
    return pd.read_parquet(DATA / "predictions.parquet")


def test_unique_keys(p):
    assert not p.duplicated(["player_id", "season", "fit"]).any()
    d = pd.read_parquet(DATA / "drivers.parquet")
    assert not d.duplicated(["player_id", "season", "fit", "target", "rank"]).any()


def test_ranges(p):
    assert p.p_mlb.between(0, 1).all()
    assert (p.war_q10 <= p.war_q50).all() and (p.war_q50 <= p.war_q90).all()
    assert (p.eta_q10 <= p.eta_q90).all()
    assert (p.eta_mean >= 0).all() and (p.eta_q10 >= 0).all()
    assert p[["p_mlb", "war_mean", "eta_mean", "ev_war", "war_scale"]].notna().all().all() and (p.war_scale > 0).all()


def test_hazard_curve_consistent(p):  # A13: P(debut = s + t) sums to P(MLB); ETA >= 1 for players not yet in MLB
    pd_ = p[[f"p_debut_t{t}" for t in range(1, 10)]].sum(axis=1)
    fresh = ~p.debuted
    assert np.allclose(pd_[fresh], p.p_mlb[fresh], atol=1e-9)
    assert (p.loc[fresh, "eta_mean"] >= 1).all() and (p.loc[fresh, "eta_q10"] >= 1).all()


def test_debuted_scored_as_reached(p):  # S16
    d = p[p.debuted]
    assert len(d) > 0 and (d.p_mlb == 1).all() and (d.eta_mean == 0).all()


def test_coverage(p):
    f = pd.read_parquet(DATA / "features.parquet")
    need = f[f.split.isin(["censored", "score"])][["player_id", "season", "group"]]
    got = p[p.fit == "final"][["player_id", "season"]]
    assert len(need.merge(got, how="left", indicator=True).query("_merge == 'left_only'")) == 0
    assert (p[p.fit == "final"].groupby("group").size().to_dict().keys()) == {"stat", "prior"}
    assert p[p.fit == "backtest"].season.between(2013, 2017).all()
    assert p[p.group == "prior"].low_confidence.all() and not p[p.group == "stat"].low_confidence.any()


def test_cv_calibration_and_spread():  # s<=2012 / training CV only; holdout tests are added after the R9 look
    m = json.loads((DATA / "b6_metrics.json").read_text())
    for k, v in m["calibration_check"].items():
        assert v["max_abs_gap"] <= 0.05 and not v["platt_applied"], k
    assert m["spread"]["stat"]["c11_pass"]  # C11 (stat): every subgroup's 10-90 coverage within 0.80 +- 0.05


def test_war_chosen_by_spearman_and_s15_cols():
    m = json.loads((DATA / "b6_metrics.json").read_text())
    c = m["cv_stat"]["war"]
    assert m["chosen_stat"]["hazard"] == ("lightgbm" if m["cv_stat"]["hazard"]["lightgbm"] < m["cv_stat"]["hazard"]["linear"] else "linear")
    assert m["chosen_stat"]["war"] == ("lightgbm" if c["spearman_lightgbm"] > c["spearman_linear"] else "linear")  # A12
    import joblib
    cols = joblib.load(DATA / "models" / "stat_final.joblib")["cols"]
    assert "height_in" in cols and not {"weight_lb", "bmi"} & set(cols)  # S15, Q15
    assert not any("BABIP" in c for c in cols)  # S7 v1.1
