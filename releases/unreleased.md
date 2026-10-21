# Unreleased

## Features

- PB8 fork backtests of purged perpetuals: PBGui reads the fork's `caches/<exchange>/synthetic_markets.json` (for example LUNA, MATIC and EOS on Binance, delisted and removed from the exchange's market list but still in the public candle archive). Those markets get inactive rows in Market Data mappings, the Binance 1m backfill takes their first candle from the stub instead of probing the API, and cloud (Vast) jobs ship the stubs with the market snapshot so the worker can load their history. A malformed stub file is logged and ignored for mappings, and stops cloud preparation with a clear error.

## Fixes

- Cloud optimizer queue: background input preparation now keeps the actual reason in **Last error** (for example missing local OHLCV files for a coin) instead of only "Input preparation failed; no instance rented". The reason is also written to `PBGui.log`.
