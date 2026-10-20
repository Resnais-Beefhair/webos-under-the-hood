# Rooting: historical starting point, not a hidden prerequisite

The source operator's initial record says that SlopBro was used on the owned CX and installed **Homebrew Channel 0.7.3**. Dropbear SSH and a temporary telnet fallback were enabled before the later work in this repository. The public toolkit does not bundle SlopBro, an exploit payload, a pairing key or an original machine's helper environment.

**If your TV is not rooted, stop the toolkit here.** Rooting is a separate, potentially disruptive security modification requiring your explicit decision. Read the actual upstream compatibility and recovery instructions:

- [SlopBro upstream](https://github.com/throwaway96/slopbro)
- [Pinned README examined for this project](https://raw.githubusercontent.com/throwaway96/slopbro/21023d56ca424607bb03d2939609cc658c655fc7/README.md)
- [Homebrew Channel upstream](https://github.com/webosbrew/webos-homebrew-channel)

The examined README describes a Python 3 host script, an SSAP pairing prompt on the TV, and a temporary HTTP server that serves the payload. It writes a local `.key` pairing credential. Those are separate resources/secrets with their own lifecycle. Do not publish them, forward a pairing request without knowing the target, or leave the temporary server running after rooting.

For a **matching, owner-approved target only**, the upstream usage shape is:

```text
python3 slopbro.py --local-ip YOUR_HOST_LAN_IP --webos-version 5 YOUR_TV_IP
```

This is a reference to the upstream interface, **not a bundled or newly tested rooting procedure**. Obtain and inspect upstream code according to its current README; use its help and compatibility guidance before running. Its defaults, flags and payloads can change. Do not add `--curl-insecure` or disable certificate validation merely to force success; correct the TV's clock and trust conditions first. The source record's claim that one firmware is the “last rootable version” was not substantiated and is deliberately not repeated.

Once you can reach a trusted root console and have checked the exact version, continue with [connection.md](connection.md). Do not install Developer Mode or remove HBC as a maintenance experiment; upstream persistence mechanisms have their own constraints. This project intentionally does not choose an exploit for an unknown future TV.
