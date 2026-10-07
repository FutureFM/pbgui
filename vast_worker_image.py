"""Resolve the pinned Vast worker image, optionally replaced by a custom PB8 build.

PBGui ships with an upstream worker. Users running a PB8 fork can publish their own
worker image (same Dockerfile recipe, fork source) and pin it in pbgui.ini:

    [vast]
    worker_image = ghcr.io/<owner>/pbgui-pb8-worker@sha256:<64 hex digest>
    worker_revision = <40 hex PB8 commit baked into the image>

Both values are required together and are read once at import; restart PBGui after
changing them. Existing rentals keep the image/revision recorded in their intent.
"""

from __future__ import annotations

import re

SERVICE = 'Vast'
DEFAULT_IMAGE = 'ghcr.io/msei99/pbgui-pb8-worker@sha256:792a11f40098a3fffe9365c46e38f60c7bddaa35179c9bc608d130b5e1449dbe'
DEFAULT_REVISION = '061e472e3d400cb3a740583d52f9d46e02eaf781'
_IMAGE = re.compile(r'ghcr\.io/[a-z0-9][a-z0-9_/-]*@sha256:[0-9a-f]{64}')
_REVISION = re.compile(r'[0-9a-f]{40}')


def resolve_worker(section: dict | None) -> tuple[str, str, str | None]:
    """Return (image, revision, error) for a [vast] ini section."""
    section = section if isinstance(section, dict) else {}
    image = str(section.get('worker_image') or '').strip()
    revision = str(section.get('worker_revision') or '').strip().lower()
    if not image and not revision:
        return DEFAULT_IMAGE, DEFAULT_REVISION, None
    if not _IMAGE.fullmatch(image) or not _REVISION.fullmatch(revision):
        # Keep the invalid pin so validation refuses rentals instead of silently
        # running upstream code for a user who configured a fork.
        return image, revision, ('pbgui.ini [vast] worker_image must be ghcr.io/<owner>/<name>@sha256:<digest> '
                                 'and worker_revision a 40-character commit; both are required together.')
    return image, revision, None


def _load_section() -> dict:
    """Read [vast] without making PBGui startup depend on a readable ini."""
    try:
        from pbgui_purefunc import load_ini_section
        return load_ini_section('vast')
    except Exception:
        return {}


IMAGE, REVISION, SETTINGS_ERROR = resolve_worker(_load_section())
CUSTOM = IMAGE != DEFAULT_IMAGE
