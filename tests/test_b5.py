"""B5 checks on real outputs: features.parquet, position_transition.parquet."""
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def f():
    return pd.read_parquet(DATA / "features.parquet")


@pytest.fixture(scope="module")
def tm():
    return pd.read_parquet(DATA / "position_transition.parquet")


def test_unique_keys(f):
    assert not f.duplicated(["player_id", "season"]).any()


def test_transition_rows_sum_to_one(tm):
    s = tm.groupby(["level_group", "milb_pos"]).p.sum()
    assert ((s - 1).abs() < 1e-9).all()


def test_transition_sanity(tm):
    p = tm.set_index(["level_group", "milb_pos", "mlb_pos"]).p
    for lg in ("low", "high"):
        assert p[(lg, "SS", "SS")] < 0.8
        assert p[(lg, "C", "C")] > 0.5


def test_stat_rows_have_mle(f):
    s = f[f.group == "stat"]
    assert len(s) > 0
    cols = [f"{p}_{r}" for p in ("reg", "blend") for r in ("K", "BB", "ISO", "BABIP")] + ["exp_pos_runs", "p_SS"]
    assert s[cols].notna().all().all()


def test_labels_consistent(f):
    r = f[f.reached_mlb]
    assert (r.eta_years >= 0).all() and r.eta_years.notna().all()
    assert f.loc[~f.reached_mlb, ["eta_years", "war_6yr"]].isna().all().all()


def test_splits(f):
    assert (f[f.split == "score"].season == 2026).all()
    assert (f[f.split == "train_era"].season <= 2017).all()
    assert f.split.isin(["train_era", "censored", "score"]).all()


def test_no_nan_war_6yr_for_reached_train_era():
    f = pd.read_parquet(DATA / "features.parquet")
    r = f[(f.split == "train_era") & f.reached_mlb]
    assert r.war_6yr.notna().all()
