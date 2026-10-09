"""B17 checks on real outputs (S19, C13, C14)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import DATA  # noqa: E402

W = pd.read_parquet(DATA / "mlb_pitch_war.parquet")
LW = pd.read_parquet(DATA / "linear_weights.parquet").set_index("season")
T = pd.read_parquet(DATA / "pitch_war_target.parquet")


def test_no_duplicate_keys():
    assert not W.duplicated(["player_id", "season"]).any()
    assert not T.duplicated("player_id").any()


def test_c13_pitcher_war_anchor():  # S17: 410 WAR per 2,430 games every season, within 1 WAR
    assert (W.groupby("season").pwar.sum() - 410 * LW.games / 2430).abs().max() < 1


def test_c14_bwar_correlation():
    v = W[W.outs >= 300].dropna(subset=["bWAR"])
    assert v.pwar.corr(v.bWAR) >= 0.75


def test_replacement_near_fangraphs():  # Q20: solved RP level should sit near FanGraphs' 0.03 wins per 9
    assert W.repl_rp_per9.between(0.0, 0.06).all()


def test_leverage_only_on_relief():
    assert (W.loc[W.outs_relief == 0, "lev"] == 1).all()
    assert W.gmLI.notna().all()


def test_kershaw_2014():
    assert W[(W.player_id == 477132) & (W.season == 2014)].pwar.iloc[0] > 5
