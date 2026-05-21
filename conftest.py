"""
Root conftest.py — applied to all tests automatically.
Blocks real network calls so tests can't accidentally hit Scryfall, EDHREC, or Anthropic.
Individual tests that need to test network code should mock at the function level.
"""

import urllib.request
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "Real network call blocked in tests. "
            "Use unittest.mock.patch to mock the function under test."
        )
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
