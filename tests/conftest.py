from pathlib import Path

import pytest

from parakh_advisor.advice.policy import Policy
from parakh_advisor.ingest.normalise import build_portfolio
from parakh_advisor.ingest.wealthlens_json import load_rows

FIXTURE = Path(__file__).parent / "fixtures" / "holdings_synthetic.json"


@pytest.fixture(scope="session")
def rows():
    return load_rows(FIXTURE)


@pytest.fixture(scope="session")
def portfolio(rows):
    return build_portfolio(rows)


@pytest.fixture
def policy():
    return Policy()
