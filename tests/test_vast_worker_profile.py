"""A [vast_worker] section selects a fork-built worker image without weakening pins."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vast_worker_profile import DEFAULT_IMAGE, DEFAULT_REVISION, resolve_worker_profile

PROJECT = Path(__file__).resolve().parents[1]
FORK_IMAGE = 'ghcr.io/futurefm/pbgui-pb8-worker@sha256:' + 'a' * 64
FORK_REVISION = 'b' * 40


def test_missing_section_keeps_published_worker():
    """Without configuration the published upstream worker stays active."""
    assert resolve_worker_profile({}) == (DEFAULT_IMAGE, DEFAULT_REVISION, False, None)
    assert resolve_worker_profile(None) == (DEFAULT_IMAGE, DEFAULT_REVISION, False, None)


def test_fork_worker_is_accepted():
    """A digest-pinned GHCR image with a full commit becomes the active worker."""
    assert resolve_worker_profile({'image': FORK_IMAGE, 'revision': FORK_REVISION.upper()}) == (
        FORK_IMAGE, FORK_REVISION, True, None)


@pytest.mark.parametrize('values', [
    {'image': FORK_IMAGE},
    {'revision': FORK_REVISION},
    {'image': 'ghcr.io/futurefm/pbgui-pb8-worker:latest', 'revision': FORK_REVISION},
    {'image': 'docker.io/futurefm/worker@sha256:' + 'a' * 64, 'revision': FORK_REVISION},
    {'image': 'ghcr.io/FutureFM/worker@sha256:' + 'a' * 64, 'revision': FORK_REVISION},
    {'image': FORK_IMAGE, 'revision': 'b' * 7},
    {'image': DEFAULT_IMAGE, 'revision': FORK_REVISION},
])
def test_invalid_fork_worker_fails_closed(values):
    """Partial, tagged, foreign-registry or short-revision profiles report an error."""
    image, revision, custom, error = resolve_worker_profile(values)
    assert custom is True
    assert error


def _profile_state(values: dict) -> dict:
    """Import the Vast modules in a fresh interpreter with a given ini section."""
    code = (
        'import json, pbgui_purefunc\n'
        f'values = {values!r}\n'
        'pbgui_purefunc.load_ini_section = lambda section: values if section == "vast_worker" else {}\n'
        'import vast_jobs, vast_calibration, vast_config_validation\n'
        'errors = vast_config_validation.validate_cloud_config({}, image=vast_jobs.IMAGE, revision=vast_jobs.REVISION)\n'
        'print(json.dumps({"image": vast_jobs.IMAGE, "revision": vast_jobs.REVISION,\n'
        '    "authorized": vast_jobs.SUPPORTED_RENTAL_IMAGE_REVISIONS.get(vast_jobs.IMAGE),\n'
        '    "upstream_authorized": vast_jobs.SUPPORTED_RENTAL_IMAGE_REVISIONS.get(' + repr(DEFAULT_IMAGE) + '),\n'
        '    "calibration": vast_calibration.calibration_worker_available(vast_jobs.IMAGE, protocol=4),\n'
        '    "compatible": vast_jobs.IMAGE in vast_calibration.COMPATIBLE_CALIBRATION_IMAGES,\n'
        '    "profile_image": vast_config_validation.PROFILE_IMAGE,\n'
        '    "worker_errors": [e["message"] for e in errors if e["path"] == "worker.image"]}))\n'
    )
    result = subprocess.run([sys.executable, '-c', code], cwd=PROJECT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_fork_worker_is_used_for_jobs_validation_and_calibration():
    """Rentals, preflight and calibration share one fork image/revision pair."""
    state = _profile_state({'image': FORK_IMAGE, 'revision': FORK_REVISION})
    assert state['image'] == state['profile_image'] == FORK_IMAGE
    assert state['revision'] == state['authorized'] == FORK_REVISION
    assert state['upstream_authorized'] == DEFAULT_REVISION
    assert state['calibration'] is True
    assert state['compatible'] is True
    assert state['worker_errors'] == []


def test_invalid_fork_worker_blocks_new_jobs():
    """An incomplete profile is never authorized for rental or calibration."""
    state = _profile_state({'image': FORK_IMAGE})
    assert state['authorized'] is None
    assert state['calibration'] is False
    assert state['compatible'] is False
    assert any('[vast_worker]' in message for message in state['worker_errors'])
