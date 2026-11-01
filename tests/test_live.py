"""Oracle live integration requires credentials; the release does not claim it was exercised."""

import pytest


def test_live_oracle_not_configured():
    pytest.skip("No Oracle credentials supplied; live SQL/TLS behavior is not verified.")
