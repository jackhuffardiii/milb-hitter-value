"""B3 checks on real outputs: data/park_factors.parquet, data/milb_player_park.parquet."""
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
COMPS = ["1B", "2B3B", "HR", "BB", "SO", "BABIP", "R"]

PF = [f"pf_{c}" for c in COMPS]


@pytest.fixture(scope="module")
def pf():
    return pd.read_parquet(DATA / "park_factors.parquet")


@pytest.fixture(scope="module")
def pp():
    return pd.read_parquet(DATA / "milb_player_park.parquet")


def test_no_duplicate_keys(pf, pp):
    assert not pf.duplicated(["sport", "season", "team_id"]).any()
    assert not pp.duplicated(["player_id", "season", "level", "league_id"]).any()
    assert pf[PF].notna().all().all()


def test_league_season_mean_is_one(pf):
    w = pf.PA_home + pf.PA_road
    for c in PF:
        m = (pf[c] * w).groupby([pf.sport, pf.season, pf.league_id]).sum() / w.groupby([pf.sport, pf.season, pf.league_id]).sum()
        assert m.between(0.99, 1.01).all(), (c, m.min(), m.max())


def test_regressed_closer_to_one(pf):
    for c in COMPS:
        assert (pf[f"pf_{c}"] - 1).abs().mean() < (pf[f"raw_{c}"] - 1).abs().mean(), c


def test_coverage(pf, pp):
    ps = pd.read_parquet(DATA / "milb_player_seasons.parquet")
    m = ps.merge(pp, on=["player_id", "season", "level", "league_id"], how="left", validate="1:1")
    hi = m[m.level.isin(["aaa", "aa", "a+", "a"])]
    assert hi.ppf_HR.notna().all() and hi[[f"ppf_{c}" for c in COMPS]].notna().all().all()
    assert len(pp) == len(ps)
    print("coverage rk/a-:", m[m.level.isin(["rk", "a-"])].groupby("level").ppf_HR.apply(lambda s: s.notna().mean()).to_dict())


def test_mlb_every_team_season(pf):
    mlb = pd.read_parquet(DATA / "mlb_seasons.parquet")[["season", "team_id"]].drop_duplicates()
    have = pf[pf.sport == "mlb"][["season", "team_id"]]
    assert len(mlb.merge(have, how="left", indicator=True).query("_merge == 'left_only'")) == 0


def test_coors_hr_and_runs(pf):
    col = pf[(pf.sport == "mlb") & (pf.team_id == 115)]
    assert (col.pf_HR > 1.05).mean() > 0.5 and (col.pf_R > 1.05).mean() > 0.5


def test_abq_or_lv_hr_aaa(pf):
    # Albuquerque 342, Las Vegas 400/529 (team ids by franchise era); take the max AAA HR factor per season
    top = pf[pf.level == "aaa"].groupby("season").pf_HR.max()
    assert (top > 1.10).mean() > 0.5
