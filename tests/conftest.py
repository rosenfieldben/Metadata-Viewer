import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    # Golden fixtures are generated, not committed; build them on demand so a
    # fresh clone can run the integration tests directly.
    if not (FIXTURES / "golden.png").exists():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_fixtures.py")],
            check=True,
        )
    return FIXTURES
