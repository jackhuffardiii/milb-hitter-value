"""B25 checks on the combined site export (S30, C5, C22)."""
import json
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "site" / "data"
LB = json.loads((D / "leaderboard.json").read_text())["rows"]
B = pd.read_parquet(ROOT / "data" / "board_2026.parquet").set_index("player_id")
PV = pd.read_parquet(ROOT / "data" / "pitch_valuations.parquet").query("fit == 'final' and season == 2026").set_index("player_id")
PKEYS = {"kind", "id", "name", "rank", "n_ranked", "bio", "role", "hist", "chain", "arsenal", "p_mlb", "war", "eta", "surplus", "drivers"}


def test_one_combined_ranking():
    ids = [r["id"] for r in LB]
    assert len(ids) == len(set(ids)) == len(B) and set(ids) == set(B.index)
    assert [r["rank"] for r in LB] == list(range(1, len(LB) + 1))
    assert all(r["role"] == B.loc[r["id"], "role"] for r in LB)


def test_pitcher_cards():
    rows = [r for r in LB if r["role"] == "P"]
    for r in random.Random(3).sample(rows, 25):
        c = json.loads((D / "players" / f"{r['id']}.json").read_text())
        v = PV.loc[r["id"]]
        assert PKEYS <= set(c) and c["kind"] == "pitcher" and c["rank"] == r["rank"] and c["n_ranked"] == len(B)
        assert abs(c["surplus"]["ev"] - v.ev_surplus / 1e6) < 1e-3 and abs(c["p_mlb"] - v.p_mlb) < 1e-4
        assert abs(c["surplus"]["ev"] - c["p_mlb"] * c["surplus"]["if_mlb"]) < 0.05  # C5 on pitcher cards (C22)
        assert (c["role"]["p_sp"] is None) == (c["group"] == "prior")


def test_method_pitchers():
    m = json.loads((D / "method.json").read_text())["pitchers"]
    assert {"c15", "c17", "c18", "c2", "c3", "c12", "combined", "c19", "war_profile"} <= set(m)
