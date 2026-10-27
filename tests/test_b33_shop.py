"""Shop a player (site/shop.js): the matcher finds the closest-to-even package, run through node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def shop(V, values, fair=10.0):
    js = (f"const s=require({json.dumps(str(ROOT / 'site/shop.js'))});"
          f"const b=s.shopTeam({V},{json.dumps([dict(id=i, v=v) for i, v in enumerate(values)])},{fair});"
          "console.log(JSON.stringify(b && {ids:b.assets.map(a=>a.id).sort(),gap:b.gap,even:b.even}))")
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


def test_closest_gap_then_fewest_pieces():
    # 50 = 30 + 15 + 5 exactly beats the 47 single ($3M short); negative and oversized assets are never used
    assert shop(50, [47, 30, 15, 5, -20, 200]) == {"ids": [1, 2, 3], "gap": 0, "even": True}
    # within $1M, the single wins on fewer pieces
    assert shop(50, [49.8, 30, 15, 5]) == {"ids": [0], "gap": pytest.approx(-0.2), "even": True}


def test_no_even_package_is_flagged():
    b = shop(100, [10, 12, 15])  # best is all three, $37M, far short
    assert b["ids"] == [0, 1, 2] and not b["even"]


def test_real_board_offers_are_even():
    T = json.loads((ROOT / "site/data/trade.json").read_text())
    star = max(T["assets"], key=lambda a: a["v"] if a["team"] == "CHC" else -1)
    other = [a for a in T["assets"] if a["team"] == "LAD"]
    js = (f"const s=require({json.dumps(str(ROOT / 'site/shop.js'))});"
          f"const b=s.shopTeam({star['v']},{json.dumps(other)},{T['fair']});"
          f"console.log(JSON.stringify({{gap:b.gap,tol:s.shopTol({star['v']},{T['fair']}),n:b.assets.length}}))")
    r = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert abs(r["gap"]) <= r["tol"] and 1 <= r["n"] <= 3
