"""B8 checks (S10, S16, A15, A16, A6, D9)."""
import numpy as np
import pandas as pd

from pipeline.b8_value import contract_surplus, family, full_contrib, load_params
from pipeline.common import DATA

SHARE = np.array([0.1, 0.15, 0.2, 0.2, 0.2, 0.15])
PRM = load_params()
VAL = pd.read_parquet(DATA / "valuations.parquet")
GD = pd.read_parquet(DATA / "drivers_grouped.parquet")


def S(war, debut, snap=2026):
    war = np.atleast_2d(np.asarray(war, float)).T
    n = len(war)
    return contract_surplus(war, np.full(n, debut), np.full(n, snap), SHARE, PRM).ravel()


def test_surplus_nondecreasing_in_war_and_floored():
    s = S(np.linspace(-4, 12, 40), 2027)
    assert (np.diff(s) >= 0).all() and (s >= 0).all() and s[0] == 0 and s[-1] > 0


def test_later_debut_lowers_surplus():
    for w in (2.0, 6.0):
        s = np.array([S([w], d)[0] for d in range(2027, 2032)])
        assert (np.diff(s) < 0).all()


def test_floor_rewards_spread():  # A15: same mean, wider spread -> at least as much surplus
    narrow = S(np.full(2, 3.0), 2027).mean()
    wide = S(np.array([-3.0, 9.0]), 2027).mean()
    assert wide >= narrow


def test_sunk_years_for_debuted():  # S16: a 2025 debut valued at the 2026 snapshot keeps control years 3-6 only
    w = np.array([[6.0]])
    full = contract_surplus(w, np.array([2027]), np.array([2026]), SHARE, PRM)[0, 0]
    part = contract_surplus(w, np.array([2025]), np.array([2026]), SHARE, PRM)[0, 0]
    assert 0 < part < full


def test_valuation_identities():
    assert (VAL.ev_surplus >= -1e-6).all()
    assert np.allclose(VAL.ev_surplus, VAL.p_mlb * VAL.surplus_if_mlb, rtol=1e-6, atol=1)
    f = VAL[VAL.fit == "final"]
    assert (f.surplus_q10 <= f.surplus_q50 + 1e-6).all() and (f.surplus_q50 <= f.surplus_q90 + 1e-6).all()
    pc = [c for c in VAL.columns if c.startswith("p_debut_")]
    fresh = ~VAL.debuted
    assert len(pc) == 9 and np.allclose(VAL.loc[fresh, pc].sum(axis=1), VAL.p_mlb[fresh])
    assert (VAL[VAL.debuted].p_mlb == 1).all()


def test_params_pinned():
    p = pd.read_csv(DATA / "manual" / "dollar_params.csv")
    assert {"dollars_per_war_2026", "mlb_min_salary_2026", "arb_share_year1", "discount_rate"} <= set(p.param)
    assert p[p.param != "discount_rate"].source_url.notna().all()


def test_family_sums_and_other_empty():
    stat = GD[GD.group == "stat"]
    assert (stat.family != "Other").all() and "Contact quality" not in set(GD.family)  # BABIP out (S7 v1.1)
    f = pd.read_parquet(DATA / "features.parquet")
    rows = f[(f.season == 2026) & (f.group == "stat")].head(200).reset_index(drop=True)
    full = full_contrib("final", "stat", rows).groupby(["player_id", "target"]).contribution.sum()
    grp = GD[(GD.fit == "final") & GD.player_id.isin(rows.player_id) & (GD.season == 2026) & (GD.group == "stat")].groupby(["player_id", "target"]).contribution.sum()
    assert np.allclose(grp.reindex(full.index), full, atol=1e-6)
    assert family("missingindicator_delta_K") == "Development pace" and family("highest_level=aa") == "Development pace"
    assert family("blend_contact_rate") == "Swing and miss"


def test_war_interval():
    s = VAL[(VAL.group == "stat")]
    assert ((s.war_q10 <= s.war_q50) & (s.war_q50 <= s.war_q90)).all()
    assert ((s.war_q10 <= s.war_mean) & (s.war_mean <= s.war_q90)).all()
    # right-skewed outcomes: median at or below the mean (CV top quintile: realized mean 5.4, median 1.4 WAR)
    assert (s.war_q50 <= s.war_mean + 1e-9).all()


def test_phrase_direction_agrees_with_contribution():
    exp_map = {"Strikeouts": -1, "Walks": 1, "Power": 1, "Swing and miss": 1, "Speed": 1}
    g = GD[(GD.group == "stat") & GD.family.isin(list(exp_map))]
    exp = g.family.map(exp_map)
    assert ((g.input_dir * exp * g.contribution) >= 0).all()
    assert g[g.fit == "final"].suppressed.mean() < 0.25
    assert g[g.suppressed].phrase.str.contains("net effect also reflects").all()
