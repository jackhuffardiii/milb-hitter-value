"""B29 (v3 draft) checks: MLB WAR projections 2027-2032 and the C23 backtest."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import config

D = Path(__file__).resolve().parent.parent / "data"
p = pd.read_parquet(D / "mlb_projections.parquet")
YEARS = range(config.PROJ_FIRST, config.PROJ_FIRST + config.PROJ_YEARS)


def test_one_row_per_contracted_player():
    ids = pd.read_parquet(D / "mlb_contracts_2026.parquet").player_id.dropna().astype(int)
    assert not p.player_id.duplicated().any() and set(p.player_id) == set(ids)
    assert set(p.kind) <= {"hitter", "pitcher", "two_way"}


def test_war_and_pt_finite():
    for y in YEARS:
        assert np.isfinite(p[[f"war_{y}", f"pt_{y}"]].to_numpy()).all() and (p[f"pt_{y}"] >= 0).all()
    assert p.age_2026.notna().all()


def test_aging_curves():
    a = json.load(open(D / "b29_aging.json"))
    assert set(a) == {"hitter", "starter", "reliever"} and all(len(c) == 16 for c in a.values())


def test_c23():
    c = json.load(open(D / "b29_c23.json"))
    for kind in ("hitter", "pitcher"):
        assert set(c[kind]) >= {"ours", "marcel", "naive"} and c[kind]["pass"]
        assert len(c["residual_sd_by_pt_tercile"][kind]) == 3 and len(c["residual_sd_by_pt_tercile"][f"cuts_{kind}"]) == 2


def test_stars_project_well():
    assert (p[p.player_id.isin([592450, 665742])].war_2027 > 3).all()
