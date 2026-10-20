#!/bin/sh
set -eu
# Mount the two verified screensaver files only; never reload or start an app.
exec /usr/bin/python @BASE@/overlay_runtime.py --apply --ack-mount --boot
