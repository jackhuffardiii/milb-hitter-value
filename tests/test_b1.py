"""B1 checks on the real outputs (S1-S3, D1, D3-D6, Q4). Run `python run.py b1` first."""
import pandas as pd
import pytest

D = "data/"
milb = pd.read_parquet(D + "milb_player_seasons.parquet")
players = pd.read_parquet(D + "players.parquet")
mlb = pd.read_parquet(D + "mlb_seasons.parquet")
draft = pd.read_parquet(D + "draft.parquet")
fld = pd.read_parquet(D + "mlb_fielding_games.parquet")


def expected_cells():
    for y in range(2005, 2027):
        if y == 2020:
            continue  # no MiLB season
        for lv in ["aaa", "aa", "a+", "a"]:
            yield y, lv
        if y <= 2019:
            yield y, "a-"  # short-season A ends 2020
        if y != 2006:
            yield y, "rk"  # repo has no 2006 rookie file (documented in handoff)


def test_every_season_level_cell_nonempty():
    got = milb.groupby(["season", "level"]).size()
    missing = [c for c in expected_cells() if got.get(c, 0) == 0]
    assert not missing
    assert not set(milb.season.unique()) & {2020}
    assert not ((milb.level == "a-") & (milb.season > 2019)).any()


def test_no_duplicate_keys():
    assert not milb.duplicated(["player_id", "season", "league_id", "level"]).any()
    assert not milb.duplicated(["player_id", "season", "league_id"]).any()  # a league sits at one level
    assert not mlb.duplicated(["player_id", "season", "team_id"]).any()
    assert not fld.duplicated(["player_id", "season", "position"]).any()
    assert not players.duplicated("player_id").any()
    assert not draft.duplicated(["draft_year", "pick_overall", "round"]).any()


def test_rates_consistent():
    for d in (milb, mlb):
        x = d[(d.AB > 0) & (d.SF == 0)]  # sac flies legitimately put OBP below AVG
        assert (x.OBP >= x.AVG - 1e-9).all()
        assert not d[["AVG", "OBP", "SLG", "BABIP", "K_pct", "BB_pct"]].isin([float("inf"), float("-inf")]).any().any()
        assert (x.AVG <= 1).all()


def test_players_join_and_ages():
    ids = set(milb.player_id)
    p = players.set_index("player_id")
    assert ids <= set(p.index)
    assert p.loc[list(ids), "birth_date"].notna().mean() >= 0.99
    a = milb.age.dropna()
    assert a.between(15, 50).all() and a.between(15, 45).mean() > 0.9999  # real 45+ vets exist (11 rows)
    assert milb.age.notna().mean() >= 0.99
    assert (set(mlb.player_id) | set(fld.player_id) | set(draft.player_id.dropna())) <= set(p.index)


def test_mlb_every_year():
    got = mlb.groupby("season").size()
    assert all(got.get(y, 0) > 500 for y in range(2005, 2027))  # 2026 is a full season as of build date
    assert set(fld.season) == set(range(2005, 2027))


def test_draft_full_range():
    assert set(draft.draft_year) == set(range(2005, 2027))
    assert draft.player_id.notna().mean() > 0.9
    assert draft.signing_bonus.notna().sum() > 0


def test_sources():
    assert set(milb[milb.season <= 2024].source) == {"repo"}
    assert set(milb[milb.season >= 2025].source) == {"statsapi"}


def test_s15_swings_and_types():
    s26 = milb[(milb.season == 2026) & milb.level.isin(["a", "a+", "aa", "aaa"])]
    assert (s26.swings > 0).mean() > 0.95
    assert milb[milb.season == 2025].swings.isna().all()
    r = milb[milb.source == "repo"]
    assert r[["FO", "PO", "LO", "ground_hits", "fly_hits", "pop_hits", "line_hits", "GiDP"]].notna().all().all()
    assert {"pos_g_SS", "pos_g_CF", "pos_g_C"} <= set(milb.columns)
    assert players.height_in.dropna().between(55, 90).all() and players.weight_lb.dropna().between(100, 400).all()
    assert players.height_in.notna().mean() > 0.9


# S3: player rows must add up to the Stats API team totals (the per-team pull once dropped traded-away stints)
STAT = {"H": "hits", "HR": "homeRuns", "BB": "baseOnBalls", "SO": "strikeOuts", "SB": "stolenBases"}


def _api_totals(sport, season):
    from pipeline.common import api_get
    d = api_get("teams/stats", stats="season", group="hitting", season=season, sportId=sport, gameType="R", limit=100)
    return {c: sum(s["stat"][k] for s in d["stats"][0]["splits"]) for c, k in STAT.items()}


def _check_totals(df, sport, season):
    got, want = df[list(STAT)].sum(), _api_totals(sport, season)
    bad = {c: (int(got[c]), want[c]) for c in STAT if abs(got[c] - want[c]) > 0.005 * want[c]}
    assert not bad, f"{sport}/{season} player sums vs API team totals (got, want): {bad}"


@pytest.mark.parametrize("season", range(2005, 2027))
def test_mlb_matches_api_team_totals(season):
    _check_totals(mlb[mlb.season == season], 1, season)


@pytest.mark.parametrize("season,level,sport", [(y, lv, sp) for y in (2025, 2026)
                                                for lv, sp in {"aaa": 11, "aa": 12, "a+": 13, "a": 14, "rk": 16}.items()])
def test_milb_api_matches_team_totals(season, level, sport):
    _check_totals(milb[(milb.season == season) & (milb.level == level)], sport, season)
