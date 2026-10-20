#!/usr/bin/python
"""Owned read-only overlay for the native screensaver. Python 2.7 compatible."""
from __future__ import print_function
import sys
sys.dont_write_bytecode = True
import argparse
import contextlib
import errno
import hashlib
import json
import os
import signal
import stat
import subprocess
import tempfile

BASE = '@BASE@'
HOOK = '@HOOK@'
BUILD = '@BUILD@'
TARGETS = {
    'ScreenSaver.qml': '@TARGET_SCREENSAVER@',
    'MainView.qml': '@TARGET_MAINVIEW@',
}
ORIGINAL = {
    'ScreenSaver.qml': '@ORIGINAL_SCREENSAVER_SHA256@',
    'MainView.qml': '@ORIGINAL_MAINVIEW_SHA256@',
}
PATCHED = {
    'ScreenSaver.qml': '@PATCHED_SCREENSAVER_SHA256@',
    'MainView.qml': '@PATCHED_MAINVIEW_SHA256@',
}
HOOK_SHA256 = '@BOOT_HOOK_SHA256@'
DISABLED_MARKER = 'screensaver-override-disabled-v1\n'


try:
    STRING_TYPES = (basestring,)
    INTEGER_TYPES = (int, long)
except NameError:
    STRING_TYPES = (str,)
    INTEGER_TYPES = (int,)


def require(value, message):
    if not value:
        raise RuntimeError(message)


class _LifecycleInterrupted(Exception):
    pass


_INTERRUPTION_SIGNAL = None


def _check_interruption():
    if _INTERRUPTION_SIGNAL == getattr(signal, 'SIGTERM', None):
        raise _LifecycleInterrupted('SIGTERM received during lifecycle operation')
    if _INTERRUPTION_SIGNAL == getattr(signal, 'SIGINT', None):
        raise KeyboardInterrupt()


@contextlib.contextmanager
def _lifecycle_lock():
    """Lock the validated runtime directory inode without writing a lock file."""
    global _INTERRUPTION_SIGNAL
    try:
        import fcntl
    except ImportError:
        raise RuntimeError('cross-process lifecycle lock is unavailable on this platform')
    try:
        path_stat = os.lstat(BASE)
    except OSError as exc:
        raise RuntimeError('cannot inspect runtime directory: %s' % exc)
    require(stat.S_ISDIR(path_stat.st_mode) and not stat.S_ISLNK(path_stat.st_mode),
            'invalid runtime directory for lifecycle lock')
    require(stat.S_IMODE(path_stat.st_mode) == 0o700,
            'runtime directory must be private mode 0700')
    flags = os.O_RDONLY
    if hasattr(os, 'O_DIRECTORY'):
        flags |= os.O_DIRECTORY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_CLOEXEC'):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(BASE, flags)
    except OSError as exc:
        raise RuntimeError('cannot safely open runtime directory for lifecycle lock: %s' % exc)
    locked = False
    try:
        opened_stat = os.fstat(fd)
        path_stat = os.lstat(BASE)
        require(stat.S_ISDIR(opened_stat.st_mode) and opened_stat.st_uid == path_stat.st_uid and
                opened_stat.st_dev == path_stat.st_dev and opened_stat.st_ino == path_stat.st_ino,
                'runtime directory changed while opening lifecycle lock')
        require(stat.S_IMODE(opened_stat.st_mode) == 0o700,
                'runtime directory must be private mode 0700')
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, descriptor_flags | fcntl.FD_CLOEXEC)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (IOError, OSError) as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, getattr(errno, 'EWOULDBLOCK', errno.EAGAIN)):
                raise RuntimeError('lifecycle operation busy; retry after it finishes')
            raise
        path_stat = os.lstat(BASE)
        require(path_stat.st_dev == opened_stat.st_dev and path_stat.st_ino == opened_stat.st_ino and
                stat.S_IMODE(path_stat.st_mode) == 0o700,
                'runtime directory changed after acquiring lifecycle lock')

        _INTERRUPTION_SIGNAL = None

        def request_interruption(signum, frame):
            global _INTERRUPTION_SIGNAL
            if _INTERRUPTION_SIGNAL is None:
                _INTERRUPTION_SIGNAL = signum
            # Let the active mount/umount child finish before raising in Python.
            signal.signal(signum, signal.SIG_IGN)

        installed_handlers = []
        for signum in (getattr(signal, 'SIGTERM', None), getattr(signal, 'SIGINT', None)):
            if signum is None:
                continue
            previous = signal.getsignal(signum)
            try:
                signal.signal(signum, request_interruption)
                installed_handlers.append((signum, previous))
            except ValueError:
                # Python permits signal handlers only in the main thread.
                pass
        try:
            yield
        finally:
            for signum, previous in reversed(installed_handlers):
                signal.signal(signum, previous)
            _INTERRUPTION_SIGNAL = None
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read(path):
    require(not os.path.islink(path), 'symlink refused: ' + path)
    with open(path, 'rb') as stream:
        return stream.read()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    return digest(read(path))


