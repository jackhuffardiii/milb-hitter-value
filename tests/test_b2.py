"""B2 checks on real outputs (S4, A2, C1)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import DATA, RAW  # noqa: E402

W = pd.read_parquet(DATA / "mlb_war.parquet")
LW = pd.read_parquet(DATA / "linear_weights.parquet")
T = pd.read_parquet(DATA / "war_target.parquet")


def test_no_duplicate_keys():
    assert not W.duplicated(["player_id", "season"]).any()
    assert not LW.duplicated("season").any()
    assert not T.duplicated("player_id").any()


def test_bat_runs_league_average_zero():
    # zero by construction over all hitters; non-pitchers sit within a few runs per 600 PA (pitcher bats excluded)
    g = W.groupby("season")[["bat_runs", "PA"]].sum()
    assert (g.bat_runs / g.PA * 600).abs().max() < 3


def test_woba_weight_order_and_rpw():
    assert (LW.w_uBB_HBP < LW.w_1B).all() and (LW.w_1B < LW.w_2B).all()
    assert (LW.w_2B < LW.w_3B).all() and (LW.w_3B < LW.w_HR).all()
    assert LW.RPW.between(8.5, 11).all()


def test_judge_2022():
    assert W[(W.player_id == 592450) & (W.season == 2022)].owar.iloc[0] > 8


def test_target_flags():
    assert T[T.pre2005].debut_season.max() < 2005
    assert (T.censored == (T.debut_season + 5 > 2026)).all()


BWAR = RAW / "bwar.csv"


@pytest.mark.skipif(not BWAR.exists(), reason="bWAR download unavailable/blocked (D7); validation skipped")
def test_c1_bwar_correlation():
    from pipeline.b2_war import validate
    j = validate(W)
    r = j.owar.corr(j.WAR)
    print(f"C1 r={r:.4f} n={len(j)}")
    assert r >= 0.85
    # elite glove / light bat: Andrelton Simmons 2017 (player_id 592743) oWAR well below bWAR
    s = j[(j.player_id == 592743) & (j.season == 2017)]
    assert len(s) == 1 and s.owar.iloc[0] < s.WAR.iloc[0] - 2


def test_bsr_present_and_league_wsb_zero():
    assert W.bsr_runs.notna().all() and W.wSB.notna().all()
    # wSB sums to 0 over ALL hitters (incl. pitchers, who are dropped from mlb_war). 2024-25 excluded: mlb_seasons
    # (B1) is ~2-4% short of the Stats API team totals in those seasons (see handoff B13).
    M = pd.read_parquet(DATA / "mlb_seasons.parquet").merge(LW, on="season")
    M["w"] = (M.SB * 0.2 + M.CS * M.runCS
              - M.lg_wSB * (M.H - M["2B"] - M["3B"] - M.HR + M.BB + M.HBP - M.IBB))
    g = M[M.season != 2024].groupby("season").w.sum()
    assert g.drop(2025).abs().max() < 1 and abs(g[2025]) < 2


def test_acuna_2023_wsb():
    assert W[(W.player_id == 660670) & (W.season == 2023)].wSB.iloc[0] > 5
