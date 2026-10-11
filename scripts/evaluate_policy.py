#!/usr/bin/env python3
"""Read-only aggregate policy comparison against retained local artifacts. No providers or activation."""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# Enforce offline evaluation before settings load (including dotenv overrides).
for name, value in {"MODEL_PROVIDER":"none", "AKAMAI_API_KEY":"", "OBJ_BUCKET":"", "SMTP_PASSWORD":"", "STRANDS_FALLBACK_ENABLED":"false"}.items():
    os.environ[name] = value

from app import db, policy
from app.config import settings
from engine.scoring import load_base_thresholds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=["baseline", "forecast"], default="forecast")
    parser.add_argument("--parameter", required=True)
    parser.add_argument("--value", type=float, required=True)
    parser.add_argument("--false-alarm-cost", type=float, default=1)
    parser.add_argument("--missed-disruption-cost", type=float, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (0 < args.false_alarm_cost <= 1000 and 0 < args.missed_disruption_cost <= 1000):
        parser.error("Scenario costs must be finite positive values no larger than 1000")
    source = settings.db_path.resolve()
    with tempfile.TemporaryDirectory(prefix="closure-policy-") as tmp:
        target = Path(tmp) / "evaluation.db"
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        manifest = source.parent / "cohorts" / "ames-7470-v1.json"
        if manifest.exists():
            (Path(tmp) / "cohorts").mkdir()
            shutil.copyfile(manifest, Path(tmp) / "cohorts" / manifest.name)
        settings.db_path = target
        engine = db.make_engine(f"sqlite:///{target}")
        db.set_engine(engine)
        base = load_base_thresholds()
        param = next((p for p in policy.parameters(base) if p["path"] == args.parameter), None)
        if param is None:
            parser.error("Parameter is not an allowed facility-policy parameter")
        changes = [{"path":args.parameter,"value":args.value}]
        cand = policy.candidate(base,param["category"],changes,"offline-comparison-v1")
        rows, excluded, frozen = policy.cohort_rows(args.cohort)
        p = {"incumbent":base.model_dump(mode="json"),"candidate":cand.model_dump(mode="json"),"category":param["category"],
             "cohort":args.cohort,"costs":{"false_alarm":args.false_alarm_cost,"missed_disruption":args.missed_disruption_cost},
             "constraints":{"minimum_recall":None,"maximum_false_alarm":None}}
        report = policy.evaluate_report(p,rows,excluded,frozen)
        report.update(parameter={**param,"proposed":args.value},activated=False,
                      note="Read-only comparison in a disposable database copy. No AI, cloud sync, archive download or notifications.")
        data = json.dumps(report,indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(data+"\n")
        else:
            print(data)
        engine.dispose()


if __name__ == "__main__":
    main()
