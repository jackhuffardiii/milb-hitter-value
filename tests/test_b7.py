"""B7 checks: top100.csv integrity and backtest.json shape."""
import json
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def t():
    return pd.read_csv(DATA / "manual" / "top100.csv")


def test_top100_shape(t):
    for y, g in t.groupby("list_year"):
        assert len(g) == 100 and sorted(g["rank"]) == list(range(1, 101)), y
    assert set(t.list_year) == set(range(2014, 2021))  # 2019-20 added for C12 (v1.1)
    assert t.source_url.notna().all() and t.source.isin(["ba", "pipeline"]).all()


def test_ids_unique_per_year_and_join(t):
    m = t[t.match_status == "matched"]
    assert m.player_id.notna().all()
    for y, g in m.groupby("list_year"):
        assert g.groupby("player_id").name.nunique().max() == 1, y
        assert not g.player_id.duplicated().any(), y
    f = pd.read_parquet(DATA / "features.parquet", columns=["player_id", "season"])
    keys = set(zip(f.player_id, f.season))
    for r in m.itertuples():
        assert (r.player_id, r.list_year - 1) in keys or (r.player_id, r.list_year - 2) in keys, r.name


def test_backtest_json():
    d = json.load(open(DATA / "backtest.json"))
    assert {"C2", "C3", "C4", "C12"} <= set(d)
    assert set(d["C12"]["ev_vs_war_thru_2026"]["all"]) == {"2018", "2019"}
    c2 = d["C2"]["primary_excl_censored"]
    vals = [c2["pooled"]["spearman_model"], c2["pooled"]["spearman_list"]]
    vals += [v[k] for v in c2["per_year"].values() for k in ("spearman_model", "spearman_list")]
    vals += [d["C3"]["primary_excl_censored"][k] for k in ("spearman_model", "spearman_baseline")]
    assert all(-1 <= v <= 1 for v in vals)
    assert len(d["C4"]["deciles"]) == 10
    p = pd.read_parquet(DATA / "backtest_players.parquet")
    assert p.player_id.notna().all() and p.ev_war.notna().all()
