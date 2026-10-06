"""B8 checks (S10, A6, A7, D9)."""
import joblib
import numpy as np
import pandas as pd

from pipeline.b8_value import MODELS, J_MAX, arrival_probs, family, full_contrib, load_params, surplus_if_mlb
from pipeline.common import DATA

PROF = pd.DataFrame({"share": [0.1, 0.15, 0.2, 0.2, 0.2, 0.15]})
PRM = load_params()
VAL = pd.read_parquet(DATA / "valuations.parquet")
GD = pd.read_parquet(DATA / "drivers_grouped.parquet")


def S(war, eta, snap=2026):
    return surplus_if_mlb(np.atleast_1d(war), np.atleast_1d(eta), np.atleast_1d(snap), PROF, PRM)


def test_arrival_sums_to_one():
    p = arrival_probs([0, 0.5, 3, 12])
    assert p.shape == (4, J_MAX + 1) and np.allclose(p.sum(axis=1), 1)
    pc = [c for c in VAL.columns if c.startswith("p_debut_")]
    assert len(pc) == 9 and np.allclose(VAL[pc].sum(axis=1), 1)


def test_surplus_increasing_in_war():
    s = S(np.linspace(-4, 12, 40), np.full(40, 1.5))
    assert (np.diff(s) > 0).all()


def test_later_eta_lowers_surplus():
    for w in (2.0, 6.0):
        s = S(np.full(5, w), np.array([0.2, 1, 2, 3, 5]))
        assert (np.diff(s) < 0).all()


def test_quantile_order():
    f = VAL[VAL.fit == "final"]
    assert (f.surplus_q10 <= f.surplus_q50 + 1e-6).all() and (f.surplus_q50 <= f.surplus_q90 + 1e-6).all()
    assert np.allclose(VAL.ev_surplus, VAL.p_mlb * VAL.surplus_if_mlb)


def test_params_pinned():
    p = pd.read_csv(DATA / "manual" / "dollar_params.csv")
    assert {"dollars_per_war_2026", "mlb_min_salary_2026", "arb_share_year1", "discount_rate"} <= set(p.param)
    assert p[p.param != "discount_rate"].source_url.notna().all()


def test_family_sums_and_other_empty():
    stat = GD[GD.group == "stat"]
    assert (stat.family != "Other").all()
    f = pd.read_parquet(DATA / "features.parquet")
    rows = f[(f.season == 2026) & (f.group == "stat")].head(200).reset_index(drop=True)
    full = full_contrib("final", "stat", rows).groupby(["player_id", "target"]).contribution.sum()
    grp = GD[(GD.fit == "final") & GD.player_id.isin(rows.player_id) & (GD.season == 2026) & (GD.group == "stat")].groupby(["player_id", "target"]).contribution.sum()
    assert np.allclose(grp.reindex(full.index), full, atol=1e-6)
    assert family("missingindicator_delta_K") == "Strikeouts" and family("highest_level=aa") == "Development pace"
