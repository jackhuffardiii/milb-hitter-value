"""Methodology knobs, in one place. Change a value here, then rerun from the earliest step in its `rerun` note:
`.venv/bin/python run.py --from b4` reruns b4 and every step after it in run.py's ORDER. docs/CHANGING.md has the full map.
Dollar parameters ($/WAR, inflation, minimum salary, arbitration shares, discount rate) live in data/manual/dollar_params.csv.
Values here are the pre-registered v2 choices; a change is a methodology change, so log it in docs/handoff.md.
"""

# ---- WAR scale (S17, Q20). rerun: --from b2 (hitters) / --from b17 (pitchers); both feed the board.
POS_WAR_PER_2430 = 590  # position-player WAR per 2,430 MLB games (Baseball-Reference split)
PITCH_WAR_PER_2430 = 410  # pitcher WAR per 2,430 games
SP_RP_GAP = 0.09  # wins per 9 IP between starter (.380) and reliever (.470) replacement

# ---- Translations (S5, S6, S20, Q25). rerun: --from b18 (pitchers) / --from b4 (hitters).
MIN_PAIR = 50  # same-season matched pairs need >= this many PA/BF at both levels
MIN_PAIR_CROSS = 300  # cross-season pairs (L in s -> L+1 in s+1)
K_STAB_HIT = {"K": 60, "BB": 120, "ISO": 160, "BABIP": 820}  # regression constants (PA/AB/BIP), hitters
K_STAB_PITCH = {"K": 70, "BB": 170, "HBP": 640, "HR": 1320, "GB": 70, "XB": 1450, "R": 1000}  # Carleton (2012) points, pitchers

# ---- Snapshot eligibility (Q7, S25, S29). rerun: --from b20 (pitchers) / --from b5 (hitters).
STAT_MIN_PA = 150  # hitter stat group: A..AAA PA over s and s-1
STAT_MIN_BF = 150  # pitcher stat group: A..AAA BF over s and s-1 (and s-2 if under STAT_SHORT_OUTS in s)
STAT_SHORT_OUTS = 60
PITCHER_MIN_BF = 150  # a non-pitcher by bio enters the pitcher population at this many BF in s
ROOKIE_MAX_MLB_OUTS = 150  # pitcher snapshots require career MLB outs through s below this (50 IP)
BLEND_WEIGHTS = (3, 2)  # Marcel weights for season s and s-1 in the blend_* features

# ---- Training windows (A12, A13). rerun: --from b22 (pitchers) / --from b6 (hitters).
SELECT_CUTOFF = 2012  # every model choice uses s <= this (GroupKFold CV)
FIT2017_CUTOFF = 2017  # the 'fit2017' fit trains through this and predicts 2018-19
FINAL_CUTOFF = 2025  # the 'final' hazard trains through this (censored rows included)
WAR_CUTOFF_HIT = 2015  # last snapshot season in the WAR model (under 2% censored)
WAR_CUTOFF_PITCH = 2014

# ---- Tracking contact (S28, C17). rerun: --from b21.
CONTACT_XWOBA_ONLY = True  # True: tracked contact term = f(xwOBAcon) (Jack 2026-10-10); False: the C17 sample-size blend
CONTACT_MIN_AAA_BIP = 100  # B22 swaps reg_XB only for seasons with this many AAA balls in play

# ---- Two-way players (S29). rerun: --from b24.
TWO_WAY_MIN_PA = 150
TWO_WAY_MIN_BF = 150
