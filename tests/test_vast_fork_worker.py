"""Custom PB8 fork worker pins and Organillo carton shipping for Vast jobs."""

import hashlib
import sys
import types
from pathlib import Path

import pytest

import pb8_config_helper
import vast_organillo as organillo
from vast_provider import VastError
from vast_worker_image import DEFAULT_IMAGE, DEFAULT_REVISION, resolve_worker

FORK_IMAGE = 'ghcr.io/futurefm/pbgui-pb8-worker@sha256:' + 'a' * 64
FORK_REVISION = 'b' * 40
JOB = 'c' * 32
OTHER_JOB = 'd' * 32


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_worker_defaults_to_upstream_without_settings() -> None:
    assert resolve_worker({}) == (DEFAULT_IMAGE, DEFAULT_REVISION, None)
    assert resolve_worker(None) == (DEFAULT_IMAGE, DEFAULT_REVISION, None)


def test_worker_accepts_a_complete_fork_pin() -> None:
    image, revision, error = resolve_worker({'worker_image': FORK_IMAGE, 'worker_revision': FORK_REVISION.upper()})
    assert (image, revision, error) == (FORK_IMAGE, FORK_REVISION, None)


@pytest.mark.parametrize('section', [
    {'worker_image': FORK_IMAGE},
    {'worker_revision': FORK_REVISION},
    {'worker_image': 'ghcr.io/futurefm/pbgui-pb8-worker:latest', 'worker_revision': FORK_REVISION},
    {'worker_image': 'docker.io/x/y@sha256:' + 'a' * 64, 'worker_revision': FORK_REVISION},
])
def test_incomplete_or_mutable_pins_are_refused_not_replaced_by_upstream(section) -> None:
    image, _, error = resolve_worker(section)
    assert error
    assert image != DEFAULT_IMAGE


def _config(carton: str, *, suite=False, scenarios=None) -> dict:
    return {
        'live': {'approved_coins': {'long': ['ETH'], 'short': []}},
        'backtest': {'organillo_mode': True, 'organillo_carton_path': carton,
                     'suite_enabled': suite, 'scenarios': scenarios or []},
    }


def test_relative_cartons_resolve_against_pb8_dir_and_are_staged_once(tmp_path) -> None:
    pb8 = tmp_path / 'pb8'
    (pb8 / 'cartons').mkdir(parents=True)
    carton = pb8 / 'cartons' / 'sel.csv'
    carton.write_text('date,BTC,ETH\n2024-01-01,1,0\n')
    config = _config('cartons/sel.csv', suite=True, scenarios=[
        {'label': 'a', 'overrides': {'backtest.organillo_carton_path': str(carton)}},
        {'label': 'b', 'overrides': {'backtest.maker_fee_override': 0.0}},
    ])
    folder = tmp_path / 'input'
    folder.mkdir()

    entries = organillo.stage_cartons(config, pb8, folder, JOB, sha256)

    checksum = sha256(carton)
    remote = f'/work/pbgui/jobs/{JOB}/input/organillo/{checksum}.csv'
    assert entries == [{'path': f'organillo/{checksum}.csv', 'bytes': carton.stat().st_size, 'sha256': checksum}]
    assert (folder / entries[0]['path']).read_bytes() == carton.read_bytes()
    assert config['backtest']['organillo_carton_path'] == remote
    assert config['backtest']['scenarios'][0]['overrides']['backtest.organillo_carton_path'] == remote
    assert 'backtest.organillo_carton_path' not in config['backtest']['scenarios'][1]['overrides']


def test_scenario_cartons_are_ignored_when_that_scenario_disables_organillo(tmp_path) -> None:
    config = _config('', suite=True, scenarios=[
        {'overrides': {'backtest.organillo_mode': False, 'backtest.organillo_carton_path': 'x.csv'}},
    ])
    config['backtest']['organillo_mode'] = False
    assert organillo.carton_slots(config) == []
    assert not organillo.uses_organillo(config)


@pytest.mark.parametrize('name, message', [('missing.csv', 'not found'), ('carton.txt', '.csv or .csv.gz')])
def test_invalid_cartons_fail_before_any_rental(tmp_path, name, message) -> None:
    (tmp_path / 'carton.txt').write_text('x')
    with pytest.raises(VastError, match=message):
        organillo.local_carton(name, tmp_path)


def test_retarget_moves_staged_cartons_to_the_executing_job() -> None:
    staged = f'/work/pbgui/jobs/{OTHER_JOB}/input/organillo/{"e" * 64}.csv.gz'
    config = _config(staged)
    organillo.retarget(config, JOB)
    assert config['backtest']['organillo_carton_path'] == f'/work/pbgui/jobs/{JOB}/input/organillo/{"e" * 64}.csv.gz'


def test_shard_selection_widens_a_copy_only() -> None:
    config = _config('x.csv')
    widened = organillo.shard_selection_config(config, ['BTC', 'ETH'])
    assert widened['live']['approved_coins'] == {'long': ['ETH', 'BTC'], 'short': ['BTC', 'ETH']}
    assert config['live']['approved_coins'] == {'long': ['ETH'], 'short': []}


