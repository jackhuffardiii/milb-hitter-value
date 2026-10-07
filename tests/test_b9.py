"""B9 checks on the site export (S11, S13, C5, C7)."""
import json
import random
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
D = SITE / "data"
LB = json.loads((D / "leaderboard.json").read_text())["rows"]
V = pd.read_parquet(ROOT / "data" / "valuations.parquet")
V = V[(V.fit == "final") & (V.season == 2026)].set_index("player_id")
KEYS = {"id", "name", "org", "level", "age", "group", "low_conf", "hist", "chain", "p_mlb", "war", "eta", "surplus", "drivers", "batted", "pos_probs", "bio", "rank"}


def test_leaderboard_one_row_per_player():
    ids = [r["id"] for r in LB]
    assert len(ids) == len(set(ids)) == len(V) and set(ids) == set(V.index)
    assert all(r["org"] for r in LB)


def test_every_player_json_has_keys():
    for r in LB:
        c = json.loads((D / "players" / f"{r['id']}.json").read_text())
        assert KEYS <= set(c), r["id"]
        assert c["drivers"]["p_mlb"] and c["drivers"]["war"]
        if r["in_mlb"]:  # S16: already debuted; no ETA, remaining control years shown instead
            assert c["eta"] is None and c["in_mlb"]["control_years_left"] <= 5 and c["p_mlb"] == 1
        else:
            assert set(c["eta"]["debut"]) == {str(y) for y in range(2027, 2036)} and c["in_mlb"] is None
        assert "BABIP" not in (c["blend"] or {})  # BABIP is display only (S7 v1.1)


def test_cards_match_valuations():
    for r in random.Random(9).sample(LB, 10):
        c = json.loads((D / "players" / f"{r['id']}.json").read_text())
        v = V.loc[r["id"]]
        assert abs(c["surplus"]["ev"] - v.ev_surplus / 1e6) < 1e-3
        assert abs(c["surplus"]["q90"] - v.surplus_q90 / 1e6) < 1e-3
        assert abs(c["p_mlb"] - v.p_mlb) < 1e-4 and abs(c["war"]["mean"] - v.war_mean) < 1e-2
        assert abs(c["surplus"]["ev"] - c["p_mlb"] * c["surplus"]["if_mlb"]) < 0.05  # C5: EV = P(MLB) x surplus if MLB
        assert c["group"] == v.group and c["low_conf"] == bool(v.low_confidence)


def test_method_keys():
    m = json.loads((D / "method.json").read_text())
    assert {"C1", "C2", "C3", "C4", "C8", "C9", "C10", "C12", "babip", "holdout_looks", "dollar_params", "sensitivity", "run_date"} <= set(m)
    assert m["C1"]["r_owar_bwar"] >= 0.85


def test_no_external_references():
    for f in list(SITE.glob("*.html")) + list(SITE.glob("*.css")):
        assert "http://" not in f.read_text() and "https://" not in f.read_text(), f
    js = (SITE / "app.js").read_text()
    assert 'createElement("script")' not in js and "@import" not in js and "cdn" not in js.lower()
    # the only absolute URLs in JS are footer/source links (anchors), never loaded resources
    assert "fetch(\"http" not in js


def test_run_date_in_every_export():
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for f in [D / "leaderboard.json", D / "method.json", D / "players" / f"{LB[0]['id']}.json"]:
        j = json.loads(f.read_text())
        assert iso.match(j["run_date"]) and iso.match(j["data_through"]), f
