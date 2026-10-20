# Verification and recovery

Keep the working SSH session and private pre-change records. Recovery is an explicit change, not permission to reset the TV, replace every key or enable every service. Work one feature at a time.

## Verification after each change

1. Require fresh native readbacks, not just the setter's exit code. With the settings CLI, a new plan should show the selected values already at the proposed state. With DNS, inspect both stored and effective lists.
2. Run another private audit using a new output path. Compare the **immediately preceding** baseline: SDX authenticated, same boot/build, foreground app and launchpoint identifiers/count. A changed count that predates your write is not proof that your write caused it; retain both observations.
3. For service masks require `LoadState=masked`, `ActiveState=inactive` and the appropriate masked unit-file state. A successful `/run` mask alone is insufficient when an `/etc` unit outranks it. Keep Home's `sdx`/`admanager` dependencies alive.
4. Manually test Home with the physical remote and launch/play actual content in your normal apps, including LAN-hosted Plex if used. Check store access, sound, HbbTV if retained, and expected voice behavior. A successful app launch/HTTP/DNS response is not a playback test.
5. For persistent hooks, schedule an owner-approved physical cold start, then repeat readbacks, navigation and playback. Never turn “needs reboot test” into an unapproved reboot. The source-device record has **not** completed this test.

## Settings and manual-DNS checkpoints

A CLI checkpoint records the target alias, boot/version/model-confirmation identity, original/proposed values and an operation journal. It is private and created exclusively. Keep it unchanged and do not merge checkpoints from different TVs or sessions. The owner confirmation must match the exact supported model.

Read the checkpoint's rollback plan first (local-only; no TV connection is needed):

```sh
python3 tvctl.py --target lg-tv rollback --checkpoint .local-state/collection.json
```

Then, only after deciding to restore that one change:

```sh
python3 tvctl.py --target lg-tv --confirm-model 'LG OLED65CX6LA' rollback --checkpoint .local-state/collection.json --apply --confirm-target lg-tv
python3 tvctl.py --target lg-tv audit --output .local-state/after-rollback.json
```

Use the corresponding `hbbtv.json`, `updates.json` or `dns.json` for that feature, not another feature's checkpoint. DNS recovery restores the **saved original manual resolver list**, never a globally hardcoded default. It verifies stored/effective values and unrelated ConnMan properties. It will not guess how to restore an empty automatic/DHCP list; the new CLI refuses such a baseline before mutation.

Rollback refuses another target, changed boot/version identity, changed Ethernet service, unknown values or a live state that matches neither checkpoint state. Settings recovery can restore only the owned changed keys after a partial write. No blind rollback runs after a failed readback. Nothing restores a stale whole-settings object over newer changes.

These checks are **not transaction isolation**. Arrange an exclusive administration window for recovery too: another native setter or TV settings-UI action can race between a check and an unconditional write. The result's `coordination` field states that arbitrary concurrent writers are not protected. A `verified` result means fresh target values matched, not that such a race was impossible. Same-boot-only rollback is an intentional limit, not an instruction to weaken identity checks.

### If a guard refuses, or the write had an ambiguous result

- Preserve the checkpoint and error, then obtain a fresh read-only audit. Do not delete the checkpoint merely to retry an apply.
- If current values are already correct, a prior setter may have succeeded despite a timeout or local parsing failure. Confirm that fact from fresh state; a failed client command is not proof of an unchanged TV.
- If another person changed a value, use the native UI and make a new explicit decision. Do not alter the checkpoint to make it look owned.
- After a reboot the boot-ID guard intentionally refuses automatic checkpoint rollback. Compare the old values with current native schemas and restore the chosen values through the TV UI or a newly reviewed, targeted manual operation. Do not spoof an old boot ID or disable the guard.
- If DNS breaks streaming, restore the saved resolver list or the original Automatic DNS choice in the TV network UI. Leave IP, gateway, proxy, IPv6 and other devices alone. Retest the exact app that failed.

## Service masks

[services.md](services.md) documents the staged files, effective mask and ownership-sensitive rollback. Stop future reapplication first by disabling **only your exact owned hook**. The `/dev/null` unit bind, runtime mask links and original running state are separate layers; do not enable collection or remove a pre-existing contentminer mask as an indiscriminate reset. No service is automatically started by removing a hook.

## Optional Home previews

