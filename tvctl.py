#!/usr/bin/env python3
"""Conservative, opt-in host CLI for an already-rooted LG CX running webOS."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence, Union


MODEL = "LG OLED65CX6LA"
FIRMWARE = "04.64.00"
WEBOS_RELEASE = "5.6.2"
WEBOS_BUILD_ID = "21"
WEBOS_VERSION = WEBOS_RELEASE + "-" + WEBOS_BUILD_ID
ETC_VERSION = "20260421173614"

FEATURES: dict[str, tuple[str, dict[str, str]]] = {
    "collection": ("option", {"watchedListCollection": "off", "hbbTvDeviceId": "off"}),
    "hbbtv": ("option", {"hbbTV": "off"}),
    "updates": ("support", {"automaticUpdate": "off"}),
}
OBSERVATIONS: dict[str, tuple[str, ...]] = {
    "option": ("livePlus", "turnOnByVoice"),
    "general": ("adCookie", "voiceLongDistance"),
}
ACTION_KEYS: dict[str, tuple[str, ...]] = {}
for _feature_category, _feature_settings in FEATURES.values():
    ACTION_KEYS.setdefault(_feature_category, ())
    ACTION_KEYS[_feature_category] += tuple(_feature_settings)
ALL_SETTING_KEYS = {
    category: tuple(dict.fromkeys(ACTION_KEYS.get(category, ()) + OBSERVATIONS.get(category, ())))
    for category in ("option", "general", "support")
}
LUNA_METHODS = frozenset((
    "luna://com.webos.settingsservice/getSystemSettings",
    "luna://com.webos.settingsservice/getSystemSettingDesc",
    "luna://com.webos.settingsservice/setSystemSettings",
    "luna://com.webos.service.sdx/getDeviceAuthenticationStatus",
    "luna://com.webos.applicationManager/listLaunchPoints",
    "luna://com.webos.applicationManager/getForegroundAppInfo",
))


COORDINATION_POLICY = {
    "owner_exclusive_window_required": True,
    "native_compare_and_set": False,
    "arbitrary_concurrent_changes_protected": False,
    "verification_scope": "fresh target-value readback; native checks and setters are not atomic",
}


class TVCtlError(Exception):
    """Expected safe refusal or transport/protocol failure."""


class RemoteError(TVCtlError):
    pass


def validate_target(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", value) or value in (".", ".."):
        raise argparse.ArgumentTypeError("target must be a safe SSH config alias (letters, digits, dot, underscore, hyphen)")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise argparse.ArgumentTypeError("target must be an SSH config alias, not an IP address")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _private_parent(path: Path) -> None:
    if os.name != "posix":
        raise TVCtlError("private state/checkpoint files require POSIX mode permissions")
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        mode = parent.lstat().st_mode
    except OSError as exc:
        raise TVCtlError("cannot prepare private state directory") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise TVCtlError("state directory must be a real directory")
    if stat.S_IMODE(mode) & 0o077:
        raise TVCtlError("state directory must be private (mode 0700)")


def _check_private_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise TVCtlError("cannot read checkpoint") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TVCtlError("checkpoint must be a regular, non-symlink file")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise TVCtlError("checkpoint must be owned by this user and private (mode 0600)")
    return info


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_private_json(path_arg: Union[str, Path], value: Any, *, exclusive: bool = False) -> None:
    path = Path(path_arg)
    _private_parent(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if exclusive:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError as exc:
            raise TVCtlError("checkpoint already exists; choose a new path") from exc
        except OSError as exc:
            raise TVCtlError("cannot create private checkpoint") from exc
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise TVCtlError("cannot write private checkpoint") from exc
        _check_private_file(path)
        _sync_directory(path.parent)
        return

    # Audit files may be refreshed, but are replaced atomically and stay private.
    temp = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _check_private_file(path)
        _sync_directory(path.parent)
    except OSError as exc:
        try:
            temp.unlink()
        except OSError:
            pass
        raise TVCtlError("cannot write private audit output") from exc


def update_checkpoint(path_arg: Union[str, Path], checkpoint: dict[str, Any], event: str, status: str) -> None:
    path = Path(path_arg)
    _check_private_file(path)
    checkpoint["status"] = status
    checkpoint.setdefault("journal", []).append({"event": event, "status": status})
    data = json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _check_private_file(path)
        os.replace(temp, path)
        _check_private_file(path)
        _sync_directory(path.parent)
    except OSError as exc:
        try:
            temp.unlink()
        except OSError:
            pass
        raise TVCtlError("cannot update private checkpoint journal") from exc


def read_checkpoint(path_arg: Union[str, Path]) -> dict[str, Any]:
    path = Path(path_arg)
    _check_private_file(path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TVCtlError("checkpoint is unreadable or malformed") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise TVCtlError("unsupported checkpoint format")
    return value


class SSHClient:
    """Small SSH/Luna transport. Remote commands are assembled only by this module."""

    def __init__(self, target: str):
        self.target = validate_target(target)

    def run(self, remote_command: str, *, pty: bool = False, timeout: int = 25) -> str:
        args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no",
                "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=8",
                "-o", "ConnectionAttempts=1"]
        if pty:
            args.append("-tt")
        args.extend((self.target, remote_command))
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RemoteError("SSH command timed out") from exc
        except OSError as exc:
            raise RemoteError("SSH could not be started") from exc
        if result.returncode != 0:
            raise RemoteError("SSH command failed (exit %d)" % result.returncode)
        return result.stdout.replace("\r\n", "\n").replace("\r", "\n")

    def luna(self, method: str, request: Mapping[str, Any]) -> dict[str, Any]:
        if method not in LUNA_METHODS:
            raise TVCtlError("Luna method is not allowed")
        payload = json.dumps(request, ensure_ascii=True, separators=(",", ":"))
        command = " ".join(shlex.quote(part) for part in
                            ("luna-send", "-w", "5000", "-n", "1", method, payload))
        text = self.run(command, pty=True, timeout=20).strip()
        if not text:
            raise RemoteError("Luna returned an empty response")
        try:
            response = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RemoteError("Luna returned malformed JSON") from exc
        if not isinstance(response, dict) or response.get("returnValue") is not True:
            raise RemoteError("Luna did not return returnValue=true")
        return response


def parse_connman_properties(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^=]+?)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.group(1).strip(), match.group(2)
        if not key or key in result:
            raise TVCtlError("ConnMan properties contain an ambiguous key")
        result[key] = value
    return result


def parse_nameservers(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            raise TVCtlError("malformed ConnMan nameserver list")
        text = text[1:-1].strip()
    if not text:
        return []
    tokens = re.split(r"\s*,\s*|\s+", text)
    if any(not token for token in tokens):
        raise TVCtlError("malformed ConnMan nameserver list")
    result: list[str] = []
    try:
        for token in tokens:
            result.append(str(ipaddress.ip_address(token)))
    except ValueError as exc:
        raise TVCtlError("ConnMan nameserver list contains an invalid address") from exc
    return result


def validate_dns_servers(values: Sequence[str]) -> list[str]:
    if not values:
        raise TVCtlError("at least one DNS server is required")
    result: list[str] = []
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise TVCtlError("DNS servers must be literal IP addresses") from exc
        if (address.is_unspecified or address.is_multicast or address.is_loopback
                or address.is_link_local or address.is_reserved):
            raise TVCtlError("DNS server must be a usable unicast address")
        canonical = str(address)
        if canonical in result:
            raise TVCtlError("duplicate DNS servers are not allowed")
        result.append(canonical)
    return result


def service_ids(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b(ethernet_[A-Za-z0-9_]+)\b", text)))


def non_dns_hash(properties: Mapping[str, str]) -> str:
    stable = {key: value for key, value in properties.items()
              if key not in ("Nameservers", "Nameservers.Configuration")}
    return hashlib.sha256(_json_bytes(stable)).hexdigest()


class TVController:
    def __init__(self, target: str, client: Optional[Any] = None,
                 confirmed_model: Optional[str] = None):
        self.target = validate_target(target)
        self.tv = client if client is not None else SSHClient(self.target)
        if confirmed_model is not None and confirmed_model != MODEL:
            raise TVCtlError("--confirm-model must exactly match the supported CX model")
        self.confirmed_model = confirmed_model

    def _get_settings(self, category: str, keys: Sequence[str]) -> dict[str, str]:
        response = self.tv.luna("luna://com.webos.settingsservice/getSystemSettings",
                                {"category": category, "keys": list(keys)})
        settings = response.get("settings")
        if not isinstance(settings, dict):
            raise TVCtlError("settings response has an unknown schema")
        result: dict[str, str] = {}
        for key in keys:
            value = settings.get(key)
            if not isinstance(value, str):
                raise TVCtlError("settings response omitted or mistyped a requested key")
            result[key] = value
        return result

    def _setting_enums(self, category: str, keys: Sequence[str]) -> dict[str, list[str]]:
        response = self.tv.luna("luna://com.webos.settingsservice/getSystemSettingDesc",
                                {"category": category, "keys": list(keys)})
        rows = response.get("results")
        if not isinstance(rows, list):
            raise TVCtlError("setting description response has an unknown schema")
        by_key: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str) or row["key"] in by_key:
                raise TVCtlError("setting descriptions contain an ambiguous key")
            by_key[row["key"]] = row
        if set(by_key) != set(keys):
            raise TVCtlError("setting description omitted or added a requested key")
        enums: dict[str, list[str]] = {}
        for key in keys:
            values = by_key[key].get("values")
            if not isinstance(values, dict):
                raise TVCtlError("setting description has no supported-value schema")
            base, extended = values.get("array", []), values.get("arrayExt", [])
            if not isinstance(base, list) or not isinstance(extended, list):
                raise TVCtlError("setting description enum has an unknown schema")
            allowed: list[str] = []
            for item in base:
                if not isinstance(item, str):
                    raise TVCtlError("setting description enum contains an unknown value type")
                allowed.append(item)
            for item in extended:
                if not isinstance(item, dict) or not isinstance(item.get("value"), str):
                    raise TVCtlError("setting description extended enum has an unknown schema")
                allowed.append(item["value"])
            if not allowed or len(set(allowed)) != len(allowed):
                raise TVCtlError("setting description enum is empty or ambiguous")
            enums[key] = allowed
        return enums

    def _identity(self) -> dict[str, str]:
        uid = self.tv.run("id -u").strip()
        if uid != "0":
            raise TVCtlError("target is not running the required root shell")
        build = self.tv.run("cat /etc/version").strip()
        boot = self.tv.run("cat /proc/sys/kernel/random/boot_id").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", boot):
            raise TVCtlError("boot identity is missing or malformed")
        try:
            os_info = json.loads(self.tv.run("cat /var/run/nyx/os_info.json").strip())
        except (json.JSONDecodeError, AttributeError) as exc:
            raise TVCtlError("Nyx OS version metadata is malformed") from exc
        if not isinstance(os_info, dict):
            raise TVCtlError("Nyx OS version metadata has an unknown schema")
        name = os_info.get("webos_name")
        release = os_info.get("webos_release")
        webos_build = os_info.get("webos_build_id")
        firmware = os_info.get("webos_manufacturing_version")
        if (name != "webOS TV" or release != WEBOS_RELEASE or webos_build != WEBOS_BUILD_ID
                or firmware != FIRMWARE or build != ETC_VERSION):
            raise TVCtlError("unsupported webOS/firmware/build version; refusing operation")
        return {"model": self.confirmed_model or "unconfirmed-by-operator",
                "model_confirmation": "operator" if self.confirmed_model else "required-before-write",
                "firmware": firmware, "webos_name": name, "webos_version": WEBOS_VERSION,
                "etc_version": build, "boot_id": boot.lower()}

    def _active_ethernet(self) -> tuple[str, dict[str, str]]:
        listing = self.tv.run("connmanctl services")
        candidates = service_ids(listing)
        if not candidates:
            raise TVCtlError("ConnMan listed no Ethernet services")
        active: list[tuple[str, dict[str, str]]] = []
        for service in candidates:
            properties = parse_connman_properties(
                self.tv.run("connmanctl services " + shlex.quote(service)))
            if properties.get("Type") == "ethernet" and properties.get("State") == "online":
                for required in ("Nameservers", "Nameservers.Configuration"):
                    if required not in properties:
                        raise TVCtlError("active ConnMan service omitted a resolver property")
                # Parse now so malformed values never get stored in a checkpoint.
                parse_nameservers(properties["Nameservers"])
                parse_nameservers(properties["Nameservers.Configuration"])
                active.append((service, properties))
        if len(active) != 1:
            raise TVCtlError("expected exactly one active Ethernet ConnMan service; found %d" % len(active))
        return active[0]

    def inspect(self, *, include_dns: bool = False) -> dict[str, Any]:
        identity = self._identity()
        settings: dict[str, dict[str, str]] = {}
        for category, keys in ALL_SETTING_KEYS.items():
            settings[category] = self._get_settings(category, keys)
        enums: dict[str, dict[str, list[str]]] = {}
        for category, keys in ACTION_KEYS.items():
            enums[category] = self._setting_enums(category, keys)
            for key in keys:
                current = settings[category][key]
                if current not in enums[category][key]:
                    raise TVCtlError("current setting value is outside its native enum")
        sdx = self.tv.luna("luna://com.webos.service.sdx/getDeviceAuthenticationStatus", {})
        if sdx.get("isDeviceAuthenticated") is not True:
            raise TVCtlError("SDX authentication health check failed")
        app_response = self.tv.luna("luna://com.webos.applicationManager/listLaunchPoints", {})
        launchpoints = app_response.get("launchPoints")
        if not isinstance(launchpoints, list):
            raise TVCtlError("application launch-point response has an unknown schema")
        foreground = self.tv.luna("luna://com.webos.applicationManager/getForegroundAppInfo", {})
        app_id = foreground.get("appId")
        if not isinstance(app_id, str) or not app_id:
            raise TVCtlError("foreground application identity is unavailable")
        result: dict[str, Any] = {
            "identity": identity,
            "settings": settings,
            "setting_enums": enums,
            "sdx_authenticated": True,
            "launchpoint_count": len(launchpoints),
            "foreground_app_id": app_id,
        }
        if include_dns:
            service, properties = self._active_ethernet()
            result["dns"] = {
                "service": service,
                "properties": properties,
                "stored": parse_nameservers(properties["Nameservers.Configuration"]),
                "effective": parse_nameservers(properties["Nameservers"]),
                "non_dns_sha256": non_dns_hash(properties),
            }
        return result

    def audit(self) -> dict[str, Any]:
        snapshot = self.inspect(include_dns=True)
        dns = snapshot["dns"]
        return {
            "target": self.target,
            "read_only": True,
            "device": snapshot["identity"],
            "settings": snapshot["settings"],
            "setting_enums": snapshot["setting_enums"],
            "sdx_authenticated": snapshot["sdx_authenticated"],
            "launchpoint_count": snapshot["launchpoint_count"],
            "foreground_app_id": snapshot["foreground_app_id"],
            "ethernet_dns": {
                "active_service_count": 1,
                "stored_nameservers": dns["stored"],
                "effective_nameservers": dns["effective"],
            },
        }

    def _new_checkpoint(self, path: Union[str, Path], operation: dict[str, Any], identity: dict[str, str],
                        before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        checkpoint = {
            "schema": 1,
            "target": self.target,
            "operation": operation,
            "identity": identity,
            "before": before,
            "after": after,
            "status": "prepared",
            "journal": [{"event": "exclusive-checkpoint-created", "status": "prepared"}],
        }
        write_private_json(path, checkpoint, exclusive=True)
        return checkpoint

    def _assert_identity(self, expected: Mapping[str, str]) -> None:
        if self._identity() != dict(expected):
            raise TVCtlError("target identity changed since checkpoint; refusing write")

    def settings(self, feature: str, *, apply: bool = False,
                 checkpoint_path: Optional[Union[str, Path]] = None) -> dict[str, Any]:
        if feature not in FEATURES:
            raise TVCtlError("unknown settings feature")
        category, proposed = FEATURES[feature]
        snapshot = self.inspect(include_dns=False)
        before = {key: snapshot["settings"][category][key] for key in proposed}
        enums = snapshot["setting_enums"][category]
        for key, wanted in proposed.items():
            if wanted not in enums[key]:
                raise TVCtlError("requested setting value is not in the native enum")
        plan = {"target": self.target, "operation": "settings", "feature": feature,
                "coordination": dict(COORDINATION_POLICY),
                "mode": "apply" if apply else "plan", "before": before,
                "proposed_after": proposed, "changed_keys": [key for key in proposed if before[key] != proposed[key]]}
        if not apply:
            return plan
        if checkpoint_path is None:
            raise TVCtlError("--checkpoint is required for apply")
        if self.confirmed_model != MODEL:
            raise TVCtlError("owner confirmation of the LG CX model is required before a write")
        if not plan["changed_keys"]:
            plan["mode"] = "no-op"
            plan["checkpoint"] = None
            return plan
        checkpoint = self._new_checkpoint(checkpoint_path, {"kind": "settings", "feature": feature},
                                          snapshot["identity"], before, dict(proposed))
        try:
            self._assert_identity(checkpoint["identity"])
            current = self._get_settings(category, tuple(proposed))
            if current != before:
                update_checkpoint(checkpoint_path, checkpoint, "pre-write-state-conflict", "conflict-before-write")
                raise TVCtlError("targeted setting changed before write; checkpoint retained")
            update_checkpoint(checkpoint_path, checkpoint, "settings-write-attempted", "write-attempted")
            self.tv.luna("luna://com.webos.settingsservice/setSystemSettings",
                         {"category": category, "settings": proposed})
            readback = self._get_settings(category, tuple(proposed))
            if readback != proposed:
                update_checkpoint(checkpoint_path, checkpoint, "settings-readback-mismatch", "readback-failed")
                raise TVCtlError("settings readback did not match; checkpoint retained, no automatic rollback")
            update_checkpoint(checkpoint_path, checkpoint, "settings-readback-verified", "verified")
        except TVCtlError:
            if checkpoint.get("status") in ("prepared", "write-attempted"):
                update_checkpoint(checkpoint_path, checkpoint, "settings-apply-failed", "apply-failed")
            raise
        plan["mode"] = "verified"
        plan["readback"] = readback
        plan["checkpoint"] = str(checkpoint_path)
        return plan

    def dns(self, servers: Sequence[str], *, apply: bool = False,
            checkpoint_path: Optional[Union[str, Path]] = None,
            ack_external_dns: bool = False) -> dict[str, Any]:
        desired = validate_dns_servers(servers)
        snapshot = self.inspect(include_dns=True)
        dns = snapshot["dns"]
        before = {"stored_nameservers": dns["stored"], "effective_nameservers": dns["effective"],
                  "non_dns_properties_sha256": dns["non_dns_sha256"]}
        after = {"stored_nameservers": desired, "effective_nameservers": desired,
                 "non_dns_properties_sha256": dns["non_dns_sha256"]}
        plan = {"target": self.target, "operation": "dns", "mode": "apply" if apply else "plan",
                "coordination": dict(COORDINATION_POLICY),
                "before": before, "proposed_after": after,
                "changed": dns["stored"] != desired or dns["effective"] != desired}
        if not apply:
            return plan
        if checkpoint_path is None:
            raise TVCtlError("--checkpoint is required for apply")
        if self.confirmed_model != MODEL:
            raise TVCtlError("owner confirmation of the LG CX model is required before a write")
        if not ack_external_dns:
            raise TVCtlError("DNS apply requires acknowledgement that resolver traffic leaves the TV")
        if not dns["stored"]:
            raise TVCtlError("automatic-DNS baseline: restoring an empty ConnMan configuration is not hardware-verified; use the TV network UI with a recorded manual recovery plan instead; no change made")
        if not plan["changed"]:
            plan["mode"] = "no-op"
            plan["checkpoint"] = None
            return plan
        operation = {"kind": "dns", "service": dns["service"]}
        checkpoint = self._new_checkpoint(checkpoint_path, operation, snapshot["identity"], before, after)
        try:
            self._assert_identity(checkpoint["identity"])
            service, properties = self._active_ethernet()
            current_dns = {"stored_nameservers": parse_nameservers(properties["Nameservers.Configuration"]),
                           "effective_nameservers": parse_nameservers(properties["Nameservers"]),
                           "non_dns_properties_sha256": non_dns_hash(properties)}
            if service != dns["service"] or current_dns != before:
                update_checkpoint(checkpoint_path, checkpoint, "pre-write-state-conflict", "conflict-before-write")
                raise TVCtlError("Ethernet resolver changed before write; checkpoint retained")
            update_checkpoint(checkpoint_path, checkpoint, "dns-write-attempted", "write-attempted")
            self._set_connman_nameservers(service, desired)
            readback_service, readback_props = self._active_ethernet()
            readback = {"stored_nameservers": parse_nameservers(readback_props["Nameservers.Configuration"]),
                        "effective_nameservers": parse_nameservers(readback_props["Nameservers"]),
                        "non_dns_properties_sha256": non_dns_hash(readback_props)}
            if readback_service != service or readback != after:
                update_checkpoint(checkpoint_path, checkpoint, "dns-readback-mismatch", "readback-failed")
                raise TVCtlError("DNS stored/effective readback did not match; checkpoint retained, no automatic rollback")
            update_checkpoint(checkpoint_path, checkpoint, "dns-readback-verified", "verified")
        except TVCtlError:
            if checkpoint.get("status") in ("prepared", "write-attempted"):
                update_checkpoint(checkpoint_path, checkpoint, "dns-apply-failed", "apply-failed")
            raise
        plan["mode"] = "verified"
        plan["readback"] = readback
        plan["checkpoint"] = str(checkpoint_path)
        return plan

    def _set_connman_nameservers(self, service: str, servers: Sequence[str]) -> None:
        if not servers:
            raise TVCtlError("automatic-DNS reset syntax is not verified; refusing an empty nameserver write")
        parts = ["connmanctl", "config", service, "--nameservers", *servers]
        self.tv.run(" ".join(shlex.quote(part) for part in parts), timeout=25)

    def _validate_checkpoint(self, checkpoint: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        if checkpoint.get("target") != self.target:
            raise TVCtlError("checkpoint target does not match --target")
        kind = checkpoint.get("operation", {}).get("kind") if isinstance(checkpoint.get("operation"), dict) else None
        if kind not in ("settings", "dns"):
            raise TVCtlError("checkpoint operation is unsupported")
        if checkpoint.get("status") not in ("prepared", "write-attempted", "apply-failed", "readback-failed",
                                               "verified", "rollback-attempted", "rollback-failed", "rollback-verified"):
            raise TVCtlError("checkpoint status is not recoverable")
        return kind, dict(checkpoint)

    def rollback(self, checkpoint_path: Union[str, Path], *, apply: bool = False) -> dict[str, Any]:
        checkpoint = read_checkpoint(checkpoint_path)
        kind, checkpoint = self._validate_checkpoint(checkpoint)
        operation = checkpoint["operation"]
        feature = operation.get("feature") if kind == "settings" else None
        if kind == "settings" and feature not in FEATURES:
            raise TVCtlError("checkpoint settings feature is unsupported")
        if kind == "settings":
            category, proposed = FEATURES[feature]
            if set(checkpoint.get("before", {})) != set(proposed) or checkpoint.get("after") != proposed:
                raise TVCtlError("checkpoint settings state is inconsistent")
        else:
            if not isinstance(operation.get("service"), str) or not re.fullmatch(r"ethernet_[A-Za-z0-9_]+", operation["service"]):
                raise TVCtlError("checkpoint ConnMan service is malformed")
            for side in (checkpoint.get("before"), checkpoint.get("after")):
                if not isinstance(side, dict) or not isinstance(side.get("stored_nameservers"), list) or not isinstance(side.get("effective_nameservers"), list):
                    raise TVCtlError("checkpoint DNS state is malformed")
                if any(not isinstance(x, str) for x in side["stored_nameservers"] + side["effective_nameservers"]):
                    raise TVCtlError("checkpoint DNS state is malformed")
                if (parse_nameservers(", ".join(side["stored_nameservers"])) != side["stored_nameservers"]
                        or parse_nameservers(", ".join(side["effective_nameservers"])) != side["effective_nameservers"]):
                    raise TVCtlError("checkpoint DNS state contains an invalid address")
            if checkpoint["after"]["stored_nameservers"] != checkpoint["after"]["effective_nameservers"]:
                raise TVCtlError("checkpoint DNS proposed state is inconsistent")
        if not apply:
            return {"target": self.target, "operation": "rollback", "mode": "plan",
                    "coordination": dict(COORDINATION_POLICY),
                    "checkpoint": str(checkpoint_path), "checkpoint_status": checkpoint["status"],
                    "checkpoint_operation": kind}

        snapshot = self.inspect(include_dns=(kind == "dns"))
        if snapshot["identity"] != checkpoint.get("identity"):
            raise TVCtlError("target boot/version identity differs from checkpoint; refusing rollback")
        if kind == "settings":
            result = self._rollback_settings(checkpoint_path, checkpoint, category, proposed)
        else:
            result = self._rollback_dns(checkpoint_path, checkpoint, snapshot)
        result["coordination"] = dict(COORDINATION_POLICY)
        return result

    def _rollback_settings(self, path: Union[str, Path], checkpoint: dict[str, Any],
                           category: str, proposed: Mapping[str, str]) -> dict[str, Any]:
        keys = tuple(proposed)
        before = checkpoint["before"]
        after = checkpoint["after"]
        enums = self._setting_enums(category, keys)
        for key in keys:
            if before[key] not in enums[key] or after[key] not in enums[key]:
                raise TVCtlError("checkpoint value is not in the current native enum")
        current = self._get_settings(category, keys)
        if any(current[key] not in (before[key], after[key]) for key in keys):
            raise TVCtlError("live setting differs from both checkpoint states; refusing to clobber another change")
        to_restore = {key: before[key] for key in keys if current[key] == after[key] and before[key] != after[key]}
        if not to_restore:
            update_checkpoint(path, checkpoint, "rollback-already-at-before-state", "rollback-verified")
            return {"target": self.target, "operation": "rollback", "mode": "already-restored", "readback": current}
        recheck = self._get_settings(category, keys)
        if recheck != current:
            raise TVCtlError("targeted setting changed before rollback write")
        update_checkpoint(path, checkpoint, "rollback-settings-write-attempted", "rollback-attempted")
        try:
            self.tv.luna("luna://com.webos.settingsservice/setSystemSettings",
                         {"category": category, "settings": to_restore})
            readback = self._get_settings(category, keys)
            if readback != before:
                update_checkpoint(path, checkpoint, "rollback-settings-readback-mismatch", "rollback-failed")
                raise TVCtlError("rollback readback did not match; checkpoint retained")
        except TVCtlError:
            if checkpoint.get("status") == "rollback-attempted":
                update_checkpoint(path, checkpoint, "rollback-settings-failed", "rollback-failed")
            raise
        update_checkpoint(path, checkpoint, "rollback-settings-verified", "rollback-verified")
        return {"target": self.target, "operation": "rollback", "mode": "verified", "readback": readback}

    def _rollback_dns(self, path: Union[str, Path], checkpoint: dict[str, Any],
                      snapshot: Mapping[str, Any]) -> dict[str, Any]:
        operation = checkpoint["operation"]
        service = operation["service"]
        live_service, properties = self._active_ethernet()
        if live_service != service:
            raise TVCtlError("active Ethernet service differs from checkpoint; refusing rollback")
        current = {"stored_nameservers": parse_nameservers(properties["Nameservers.Configuration"]),
                   "effective_nameservers": parse_nameservers(properties["Nameservers"]),
                   "non_dns_properties_sha256": non_dns_hash(properties)}
        before, after = checkpoint["before"], checkpoint["after"]
        if not before["stored_nameservers"]:
            raise TVCtlError("automatic-DNS rollback is not verified; restore Automatic DNS through the TV network UI, not a guessed ConnMan reset")
        if current["non_dns_properties_sha256"] != before.get("non_dns_properties_sha256"):
            raise TVCtlError("unrelated ConnMan properties changed; refusing rollback")
        if current == before:
            update_checkpoint(path, checkpoint, "rollback-already-at-before-state", "rollback-verified")
            return {"target": self.target, "operation": "rollback", "mode": "already-restored", "readback": current}
        if current != after:
            raise TVCtlError("live resolver differs from both checkpoint states; refusing to clobber another change")
        service_again, props_again = self._active_ethernet()
        check_again = {"stored_nameservers": parse_nameservers(props_again["Nameservers.Configuration"]),
                       "effective_nameservers": parse_nameservers(props_again["Nameservers"]),
                       "non_dns_properties_sha256": non_dns_hash(props_again)}
        if service_again != service or check_again != current:
            raise TVCtlError("Ethernet resolver changed before rollback write")
        update_checkpoint(path, checkpoint, "rollback-dns-write-attempted", "rollback-attempted")
        try:
            self._set_connman_nameservers(service, before["stored_nameservers"])
            restored_service, restored_props = self._active_ethernet()
            readback = {"stored_nameservers": parse_nameservers(restored_props["Nameservers.Configuration"]),
                        "effective_nameservers": parse_nameservers(restored_props["Nameservers"]),
                        "non_dns_properties_sha256": non_dns_hash(restored_props)}
            if restored_service != service or readback != before:
                update_checkpoint(path, checkpoint, "rollback-dns-readback-mismatch", "rollback-failed")
                raise TVCtlError("DNS rollback readback did not match; checkpoint retained")
        except TVCtlError:
            if checkpoint.get("status") == "rollback-attempted":
                update_checkpoint(path, checkpoint, "rollback-dns-failed", "rollback-failed")
            raise
        update_checkpoint(path, checkpoint, "rollback-dns-verified", "rollback-verified")
        return {"target": self.target, "operation": "rollback", "mode": "verified", "readback": readback}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only audit and explicitly approved LG CX settings/DNS operations.")
    parser.add_argument("--target", required=True, type=validate_target,
                        help="required SSH config alias; no default device is inferred")
    parser.add_argument("--confirm-model", help="owner confirmation; required for every mutation (exact: LG OLED65CX6LA)")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="collect a safe, read-only TV snapshot")
    audit.add_argument("--output", help="write a private JSON audit file (default: stdout)")

    settings = commands.add_parser("settings", help="plan or apply one supported settings feature")
    settings.add_argument("--feature", required=True, choices=sorted(FEATURES))
    settings.add_argument("--apply", action="store_true", help="perform the explicitly confirmed mutation")
    settings.add_argument("--confirm-target", help="must exactly match --target for apply")
    settings.add_argument("--checkpoint", help="new private, exclusive-create checkpoint path")

    dns = commands.add_parser("dns", help="plan or apply a ConnMan DNS-only change")
    dns.add_argument("--servers", nargs="+", required=True, metavar="IP")
    dns.add_argument("--apply", action="store_true", help="perform the explicitly confirmed mutation")
    dns.add_argument("--confirm-target", help="must exactly match --target for apply")
    dns.add_argument("--ack-external-dns", action="store_true", help="acknowledge DNS resolver traffic leaves the TV")
    dns.add_argument("--checkpoint", help="new private, exclusive-create checkpoint path")

    rollback = commands.add_parser("rollback", help="plan or safely restore one owned checkpoint")
    rollback.add_argument("--checkpoint", required=True, help="private checkpoint created by this CLI")
    rollback.add_argument("--apply", action="store_true", help="perform explicitly confirmed rollback")
    rollback.add_argument("--confirm-target", help="must exactly match --target for rollback")
    return parser


def _validate_consent(args: argparse.Namespace) -> None:
    if args.confirm_model is not None and args.confirm_model != MODEL:
        raise TVCtlError("--confirm-model must exactly match the supported CX model")
    if args.command == "settings":
        if args.apply:
            if args.confirm_target != args.target:
                raise TVCtlError("settings apply requires --confirm-target exactly matching --target")
            if args.confirm_model != MODEL:
                raise TVCtlError("settings apply requires owner --confirm-model 'LG OLED65CX6LA'")
            if not args.checkpoint:
                raise TVCtlError("settings apply requires --checkpoint")
        elif args.confirm_target is not None or args.checkpoint is not None:
            raise TVCtlError("--confirm-target and --checkpoint are only valid with --apply")
    elif args.command == "dns":
        validate_dns_servers(args.servers)
        if args.apply:
            if args.confirm_target != args.target:
                raise TVCtlError("DNS apply requires --confirm-target exactly matching --target")
            if args.confirm_model != MODEL:
                raise TVCtlError("DNS apply requires owner --confirm-model 'LG OLED65CX6LA'")
            if not args.ack_external_dns:
                raise TVCtlError("DNS apply requires --ack-external-dns")
            if not args.checkpoint:
                raise TVCtlError("DNS apply requires --checkpoint")
        elif args.confirm_target is not None or args.checkpoint is not None or args.ack_external_dns:
            raise TVCtlError("DNS consent/checkpoint flags are only valid with --apply")
    elif args.command == "rollback":
        if args.apply and args.confirm_target != args.target:
            raise TVCtlError("rollback apply requires --confirm-target exactly matching --target")
        if args.apply and args.confirm_model != MODEL:
            raise TVCtlError("rollback apply requires owner --confirm-model 'LG OLED65CX6LA'")
        if not args.apply and args.confirm_target is not None:
            raise TVCtlError("--confirm-target is only valid with --apply")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_consent(args)
        controller = TVController(args.target, confirmed_model=args.confirm_model)
        if args.command == "audit":
            result = controller.audit()
            if args.output:
                write_private_json(args.output, result)
                print(json.dumps({"status": "written", "output": args.output, "mode": "0600"}, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command == "settings":
            result = controller.settings(args.feature, apply=args.apply, checkpoint_path=args.checkpoint)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command == "dns":
            result = controller.dns(args.servers, apply=args.apply, checkpoint_path=args.checkpoint,
                                    ack_external_dns=args.ack_external_dns)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            result = controller.rollback(args.checkpoint, apply=args.apply)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except TVCtlError as exc:
        print("tvctl: " + str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not dump provider responses, command output, or a traceback to the terminal.
        print("tvctl: operation failed (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
