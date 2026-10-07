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
    s = tm.groupby(["cutoff", "level_group", "milb_pos"]).p.sum()
    assert ((s - 1).abs() < 1e-9).all()


def test_transition_sanity(tm):
    p = tm.set_index(["cutoff", "level_group", "milb_pos", "mlb_pos"]).p
    assert set(tm.cutoff) == {2012, 2017}  # per-fit matrices: backtest never sees holdout positions (v1.1)
    for c in (2012, 2017):
        for lg in ("low", "high"):
            assert p[(c, lg, "SS", "SS")] < 0.8
            assert p[(c, lg, "C", "C")] > 0.5


def test_stat_rows_have_mle(f):
    s = f[f.group == "stat"]
    assert len(s) > 0
    cols = [f"{p}_{r}" for p in ("reg", "blend") for r in ("K", "BB", "ISO", "BABIP")] + ["exp_pos_runs", "p_SS"]
    assert s[cols].notna().all().all()


def test_labels_consistent(f):
    assert (f.debuted == (f.debut_year <= f.season)).all()  # S16
    r = f[f.reached_mlb & ~f.debuted]
    assert (r.eta_years >= 1).all() and r.eta_years.notna().all()  # A13: ETA >= 1 for players not yet in MLB
    assert f.loc[f.debuted, "eta_years"].isna().all()
    assert f.loc[~f.reached_mlb, ["eta_years", "war_6yr"]].isna().all().all()


def test_splits(f):
    assert (f[f.split == "score"].season == 2026).all()
    assert (f[f.split == "train_era"].season <= 2017).all()
    assert f.split.isin(["train_era", "censored", "score"]).all()


def test_no_nan_war_6yr_for_reached_train_era():
    f = pd.read_parquet(DATA / "features.parquet")
    r = f[(f.split == "train_era") & f.reached_mlb]
    assert r.war_6yr.notna().all()


def test_s15_columns_and_ranges(f):
    from pipeline.b5_features import S15_GROUPS, S15_KEPT
    cols = [c for g in S15_GROUPS.values() for c in g]
    assert set(S15_KEPT) <= set(cols) and set(cols) <= set(f.columns)
    s = f[f.group == "stat"]
    assert f.loc[f.group == "prior", cols].isna().all().all()
    rates = [c for c in cols if c.endswith("_rate") or c.startswith(("pos_share", "blend_")) and "gofb" not in c] + ["sb_success"]
    for c in rates:
        v = s[c].dropna()
        assert len(v) > 0 and v.between(0, 1).all(), c
    assert s.height_in.dropna().between(60, 85).all() and s.weight_lb.dropna().between(110, 320).all()
    assert s.bmi.dropna().between(14, 45).all() and s.repeated_level.isin([0, 1]).all()
    assert (s.ascent_pace >= 0).all() and (s.games_at_current_level >= 1).all()


def test_contact_availability(f):
    s = f[(f.group == "stat") & (f.highest_level.isin(["a", "a+", "aa", "aaa"]))]
    assert s[s.season == 2026].contact_rate.notna().mean() > 0.95
    assert s[s.season == 2025].contact_rate.isna().all()  # Q16: no 2025 swings


def test_history_removes_left_censoring(f):  # Q17: 2000-04 backfill
    t = f[(f.split == "train_era") & (f.group == "stat")]
    med = t.groupby("season").pro_years.median()
    assert med.loc[2005] >= med.loc[2012] - 1
