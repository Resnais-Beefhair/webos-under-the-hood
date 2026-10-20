#!/usr/bin/env python
"""Reload only webOS Home; mutations require --ack-home-reload."""
from __future__ import print_function
import json
import os
import shlex
try:
    from shlex import quote
except ImportError:  # TV Python 2.7; pipes is absent from newer host Python.
    from pipes import quote
import signal
import subprocess
import sys
import time

APP = "com.webos.app.home"
SCHEMA_DIR = "/etc/palm/schemas/sam"
ALLOWED = (
    "com.webos.applicationManager/running",
    "com.webos.applicationManager/closeByAppId",
    "com.webos.applicationManager/launch",
)


def require_root():
    if os.getuid() != 0:
        raise RuntimeError("root privileges are required on the TV")


def validate_payload(method, payload, schema_dir=SCHEMA_DIR, schema_loader=None):
    if method not in ("com.webos.applicationManager/closeByAppId", "com.webos.applicationManager/launch"):
        return
    name = method.rsplit("/", 1)[1]
    if schema_loader is None:
        path = os.path.join(schema_dir, "applicationManager." + name + ".schema")
        with open(path, "r") as stream:
            schema = json.load(stream)
    else:
        schema = schema_loader(name)
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    missing = [key for key in required if key not in payload]
    unknown = [key for key in payload if key not in properties]
    if missing:
        raise ValueError("native schema requires %s parameter(s)" % ", ".join(missing))
    if unknown:
        raise ValueError("native schema does not allow %s parameter(s)" % ", ".join(unknown))
    for key, value in payload.items():
        definition = properties.get(key, {})
        expected = definition.get("type")
        if expected is None:
            continue
        accepted = expected if isinstance(expected, list) else [expected]
        actual = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string" if isinstance(value, (str, bytes)) else "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "null"
        if actual not in accepted and not (actual == "integer" and "number" in accepted):
            raise ValueError("parameter %s has type %s; native schema expects %s" % (key, actual, ", ".join(accepted)))
        enum = definition.get("enum")
        if enum is not None and value not in enum:
            raise ValueError("parameter %s value is outside the native schema enum" % key)


def luna(method, payload, schema_dir=SCHEMA_DIR):
    if method not in ALLOWED:
        raise ValueError("Luna method is not in the Home-reload allowlist")
    validate_payload(method, payload, schema_dir)
    command = "luna-send -w 5000 -n 1 %s %s" % (
        quote("luna://" + method),
        quote(json.dumps(payload, separators=(",", ":"))),
    )
    # Luna on this firmware requires a controlling PTY. Its request timeout is bounded.
    data = subprocess.check_output(["script", "-q", "-e", "-c", command, "/dev/null"])
    if not isinstance(data, str):
        data = data.decode("utf-8")
    response = json.loads(data.replace("\r", "").strip())
    if response.get("returnValue") is not True:
        raise RuntimeError("Luna request failed: %r" % response)
    return response


def running(api=luna):
    result = api("com.webos.applicationManager/running", {})
    apps = result.get("running")
    if not isinstance(apps, list):
        raise ValueError("running response has no running list")
    return apps


def home_pids(apps):
    pids = set()
    for item in apps:
        if not isinstance(item, dict):
            raise ValueError("running list contains a non-object")
        if item.get("id") == APP:
            try:
                pids.add(int(item["processid"]))
            except (KeyError, TypeError, ValueError):
                raise ValueError("Home running record is missing a valid processid")
    return pids


def start_time(pid):
    try:
        with open("/proc/%s/stat" % pid, "r") as stream:
            fields = stream.read().rsplit(")", 1)[1].split()
        return fields[19]
    except (IOError, OSError, IndexError):
        return None


def is_snapshot(params):
    return params.get("snapshot") is True or params.get("parameters", {}).get("snapshot") is True


def read_home_params(pid):
    with open("/proc/%s/cmdline" % pid, "rb") as stream:
        fields = stream.read().decode("utf-8").split("\0")
    if len(fields) < 2 or not fields[1]:
        raise ValueError("Home process command line has no parameter JSON")
    result = json.loads(fields[1])
    if not isinstance(result, dict):
        raise ValueError("Home process parameters are not an object")
    return result


