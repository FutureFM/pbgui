# Unreleased

## Fixes

- Cloud optimizer queue: background input preparation now keeps the actual reason in **Last error** (for example missing local OHLCV files for a coin) instead of only "Input preparation failed; no instance rented". The reason is also written to `PBGui.log`.
