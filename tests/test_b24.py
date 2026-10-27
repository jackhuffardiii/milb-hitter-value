"""B24 checks on real outputs: board_2026.parquet, pitch_valuations.parquet, b24_c19.json."""
import json
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
b = pd.read_parquet(DATA / "board_2026.parquet")
pv = pd.read_parquet(DATA / "pitch_valuations.parquet")


def test_board():
    assert b.player_id.is_unique and set(b.role) <= {"H", "P", "2W"}
    assert (b["rank"] == range(1, len(b) + 1)).all() and b.ev_surplus.is_monotonic_decreasing


def test_pitcher_values():
    fin = pv[(pv.fit == "final") & (pv.season == 2026)]
    assert (pv.ev_surplus >= 0).all() and (fin.surplus_q10 <= fin.surplus_q90).all()


def test_c19():
    c = json.loads((DATA / "b24_c19.json").read_text())
    assert {"57/43", "61/39"} <= set(c) and all(0 <= c[k]["top50_overlap"] <= 50 for k in ("57/43", "61/39"))
