# What is under the hood?

## Read-only firmware, writable state, reversible overlays

On the inspected CX the root filesystem is read-only **SquashFS**. Persistent project files live under `/var/lib/webosbrew/`; an exact bind mount can change what one path exposes without overwriting its firmware bytes.

Two uses must not be confused:

- A `/dev/null` bind over the **voiceinput unit file** makes systemd treat that unit as masked. This is not replacing the executable and not a claim that the whole audio stack is disabled. The observed devtmpfs bind is `rw`; the underlying firmware root remains read-only.
- The optional Home overlay exposes a locally generated QML file with a **read-only** bind. It also overlays only Home's checkpoint directories with an owned read-only empty directory. Snapshots remain behind the mount and are never deleted.

Why not just `systemctl mask --runtime voiceinput`? The source TV had an `/etc/systemd/system/voiceinput.service` unit that took precedence over the `/run` mask. The command alone looked reassuring but did not produce an effective manager state. The later fix checked `LoadState`, `ActiveState` and `UnitFileState`, then tested that a masked start was refused. Do not run a start test before independently proving the unit is masked.

## Luna is an API, not a guessable settings dictionary

`luna-send` exposes settings, app management and other services. On this firmware a non-PTY SSH command could return code zero and an empty body. The host tool uses a controlling PTY, normalizes CRLF, parses JSON and requires `returnValue: true`.

Read the category/key and `getSystemSettingDesc` enumeration before setting a value; write only the chosen key and read it back. Do not submit a whole settings or EULA object from another TV. A successful API call is weaker evidence than correct state read from a fresh call.

## Home is stateful

The existing `getAppPreview()` path creates a model transaction. Simply hiding a view with a reactive binding can invoke a consumer that clears the model and resets the selected launch point. The optional guard instead supplies an empty model and finishes the existing switch transaction, only for `systemProperties.youTubeAppId + "_default"`.

A new QML mount does not change a process restored from CRIU. The optional module loads a fresh **Home only**; it never restarts SAM. CRIU can reuse a PID, so process identity includes `/proc/PID/stat` start time. Another app must preserve both PID and start time, not merely its name.

## DNS is one layer

The TV uses ConnMan. The public tool discovers the active Ethernet service instead of containing someone else's MAC-based service identifier. `Nameservers.Configuration` can contain comma/space separators or be empty for an automatic list. Capture it exactly before a write and preserve IP, route, proxy and IPv6 settings.

Filtering known names is not packet filtering. Applications can keep cached addresses, contact direct IPs, choose another resolver or use encrypted DNS. Ordinary same-subnet traffic does not traverse a router's WAN firewall. This project did not find a suitable per-TV wired-isolation feature on the source router and made **no router change**; that result is not a statement about every ASUS router or firmware.

## Diagnostics are not surveillance proof

The original bounded packet observations retained DNS names, tuples and counters, not packet payloads or TLS contents. Cached DNS and short observation periods prevent causal before/after traffic claims. The public evidence set contains only allowlisted non-identifying fields; raw traffic observations and viewing screenshots were excluded.
