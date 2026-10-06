"""B6 checks on real outputs: predictions.parquet, drivers.parquet, b6_metrics.json."""
import json
from pathlib import Path

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
    assert p[["p_mlb", "war_mean", "eta_mean", "ev_war"]].notna().all().all()


def test_coverage(p):
    f = pd.read_parquet(DATA / "features.parquet")
    need = f[f.split.isin(["censored", "score"])][["player_id", "season", "group"]]
    got = p[p.fit == "final"][["player_id", "season"]]
    assert len(need.merge(got, how="left", indicator=True).query("_merge == 'left_only'")) == 0
    assert (p[p.fit == "final"].groupby("group").size().to_dict().keys()) == {"stat", "prior"}
    assert p[p.fit == "backtest"].season.between(2013, 2017).all()
    assert p[p.group == "prior"].low_confidence.all() and not p[p.group == "stat"].low_confidence.any()


def test_holdout_auc():
    m = json.loads((DATA / "b6_metrics.json").read_text())
    assert m["holdout_stat"]["auc"] > 0.75
