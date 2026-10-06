"""Active Vast worker image/revision pair, optionally replaced by a self-built fork image.

The default pair is the published PBGui worker built from official Passivbot.
An operator can select a worker built from a Passivbot fork with the
``[vast_worker]`` section in ``pbgui.ini``::

    [vast_worker]
    image = ghcr.io/<owner>/pbgui-pb8-worker@sha256:<64 hex digest>
    revision = <40 hex Passivbot commit baked into the image>

Both keys are required together. An incomplete or invalid section fails
closed: the profile keeps the configured values, ``PROFILE_ERROR`` explains the
problem, and config validation blocks new cloud jobs. PBGui reads the section at
API start, so restart the API after a change.
"""
from __future__ import annotations

import re

from logging_helpers import human_log as _log

SERVICE = 'Vast'
INI_SECTION = 'vast_worker'
DEFAULT_IMAGE = 'ghcr.io/msei99/pbgui-pb8-worker@sha256:792a11f40098a3fffe9365c46e38f60c7bddaa35179c9bc608d130b5e1449dbe'
DEFAULT_REVISION = '061e472e3d400cb3a740583d52f9d46e02eaf781'
# Same identity rule as the anonymous registry preflight in vast_image.py.
IMAGE_PATTERN = re.compile(r'ghcr\.io/[a-z0-9][a-z0-9_/-]*@sha256:[0-9a-f]{64}')
REVISION_PATTERN = re.compile(r'[0-9a-f]{40}')


def resolve_worker_profile(values: dict | None) -> tuple[str, str, bool, str | None]:
    """Return image, revision, custom flag and error for one ini section."""
    values = values if isinstance(values, dict) else {}
    image = str(values.get('image') or '').strip()
    revision = str(values.get('revision') or '').strip().lower()
    if not image and not revision:
        return DEFAULT_IMAGE, DEFAULT_REVISION, False, None
    if not image or not revision:
        return image, revision, True, ('[vast_worker] needs both image and revision. '
                                       'No cloud job uses a partial worker profile.')
    if not IMAGE_PATTERN.fullmatch(image):
        return image, revision, True, ('[vast_worker] image must be ghcr.io/<owner>/<name>@sha256:<digest> '
                                       'in lowercase. Tags are not accepted because rentals pin the digest.')
    if not REVISION_PATTERN.fullmatch(revision):
        return image, revision, True, '[vast_worker] revision must be the full 40-character Passivbot commit.'
    if image == DEFAULT_IMAGE and revision != DEFAULT_REVISION:
        return image, revision, True, f'[vast_worker] the published PBGui worker contains revision {DEFAULT_REVISION}.'
    return image, revision, image != DEFAULT_IMAGE, None


def load_worker_profile() -> tuple[str, str, bool, str | None]:
    """Read the ini section once; an unreadable ini blocks fork use, not the API."""
    try:
        from pbgui_purefunc import load_ini_section
        values = load_ini_section(INI_SECTION)
    except Exception as error:
        _log(SERVICE, f'Cannot read [{INI_SECTION}] from pbgui.ini: {error}', level='ERROR')
        return DEFAULT_IMAGE, DEFAULT_REVISION, False, f'Cannot read [{INI_SECTION}] from pbgui.ini.'
    profile = resolve_worker_profile(values)
    if profile[3]:
        _log(SERVICE, profile[3], level='ERROR')
    elif profile[2]:
        _log(SERVICE, f'Using custom Vast worker {profile[0]} at PB8 revision {profile[1]}')
    return profile


WORKER_IMAGE, WORKER_REVISION, CUSTOM_WORKER, PROFILE_ERROR = load_worker_profile()
