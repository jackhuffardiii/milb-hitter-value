"""Run build steps in order. `python run.py` runs all registered; `python run.py b1` runs one."""
import importlib
import sys

ORDER = ["b1", "b3", "b2", "b4", "b5", "b12", "b6", "b11", "b7", "b8", "b9", "b10"]
MODULES = {"b1": "pipeline.b1_data", "b3": "pipeline.b3_park", "b2": "pipeline.b2_war", "b4": "pipeline.b4_mle", "b5": "pipeline.b5_features", "b12": "pipeline.b12_select",
           "b6": "pipeline.b6_models", "b11": "pipeline.b11_batted","b7": "pipeline.b7_backtest", "b8": "pipeline.b8_value"}  # add each step's module here when implemented

if __name__ == "__main__":
    want = sys.argv[1:] or [s for s in ORDER if s in MODULES]
    for step in want:
        print(f"== {step}", flush=True)
        importlib.import_module(MODULES[step]).main()
