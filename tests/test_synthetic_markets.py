"""Purged perps from the PB8 fork's synthetic_markets.json reach mappings, backfill and Vast."""

import asyncio
import json
import os
import shlex
import time
from types import SimpleNamespace

import pytest

import synthetic_markets
import vast_market_cache as cache
from vast_provider import VastError

LUNA_ONBOARD_MS = 1611817200000


def _market(symbol, base, **extra):
    return {"id": base + "USDT", "symbol": symbol, "base": base, "quote": "USDT",
            "swap": True, "linear": True, "active": True, "info": {}, **extra}


def _luna():
    return _market("LUNA/USDT:USDT", "LUNA", info={"onboardDate": str(LUNA_ONBOARD_MS)})


@pytest.fixture
def pb8_root(tmp_path, monkeypatch):
    root = tmp_path / "pb8"
    monkeypatch.setattr(synthetic_markets, "pb8dir", lambda: str(root))
    return root


def _write_stubs(pb8_root, stubs, exchange="binance"):
    path = pb8_root / "caches" / exchange / synthetic_markets.FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stubs))


def test_no_pb8_directory_or_file_means_no_stubs(pb8_root, monkeypatch):
    assert synthetic_markets.load_synthetic_markets("binance") == {}
    monkeypatch.setattr(synthetic_markets, "pb8dir", lambda: "")
    assert synthetic_markets.load_synthetic_markets("binance") == {}


def test_stubs_are_forced_inactive_and_real_markets_win(pb8_root):
    _write_stubs(pb8_root, {"LUNA/USDT:USDT": _luna()})

    stubs = synthetic_markets.load_synthetic_markets("binance")
    assert stubs["LUNA/USDT:USDT"]["active"] is False
    assert synthetic_markets.is_synthetic_market(stubs["LUNA/USDT:USDT"])
    assert synthetic_markets.synthetic_onboard_ms("binance", "LUNA/USDT:USDT") == LUNA_ONBOARD_MS
    assert synthetic_markets.synthetic_onboard_ms("binance", "BTC/USDT:USDT") is None

    real = _market("LUNA/USDT:USDT", "LUNA", id="REAL")
    merged = synthetic_markets.merge_synthetic_markets("binance", {"LUNA/USDT:USDT": real})
    assert merged["LUNA/USDT:USDT"]["id"] == "REAL"


@pytest.mark.parametrize("stubs", [
    {"LUNA/USDT:USDT": _market("LUNA/USDT:USDT", "LUNA")},  # no onboardDate
    {"LUNA/USDT:USDT": _market("XYZ/USDT:USDT", "XYZ", info={"onboardDate": "1"})},
    ["not", "a", "dict"],
])
def test_malformed_stub_file_raises(pb8_root, stubs):
    _write_stubs(pb8_root, stubs)
    with pytest.raises(ValueError):
        synthetic_markets.load_synthetic_markets("binance")


def _local_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "coindata"
    source = root / "binance/ccxt_markets.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"BTC/USDT:USDT": _market("BTC/USDT:USDT", "BTC")}))
    monkeypatch.setattr(cache, "MARKET_ROOT", root)


def test_vast_snapshot_carries_stubs(tmp_path, monkeypatch, pb8_root):
    _local_snapshot(tmp_path, monkeypatch)
    _write_stubs(pb8_root, {"LUNA/USDT:USDT": _luna()})

    result = asyncio.run(cache.fetch_markets(["binance"]))["binance"]

    assert set(result["markets"]) == {"BTC/USDT:USDT", "LUNA/USDT:USDT"}
    assert set(result["synthetic"]) == {"LUNA/USDT:USDT"}
    assert result["markets"]["LUNA/USDT:USDT"]["active"] is False


def test_vast_snapshot_rejects_broken_stubs(tmp_path, monkeypatch, pb8_root):
    _local_snapshot(tmp_path, monkeypatch)
    _write_stubs(pb8_root, {"LUNA/USDT:USDT": _market("LUNA/USDT:USDT", "LUNA")})
    with pytest.raises(VastError, match="Synthetic market stubs are invalid"):
        asyncio.run(cache.fetch_markets(["binance"]))


def test_stage_installs_stub_file_next_to_markets(tmp_path, monkeypatch):
    stamp = time.time() - 1
    luna = {**_luna(), "active": False, "info": {"onboardDate": str(LUNA_ONBOARD_MS), "synthetic": True}}

    async def fetch(exchanges):
        return {
            "binance": {"markets": {"LUNA/USDT:USDT": luna}, "fetched_at": stamp,
                        "synthetic": {"LUNA/USDT:USDT": luna}},
            "bybit": {"markets": {"ETH/USDT:USDT": {"swap": True}}, "fetched_at": stamp},
        }

    def command(value, stdin, **kwargs):
        import subprocess
        import sys
        subprocess.run([sys.executable, "-c", shlex.split(value)[2]], stdin=stdin, check=True)

    stale = tmp_path / "output/caches/bybit/synthetic_markets.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    monkeypatch.setattr(cache, "fetch_markets", fetch)
    connection = SimpleNamespace(identifier="test", remote_root=str(tmp_path), command=command,
        store=SimpleNamespace(read=lambda identifier: {"exchanges": ["binance", "bybit"]}))

    cache.stage_public_markets(connection)

    stubs = tmp_path / "output/caches/binance/synthetic_markets.json"
    assert json.loads(stubs.read_text())["LUNA/USDT:USDT"]["info"]["onboardDate"] == str(LUNA_ONBOARD_MS)
    assert "LUNA/USDT:USDT" in json.loads((stubs.parent / "markets.json").read_text())
    assert not stale.exists()


def test_binance_backfill_uses_stub_inception_without_api(monkeypatch, pb8_root):
    import binance_best_1m as bb

    _write_stubs(pb8_root, {"LUNA/USDT:USDT": _luna()})
    monkeypatch.setattr(bb, "get_current_market_inception_ms", lambda coin: None)
    monkeypatch.setattr(bb, "_coin_to_ccxt_symbol", lambda coin: f"{coin}/USDT:USDT")
    monkeypatch.setattr(bb, "_get_ccxt_exchange", lambda *_: pytest.fail("purged perps must not be probed"))

    assert bb._ccxt_find_inception("LUNA") == LUNA_ONBOARD_MS
