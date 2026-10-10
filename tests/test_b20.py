"""B20 checks on real outputs: pitch_features.parquet, b20_psp.json, b20_c15.json."""
import json
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def f():
    return pd.read_parquet(DATA / "pitch_features.parquet")


def test_unique_keys(f):
    assert not f.duplicated(["player_id", "season"]).any()


def test_stat_rows_complete(f):
    s = f[f.group == "stat"]
    assert len(s) > 0 and s[["reg_K", "reg_BB", "reg_GB", "reg_XB"]].notna().all().all()


def test_rookie_eligible(f):
    mp = pd.read_parquet(DATA / "mlb_pitching.parquet").groupby(["player_id", "season"]).outs.sum().reset_index()
    m = f[["player_id", "season"]].merge(mp, on="player_id", suffixes=("", "_m"))
    thru = m[m.season_m <= m.season].groupby(["player_id", "season"]).outs.sum()
    assert (thru < 150).all()


def test_prior_rows_blank(f):
    cols = [c for c in f.columns if c.startswith(("reg_", "blend_reg_", "delta_reg_", "mera"))]
    assert f.loc[f.group == "prior", cols].isna().all().all()


def test_p_sp(f):
    assert f.loc[f.group == "stat", "p_sp"].between(0, 1).all() and f.loc[f.group == "prior", "p_sp"].isna().all()
    m = json.loads((DATA / "b20_psp.json").read_text())
    assert m["oof_logloss"] < m["baseline_logloss"] and m["oof_auc"] > 0.7


def test_c15_json():
    c = json.loads((DATA / "b20_c15.json").read_text())
    for k in ("mera_cv_blend", "mera_cv"):
        assert isinstance(c[k]["keep"], bool) and "d_logloss_gain" in c[k] and "d_spearman_gain" in c[k]
    assert c["kept_feature"] in (None, "mera_cv_blend", "mera_cv")


def test_splits(f):
    assert (f[f.split == "score"].season == 2026).all() and (f[f.split == "train_era"].season <= 2017).all()
    assert (f[f.split == "censored"].season.between(2018, 2025)).all()
    assert f.il_count.notna().eq(f.season == 2026).all()


def test_spot_check_gerrit_cole_2012(f):
    # Cole: UCLA college arm, 2011 #1 pick, AAA in 2012, debuted 2013 as a starter -> eta 1, stat group, all starts
    r = f[(f.name == "Gerrit Cole") & (f.season == 2012)].iloc[0]
    assert r.highest_level == "aaa" and r.group == "stat" and r.hs_draftee == 0 and r.round_num == 1
    assert r.debut_year == 2013 and r.eta_years == 1 and r.blend_GS_share > 0.95 and r.throws == "R"
