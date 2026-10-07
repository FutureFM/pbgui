"""Ship PB8 fork Organillo cartons (daily historical coin selection CSVs) with Vast jobs.

A carton is a local CSV/CSV.GZ referenced by ``backtest.organillo_carton_path`` and,
in suites, by ``backtest.organillo_carton_path`` scenario overrides. Cloud jobs copy
each distinct carton into ``input/organillo/<sha256><suffix>``, list it in the input
manifest (the worker verifies and caches it like market data), and point the shipped
config at the job's remote copy. Relative paths resolve against the PB8 directory,
which is the working directory of local PB8 optimizer runs.
"""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path

from vast_provider import VastError

SERVICE = 'Vast'
FOLDER = 'organillo'
MAX_CARTON_BYTES = 256 * 1024**2
_OVERRIDE_PATH = 'backtest.organillo_carton_path'
_OVERRIDE_MODE = 'backtest.organillo_mode'
_REMOTE = re.compile(r'/work/pbgui/jobs/[0-9a-f]{32}/input/' + FOLDER + r'/([0-9a-f]{64}\.csv(?:\.gz)?)')


def carton_slots(config: dict) -> list[tuple[dict, str]]:
    """Return (container, key) for every carton path PB8 would read for this config."""
    bt = config.get('backtest') or {}
    base_mode = bool(bt.get('organillo_mode', False))
    slots = []
    if base_mode and bt.get('organillo_carton_path'):
        slots.append((bt, 'organillo_carton_path'))
    if bt.get('suite_enabled'):
        for scenario in bt.get('scenarios') or []:
            overrides = scenario.get('overrides') if isinstance(scenario, dict) else None
            if not isinstance(overrides, dict) or not overrides.get(_OVERRIDE_PATH):
                continue
            if bool(overrides.get(_OVERRIDE_MODE, base_mode)):
                slots.append((overrides, _OVERRIDE_PATH))
    return slots


def uses_organillo(config: dict) -> bool:
    """True when any base or scenario window reads a carton."""
    return bool(carton_slots(config))


def local_carton(value, pb8_root: Path) -> Path:
    """Resolve one configured carton on the PBGui host, as local PB8 would."""
    if not isinstance(value, str) or not value.strip():
        raise VastError('Organillo requires backtest.organillo_carton_path', 422)
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = Path(pb8_root) / path
    path = path.resolve()
    if not path.name.endswith(('.csv', '.csv.gz')):
        raise VastError(f'Organillo carton must be a .csv or .csv.gz file: {value}', 422)
    if not path.is_file():
        raise VastError(f'Organillo carton not found on this host: {value}', 422)
    if path.stat().st_size > MAX_CARTON_BYTES:
        raise VastError(f'Organillo carton exceeds {MAX_CARTON_BYTES // 1024**2} MB: {value}', 422)
    return path


def localized(config: dict, pb8_root: Path) -> dict:
    """Copy the config with absolute local carton paths for PB8-side inspection."""
    result = copy.deepcopy(config)
    for container, key in carton_slots(result):
        container[key] = str(local_carton(container[key], pb8_root))
    return result


def remote_path(identifier: str, name: str) -> str:
    """Absolute carton path inside one job's verified remote input directory."""
    return '/work/pbgui/jobs/' + identifier + '/input/' + FOLDER + '/' + name


def stage_cartons(config: dict, pb8_root: Path, folder: Path, identifier: str, digest) -> list[dict]:
    """Copy cartons into the job input, retarget config paths, return manifest entries."""
    entries: dict[str, dict] = {}
    for container, key in carton_slots(config):
        source = local_carton(container[key], pb8_root)
        before = source.stat()
        checksum = digest(source)
        name = checksum + ('.csv.gz' if source.name.endswith('.gz') else '.csv')
        relative = Path(FOLDER) / name
        if str(relative) not in entries:
            destination = folder / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with source.open('rb') as src, destination.open('xb') as dest:
                shutil.copyfileobj(src, dest, 1024 * 1024)
            destination.chmod(0o600)
            after = source.stat()
            if ((before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns)
                    or digest(destination) != checksum):
                raise VastError('Organillo carton changed during preparation; prepare the job again', 409)
            entries[str(relative)] = {'path': str(relative), 'bytes': after.st_size, 'sha256': checksum}
        container[key] = remote_path(identifier, name)
    return list(entries.values())


def retarget(config: dict, identifier: str) -> None:
    """Point already-staged carton paths at another job's remote input directory."""
    for container, key in carton_slots(config):
        match = _REMOTE.fullmatch(str(container[key]))
        if match:
            container[key] = remote_path(identifier, match.group(1))


def shard_selection_config(config: dict, coins: list[str]) -> dict:
    """Widen approved coins to the carton universe for market-data export only.

    The shipped config is unchanged: PB8 replaces approved_coins per window itself,
    and scenarios without Organillo must keep their original universe.
    """
    result = copy.deepcopy(config)
    approved = result['live']['approved_coins']
    for side in ('long', 'short'):
        merged = list(approved.get(side) or [])
        merged.extend(coin for coin in coins if coin not in merged)
        approved[side] = merged
    return result