def regular_file(path):
    require(not os.path.islink(path), 'symlink refused: ' + path)
    try:
        mode = os.stat(path).st_mode
    except OSError as exc:
        raise RuntimeError('cannot stat %s: %s' % (path, exc))
    require(stat.S_ISREG(mode), 'not a regular file: ' + path)
    return os.stat(path)


def boot_id():
    return read('/proc/sys/kernel/random/boot_id').decode('ascii').strip()


def _unescape_mount_path(value):
    return value.replace('\\040', ' ').replace('\\011', '\t').replace('\\012', '\n').replace('\\134', '\\')


def mount_rows(target=None):
    rows = []
    for line in read('/proc/self/mountinfo').decode('ascii').splitlines():
        fields = line.split()
        if len(fields) < 10 or '-' not in fields:
            continue
        mountpoint = _unescape_mount_path(fields[4])
        if target is not None and mountpoint != target:
            continue
        separator = fields.index('-')
        rows.append({
            'id': fields[0],
            'mountpoint': mountpoint,
            'options': fields[5].split(','),
            'super_options': fields[separator + 3].split(',') if len(fields) > separator + 3 else [],
        })
    return rows


def _has_nested_mount(target):
    prefix = target.rstrip('/') + '/'
    return [row['mountpoint'] for row in mount_rows() if row['mountpoint'].startswith(prefix)]


def _inode(path):
    st = regular_file(path)
    return [int(st.st_dev), int(st.st_ino)]


def _same_file(source, target):
    try:
        return _inode(source) == _inode(target)
    except RuntimeError:
        return False


def _load_manifest():
    require(os.path.isdir(BASE) and not os.path.islink(BASE), 'invalid runtime directory')
    root_stat = os.stat(BASE)
    require(root_stat.st_uid == 0 and stat.S_IMODE(root_stat.st_mode) == 0o700,
            'runtime directory must be root-owned mode 0700')
    value = json.loads(read(os.path.join(BASE, 'manifest.json')).decode('utf-8'))
    require(value.get('feature') == 'optional-moving-rings-screensaver', 'wrong package feature')
    require(value.get('build') == BUILD, 'manifest build mismatch')
    require(value.get('runtime_base') == BASE and value.get('boot_hook') == HOOK, 'runtime path mismatch')
    require(value.get('targets') == TARGETS, 'target allowlist mismatch')
    require(value.get('original_sha256') == ORIGINAL, 'original source pins mismatch')
    require(value.get('patched_sha256') == PATCHED, 'patched source pins mismatch')
    require(read('/etc/version').decode('ascii').strip() == BUILD, 'firmware build changed')
    package_hashes = value.get('package_sha256')
    require(isinstance(package_hashes, dict), 'manifest package hashes missing')
    require(set(package_hashes.keys()) == set([
        'ScreenSaver.original.qml', 'ScreenSaver.patched.qml',
        'MainView.original.qml', 'MainView.patched.qml',
        'overlay_runtime.py', 'manage_boot_hook.py', 'reload_screensaver.py',
        'screensaver-boot-hook.sh']), 'manifest package file allowlist mismatch')
    expected_files = {
        'ScreenSaver.original.qml': ORIGINAL['ScreenSaver.qml'],
        'ScreenSaver.patched.qml': PATCHED['ScreenSaver.qml'],
        'MainView.original.qml': ORIGINAL['MainView.qml'],
        'MainView.patched.qml': PATCHED['MainView.qml'],
    }
    for name, expected in expected_files.items():
        require(package_hashes.get(name) == expected, 'manifest hash mismatch: ' + name)
    require(package_hashes.get('screensaver-boot-hook.sh') == HOOK_SHA256, 'boot hook hash pin mismatch')
    for name, expected in package_hashes.items():
        require(name not in ('manifest.json',) and '/' not in name and name not in ('.', '..'),
                'invalid package filename in manifest')
        actual = file_digest(os.path.join(BASE, name))
        require(actual == expected, 'package file hash mismatch: ' + name)
    return value


