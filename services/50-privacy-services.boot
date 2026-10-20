#!/bin/sh
# Installing this hook is the explicit opt-in to reapplying masks at boot.
set -eu
[ "$(id -u)" = 0 ] || { printf '%s\n' 'Root required' >&2; exit 1; }
[ "$(cat /etc/version)" = '20260421173614' ] || { printf '%s\n' 'Unvalidated firmware build: service hook refused' >&2; exit 1; }
exec sh /var/lib/webosbrew/privacy-services/privacy-services.sh --apply-services
