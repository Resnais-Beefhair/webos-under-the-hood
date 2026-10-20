#!/usr/bin/env python
"""Restore only the known Home preview binds; never delete backups/placeholders."""
from __future__ import print_function
import os
import subprocess
import sys
sys.dont_write_bytecode = True
import manage_boot_hook
import preview_runtime


def _rows():
    return preview_runtime._mount_rows()


def detach_owned(target, source):
    state = preview_runtime.mount_state(source, target)
    if state == "absent":
        return False
    process = subprocess.Popen(["umount", target], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = process.communicate()[0]
    if process.returncode:
        if process.returncode != 32 or b"target is busy" not in output:
            raise RuntimeError("ordinary unmount failed: %r" % output)
        # Revalidate exact source inode, single mount, no nested mount and ro
        # immediately before the only permitted lazy-detach path.
        if preview_runtime.mount_state(source, target) != "owned":
            raise RuntimeError("busy target no longer has our exact read-only bind")
        subprocess.check_call(["umount", "-l", target])
        print("Lazy-detached exact owned read-only bind; open Home/SAM FDs may retain it: " + target)
    if any(row[1] == target for row in _rows()):
        raise RuntimeError("mount remains after unmount: %s" % target)
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv != ["--restore-owned-mounts", "--ack-rollback"]:
        print("No action. Use --restore-owned-mounts --ack-rollback after reviewing the exact targets.", file=sys.stderr)
        return 2
    try:
        if os.getuid() != 0:
            raise RuntimeError("root privileges are required on the TV")
        plan = preview_runtime.inspect()  # All mount and source guards run before writes.
        hook_state = manage_boot_hook.hook_state()
        if hook_state == "foreign":
            raise RuntimeError("foreign boot hook found; no rollback changes made")
        # Disarm future boot application first. Its exact bytes are checked again
        # inside remove_hook; unknown hook contents are never renamed or deleted.
        if hook_state == "owned":
            manage_boot_hook.remove_hook()
        detached = []
        for target, source, state in reversed(plan):
            if state == "owned" and detach_owned(target, source):
                detached.append(target)
        if preview_runtime.digest(preview_runtime.UI) != preview_runtime.ORIGINAL_SHA256:
            raise RuntimeError("Home source hash after unmount is not the pinned original")
        print("Restored original Home source; detached=%d; original files/placeholders retained; Home was not reloaded." % len(detached))
        return 0
    except Exception as exc:
        print("rollback refused or incomplete: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