def _load_state():
    path = os.path.join(BASE, 'active.json')
    if not os.path.lexists(path):
        return {'version': 1, 'boot_id': '', 'mounts': {}}
    _validate_private_record(path, 'active state')
    value = json.loads(read(path).decode('utf-8'))
    require(value.get('version') == 1 and isinstance(value.get('mounts'), dict), 'invalid active state')
    require(isinstance(value.get('boot_id'), STRING_TYPES), 'invalid active-state boot ID')
    return value


def _disabled_state():
    path = os.path.join(BASE, 'disabled')
    if not os.path.lexists(path):
        return False
    require(read(path).decode('ascii') == DISABLED_MARKER, 'foreign disable marker')
    return True


def _target_status(name, state):
    target = TARGETS[name]
    source = os.path.join(BASE, name + '.patched.qml')
    regular_file(target)
    regular_file(source)
    nested = _has_nested_mount(target)
    require(not nested, 'nested mount below target %s: %s' % (target, ', '.join(nested)))
    rows = mount_rows(target)
    if not rows:
        actual = file_digest(target)
        require(actual == ORIGINAL[name], 'target has unknown unmounted content: ' + target)
        return 'original'
    require(len(rows) == 1, 'stacked mounts at target: ' + target)
    row = rows[0]
    require('ro' in row['options'], 'writable mount refused at target: ' + target)
    record = state.get('mounts', {}).get(name)
    require(state.get('boot_id') == boot_id() and isinstance(record, dict),
            'unowned mount at target: ' + target)
    require(record.get('mount_id') == row['id'], 'mount instance changed at target: ' + target)
    require(record.get('source_inode') == _inode(source), 'source inode changed at target: ' + target)
    require(record.get('target_inode') == _inode(target), 'target inode changed at target: ' + target)
    require(_same_file(source, target), 'source/target inode mismatch at target: ' + target)
    require(file_digest(source) == PATCHED[name] and file_digest(target) == PATCHED[name],
            'mounted source hash mismatch at target: ' + target)
    return 'owned-ro'


def _inspect_unlocked():
    require(_load_journal() is None,
            'interrupted apply has a recovery journal; run --apply or --rollback to recover')
    manifest = _load_manifest()
    state = _load_state()
    mounts = {}
    for name in sorted(TARGETS):
        mounts[name] = _target_status(name, state)
    return {
        'feature': 'optional-moving-rings-screensaver',
        'build': BUILD,
        'boot_id': boot_id(),
        'disabled': _disabled_state(),
        'mounts': mounts,
        'package_verified': True,
    }


def inspect():
    with _lifecycle_lock():
        return _inspect_unlocked()


def _validate_private_record(path, label):
    require(not os.path.islink(path), label + ' symlink refused')
    try:
        st = os.lstat(path)
        base_stat = os.lstat(BASE)
    except OSError as exc:
        raise RuntimeError('cannot inspect %s: %s' % (label, exc))
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1,
            label + ' must be a single-link regular file')
    require(st.st_uid == base_stat.st_uid and stat.S_IMODE(st.st_mode) == 0o600,
            label + ' must be privately owned mode 0600')
    return st


