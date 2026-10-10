"""B22 checks on real outputs: pitch_predictions.parquet, data/models/pitch_*.joblib, b22_metrics.json."""
import json
from pathlib import Path

import joblib
import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def p():
    return pd.read_parquet(DATA / "pitch_predictions.parquet")


def test_unique_keys(p):
    assert not p.duplicated(["player_id", "season", "fit"]).any()


def test_ranges(p):
    assert p.p_mlb.between(0, 1).all() and (p.loc[p.debuted, "p_mlb"] == 1).all()
    assert (p.war_q10 <= p.war_q50).all() and (p.war_q50 <= p.war_q90).all()


def test_2026_rows_scored_by_final(p):
    f = pd.read_parquet(DATA / "pitch_features.parquet", columns=["player_id", "season", "group"])
    want = f[f.season == 2026]
    got = p[(p.fit == "final") & (p.season == 2026)]
    assert len(want) > 0 and want.merge(got, on=["player_id", "season", "group"]).shape[0] == len(want)


def test_models_load():
    for kind in ("stat", "prior"):
        for fit in ("backtest", "fit2017", "final"):
            assert len(joblib.load(DATA / "models" / f"pitch_{kind}_{fit}.joblib")["z"]) == 199


def test_metrics_no_holdout():
    m = json.loads((DATA / "b22_metrics.json").read_text())
    assert {"group_kfold", "forward_2009_to_2010_12"} <= set(m["c18"])
    assert "holdout" not in m and set(m["calibration_check"]) == {"stat_backtest", "prior_backtest"}
