"""Offline safety tests for tvctl; every device interface is synthetic."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import Optional
from unittest.mock import patch

import tvctl


BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"
SERVICE = "ethernet_fixture_cable"
SERVERS = ["94.140.14.14", "94.140.15.15"]


class FakeTV:
    """In-memory TV contract; never opens sockets or launches SSH."""
    def __init__(self):
        self.settings = {
            "option": {"watchedListCollection": "on", "hbbTvDeviceId": "on", "hbbTV": "on",
                       "livePlus": "off", "turnOnByVoice": "off"},
            "general": {"adCookie": "off", "voiceLongDistance": "off"},
            "support": {"automaticUpdate": "on"},
        }
        self.setting_set_calls = []
        self.run_calls = []
        self.setting_get_counts = {}
        self.change_on_recheck = None
        self.enum_values = {key: ["on", "off"] for values in self.settings.values() for key in values}
        self.enum_extended = {}
        for key in ("livePlus", "turnOnByVoice", "adCookie", "voiceLongDistance"):
            self.enum_values[key] = []
            self.enum_extended[key] = ["on", "off"]
        self.enum_values["hbbTV"] = ["on", "off"]
        self.enum_extended["hbbTV"] = ["onByUser", "offByUser"]
        self.drop_setting_writes = False
        self.fail_setting_category: Optional[str] = None
        self.service_state = "online"
        self.extra_active_service = False
        self.dns_stored = ["192.0.2.53"]
        self.dns_effective = ["192.0.2.53"]
        self.dhcp_effective = ["192.0.2.53"]
        self.keep_dns_effective = False
        self.non_dns = {
            "Type": "ethernet", "State": "online", "IPv4.Method": "dhcp",
            "IPv4.Address": "192.0.2.10", "Proxy.Method": "direct",
        }
        self.os_info = {
            "webos_name": "webOS TV", "webos_release": "5.6.2", "webos_build_id": "21",
            "webos_manufacturing_version": "04.64.00",
        }
        self.build = "20260421173614"
        self.setter_calls = []
        self.service_states = {
            "voiceinput.service": {"LoadState": "masked", "ActiveState": "inactive", "UnitFileState": "masked"},
            "contentminer.service": {"LoadState": "masked", "ActiveState": "inactive", "UnitFileState": "masked-runtime"},
            "voiceconductor.service": {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "static"},
        }
        self.mount_modes = {
            "/etc/hosts": "rw",
            "/etc/systemd/system/voiceinput.service": "rw",
            "/usr/palm/applications/com.webos.app.home/qml/Controllers/PreviewInterfaces/Interfaces.qml": "ro",
            "/mnt/lg/cmn_data/checkpoint/com.webos.app.home": "ro",
            "/tmp/checkpoint/com.webos.app.home": "ro",
        }
        self.probe_output = "answered nslookup\n"

    def run(self, command, *, pty=False, timeout=25):
        self.run_calls.append((command, pty, timeout))
        if command == "id -u":
            return "0\n"
        if command == "cat /etc/version":
            return self.build + "\n"
        if command == "cat /proc/sys/kernel/random/boot_id":
            return BOOT_ID + "\n"
        if command == "cat /var/run/nyx/os_info.json":
            return json.dumps(self.os_info) + "\n"
        if command == "connmanctl services":
            if self.service_state != "online":
                return "Wired " + SERVICE + "\n"
            return "*AO Wired " + SERVICE + "\n" + ("*AO Wired ethernet_fixture_other_cable\n" if self.extra_active_service else "")
        if (command == "connmanctl services " + SERVICE
                or (self.extra_active_service and command == "connmanctl services ethernet_fixture_other_cable")):
            props = dict(self.non_dns)
            props["State"] = self.service_state
            props["Nameservers"] = "[ " + ", ".join(self.dns_effective) + " ]" if self.dns_effective else "[]"
            props["Nameservers.Configuration"] = "[ " + ", ".join(self.dns_stored) + " ]" if self.dns_stored else "[]"
            return "".join("  %s = %s\n" % pair for pair in props.items())
        if command.startswith("systemctl show "):
            unit = command.split()[2]
            values = self.service_states[unit]
            return "".join("%s=%s\n" % pair for pair in values.items())
        if command.startswith("awk ") and command.endswith(" /proc/mounts"):
            return "".join("%s %s\n" % pair for pair in self.mount_modes.items())
        if command.startswith("python -c "):
            if "hooks = " in command:
                return ("50-privacy-services regular " + "a" * 64 + "\n"
                        "60-home-preview-override absent -\n")
            if "flags = " in command:
                return "sshd_enabled true\nnormal_telnet_disabled true\n"
        if command.startswith("if command -v nslookup "):
            return self.probe_output
        if command.startswith("connmanctl config "):
            import shlex
            parts = shlex.split(command)
            self.setter_calls.append(parts)
            if parts[:4] != ["connmanctl", "config", SERVICE, "--nameservers"]:
                raise AssertionError("unexpected synthetic command")
            servers = parts[4:]
            self.dns_stored = list(servers)
            if not self.keep_dns_effective:
                self.dns_effective = list(servers) if servers else list(self.dhcp_effective)
            return ""
        raise AssertionError("unexpected remote command: " + command)

    def luna(self, method, request):
        if method == "luna://com.webos.settingsservice/getSystemSettings":
            category, keys = request["category"], request["keys"]
            count = self.setting_get_counts.get(category, 0) + 1
            self.setting_get_counts[category] = count
            if (self.change_on_recheck is not None
                    and self.change_on_recheck[:2] == (category, count)):
                self.settings[category][self.change_on_recheck[2]] = "off"
            return {"returnValue": True, "settings": {key: self.settings[category][key] for key in keys}}
        if method == "luna://com.webos.settingsservice/getSystemSettingDesc":
            rows = []
            for key in request["keys"]:
                rows.append({"key": key, "values": {"array": list(self.enum_values[key]), "arrayExt": list(self.enum_extended.get(key, []))}})
            return {"returnValue": True, "results": rows}
        if method == "luna://com.webos.settingsservice/setSystemSettings":
            self.setting_set_calls.append(request)
            if self.fail_setting_category == request["category"]:
                raise tvctl.RemoteError("synthetic setter failure")
            if not self.drop_setting_writes:
                self.settings[request["category"]].update(request["settings"])
            return {"returnValue": True}
        if method == "luna://com.webos.service.sdx/getDeviceAuthenticationStatus":
            return {"returnValue": True, "isDeviceAuthenticated": True}
        if method == "luna://com.webos.applicationManager/listLaunchPoints":
            return {"returnValue": True, "launchPoints": [{"launchPointId": "synthetic.%d" % n} for n in range(3)]}
        if method == "luna://com.webos.applicationManager/getForegroundAppInfo":
            return {"returnValue": True, "appId": "com.example.synthetic", "windowId": "not-retained"}
        raise AssertionError("unexpected Luna method: " + method)


def private_tempdir():
    return tempfile.TemporaryDirectory(prefix="tvctl-test-")


class ParserAndTransportTests(unittest.TestCase):
    def test_target_rejects_injection_and_ip_literals(self):
        for target in ("lg-tv;id", "-oProxyCommand=bad", "name@example", "192.0.2.1", "../lg-tv"):
            with self.subTest(target=target), self.assertRaises(tvctl.argparse.ArgumentTypeError):
                tvctl.validate_target(target)

    def test_target_alias_is_passed_with_strict_bounded_ssh_options(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("tvctl.subprocess.run", return_value=result) as run:
            self.assertEqual(tvctl.SSHClient("lg-tv").run("id -u", pty=True), "ok\n")
        args = run.call_args.args[0]
        self.assertIn("-tt", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("IdentitiesOnly=yes", args)
        self.assertIn("ForwardAgent=no", args)
        self.assertIn("ConnectTimeout=8", args)
        self.assertEqual(args[-2:], ["lg-tv", "id -u"])
        self.assertIs(run.call_args.kwargs["capture_output"], True)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_luna_rejects_empty_malformed_and_negative_replies(self):
        class OutputClient(tvctl.SSHClient):
            def __init__(self, text):
                self.text = text
            def run(self, command, *, pty=False, timeout=25):
                self.assert_pty = pty
                return self.text
        for output, expected in (("", "empty"), ("noise", "malformed"),
                                 ('{"returnValue":false}', "returnValue=true")):
            with self.subTest(output=output), self.assertRaisesRegex(tvctl.RemoteError, expected):
                OutputClient(output).luna("luna://com.webos.settingsservice/getSystemSettings", {})

    def test_luna_normalizes_crlf_and_requires_pty(self):
        class OutputClient(tvctl.SSHClient):
            def run(self, command, *, pty=False, timeout=25):
                if not pty:
                    raise AssertionError("Luna requires a pseudo-terminal")
                return '{"returnValue":true,"settings":{}}\r\n'
        self.assertTrue(OutputClient("lg-tv").luna(
            "luna://com.webos.settingsservice/getSystemSettings", {})["returnValue"])

    def test_connman_parser_handles_comma_space_and_empty_values(self):
        self.assertEqual(tvctl.parse_nameservers("[ 94.140.14.14, 94.140.15.15 ]"), SERVERS)
        self.assertEqual(tvctl.parse_nameservers("[ 94.140.14.14  94.140.15.15 ]"), SERVERS)
        self.assertEqual(tvctl.parse_nameservers("[]"), [])
        self.assertEqual(tvctl.parse_nameservers(""), [])
        with self.assertRaises(tvctl.TVCtlError):
            tvctl.parse_nameservers("[ 94.140.14.14,, 94.140.15.15 ]")
        with self.assertRaises(tvctl.TVCtlError):
            tvctl.parse_nameservers("[ not-an-ip ]")

    def test_dns_input_rejects_non_unicast_and_duplicate_servers(self):
        for values in (("127.0.0.1",), ("255.255.255.255",), ("94.140.14.14", "94.140.14.14")):
            with self.subTest(values=values), self.assertRaises(tvctl.TVCtlError):
                tvctl.validate_dns_servers(values)

    def test_connman_property_parser_keeps_empty_value_and_rejects_duplicates(self):
        self.assertEqual(tvctl.parse_connman_properties("  State = online\n  Nameservers.Configuration =\n"),
                         {"State": "online", "Nameservers.Configuration": ""})
        with self.assertRaises(tvctl.TVCtlError):
            tvctl.parse_connman_properties(" State = online\n State = ready\n")

    def test_help_runs_without_target_or_network(self):
        entrypoint = Path(tvctl.__file__)
        result = subprocess.run([sys.executable, str(entrypoint), "--help"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("settings", result.stdout)
        self.assertIn("rollback", result.stdout)
        detail = subprocess.run([sys.executable, str(entrypoint), "settings", "--help"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(detail.returncode, 0, detail.stderr)
        for feature in tvctl.FEATURES:
            self.assertIn(feature, detail.stdout)

    def test_version_and_feature_catalog_need_no_target_or_network(self):
        entrypoint = Path(tvctl.__file__)
        version = subprocess.run([sys.executable, str(entrypoint), "--version"],
                                 capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertTrue(version.stdout.strip().startswith("tvctl 0.2.0"))
        self.assertIn(tvctl.MODEL, version.stdout)
        self.assertIn(tvctl.ETC_VERSION, version.stdout)
        listed = subprocess.run([sys.executable, str(entrypoint), "--list-features"],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        catalog = json.loads(listed.stdout)
        self.assertEqual(catalog["version"], "0.2.0")
        self.assertEqual({feature["name"] for feature in catalog["covered"]},
                         {"collection", "hbbtv", "updates", "acr", "advertising", "voice"})
        keys = {(item["category"], item["key"], item["requested_value"])
                for feature in catalog["covered"] for item in feature["settings"]}
        self.assertEqual(keys, {
            ("option", "watchedListCollection", "off"), ("option", "hbbTvDeviceId", "off"),
            ("option", "hbbTV", "off"), ("support", "automaticUpdate", "off"),
            ("option", "livePlus", "off"), ("general", "adCookie", "off"),
            ("option", "turnOnByVoice", "off"), ("general", "voiceLongDistance", "off"),
        })
        self.assertEqual(catalog["observed_only"], [])
        self.assertIn("All other settings", catalog["not_covered"])

    def test_windows_mutation_and_private_state_rejections_are_portable(self):
        stderr = io.StringIO()
        args = ["--target", "lg-tv", "--confirm-model", tvctl.MODEL,
                "settings", "--feature", "collection", "--apply",
                "--confirm-target", "lg-tv", "--checkpoint", "private.json"]
        with patch("tvctl.os.name", "nt"), patch("tvctl.TVController") as factory, contextlib.redirect_stderr(stderr):
            code = tvctl.main(args)
        self.assertEqual(code, 2)
        factory.assert_not_called()
        self.assertIn("WSL", stderr.getvalue())
        path = Path("checkpoint.json")
        with patch("tvctl.os.name", "nt"), self.assertRaisesRegex(tvctl.TVCtlError, "WSL"):
            tvctl._private_parent(path)


class SafetyAndMutationTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTV()
        self.controller = tvctl.TVController("lg-tv", client=self.fake, confirmed_model=tvctl.MODEL)

    def test_settings_and_dns_default_to_no_write_plans(self):
        settings = self.controller.settings("collection")
        dns = self.controller.dns(SERVERS)
        self.assertEqual(settings["mode"], "plan")
        self.assertEqual(dns["mode"], "plan")
        self.assertEqual(self.fake.setting_set_calls, [])
        self.assertEqual(self.fake.setter_calls, [])

    def test_dns_refuses_more_than_one_active_ethernet_service(self):
        self.fake.extra_active_service = True
        with self.assertRaisesRegex(tvctl.TVCtlError, "exactly one active Ethernet"):
            self.controller.dns(SERVERS)
        self.assertEqual(self.fake.setter_calls, [])

    def test_audit_is_whitelisted_and_reports_owner_model_confirmation(self):
        result = self.controller.audit()
        encoded = json.dumps(result)
        self.assertEqual(result["device"]["model"], tvctl.MODEL)
        self.assertEqual(result["launchpoint_count"], 3)
        self.assertEqual(result["foreground_app_id"], "com.example.synthetic")
        self.assertNotIn("windowId", encoded)
        self.assertNotIn(SERVICE, encoded)
        self.assertNotIn("IPv4.Address", encoded)
        self.assertEqual(result["ethernet_dns"]["stored_nameservers"], ["192.0.2.53"])
        self.assertEqual(result["version"], "0.2.0")
        self.assertEqual(result["services"]["voiceinput.service"]["ActiveState"], "inactive")
        self.assertEqual(result["services"]["voiceconductor.service"]["ActiveState"], "active")
        qml = tvctl.AUDIT_MOUNT_TARGETS[2]
        self.assertEqual(result["mounts"][qml], {"count": 1, "modes": ["ro"]})
        self.assertEqual(result["hbc_hooks"]["50-privacy-services"]["sha256"], "a" * 64)
        self.assertEqual(result["hbc_hooks"]["60-home-preview-override"]["state"], "absent")
        self.assertTrue(result["boot_flags"]["normal_telnet_disabled"])
        self.assertNotIn("unknown-foreign-hook", encoded)
        self.assertNotIn("IPv4.Address", encoded)
        audit_commands = [command for command, _pty, _timeout in self.fake.run_calls]
        self.assertTrue(any(command.startswith("awk ") for command in audit_commands))
        self.assertFalse(any(command == "cat /proc/mounts" or command.startswith("ls ") for command in audit_commands))

    def test_hbbtv_requested_value_is_exact_off_not_offbyuser(self):
        plan = self.controller.settings("hbbtv")
        self.assertEqual(plan["proposed_after"], {"hbbTV": "off"})
        self.assertEqual(self.fake.setting_set_calls, [])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_optional_acr_advertising_and_voice_groups_are_opt_in_and_checkpointed(self):
        for feature in ("acr", "advertising", "voice"):
            plan = self.controller.settings(feature)
            self.assertEqual(plan["mode"], "plan")
            self.assertFalse(plan["changed_keys"])
            with private_tempdir() as temp:
                no_op = self.controller.settings(feature, apply=True, checkpoint_path=Path(temp) / "noop.json")
                self.assertEqual(no_op["mode"], "no-op")
                self.assertIsNone(no_op["checkpoint"])
        self.assertEqual(self.fake.setting_set_calls, [])
        for feature in ("acr", "advertising", "voice"):
            for settings in tvctl.FEATURES[feature].values():
                for key in settings:
                    category = next(category for category, values in tvctl.FEATURES[feature].items() if key in values)
                    self.fake.settings[category][key] = "on"
        with private_tempdir() as temp:
            checkpoints = {}
            for feature in ("acr", "advertising", "voice"):
                path = Path(temp) / (feature + ".json")
                result = self.controller.settings(feature, apply=True, checkpoint_path=path)
                self.assertEqual(result["mode"], "verified")
                checkpoints[feature] = path
            voice_checkpoint = tvctl.read_checkpoint(checkpoints["voice"])
            self.assertEqual(voice_checkpoint["before"], {"turnOnByVoice": "on", "voiceLongDistance": "on"})
            self.assertEqual(voice_checkpoint["after"], {"turnOnByVoice": "off", "voiceLongDistance": "off"})
            voice_writes = [call for call in self.fake.setting_set_calls if set(call["settings"]) & {"turnOnByVoice", "voiceLongDistance"}]
            self.assertEqual({call["category"] for call in voice_writes}, {"option", "general"})
            rollback = self.controller.rollback(checkpoints["voice"], apply=True)
            self.assertEqual(rollback["mode"], "verified")
            self.assertEqual(self.fake.settings["option"]["turnOnByVoice"], "on")
            self.assertEqual(self.fake.settings["general"]["voiceLongDistance"], "on")

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_partial_voice_apply_keeps_checkpoint_for_explicit_rollback(self):
        self.fake.settings["option"]["turnOnByVoice"] = "on"
        self.fake.settings["general"]["voiceLongDistance"] = "on"
        self.fake.fail_setting_category = "general"
        with private_tempdir() as temp:
            path = Path(temp) / "voice.json"
            with self.assertRaisesRegex(tvctl.RemoteError, "synthetic setter failure"):
                self.controller.settings("voice", apply=True, checkpoint_path=path)
            checkpoint = tvctl.read_checkpoint(path)
            self.assertEqual(checkpoint["status"], "apply-failed")
            self.assertEqual(self.fake.settings["option"]["turnOnByVoice"], "off")
            self.assertEqual(self.fake.settings["general"]["voiceLongDistance"], "on")
            self.fake.fail_setting_category = None
            rollback = self.controller.rollback(path, apply=True)
            self.assertEqual(rollback["mode"], "verified")
            self.assertEqual(self.fake.settings["option"]["turnOnByVoice"], "on")
            self.assertEqual(self.fake.settings["general"]["voiceLongDistance"], "on")

    def test_missing_consent_fails_before_client_creation(self):
        output = io.StringIO()
        with patch("tvctl.TVController") as factory, contextlib.redirect_stderr(output):
            code = tvctl.main(["--target", "lg-tv", "settings", "--feature", "collection", "--apply"])
        self.assertEqual(code, 2)
        factory.assert_not_called()
        self.assertIn("confirm-target", output.getvalue())

    def test_dns_apply_requires_external_ack_and_owner_model(self):
        for args in (
            ["--target", "lg-tv", "--confirm-model", tvctl.MODEL, "dns", "--servers", *SERVERS,
             "--apply", "--confirm-target", "lg-tv", "--checkpoint", "x"],
            ["--target", "lg-tv", "dns", "--servers", *SERVERS, "--apply", "--confirm-target", "lg-tv",
             "--ack-external-dns", "--checkpoint", "x"],
        ):
            with self.subTest(args=args):
                stderr = io.StringIO()
                with patch("tvctl.TVController") as factory, contextlib.redirect_stderr(stderr):
                    self.assertEqual(tvctl.main(args), 2)
                factory.assert_not_called()

    def test_changed_software_version_fails_closed(self):
        self.fake.os_info["webos_manufacturing_version"] = "04.64.01"
        with self.assertRaisesRegex(tvctl.TVCtlError, "unsupported webOS/firmware/build version"):
            self.controller.settings("collection", apply=False)
        self.assertEqual(self.fake.setting_set_calls, [])

    def test_unconfirmed_model_refuses_direct_apply(self):
        controller = tvctl.TVController("lg-tv", client=self.fake)
        with private_tempdir() as temp:
            with self.assertRaisesRegex(tvctl.TVCtlError, "owner confirmation"):
                controller.settings("collection", apply=True, checkpoint_path=Path(temp) / "cp.json")
            self.assertEqual(self.fake.setting_set_calls, [])
            self.assertFalse((Path(temp) / "cp.json").exists())

    def test_unknown_or_unsupported_native_enum_refuses(self):
        self.fake.enum_values["watchedListCollection"] = ["on"]
        with self.assertRaisesRegex(tvctl.TVCtlError, "not in the native enum"):
            self.controller.settings("collection", apply=False)
        self.assertEqual(self.fake.setting_set_calls, [])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_prewrite_changed_state_refuses_without_setting_write(self):
        # option read #1 is the baseline; #2 is the immediate pre-write recheck.
        self.fake.change_on_recheck = ("option", 2, "watchedListCollection")
        with private_tempdir() as temp:
            with self.assertRaisesRegex(tvctl.TVCtlError, "changed before write"):
                self.controller.settings("collection", apply=True, checkpoint_path=Path(temp) / "cp.json")
            self.assertEqual(self.fake.setting_set_calls, [])
            checkpoint = tvctl.read_checkpoint(Path(temp) / "cp.json")
            self.assertEqual(checkpoint["status"], "conflict-before-write")

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_settings_apply_checkpoints_and_verifies_exact_readback(self):
        with private_tempdir() as temp:
            path = Path(temp) / "collection.json"
            result = self.controller.settings("collection", apply=True, checkpoint_path=path)
            self.assertEqual(result["mode"], "verified")
            self.assertEqual(result["readback"], {"watchedListCollection": "off", "hbbTvDeviceId": "off"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            checkpoint = tvctl.read_checkpoint(path)
            self.assertEqual(checkpoint["status"], "verified")
            self.assertEqual(checkpoint["identity"]["boot_id"], BOOT_ID)
            self.assertEqual(checkpoint["before"], {"watchedListCollection": "on", "hbbTvDeviceId": "on"})
            self.assertEqual(len(self.fake.setting_set_calls), 1)

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_checkpoint_is_exclusive_and_private(self):
        with private_tempdir() as temp:
            path = Path(temp) / "checkpoint.json"
            tvctl.write_private_json(path, {"schema": 1}, exclusive=True)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(tvctl.TVCtlError, "already exists"):
                tvctl.write_private_json(path, {"schema": 1}, exclusive=True)

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_readback_failure_keeps_checkpoint_and_never_blindly_rolls_back(self):
        self.fake.drop_setting_writes = True
        with private_tempdir() as temp:
            path = Path(temp) / "checkpoint.json"
            with self.assertRaisesRegex(tvctl.TVCtlError, "no automatic rollback"):
                self.controller.settings("collection", apply=True, checkpoint_path=path)
            self.assertEqual(len(self.fake.setting_set_calls), 1)
            checkpoint = tvctl.read_checkpoint(path)
            self.assertEqual(checkpoint["status"], "readback-failed")
            self.assertEqual(self.fake.settings["option"]["watchedListCollection"], "on")

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_dns_apply_uses_dynamic_service_and_verifies_stored_and_effective_state(self):
        with private_tempdir() as temp:
            path = Path(temp) / "dns.json"
            result = self.controller.dns(SERVERS, apply=True, checkpoint_path=path, ack_external_dns=True)
            self.assertEqual(result["mode"], "verified")
            self.assertEqual(result["readback"]["stored_nameservers"], SERVERS)
            self.assertEqual(result["readback"]["effective_nameservers"], SERVERS)
            checkpoint = tvctl.read_checkpoint(path)
            self.assertEqual(checkpoint["operation"]["service"], SERVICE)
            self.assertEqual(checkpoint["status"], "verified")
            self.assertEqual(len(self.fake.setter_calls), 1)
            probe = result["reachability_probe"]
            self.assertEqual(probe["status"], "answered")
            self.assertEqual(probe["hostname"], "example.com")
            self.assertEqual(probe["approved_resolver"], SERVERS[0])
            self.assertEqual(probe["resolver_path"], "direct-selected-resolver")
            probe_call = next(call for call in self.fake.run_calls if call[0].startswith("if command -v nslookup "))
            self.assertIn("nslookup example.com " + SERVERS[0], probe_call[0])
            self.assertEqual(probe_call[2], tvctl.DNS_PROBE_TIMEOUT)
            self.assertIn("not an Internet-connectivity", probe["limitations"])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_dns_probe_failure_and_unavailability_keep_verified_checkpoint_without_rollback(self):
        for output, expected in (("failed nslookup", "failed"), ("unavailable none", "unavailable")):
            with self.subTest(expected=expected), private_tempdir() as temp:
                self.fake.dns_stored = ["192.0.2.53"]
                self.fake.dns_effective = ["192.0.2.53"]
                self.fake.setter_calls.clear()
                self.fake.probe_output = output
                path = Path(temp) / "dns.json"
                result = self.controller.dns(SERVERS, apply=True, checkpoint_path=path, ack_external_dns=True)
                self.assertEqual(result["mode"], "verified")
                self.assertEqual(result["reachability_probe"]["status"], expected)
                self.assertEqual(tvctl.read_checkpoint(path)["status"], "verified")
                self.assertEqual(len(self.fake.setter_calls), 1)
                self.assertIn("No automatic rollback", result["advice"])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_dns_readback_failure_leaves_checkpoint_without_auto_rollback(self):
        self.fake.keep_dns_effective = True
        with private_tempdir() as temp:
            path = Path(temp) / "dns.json"
            with self.assertRaisesRegex(tvctl.TVCtlError, "no automatic rollback"):
                self.controller.dns(SERVERS, apply=True, checkpoint_path=path, ack_external_dns=True)
            self.assertEqual(len(self.fake.setter_calls), 1)
            checkpoint = tvctl.read_checkpoint(path)
            self.assertEqual(checkpoint["status"], "readback-failed")
            self.assertEqual(self.fake.dns_stored, SERVERS)
            self.assertEqual(self.fake.dns_effective, ["192.0.2.53"])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_settings_rollback_restores_owned_after_state(self):
        with private_tempdir() as temp:
            path = Path(temp) / "cp.json"
            self.controller.settings("collection", apply=True, checkpoint_path=path)
            result = self.controller.rollback(path, apply=True)
            self.assertEqual(result["mode"], "verified")
            self.assertEqual(self.fake.settings["option"]["watchedListCollection"], "on")
            self.assertEqual(self.fake.settings["option"]["hbbTvDeviceId"], "on")

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_rollback_after_reboot_refuses_without_a_setter(self):
        with private_tempdir() as temp:
            path = Path(temp) / "cp.json"
            self.controller.settings("collection", apply=True, checkpoint_path=path)
            count = len(self.fake.setting_set_calls)
            original_run = self.fake.run
            def after_reboot(command, **kwargs):
                if "/proc/sys/kernel/random/boot_id" in command:
                    return "fedcba98-7654-3210-fedc-ba9876543210\n"
                return original_run(command, **kwargs)
            with patch.object(self.fake, "run", side_effect=after_reboot):
                with self.assertRaisesRegex(tvctl.TVCtlError, "boot/version identity"):
                    self.controller.rollback(path, apply=True)
            self.assertEqual(len(self.fake.setting_set_calls), count)

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_rollback_on_different_target_refuses_before_a_setter(self):
        with private_tempdir() as temp:
            path = Path(temp) / "cp.json"
            self.controller.settings("collection", apply=True, checkpoint_path=path)
            count = len(self.fake.setting_set_calls)
            other = tvctl.TVController("another-tv", client=self.fake, confirmed_model=tvctl.MODEL)
            with self.assertRaisesRegex(tvctl.TVCtlError, "checkpoint target"):
                other.rollback(path, apply=True)
            self.assertEqual(len(self.fake.setting_set_calls), count)

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_native_setter_race_is_explicitly_reported_as_unprotected(self):
        original_luna = self.fake.luna
        def interleaved(method, payload, **kwargs):
            if method.endswith("/setSystemSettings"):
                # Another native writer after the final recheck cannot be CAS'd.
                self.fake.settings["option"]["watchedListCollection"] = "automatic"
            return original_luna(method, payload, **kwargs)
        with private_tempdir() as temp, patch.object(self.fake, "luna", side_effect=interleaved):
            result = self.controller.settings("collection", apply=True, checkpoint_path=Path(temp) / "cp.json")
        self.assertEqual(result["mode"], "verified")
        self.assertTrue(result["coordination"]["owner_exclusive_window_required"])
        self.assertFalse(result["coordination"]["native_compare_and_set"])
        self.assertFalse(result["coordination"]["arbitrary_concurrent_changes_protected"])

    @unittest.skipUnless(os.name == "posix", "private checkpoint mode bits require POSIX/WSL")
    def test_rollback_refuses_concurrent_setting_state(self):
        self.fake.enum_values["watchedListCollection"].append("automatic")
        with private_tempdir() as temp:
            path = Path(temp) / "cp.json"
            self.controller.settings("collection", apply=True, checkpoint_path=path)
            self.fake.settings["option"]["watchedListCollection"] = "automatic"
            before_writes = len(self.fake.setting_set_calls)
            with self.assertRaisesRegex(tvctl.TVCtlError, "differs from both checkpoint states"):
                self.controller.rollback(path, apply=True)
            self.assertEqual(len(self.fake.setting_set_calls), before_writes)

    def test_dns_apply_from_automatic_baseline_refuses_unverified_recovery(self):
        self.fake.dns_stored = []
        self.fake.dns_effective = ["192.0.2.53"]
        with private_tempdir() as temp:
            path = Path(temp) / "dns.json"
            plan = self.controller.dns(SERVERS)
            self.assertEqual(plan["mode"], "plan")
            with self.assertRaisesRegex(tvctl.TVCtlError, "automatic-DNS baseline"):
                self.controller.dns(SERVERS, apply=True, checkpoint_path=path, ack_external_dns=True)
            self.assertFalse(path.exists())
            self.assertEqual(self.fake.setter_calls, [])

    def test_empty_nameserver_setter_never_guesses_connman_reset_syntax(self):
        with self.assertRaisesRegex(tvctl.TVCtlError, "automatic-DNS"):
            self.controller._set_connman_nameservers(SERVICE, [])
        self.assertEqual(self.fake.setter_calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
