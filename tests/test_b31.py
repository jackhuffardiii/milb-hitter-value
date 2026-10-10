"""B31/B32 (v3 draft) checks: MLB surplus, trade assets, simulator export."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
v = pd.read_parquet(ROOT / "data" / "mlb_values.parquet")
a = pd.read_parquet(ROOT / "data" / "trade_assets.parquet")


def test_values_shape():
    assert v.player_id.is_unique and (v.surplus_q10 <= v.surplus_q90).all()
    assert set(v.status_2027.dropna()) <= {"g", "a", "p"} and v.control_years.between(0, 6).all()


def test_floors_and_salaries():
    pre = v[v.status_2027 == "p"]
    assert (pre.salary_2027 > 0).all() and (pre.salary_2027 < 1e6).all()  # pre-arb pays about the minimum
    arb = v[v.status_2027 == "a"]
    assert (arb.salary_2027 >= pre.salary_2027.min()).all()


def test_known_players():
    skenes = v[v.name == "Paul Skenes"].iloc[0]
    assert skenes.surplus > 50e6  # cheap ace under control
    machado = v[v.name == "Manny Machado"].iloc[0]
    assert machado.surplus < 0  # long guaranteed deal past his projection


def test_assets_and_site():
    assert a.player_id.is_unique and a.team.notna().all() and a.team.nunique() == 30
    t = json.loads((ROOT / "site" / "data" / "trade.json").read_text())
    assert len(t["teams"]) == 30 and len(t["assets"]) == len(a) and t["cbt"] > 0