def test_helper_universe_mirrors_suite_windows_and_scenario_coins(monkeypatch) -> None:
    calls = []

    def prepare_config(config, *, allowed_coins=None):
        bt = config['backtest']
        calls.append((bt['start_date'], bt['organillo_carton_path'], allowed_coins))
        if not bt.get('organillo_mode'):
            return config
        selected = {'base.csv': ['BTC', 'ETH'], 'late.csv': ['SOL', 'ETH', 'DOGE']}[bt['organillo_carton_path']]
        if allowed_coins is not None:
            selected = [coin for coin in selected if coin in allowed_coins]
        result = {**config, 'live': {'approved_coins': {'long': selected, 'short': selected}}}
        return result

    monkeypatch.setitem(sys.modules, 'historical_selection', types.SimpleNamespace(prepare_config=prepare_config))
    config = {
        'live': {'approved_coins': {'long': [], 'short': []}},
        'backtest': {'organillo_mode': True, 'organillo_carton_path': 'base.csv', 'organillo_carton_hash': 'old',
                     'start_date': '2024-01-01', 'end_date': '2024-06-01', 'suite_enabled': True,
                     'scenarios': [{'label': 'late', 'start_date': '2024-03-01',
                                    'coins': ['SOL', 'ETH'],
                                    'overrides': {'backtest.organillo_carton_path': 'late.csv'}}]},
    }
    assert pb8_config_helper._organillo_universe(config) == {'coins': ['BTC', 'ETH', 'SOL']}
    assert calls == [('2024-01-01', 'base.csv', None), ('2024-03-01', 'late.csv', ['SOL', 'ETH'])]


def test_prepare_ships_carton_and_exports_its_coin_universe(tmp_path, monkeypatch) -> None:
    """A frozen job contains the carton, its manifest entry and data for carton-selected coins."""
    import json
    import tarfile

    import pb8_config
    import vast_config_validation
    from tests.test_vast_scenarios import make_market
    from vast_jobs import JobStore

    pb8 = tmp_path / 'pb8'
    pb8.mkdir()
    carton = pb8 / 'sel.csv'
    carton.write_text('date,BTC,SOL\n2024-01-01,1,1\n')

    def helper(operation, **payload):
        if operation == 'organillo_universe':
            assert payload['config']['backtest']['organillo_carton_path'] == str(carton)
            return {'coins': ['BTC', 'SOL']}
        return {'minutes': [31 * 1440] * len(payload['configs'])}

    monkeypatch.setattr(pb8_config, '_call_helper', helper)
    monkeypatch.setattr(pb8_config, 'save_prepared_pb8_config', lambda value, path: path.write_text(json.dumps(value)))
    monkeypatch.setattr('pbgui_purefunc.pb8dir', lambda: str(pb8))
    monkeypatch.setattr(vast_config_validation, 'CUSTOM_WORKER', True)
    config = {'live': {'strategy_kind': 'ema_anchor', 'approved_coins': {'long': ['BTC'], 'short': ['BTC']},
                       'ignored_coins': {'long': [], 'short': []}, 'hedge_mode': True},
              'bot': {side: {'risk': {'n_positions': 3, 'total_wallet_exposure_limit': 1.0},
                             'hsl': {'enabled': False}} for side in ('long', 'short')},
              'backtest': {'suite_enabled': False, 'exchanges': ['binance'], 'start_date': '2024-01-01',
                           'end_date': '2024-12-31', 'starting_balance': 1000, 'scenarios': [],
                           'organillo_mode': True, 'organillo_carton_path': 'sel.csv'},
              'optimize': {'iters': 512, 'n_cpus': 4, 'scoring': [{'metric': 'adg_strategy_eq', 'goal': 'max'}], 'limits': []}}
    make_market(tmp_path, 'binance', ['BTC', 'SOL'])
    store = JobStore(tmp_path / 'vast')

    row = store.prepare('organillo', config, 'source', tmp_path / 'raw', tmp_path / 'mapping',
                        tmp_path / 'results', 512, 4, False)

    assert row['status'] == 'ready'
    directory = store.directory(row['id'])
    manifest = store.read(row['id'], 'input/manifest.json')
    checksum = sha256(carton)
    assert {'path': f'organillo/{checksum}.csv', 'bytes': carton.stat().st_size, 'sha256': checksum} in manifest['files']
    assert any(item['path'].startswith('ohlcv/binance/1m/SOL_') for item in manifest['files'])
    saved = json.loads((directory / 'input/optimize.json').read_text())
    assert saved['backtest']['organillo_carton_path'] == f'/work/pbgui/jobs/{row["id"]}/input/organillo/{checksum}.csv'
    assert saved['live']['approved_coins'] == {'long': ['BTC'], 'short': ['BTC']}
    with tarfile.open(directory / 'input.tar.gz') as archive:
        assert f'input/organillo/{checksum}.csv' in archive.getnames()
    assert config['backtest']['organillo_carton_path'] == 'sel.csv'


def test_upstream_worker_rejects_organillo_jobs() -> None:
    import vast_config_validation
    config = {'live': {'strategy_kind': 'ema_anchor'}, 'backtest': {'organillo_mode': True}}
    if vast_config_validation.CUSTOM_WORKER:
        pytest.skip('a fork worker is pinned in pbgui.ini')
    errors = vast_config_validation.validate_cloud_config(config)
    assert any(item['path'] == 'backtest.organillo_mode' for item in errors)
