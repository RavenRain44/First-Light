#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.evals import run_eval_set


def main() -> int:
    results = run_eval_set()
    print(json.dumps(results, indent=2))
    passed = sum(item["passed"] for item in results)
    print(f"{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
