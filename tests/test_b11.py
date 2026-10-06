"""B11 checks on real outputs (S13, S14, C8, Q14)."""
import numpy as np
import pandas as pd

from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

CLASSES = ["out", "1B", "2B", "3B", "HR"]


def test_bip_unique_and_levels():
    b = pd.read_parquet(DATA / "bip.parquet")
    assert set(b.level) <= {"aaa", "a"} and set(b.source) == {"savant"}
    assert b.launch_speed.notna().all() and b.launch_angle.notna().all()
    assert set(b.outcome) <= set(CLASSES)
    P = b[[f"p_{c}" for c in CLASSES]]
    assert np.allclose(P.sum(axis=1), 1, atol=1e-6)


def test_batted_ball_table():
    t = pd.read_parquet(DATA / "batted_ball.parquet")
    assert not t.duplicated(["player_id", "season", "level"]).any()
    assert set(t.level) <= {"aaa", "a"}
    big = t[t.n_bip_tracked >= 50]
    assert len(big) > 0 and (big.barrel_pct <= big.hard_hit_pct + 1e-9).all()


def test_predictions_final():
    f = pd.read_parquet(DATA / "predictions_final.parquet")
    p = pd.read_parquet(DATA / "predictions.parquet").query("fit == 'final'")
    assert not f.duplicated(["player_id", "season"]).any()
    assert set(zip(f.player_id, f.season)) == set(zip(p.player_id, p.season)) and len(f) == len(p)
    bb = pd.read_parquet(DATA / "batted_ball.parquet")
    trk = set(zip(bb.player_id, bb.season))
    a = f[f.s14_applied]
    assert all(k in trk for k in zip(a.player_id, a.season))
    assert a.ev_war_base.notna().all() and f[~f.s14_applied].ev_war_base.isna().all()
