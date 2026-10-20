#!/bin/sh
# Installed only by an explicit, audited opt-in after screen QA.
# Fresh mounts require an explicitly approved, hidden Home-only reload.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
exec python "@BASE@/preview_runtime.py" --boot --ack-mount --ack-home-reload