def _sync_directory(path):
    flags = os.O_RDONLY
    if hasattr(os, 'O_DIRECTORY'):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_record(path, data, label, exclusive=False):
    directory = os.path.dirname(path) or '.'
    if exclusive:
        require(not os.path.lexists(path), label + ' already exists: ' + path)
    elif os.path.lexists(path):
        _validate_private_record(path, label)
    fd, temporary = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.',
                                     suffix='.tmp', dir=directory)
    try:
        os.fchmod(fd, 0o600)
        stream = os.fdopen(fd, 'wb')
        fd = -1
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()
        if exclusive:
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.rename(temporary, path)
        _sync_directory(directory)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _journal_path():
    return os.path.join(BASE, 'lifecycle.json')


def _validate_journal(value):
    require(isinstance(value, dict) and
            set(value.keys()) == set(('version', 'operation', 'boot_id', 'targets')) and
            value.get('version') == 1 and value.get('operation') == 'apply',
            'invalid lifecycle journal')
    require(isinstance(value.get('boot_id'), STRING_TYPES) and value['boot_id'],
            'invalid journal boot ID')
    targets = value.get('targets')
    require(isinstance(targets, dict) and targets and
            set(targets).issubset(set(TARGETS)), 'invalid lifecycle journal targets')
    for name, entry in targets.items():
        require(isinstance(entry, dict), 'invalid journal target record: ' + name)
        phase = entry.get('phase')
        require(phase in ('intent', 'bound', 'readonly'),
                'invalid journal phase: ' + name)
        expected_keys = set(('phase', 'source_inode', 'target_inode'))
        if phase != 'intent':
            expected_keys.add('mount_id')
        require(set(entry.keys()) == expected_keys,
                'invalid journal fields: ' + name)
        for key in ('source_inode', 'target_inode'):
            identity = entry.get(key)
            require(isinstance(identity, list) and len(identity) == 2 and
                    all(isinstance(part, INTEGER_TYPES) and not isinstance(part, bool)
                        for part in identity),
                    'invalid journal %s identity: %s' % (key, name))
        require(entry['source_inode'] != entry['target_inode'],
                'journal source and target identities alias: ' + name)
        if phase != 'intent':
            require(isinstance(entry.get('mount_id'), STRING_TYPES) and entry['mount_id'],
                    'journal mount ID missing: ' + name)
    return value


def _load_journal():
    path = _journal_path()
    if not os.path.lexists(path):
        return None
    _validate_private_record(path, 'lifecycle journal')
    value = json.loads(read(path).decode('utf-8'))
    return _validate_journal(value)


def _save_journal(value):
    _validate_journal(value)
    data = (json.dumps(value, sort_keys=True) + '\n').encode('ascii')
    _atomic_record(_journal_path(), data, 'lifecycle journal')


def _clear_journal():
    path = _journal_path()
    if not os.path.lexists(path):
        return
    _load_journal()
    os.unlink(path)
    _sync_directory(BASE)


def _ensure_checkpoints(names):
    directory = os.path.join(BASE, 'checkpoints')
    if os.path.lexists(directory):
        require(os.path.isdir(directory) and not os.path.islink(directory), 'invalid checkpoint directory')
        st = os.stat(directory)
        require(st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o700, 'checkpoint directory must be root/private')
    else:
        os.mkdir(directory, 0o700)
        _sync_directory(BASE)
    for name in names:
        target = TARGETS[name]
        actual = read(target)
        require(digest(actual) == ORIGINAL[name], 'target changed before checkpoint: ' + target)
        checkpoint = os.path.join(directory, name + '.before')
        if os.path.lexists(checkpoint):
            require(not os.path.islink(checkpoint) and os.path.isfile(checkpoint), 'checkpoint collision: ' + checkpoint)
            require(file_digest(checkpoint) == ORIGINAL[name] and read(checkpoint) == actual,
                    'checkpoint collision/content mismatch: ' + checkpoint)
        else:
            _atomic_record(checkpoint, actual, 'checkpoint', exclusive=True)


