"""Fallback must never opt into Bedrock merely because Akamai fails."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("configured,expected", [(None, False), ("false", False), ("true", True)])
def test_strands_fallback_requires_opt_in(configured, expected):
    env = dict(os.environ)
    env.pop("STRANDS_FALLBACK_ENABLED", None)
    if configured is not None:
        env["STRANDS_FALLBACK_ENABLED"] = configured
    code = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
        "from app.config import settings; "
        f"assert settings.strands_fallback_enabled is {expected!r}"
    )
    subprocess.run([sys.executable, "-c", code], env=env,
                   cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
