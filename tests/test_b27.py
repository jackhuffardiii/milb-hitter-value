"""B27 (v3 draft) checks: Cot's salaries joined to MLBAM ids (C27)."""
import json
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
if not (DATA / "mlb_salaries.parquet").exists():
    pytest.skip("Cot's workbook is local only (gitignored)", allow_module_level=True)
d = pd.read_parquet(DATA / "mlb_salaries.parquet")


def test_c27_coverage():
    assert json.loads((DATA / "b27_c27.json").read_text())["matched_share_paid_2010_2026"] >= 0.95


def test_no_id_twice_in_a_season():
    m = d[d.match_status == "matched"]
    listed = m[m.pos != ""]  # blank-position rows are a former club's deferred money for the same player
    assert not listed.duplicated(["season", "player_id"]).any()


def test_known_rows():
    soto = d[(d.season == 2026) & (d.name == "Juan Soto")].iloc[0]
    assert soto.player_id == 665742 and soto.salary == 61875000
