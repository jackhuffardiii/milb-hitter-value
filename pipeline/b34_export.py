"""B34: hand the model output to the Trade Web, the one public site (trade-web-merge-spec.md A2).

Copies trade.json, leaderboard.json and method.json into mlb-trade-web/public/data/projections/, writes a slim stat file
per prospect (milb/<id>.json: bio and level-by-level history, not the full card), then rebuilds the Trade Web's
values.json from the copied trade.json. Commit the result in the Trade Web repo.
"""
import json
import shutil
import subprocess

from . import config
from .b9_site import SITE, dump

CARD_KEYS = ["id", "name", "kind", "org", "team", "level", "age", "low_conf", "in_mlb", "bio", "hist"]


def main():
    out = config.TRADE_WEB / "public" / "data" / "projections"
    shutil.rmtree(out / "milb", ignore_errors=True)  # a player dropped from the board must not keep a stale file
    for name in ("trade.json", "leaderboard.json", "method.json"):
        dump(out / name, json.loads((SITE / name).read_text()))
    cards = sorted((SITE / "players").glob("*.json"))
    for f in cards:
        card = json.loads(f.read_text())
        dump(out / "milb" / f.name, {k: card[k] for k in CARD_KEYS if k in card})
    subprocess.run(["node", "scripts/fetch-values.mjs"], cwd=config.TRADE_WEB, check=True)
    print(f"b34: {len(cards)} prospect stat files and the value board written to {out}")


if __name__ == "__main__":
    main()