def other_app_identities(apps, starttime=start_time):
    rows = []
    for item in apps:
        if item.get("id") == APP:
            continue
        try:
            pid = int(item["processid"])
            app_id = item["id"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("running list has an invalid non-Home app record")
        rows.append((app_id, pid, starttime(pid)))
    return tuple(sorted(rows))


def launch_payload(mode):
    payload = {
        "id": APP,
        "spinner": False,
        "noSplash": True,
        "checkUpdateOnLaunch": False,
        "launchHidden": False,
    }
    if mode == "--hidden":
        payload.update({"preload": "full", "launchHidden": True})
    return payload


def reload_home(mode, allow_original_snapshot=False, api=luna, sleep=time.sleep,
                clock=time.time, starttime=start_time, read_params=read_home_params,
                readlink=os.readlink, terminate=os.kill, validator=validate_payload):
    if mode not in ("--hidden", "--visible"):
        raise ValueError("reload mode must be --hidden or --visible")
    # Validate every mutating request before closing Home, so schema failure
    # cannot strand the user without a relaunched Home process.
    validator("com.webos.applicationManager/closeByAppId", {"id": APP})
    payload = launch_payload(mode)
    validator("com.webos.applicationManager/launch", payload)
    before = running(api)
    old = home_pids(before)
    stamps = dict((pid, starttime(pid)) for pid in old)
    other_before = other_app_identities(before, starttime)
    if old:
        api("com.webos.applicationManager/closeByAppId", {"id": APP})
        sleep(1)
        for pid in old:
            if stamps[pid] is not None and starttime(pid) == stamps[pid]:
                executable = readlink("/proc/%s/exe" % pid)
                if executable != "/usr/bin/com.webos.app.home":
                    raise RuntimeError("refusing TERM: PID no longer names the exact Home executable")
                terminate(pid, signal.SIGTERM)
        deadline = clock() + 6
        while any(stamps[pid] is not None and starttime(pid) == stamps[pid] for pid in old):
            if clock() > deadline:
                raise RuntimeError("original Home did not exit; no KILL escalation")
            sleep(0.2)
    api("com.webos.applicationManager/launch", payload)
    deadline = clock() + 12
    while True:
        after = running(api)
        new = home_pids(after)
        if new and all(starttime(pid) is not None and starttime(pid) != stamps.get(pid) for pid in new):
            break
        if clock() > deadline:
            raise RuntimeError("no fresh Home PID appeared")
        sleep(0.4)
    sleep(2)
    final = running(api)
    final_home = home_pids(final)
    if final_home != new:
        raise RuntimeError("Home PID set changed during final verification")
    if any(starttime(pid) is None or starttime(pid) == stamps.get(pid) for pid in final_home):
        raise RuntimeError("Home process identity changed during final verification")
    params = dict((str(pid), read_params(pid)) for pid in final_home)
    snapshot_flags = dict((pid, is_snapshot(value)) for pid, value in params.items())
    if not allow_original_snapshot and any(snapshot_flags.values()):
        raise RuntimeError("Home restored a CRIU snapshot instead of starting new code")
    if other_app_identities(final, starttime) != other_before:
        raise RuntimeError("another app PID or process start time changed while reloading Home")
    return {
        "old_home_pids": sorted(old),
        "new_home_pids": sorted(final_home),
        "old_home_starttimes": stamps,
        "new_home_starttimes": dict((pid, starttime(pid)) for pid in final_home),
        "new_home_snapshot_flags": snapshot_flags,
        "other_app_pids_and_starttimes_unchanged": True,
        "mode": mode,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("No action. Use --preflight or a reload mode plus --ack-home-reload.", file=sys.stderr)
        return 2
    if argv == ["--preflight"]:
        try:
            require_root()
            validate_payload("com.webos.applicationManager/closeByAppId", {"id": APP})
            validate_payload("com.webos.applicationManager/launch", launch_payload("--visible"))
            validate_payload("com.webos.applicationManager/launch", launch_payload("--hidden"))
            apps = running()
            pids = home_pids(apps)
            missing = [pid for pid in pids if start_time(pid) is None]
            if missing:
                raise RuntimeError("could not read process start time for Home PID(s)")
            print(json.dumps({"home_pids": sorted(pids), "running_app_count": len(apps)}, sort_keys=True))
            return 0
        except Exception as exc:
            print("reload preflight refused: %s" % exc, file=sys.stderr)
            return 1
    allowed_options = {"--ack-home-reload", "--allow-original-snapshot"}
    options = argv[1:]
    if (argv[0] not in ("--hidden", "--visible") or
            "--ack-home-reload" not in options or
            any(option not in allowed_options for option in options) or
            len(options) != len(set(options))):
        print("Explicit reload mode and --ack-home-reload are required; no reload made.", file=sys.stderr)
        return 2
    try:
        require_root()
        result = reload_home(argv[0], "--allow-original-snapshot" in argv)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("Home reload failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
