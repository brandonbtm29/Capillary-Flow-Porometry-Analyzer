"""Where the real lab test files live (outside the repo, in SyncThing).

Order: $POROMETRY_TEST_DATA, else $UAKRON_DATA_DIR/Capillary Flow Porometer/Test Data,
else ~/SyncThing/UAkron Playground/Capillary Flow Porometer/Test Data.
Tests that need these files are skipped when they are not there (e.g. a fresh public clone).
"""

import json
import os
from pathlib import Path

import pytest


def _test_data_dir() -> Path:
    env = os.environ.get("POROMETRY_TEST_DATA")
    if env:
        return Path(env)
    base = os.environ.get("UAKRON_DATA_DIR") or Path.home() / "SyncThing" / "UAkron Playground"
    return Path(base) / "Capillary Flow Porometer" / "Test Data"


DATA = _test_data_dir()
# expected results for the lab files (kept next to them, not in the public repo)
_exp = DATA / "expected_values.json"
EXPECTED = json.loads(_exp.read_text(encoding="utf-8")) if _exp.exists() else {}
needs_data = pytest.mark.skipif(
    not (DATA / "CFP-0_25MM_MIN_TEST1.CFT").exists() or not EXPECTED,
    reason=f"lab test data not found at {DATA} (set POROMETRY_TEST_DATA)",
)
