"""B16 checks on real outputs (S18, D13-D15, D18, Q4)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import DATA, api_get  # noqa: E402

MILB = pd.read_parquet(DATA / "milb_pitching_seasons.parquet")
HIST = pd.read_parquet(DATA / "milb_pitch_history.parquet")
MLB = pd.read_parquet(DATA / "mlb_pitching.parquet")
PL = pd.read_parquet(DATA / "pitch_players.parquet")
IL = pd.read_parquet(DATA / "il_2026.parquet")
VAL = json.loads((DATA / "b16_api_validation_2024.json").read_text())


def test_no_duplicate_keys():
    assert not MILB.duplicated(["player_id", "season", "level", "league_id"]).any()
    assert not HIST.duplicated(["player_id", "season", "level", "league_id"]).any()
    assert not MLB.duplicated(["player_id", "season", "team_id"]).any()
    assert not PL.duplicated("player_id").any()
    assert set(MILB.player_id) | set(MLB.player_id) | set(HIST.player_id) == set(PL.player_id)


@pytest.mark.parametrize("season", range(2005, 2027))
def test_mlb_matches_api_team_totals(season):
    # exact: per-team rows + the S3 repair reproduce the API's team pitching totals
    t = api_get("teams/stats", stats="season", group="pitching", season=season, sportId=1, gameType="R", limit=100)
    api = pd.DataFrame([s["stat"] for s in t["stats"][0]["splits"]])[["battersFaced", "outs"]].sum()
    ours = MLB[MLB.season == season][["BF", "outs"]].sum()
    assert abs(ours.BF - api.battersFaced) / api.battersFaced <= 0.001
    assert abs(ours.outs - api.outs) / api.outs <= 0.001


def test_2024_repo_vs_api():
    for c in ["SO", "BB", "HR", "BF", "outs"]:
        assert VAL["per_stat_equal"][c] >= 0.98, c


def test_every_season_has_each_level():
    have = MILB.groupby("season")["level"].agg(set)
    for s in [s for s in range(2005, 2027) if s != 2020]:
        assert {"aaa", "aa", "a+", "a"} <= have[s], s


def test_rates_bounded_and_finite():
    for d in (MILB, MLB):
        for c in ["K_pct", "BB_pct", "HBP_pct", "HR_pct", "GS_share"]:
            assert d[c].dropna().between(0, 1).all(), c
        assert d.BABIP.dropna().between(0, 1).all()
        assert not np.isinf(d.select_dtypes("number")).any().any()
    assert (MLB.IP.dropna() == MLB.outs.dropna() / 3).all()


def test_spot_check_kershaw_2014():
    # league-wide API row, independent of the per-team pull
    d = api_get("stats", stats="season", group="pitching", sportId=1, season=2014, playerPool="All", limit=5000)
    api = next(s["stat"] for s in d["stats"][0]["splits"] if s["player"]["id"] == 477132)
    row = MLB[(MLB.player_id == 477132) & (MLB.season == 2014)].iloc[0]
    assert (row.BF, row.SO, row.outs) == (api["battersFaced"], api["strikeOuts"], api["outs"])


def test_il_snapshot():
    assert not IL.duplicated(["player_id", "date", "team_id", "description"]).any()
    assert IL.il_days.dropna().isin([7, 10, 15, 60]).all()
