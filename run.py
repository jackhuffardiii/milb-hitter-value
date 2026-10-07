"""Run build steps in order. `python run.py` runs all registered; `python run.py b1` runs one; `--refresh` re-pulls
people and current-season API answers."""
import importlib
import sys
import time

ORDER = ["b1", "b3", "b2", "b4", "b5", "b12", "b6", "b11", "b7", "b8", "b9", "b10"]
MODULES = {"b1": "pipeline.b1_data", "b3": "pipeline.b3_park", "b2": "pipeline.b2_war", "b4": "pipeline.b4_mle", "b5": "pipeline.b5_features", "b12": "pipeline.b12_select",
           "b6": "pipeline.b6_models", "b11": "pipeline.b11_batted","b7": "pipeline.b7_backtest", "b8": "pipeline.b8_value", "b9": "pipeline.b9_site"}  # add each step's module here when implemented

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--refresh"]
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