def _state_record(name, mount_id):
    source = os.path.join(BASE, name + '.patched.qml')
    target = TARGETS[name]
    return {
        'mount_id': str(mount_id),
        'source_inode': _inode(source),
        'target_inode': _inode(target),
    }


def _save_state(value):
    path = os.path.join(BASE, 'active.json')
    data = (json.dumps(value, sort_keys=True) + '\n').encode('ascii')
    _atomic_record(path, data, 'active state')


def _recover_pending_apply():
    journal = _load_journal()
    if journal is None:
        return False
    current_boot = boot_id()
    state = _load_state()
    entries = journal['targets']
    if journal['boot_id'] != current_boot:
        for name in sorted(entries):
            entry = entries[name]
            target = TARGETS[name]
            source = os.path.join(BASE, name + '.patched.qml')
            require(entry['source_inode'] == _inode(source) and
                    file_digest(source) == PATCHED[name],
                    'old-boot journal source changed; recovery refused: ' + target)
            require(not _has_nested_mount(target) and not mount_rows(target) and
                    entry['target_inode'] == _inode(target) and
                    file_digest(target) == ORIGINAL[name],
                    'old-boot journal target is not restored; recovery refused: ' + target)
        # A boot transition destroys the prior kernel mount instances. Retire
        # only an old-boot journal whose exact original targets are visible.
        _clear_journal()
        return True
    claimed = [name for name in entries
               if state.get('boot_id') == journal['boot_id'] and
               name in state.get('mounts', {})]
    if claimed:
        require(set(claimed) == set(entries) and
                all(entries[name].get('phase') == 'readonly' and
                    state['mounts'][name].get('mount_id') == entries[name].get('mount_id')
                    for name in entries),
                'lifecycle journal conflicts with active ownership; recovery refused')
        for name in sorted(entries):
            require(_target_status(name, state) == 'owned-ro',
                    'committed lifecycle journal does not match owned mount: ' + name)
        _clear_journal()
        return True

    for name in sorted(entries, reverse=True):
        entry = entries[name]
        target = TARGETS[name]
        source = os.path.join(BASE, name + '.patched.qml')
        require(entry['source_inode'] == _inode(source) and
                file_digest(source) == PATCHED[name],
                'journal source identity changed; recovery refused: ' + target)
        nested = _has_nested_mount(target)
        require(not nested, 'nested mount blocks journal recovery at %s: %s' %
                (target, ', '.join(nested)))
        rows = mount_rows(target)
        if not rows:
            require(entry['target_inode'] == _inode(target) and
                    file_digest(target) == ORIGINAL[name],
                    'journal target changed without an owned mount; recovery refused: ' + target)
            continue
        require(len(rows) == 1 and rows[0]['mountpoint'] == target,
                'stacked or mismatched mount blocks journal recovery: ' + target)
        row = rows[0]
        if 'mount_id' in entry:
            require(row['id'] == entry['mount_id'],
                    'journal mount instance changed; recovery refused: ' + target)
        require(('ro' in row['options']) != ('rw' in row['options']),
                'journal mount mode is ambiguous; recovery refused: ' + target)
        require(_inode(target) == entry['source_inode'] and _same_file(source, target) and
                file_digest(target) == PATCHED[name],
                'journal source/target identity mismatch; recovery refused: ' + target)
        # With phase=intent, a unique exact bind is recoverable after a crash
        # before its mount ID could be fsynced. This relies on the exclusive
        # administrator window documented for non-cooperating mount writers.
        subprocess.check_call(['umount', target])
        require(not mount_rows(target) and _inode(target) == entry['target_inode'] and
                file_digest(target) == ORIGINAL[name],
                'journal rollback did not restore the original target: ' + target)
    _clear_journal()
    return True


