"""B28 (v3 draft) checks: 2026 contracts from Baseball-Reference payroll pages."""
from pathlib import Path

import pandas as pd

d = pd.read_parquet(Path(__file__).resolve().parent.parent / "data" / "mlb_contracts_2026.parquet")


def test_all_teams_and_ids():
    assert d.team.nunique() == 30 and d.groupby("team").size().between(25, 60).all()  # offseason rosters dip below 30 after non-tenders
    assert d.player_id.notna().mean() > 0.98 and not d.duplicated(["team", "bbref_id"]).any()


def test_known_contracts():
    judge = d[d.name == "Aaron Judge"].iloc[0]
    assert judge.team == "NYY" and judge.sal_2026 == 40e6 and judge.raw_2032 == "FA"
    assert (d.service_years.dropna() >= 0).all() and d.service_years.max() < 25
