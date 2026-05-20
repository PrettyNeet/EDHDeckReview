"""Tests for deploy cache loading."""

import gzip
import json

from app.agents import card_lookup


def test_loads_gzipped_card_index_when_plain_json_missing(tmp_path, monkeypatch):
    card_index_gz = tmp_path / "card_index.json.gz"
    with gzip.open(card_index_gz, "wt", encoding="utf-8") as f:
        json.dump({"sol ring": {"name": "Sol Ring", "prices": {}}}, f)

    monkeypatch.setattr(card_lookup, "CARD_INDEX_PATH", tmp_path / "card_index.json")
    monkeypatch.setattr(card_lookup, "CARD_INDEX_GZ_PATH", card_index_gz)
    monkeypatch.setattr(card_lookup, "_INDEX", None)

    assert card_lookup.lookup("Sol Ring")["name"] == "Sol Ring"


def test_loads_gzipped_otag_index_when_plain_json_missing(tmp_path, monkeypatch):
    otag_index_gz = tmp_path / "otag_index.json.gz"
    with gzip.open(otag_index_gz, "wt", encoding="utf-8") as f:
        json.dump({"sol ring": ["mana-rock"]}, f)

    monkeypatch.setattr(card_lookup, "OTAG_INDEX_PATH", tmp_path / "otag_index.json")
    monkeypatch.setattr(card_lookup, "OTAG_INDEX_GZ_PATH", otag_index_gz)
    monkeypatch.setattr(card_lookup, "_OTAG_INDEX", None)

    assert card_lookup.lookup_otags("Sol Ring") == ["mana-rock"]
