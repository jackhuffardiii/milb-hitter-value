"""B12 C9 selection artifacts (C9, S15)."""
import json
from pathlib import Path

from pipeline.b5_features import S15_GROUPS, S15_KEPT

c9 = json.loads((Path(__file__).resolve().parent.parent / "data" / "b12_c9.json").read_text())


def test_row_per_group():
    assert set(S15_GROUPS) <= set(c9["table"]) and "baseline" in c9["table"]
    for g in S15_GROUPS:
        assert {"logloss", "ev_spearman", "keep"} <= set(c9["table"][g])


def test_kept_consistent():
    assert c9["kept_features"] == S15_KEPT
    assert c9["kept_groups"] == [g for g in S15_GROUPS if c9["table"][g]["keep"]]
