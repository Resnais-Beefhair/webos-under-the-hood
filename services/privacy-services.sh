#!/bin/sh
# Keep Home's sdx/admanager/voiceconductor dependencies untouched.
# A /run mask alone cannot override this TV's /etc voiceinput unit.
set -eu
# No-argument invocation must never be mistaken for a status check.
case "${1:-}" in --apply-services) shift ;; *) printf '%s\n' 'Write operation: requires --apply-services after the documented checkpoint and consent.' >&2; exit 2 ;; esac
[ "$#" -eq 0 ] || exit 2
BASE=${WEBOS_PRIVACY_BASE:-/var/lib/webosbrew}
UNITDIR=${WEBOS_PRIVACY_UNITDIR:-/etc/systemd/system}
MOUNTS=${WEBOS_PRIVACY_MOUNTS:-/proc/mounts}
VERSION=${WEBOS_PRIVACY_VERSIONFILE:-/etc/version}
RUNDIR=${WEBOS_PRIVACY_RUNDIR:-/run/systemd/system}
LOG=$BASE/privacy.log
VOICE=voiceinput.service
TARGET=$UNITDIR/$VOICE

log() { printf '%s\n' "$*" >> "$LOG"; }
fail() { log "[FAIL] $*"; printf '%s\n' "$*" >&2; exit 1; }
verify_mask() {
    unit=$1
    load=$(systemctl show "$unit" -p LoadState) || fail "$unit: show failed"
    active=$(systemctl show "$unit" -p ActiveState) || fail "$unit: state failed"
    enabled=$(systemctl is-enabled "$unit" 2>/dev/null) || :
    [ "$load" = 'LoadState=masked' ] || fail "$unit: $load (not masked)"
    [ "$active" = 'ActiveState=inactive' ] || fail "$unit: $active"
    case "$enabled" in masked|masked-runtime) ;; *) fail "$unit: $enabled" ;; esac
    log "[ok] $unit: masked, inactive ($enabled)"
}

[ "$(id -u)" = 0 ] || fail 'root is required'
[ "$(cat "$VERSION")" = 20260421173614 ] || fail 'unsupported firmware build'
LOCK=$RUNDIR/.privacy-services.lock
(umask 077; mkdir "$LOCK") || fail 'another invocation or stale lock exists; inspect it, do not remove it blindly'
trap 'rmdir "$LOCK"' 0
# Validate every layer before stopping either service. A matching path is not
# evidence that an existing mount or runtime mask belongs to this operation.
[ -e "$TARGET" ] || fail "missing expected voiceinput unit: $TARGET"
[ ! -L "$TARGET" ] || fail 'foreign voiceinput symlink'
count=$(grep -Fc " $TARGET " "$MOUNTS") || :
case "$count" in
    0) [ -f "$TARGET" ] || fail 'voiceinput unit is not a regular file' ;;
    1) actual=$(stat -Lc '%d:%i' "$TARGET") || fail 'cannot stat voiceinput mount'
       null=$(stat -Lc '%d:%i' /dev/null) || fail 'cannot stat /dev/null'
       [ "$actual" = "$null" ] || fail 'foreign voiceinput mount' ;;
    *) fail 'stacked voiceinput mounts' ;;
esac
for unit in contentminer.service "$VOICE"; do
    link=$RUNDIR/$unit
    if [ -L "$link" ]; then
        [ "$(readlink "$link")" = /dev/null ] || fail "foreign runtime link: $unit"
    elif [ -e "$link" ]; then
        fail "foreign runtime unit: $unit"
    fi
done
log "=== privacy services v2: $(date) ==="
systemctl stop contentminer.service >>"$LOG" 2>&1 || fail 'contentminer stop failed'
systemctl mask --runtime contentminer.service >>"$LOG" 2>&1 || fail 'contentminer mask failed'
verify_mask contentminer.service

systemctl stop "$VOICE" >>"$LOG" 2>&1 || fail 'voiceinput stop failed'
if ! grep -Fq " $TARGET " "$MOUNTS"; then
    mount --bind /dev/null "$TARGET" >>"$LOG" 2>&1 || fail 'voiceinput bind mask failed'
    systemctl daemon-reload >>"$LOG" 2>&1 || fail 'daemon-reload failed'
fi
systemctl mask --runtime "$VOICE" >>"$LOG" 2>&1 || fail 'voiceinput runtime mask failed'
verify_mask "$VOICE"
