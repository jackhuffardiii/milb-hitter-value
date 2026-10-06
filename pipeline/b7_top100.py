"""B7 part 1 (D8, Q6, Q12): build data/manual/top100.csv from /tmp scrape output.

Run once by hand (data is committed): `python -m pipeline.b7_top100 raw.json`.
Source: MLB Pipeline preseason Top 100 (BA lists are paywalled); source='pipeline'.
Matching rejects ambiguity (Q12): never guesses.
"""
import json, re, sys, unicodedata
import pandas as pd

PITCH = {"P", "RHP", "LHP", "SP", "RP"}
NICK = {"nick": "nicholas", "nicky": "nicholas", "mike": "michael", "matt": "matthew", "jake": "jacob", "joc": "joc",
        "jon": "jonathan", "alex": "alexander", "josh": "joshua", "zach": "zachary", "chris": "christopher",
        "dan": "daniel", "tom": "thomas", "ben": "benjamin", "sam": "samuel", "andy": "andrew", "rob": "robert",
        "jim": "james", "will": "william", "billy": "william", "bobby": "robert", "tony": "anthony", "joey": "joseph",
        "joe": "joseph", "jackie": "jackie", "dom": "dominic", "greg": "gregory", "gregory": "gregory",
        "adalberto": "adalberto", "teoscar": "teoscar"}
SUF = {"jr", "sr", "ii", "iii", "iv"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s.replace("-", " "))
    return [w for w in s.split() if w not in SUF]


def keys(name):
    w = norm(name)
    ks = {" ".join(w), " ".join([NICK.get(w[0], w[0])] + w[1:]) if w else ""}
    if len(w) > 2:  # drop middle names, e.g. "Raul Adalberto Mondesi" -> first+last
        ks.add(w[0] + " " + w[-1]); ks.add(NICK.get(w[0], w[0]) + " " + w[-1])
    return ks


def pos_ok(lp, mp):  # list position vs MiLB position; loose compatibility only
    if not isinstance(mp, str): return True
    parts = set(re.split(r"[/]", lp))
    if parts & {"INF", "IF"}: parts |= {"SS", "2B", "3B", "1B"}
    if "OF" in parts: parts |= {"LF", "CF", "RF"}
    return mp in parts or (mp in {"LF", "CF", "RF"} and "OF" in parts)


def main(raw):
    rows = json.load(open(raw))
    pl = pd.read_parquet("data/players.parquet")
    ft = pd.read_parquet("data/features.parquet", columns=["player_id", "season", "milb_pos", "team"])
    pl = pl.assign(ks=pl.full_name.fillna("").map(keys))
    out = []
    for r in rows:
        r = dict(r); ly = r["list_year"]
        r["is_hitter"] = any(p not in PITCH for p in r["pos"].split("/"))
        r["player_id"] = pd.NA; r["match_status"] = "pitcher"
        if r["is_hitter"]:
            kk = keys(r["name"])
            ids = pl[pl.ks.map(lambda s: bool(s & kk))].player_id
            res = "unmatched"
            for s in (ly - 1, ly - 2):
                c = ft[(ft.season == s) & ft.player_id.isin(ids)].drop_duplicates("player_id")
                if len(c) > 1:
                    c2 = c[c.milb_pos.map(lambda m: pos_ok(r["pos"], m))]
                    if len(c2) >= 1: c = c2
                if len(c) == 1: r["player_id"] = int(c.player_id.iloc[0]); res = "matched"; break
                if len(c) > 1: res = "ambiguous"; break
            r["match_status"] = res
        out.append(r)
    df = pd.DataFrame(out)[["list_year", "source", "source_url", "rank", "name", "pos", "org", "is_hitter", "player_id", "match_status"]]
    df["player_id"] = df.player_id.astype("Int64")
    df.to_csv("data/manual/top100.csv", index=False)
    h = df[df.is_hitter]
    print(h.groupby(["list_year", "match_status"]).size().unstack(fill_value=0))
    print(h[h.match_status != "matched"][["list_year", "rank", "name", "pos", "org", "match_status"]].to_string())


if __name__ == "__main__":
    main(sys.argv[1])
