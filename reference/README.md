# Historical hosts reference: provenance and omissions

[hosts-observed.txt](hosts-observed.txt) is a deliberately partial, historical transcription of 44 selected exact-name redirects observed on the source TV. They are **not 44 proven trackers**. The generic localhost alias was removed from the data rows because resolver plumbing is not a tracking domain. This is neither a maintained blocklist nor an installer.

## What was left out

The private original also contained comments, host-local/loopback aliases, an IPv6 network alias and IPv6 multicast/discovery aliases. Those rows were intentionally excluded rather than reproduced as another household's resolver configuration. They are normal local-network/protocol plumbing, not additional tracking domains to block. No private hostname, LAN address or device identifier is needed to understand the selected redirects.

Do not reconstruct the omitted rows from this description, remove your TV's own local aliases, or replace `/etc/hosts` with this reference. HBC and pre-existing custom hooks may already bind that path; another bind can hide their current state or create an unsafe stack. [Architecture and existing protections](../docs/changes.md#existing-startup-and-hosts-protections)

## Review categories, not a paste-all policy

- Advertising/recommendation-looking names are observations, not proof of their payload or purpose.
- Store, account, update, ThinQ/voice and other shared infrastructure can overlap the apparent categories. Blocking a name may break useful functionality or security updates.
- Exact names do not block a parent domain's subdomains; `/etc/hosts` does not support wildcard policy.
- DNS filtering, IPv6/direct-IP traffic and application-selected resolvers have different coverage. No redirect list establishes LAN isolation or complete telemetry prevention.

Inspect the TV's own original file and currently active mount layers before deciding anything. Preserve a **private**, no-overwrite copy first if you are investigating the source state:

```sh
mkdir -p .local-state
chmod 700 .local-state
(umask 077; set -C; ssh -o BatchMode=yes -o StrictHostKeyChecking=yes lg-tv 'cat /etc/hosts' > .local-state/hosts-original.txt)
```

The captured file can contain household identifiers. Never commit, attach or upload it. This read-only example does not install the published reference or authorize a hosts change. See [verification and recovery](../docs/recovery.md).
