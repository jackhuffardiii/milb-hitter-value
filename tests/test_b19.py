"""B19 checks on real outputs (S21, S22, C15 slope test)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.common import DATA  # noqa: E402

M = pd.read_parquet(DATA / "pitch_mera.parquet")
PS = pd.read_parquet(DATA / "pitch_mera_player_season.parquet")
R = json.loads((DATA / "b19_mera.json").read_text())
LEVELS = ["a", "a+", "aa", "aaa"]


def test_unique_keys():
    assert not M.duplicated(["player_id", "season", "level", "league_id"]).any()
    assert not PS.duplicated(["player_id", "season"]).any()


def test_mera_on_run_average_scale():
    x = M.mera.dropna()
    assert np.isfinite(x).all() and x.between(1, 20).all()
    assert M.mera.notna().mean() > 0.95


def test_ladder_rises_toward_mlb():  # S22: runs chain factors > 1, so each higher level shows a higher run average
    cols = [f"mera_{lv}" for lv in LEVELS] + ["mera"]
    a = M[M.level == "a"].dropna(subset=cols)
    assert len(a) > 1000
    assert all((a[lo] < a[hi]).all() for lo, hi in zip(cols[:-1], cols[1:]))
    assert M.loc[M.level == "aaa", ["mera_a", "mera_a+", "mera_aa"]].isna().all().all()


def test_spec_chosen_by_cv_and_converged():
    assert R["chosen"] == min(R["cv_weighted_mse"], key=R["cv_weighted_mse"].get)
    assert all(v < R["cv_baseline_weighted_mean"] for v in R["cv_weighted_mse"].values())
    assert R["fit_cv"]["rhat_max"] < 1.05 and R["fit_final"]["rhat_max"] < 1.05


def test_strikeouts_lower_mera():
    assert R["fit_final"]["b_pooled"]["reg_K"] < 0 and R["fit_final"]["b_pooled"]["reg_BB"] > 0


def test_cv_fit_predicts_later_seasons():
    # mera_cv was fit on target seasons <= 2012: target seasons >= 2014 are out of sample for it
    o = M[(M.season >= 2013) & (M.BF >= 50) & (M.BF_next >= 100)].dropna(subset=["mera_cv", "next_ra9_mle"])
    w = o.BF_next
    cw = np.cov(o.mera_cv, o.next_ra9_mle, aweights=w)
    assert cw[0, 1] / np.sqrt(cw[0, 0] * cw[1, 1]) > 0.2
