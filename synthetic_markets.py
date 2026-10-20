"""Backtest-only market stubs for perpetuals an exchange no longer lists.

The PB8 fork reads ``caches/<exchange>/synthetic_markets.json`` (for example LUNA, MATIC and
EOS on Binance, purged from exchangeInfo but still in the public candle archive). PBGui reads the
same file from the configured PB8 directory so its market mappings, 1m backfill and Vast exports
see those markets too. Stubs are always inactive: they can be backtested, never traded.
"""

import json
from copy import deepcopy
from pathlib import Path

from pbgui_purefunc import pb8dir

SERVICE = "SyntheticMarkets"
FILENAME = "synthetic_markets.json"


def synthetic_markets_path(exchange: str) -> Path | None:
    """Return the PB8 fork's stub file for an exchange, or None without a PB8 directory."""
    configured = pb8dir()
    if not configured:
        return None
    return Path(configured).expanduser() / "caches" / str(exchange) / FILENAME


def load_synthetic_markets(exchange: str) -> dict:
    """Load validated stubs keyed by CCXT symbol; an absent file means none.

    Raises ValueError for a malformed file so callers decide whether to fail or degrade.
    """
    path = synthetic_markets_path(exchange)
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a markets dict")
    result = {}
    for symbol, market in raw.items():
        if not isinstance(market, dict) or market.get("symbol") != symbol:
            raise ValueError(f"{path}: market {symbol!r} must be a dict with matching 'symbol'")
        info = market.get("info")
        try:
            onboard = float(info.get("onboardDate") or 0) if isinstance(info, dict) else 0.0
        except (TypeError, ValueError):
            onboard = 0.0
        if onboard <= 0:
            raise ValueError(f"{path}: market {symbol!r} needs info.onboardDate (ms)")
        market = deepcopy(market)
        market["active"] = False
        market["info"]["synthetic"] = True
        result[symbol] = market
    return result


def is_synthetic_market(market) -> bool:
    return isinstance(market, dict) and bool((market.get("info") or {}).get("synthetic"))


def merge_synthetic_markets(exchange: str, markets: dict) -> dict:
    """Return markets plus stubs for symbols the exchange does not list; real markets win."""
    added = {k: v for k, v in load_synthetic_markets(exchange).items() if k not in markets}
    return {**markets, **added} if added else markets


def synthetic_onboard_ms(exchange: str, symbol: str) -> int | None:
    """First archived candle of a stubbed market, or None when the symbol has no stub."""
    market = load_synthetic_markets(exchange).get(symbol)
    return int(float(market["info"]["onboardDate"])) if market else None
