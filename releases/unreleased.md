# Unreleased

### Added

- Vast.ai GPU optimization can use a worker image built from a Passivbot fork. Set `image` (GHCR digest) and `revision` (full commit) in a new `[vast_worker]` section of `pbgui.ini` and restart the API. New jobs, configuration checks and GPU calibration then use this pair. An incomplete or invalid section blocks new cloud jobs and does not fall back to the upstream image. Existing rentals keep their own image and revision.
- New manual GitHub Actions workflow **Build Vast PB8 worker image** builds the worker from a Passivbot repository and commit, checks it offline, pushes it to the GHCR namespace of the repository owner and prints the `[vast_worker]` section. The worker Dockerfiles accept `PB8_REPOSITORY`, `BASE_IMAGE` and `PB8_REVISION` build arguments.
