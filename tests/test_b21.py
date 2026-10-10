"""B21 checks on real outputs: pitch_arsenal.parquet, pitch_contact.parquet, b21_c17.json."""
import json
from pathlib import Path

import pandas as pd

from pipeline.b9_site import savant_family

DATA = Path(__file__).resolve().parent.parent / "data"
arsenal = pd.read_parquet(DATA / "pitch_arsenal.parquet")
contact = pd.read_parquet(DATA / "pitch_contact.parquet")


def test_unique_keys():
    assert not arsenal.duplicated(["player_id", "season", "pitch_type"]).any()
    assert not contact.duplicated(["player_id", "season"]).any()


def test_usage_and_whiff():
    assert arsenal.usage.between(0, 1).all()
    # families cover most pitch codes; the remainder (e.g. unclassified) keeps the sum at or below 1
    assert arsenal.groupby(["player_id", "season"]).usage.sum().max() < 1.001
    assert arsenal.groupby(["player_id", "season"]).usage.sum().median() > 0.99
    assert arsenal.whiff.dropna().between(0, 1).all()


def test_velocity():
    assert 88 <= arsenal[arsenal.pitch_type == "FF"].velocity.median() <= 96


def test_movement_inches():
    med = arsenal[arsenal.pitches >= 100].groupby("pitch_type")[["ivb", "hb"]].median()
    assert 13 <= med.loc["FF", "ivb"] <= 19 and med.loc["SI", "ivb"] < med.loc["FF", "ivb"] - 4  # four-seam rides, sinker sinks
    assert med.loc["SI", "hb"] > med.loc["FF", "hb"] and med.loc["SL", "hb"] < 0 and med.loc["CH", "hb"] > 0


def test_c17_json():
    c = json.loads((DATA / "b21_c17.json").read_text())
    assert c["n"] > 0 and isinstance(c["pass"], bool)
    assert all(c[k] > 0 for k in ("rmse_observed", "rmse_blended", "rmse_shrunk_control"))


def test_hitter_cache_unchanged(monkeypatch):
    monkeypatch.setattr("pipeline.b9_site._get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert len(savant_family(2024, "Fastball")) > 0