Use the [module's rollback](../optional-preview/README.md#rollback). It removes only its exact owned hook/mounts; it keeps the source files and empty checkpoint placeholder. Restoring the visible firmware file does not replace code already mapped into Home, so an explicitly approved Home-only reload is a separate step. No SAM restart, snapshot deletion, reboot or package-directory deletion is part of recovery.

## If Home is visible but no apps launch

Do not assume another ad or telemetry process must be disabled. On the tested CX, breaking the SDX/admanager authentication dependency produced an unusable launcher, with `ServiceDown` in diagnostics, even while Home could remain visible. [Why these services stay, native launch path and observed fragment paths](services.md#why-sdx-admanager-and-voiceconductor-stay).

Restore only the exact changes from the experiment's own checkpoint. Preserve `sdx`, `admanager`, `voiceconductor` and original binaries; an active `voiceconductor` is not proof of recording. Confirm the native SDX authentication readback, then decide separately whether a Home-only reload is required. Do not use a SAM restart or broad service start/unmask as a diagnostic probe.

## Failure playbook: streaming breaks after DNS

Stop applying further features. Keep your working pinned SSH session and checkpoint. A DNS response or successful ConnMan readback is not proof that a particular streaming provider works.

1. Collect a fresh **private** audit in a new output file, without replaying the setter:

```sh
python3 tvctl.py --target lg-tv audit --output .local-state/dns-failure-audit.json
python3 -c 'import json; from pathlib import Path; c=json.loads(Path(".local-state/dns.json").read_text()); print("Saved manual resolvers:", c["before"]["stored_nameservers"])'
python3 tvctl.py --target lg-tv rollback --checkpoint .local-state/dns.json
```

2. Review that plan. If you explicitly decide to restore this one change, in the same-boot exclusive administration window:

```sh
python3 tvctl.py --target lg-tv --confirm-model 'LG OLED65CX6LA' rollback --checkpoint .local-state/dns.json --apply --confirm-target lg-tv
python3 tvctl.py --target lg-tv audit --output .local-state/dns-restored-audit.json
```

3. Retest the exact failing app and LAN-hosted playback, if used. Do not replace the saved resolver with a copied public default or alter IP, gateway, IPv6 or router settings. If the guard refuses after a new boot, inspect the saved list and restore it through the TV network UI, or restore the recorded **Automatic DNS** UI choice for an originally automatic configuration. Empty ConnMan-list reset syntax remains unsupported. Do not edit the checkpoint's boot ID to bypass that refusal.

The bounded post-apply DNS probe reports resolution separately from configuration verification. A failed or unavailable probe is a reason to investigate or explicitly restore the saved baseline, not an automatic rollback. A successful probe does not prove filtering coverage, HTTPS reachability or video playback.

## Failure playbook: optional Home reload fails

Only enter a reload/recovery step in an owner-approved interruption window. Use the **same runtime base you installed**, not a guessed path. From the optional module's documented installation, with `TV` set to your already-verified SSH alias:

```sh
BASE=/var/lib/webosbrew/home-preview-override
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" "python '$BASE/preview_runtime.py' --check"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" "python '$BASE/manage_boot_hook.py' --check"
```

Keep the error and package files private. Missing checkpoint directories, foreign or stacked mounts, unsupported hashes/schemas and changed app identities mean **stop**, not create directories, kill more processes or force-unmount. A newly appearing app is not itself evidence of damage; compare the identities of apps that existed before the reload.

If you explicitly choose to abandon the cosmetic feature, this first command disables only the exact owned persistent hook and detaches only the verified owned binds. It does **not** reboot or start Home:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" "python '$BASE/rollback_preview.py' --restore-owned-mounts --ack-rollback"
```

Inspect the result. Only after successful layer restoration and a **separate Home-only reload decision**, the next command requests the original firmware presentation, allowing its original Home snapshot behavior:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$TV" "python '$BASE/reload_home.py' --visible --allow-original-snapshot --ack-home-reload"
```

Do not start the patched reload without all required owned read-only mounts. If this recovery also fails, stop and preserve evidence; do not restart SAM, delete CRIU state, escalate to KILL or reboot as an undocumented fallback. After any lazy detach, keep the source/empty-placeholder files while existing processes may retain their file descriptors. [Module-specific failure handling](../optional-preview/README.md)

## SSH and telnet

Use [connection.md](connection.md#recovery). Preserve an old working management route until a **new** key-authenticated, pinned SSH session works. Never remove every authorized key, copy another person's private key, blindly accept a changed server host key or reopen network access without the owner's security decision.

## When to stop

Unknown firmware/hash/schema, foreign or stacked mounts, mixed checkpoint ownership, unexpected service dependencies, another app/process changing during Home reload, or loss of recovery access all mean **stop and inspect**. None is an invitation to add a force switch, restart SAM or factory-reset the TV.