def apply_mounts(boot=False):
    with _lifecycle_lock():
        _check_interruption()
        _load_manifest()
        _recover_pending_apply()
        _check_interruption()
        if boot and _disabled_state():
            result = _inspect_unlocked()
            result['boot_hook_no_op'] = True
            return result
        require(not _disabled_state(), 'future apply disabled by rollback marker')
        state = _load_state()
        before = {name: _target_status(name, state) for name in sorted(TARGETS)}
        require(all(value in ('original', 'owned-ro') for value in before.values()),
                'foreign target; apply refused')
        if state.get('boot_id') == boot_id():
            stale = [name for name in before
                     if before[name] == 'original' and name in state.get('mounts', {})]
            require(not stale, 'active state claims an unmounted target; apply refused: ' +
                    ', '.join(stale))
        _check_interruption()
        if all(value == 'owned-ro' for value in before.values()):
            return {'changed': 0, 'status': _inspect_unlocked()}
        new_names = [name for name in sorted(TARGETS) if before[name] == 'original']
        _ensure_checkpoints(new_names)
        _check_interruption()
        current_boot = boot_id()
        records = {}
        if state.get('boot_id') == current_boot:
            records.update(state.get('mounts', {}))
        journal = None
        if new_names:
            entries = {}
            for name in new_names:
                source = os.path.join(BASE, name + '.patched.qml')
                target = TARGETS[name]
                source_inode = _inode(source)
                target_inode = _inode(target)
                require(source_inode != target_inode,
                        'patched source already aliases original target: ' + target)
                entries[name] = {'phase': 'intent', 'source_inode': source_inode,
                                 'target_inode': target_inode}
            journal = {'version': 1, 'operation': 'apply',
                       'boot_id': current_boot, 'targets': entries}
            _save_journal(journal)
            _check_interruption()
        try:
            for name in sorted(TARGETS):
                _check_interruption()
                if before[name] == 'owned-ro':
                    records[name] = state['mounts'][name]
                    continue
                source = os.path.join(BASE, name + '.patched.qml')
                target = TARGETS[name]
                subprocess.check_call(['mount', '--bind', source, target])
                _check_interruption()
                rows = mount_rows(target)
                require(len(rows) == 1 and rows[0]['mountpoint'] == target,
                        'new bind did not create one mount instance: ' + target)
                mount_id = str(rows[0]['id'])
                require(_same_file(source, target) and
                        _inode(target) == journal['targets'][name]['source_inode'],
                        'new bind inode mismatch: ' + target)
                journal['targets'][name]['phase'] = 'bound'
                journal['targets'][name]['mount_id'] = mount_id
                _save_journal(journal)
                _check_interruption()
                subprocess.check_call(['mount', '-o', 'remount,bind,ro', target])
                _check_interruption()
                rows = mount_rows(target)
                require(len(rows) == 1 and rows[0]['id'] == mount_id and 'ro' in rows[0]['options'],
                        'new bind did not become the same read-only mount: ' + target)
                require(file_digest(target) == PATCHED[name],
                        'new bind hash mismatch: ' + target)
                journal['targets'][name]['phase'] = 'readonly'
                _save_journal(journal)
                _check_interruption()
                records[name] = _state_record(name, mount_id)
            candidate = {'version': 1, 'boot_id': current_boot, 'mounts': records}
            for name in sorted(TARGETS):
                require(_target_status(name, candidate) == 'owned-ro',
                        'pre-save ownership verification failed: ' + TARGETS[name])
            _save_state(candidate)
            saved = _load_state()
            for name in sorted(TARGETS):
                require(_target_status(name, saved) == 'owned-ro',
                        'post-save ownership verification failed: ' + TARGETS[name])
            if journal is not None:
                _clear_journal()
            _check_interruption()
            result = _inspect_unlocked()
            require(all(value == 'owned-ro' for value in result['mounts'].values()),
                    'post-apply ownership verification failed')
            return {'changed': len(new_names), 'status': result, 'apply_performed': True,
                    'reload_performed': False, 'visible_rendering_verified': False}
        except BaseException as exc:
            try:
                if _load_journal() is not None:
                    _recover_pending_apply()
            except BaseException as cleanup_exc:
                raise RuntimeError('%s; durable apply recovery incomplete: %s' %
                                   (exc, cleanup_exc))
            raise


