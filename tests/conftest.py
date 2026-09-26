from __future__ import annotations

from pathlib import Path

import pytest

from nctab.profiles.loader import Profile, load_profile

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.nc"))


@pytest.fixture(scope="session")
def fanuc() -> Profile:
    return load_profile("fanuc-mill")


@pytest.fixture(params=GOLDEN_FILES, ids=lambda p: p.name)
def golden_path(request: pytest.FixtureRequest) -> Path:
    return request.param
