"""Run build steps in order. `python run.py` runs all registered; `python run.py b1 b5` runs those; `python run.py --from b20`
runs b20 and every later step in ORDER (after a change in pipeline/config.py, see docs/CHANGING.md); `--refresh` re-pulls
people and current-season API answers."""
import importlib
import sys
import time

ORDER = ["b1", "b3", "b2", "b16", "b17", "b18", "b19", "b20", "b21", "b22", "b4", "b5", "b12", "b6", "b11", "b7", "b23", "b8", "b24", "b9", "b25", "b27", "b28", "b10"]
MODULES = {"b1": "pipeline.b1_data", "b3": "pipeline.b3_park", "b2": "pipeline.b2_war", "b16": "pipeline.b16_pitch_data", "b17": "pipeline.b17_pitch_war", "b18": "pipeline.b18_pitch_mle", "b19": "pipeline.b19_mera", "b20": "pipeline.b20_pitch_features", "b21": "pipeline.b21_pitch_tracking", "b22": "pipeline.b22_pitch_models", "b4": "pipeline.b4_mle", "b5": "pipeline.b5_features", "b12": "pipeline.b12_select",
           "b6": "pipeline.b6_models", "b11": "pipeline.b11_batted","b7": "pipeline.b7_backtest", "b8": "pipeline.b8_value", "b9": "pipeline.b9_site", "b23": "pipeline.b23_pitch_holdout", "b24": "pipeline.b24_pitch_value", "b25": "pipeline.b25_site", "b27": "pipeline.b27_salaries", "b28": "pipeline.b28_payroll"}  # add each step's module here when implemented

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--refresh"]
    if args[:1] == ["--from"]:
        args = [s for s in ORDER[ORDER.index(args[1]):] if s in MODULES]  # b10 (publish) has no module
    if "--refresh" in sys.argv:  # re-pull people and current-season API answers (cache is otherwise permanent)
        import pipeline.common
        pipeline.common.REFRESH = True
    want = args or [s for s in ORDER if s in MODULES]
    times = {}
    for step in want:
        print(f"== {step}", flush=True)
        t0 = time.time()
        importlib.import_module(MODULES[step]).main()
        times[step] = time.time() - t0
    print("== step times (s): " + ", ".join(f"{k} {v:.0f}" for k, v in times.items()) + f"; total {sum(times.values()):.0f}")