def _write_disabled_marker():
    path = os.path.join(BASE, 'disabled')
    if os.path.lexists(path):
        require(_disabled_state(), 'foreign disable marker')
        return False
    _atomic_record(path, DISABLED_MARKER.encode('ascii'), 'disable marker', exclusive=True)
    return True


def rollback_mounts():
    with _lifecycle_lock():
        _check_interruption()
        _load_manifest()
        _recover_pending_apply()
        _check_interruption()
        state = _load_state()
        before = {name: _target_status(name, state) for name in sorted(TARGETS)}
        require(all(value in ('original', 'owned-ro') for value in before.values()),
                'foreign target; rollback refused without changes')
        _check_interruption()
        _write_disabled_marker()
        _check_interruption()
        remaining = dict(state.get('mounts', {})) if state.get('boot_id') == boot_id() else {}
        for name in sorted(TARGETS, reverse=True):
            if before[name] == 'owned-ro':
                record = state.get('mounts', {}).get(name, {})
                rows = mount_rows(TARGETS[name])
                require(len(rows) == 1 and rows[0]['id'] == record.get('mount_id'),
                        'mount instance changed during rollback: ' + TARGETS[name])
                require('ro' in rows[0]['options'] and
                        _same_file(os.path.join(BASE, name + '.patched.qml'), TARGETS[name]),
                        'owned read-only bind changed during rollback: ' + TARGETS[name])
                subprocess.check_call(['umount', TARGETS[name]])
                require(not mount_rows(TARGETS[name]) and
                        file_digest(TARGETS[name]) == ORIGINAL[name],
                        'original target not restored after detach: ' + TARGETS[name])
            remaining.pop(name, None)
            _save_state({'version': 1, 'boot_id': boot_id(), 'mounts': remaining})
            _check_interruption()
        result = _inspect_unlocked()
        _check_interruption()
        require(all(value == 'original' for value in result['mounts'].values()),
                'rollback left a target changed')
        result['future_apply_disabled'] = True
        result['checkpoint_files_retained'] = True
        result['rollback_performed'] = True
        result['reload_performed'] = False
        result['visible_rendering_verified'] = False
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true', help='read-only package and mount verification')
    actions.add_argument('--apply', action='store_true', help='create the two owned read-only binds')
    actions.add_argument('--rollback', action='store_true', help='disable future apply and detach only owned binds')
    parser.add_argument('--ack-mount', action='store_true', help='explicitly approve mount changes')
    parser.add_argument('--ack-rollback', action='store_true', help='explicitly approve rollback')
    parser.add_argument('--boot', action='store_true', help='boot-hook mode; mount only and no-op after rollback')
    args = parser.parse_args(argv)
    if not (args.check or args.apply or args.rollback):
        parser.print_help()
        return 2
    if args.check and (args.ack_mount or args.ack_rollback or args.boot):
        parser.error('--check is read-only and takes no acknowledgement flags')
    if args.apply and (not args.ack_mount or args.ack_rollback):
        parser.error('--apply requires --ack-mount and does not accept --ack-rollback')
    if args.rollback and (not args.ack_rollback or args.ack_mount or args.boot):
        parser.error('--rollback requires --ack-rollback only')
    if args.boot and not args.apply:
        parser.error('--boot is valid only with --apply')
    if args.check:
        result = inspect()
    elif args.apply:
        require(os.geteuid() == 0, 'apply requires root')
        result = apply_mounts(boot=args.boot)
    else:
        require(os.geteuid() == 0, 'rollback requires root')
        result = rollback_mounts()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('screensaver overlay: ' + str(exc), file=sys.stderr)
        sys.exit(1)
