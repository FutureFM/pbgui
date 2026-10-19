# Unreleased

- Vast.ai GPU supervision now works on macOS. Without user systemd, the job controller, rental guard and pool scheduler start as detached sessions with private append-only logs; their existing process locks still reject duplicates. There is no automatic restart on macOS: after a crash or reboot use **Resume supervision**. Linux keeps the systemd path unchanged. Transfers require GNU rsync (`brew install rsync`) because the bundled openrsync lacks `--append-verify`.
