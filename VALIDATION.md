# Validation

Checked on 2026-10-27.

## Passed

- 13 Python unit/integration tests: palette contrast across 72 hues, four
  saturation levels and both modes; shared accent hue; grayscale preservation;
  image extraction/cache invalidation; file generation; preview persistence;
  fragmented IPC decoding; disconnect handling; command quoting; atomic writes;
  deployment/restore including symlinks; rejected invalid restore manifests.
- Actual GTK3 widgets rendered in an Xvfb test display in dark and light modes.
  Inspected the bar, launcher, media popup, battery window and wallpaper picker.
- GTK smoke checks: launcher toggle; four persistent workspace circles and focus
  styling; wallpaper selection, thumbnail generation, cancel and commit;
  Wi-Fi/power/clipboard window construction; fullscreen hide/show behavior.
- Actual Gio/D-Bus StatusNotifierItem registration and icon rendering, plus
  DBusMenu construction including check items, on an isolated test bus.
- Notification JSON validated against the upstream SwayNotificationCenter schema.
- Python compilation, Bash prompt syntax and POSIX shell wrapper syntax.
- Void package names checked against current official package templates;
  SwayFX commands cross-checked against upstream 0.6 documentation.

Re-run the portable checks from this folder:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q bin share deploy.py
bash -n config/frost/prompt.bash
sh -n bin/frost-session
```

## Limits

The test host is not Void and has no ThinkPad hardware or installed SwayFX.
The GTK smoke test substitutes compositor anchoring and hardware/player samples;
it checks actual widget behavior, not the final compositor blur/shadow rendering.
The test filesystem does not support the Wayland socket needed to start a real
compositor, so full SwayFX configuration loading was not run here.

Audio routing, headphone jack switching, Wi-Fi connection, lid suspend, lock
integration, physical Super-key mapping, gestures, real MPRIS transport and
multi-monitor anchoring must be checked on the laptop. `INSTALL.md` includes
`frostctl doctor`, `wpctl status`, `pactl info` and Sway configuration validation.

Read the app-coverage limits in README: Hyprland-style splitting is an
approximation within SwayFX; libadwaita/web content can retain their own colors;
Qt and optional Firefox chrome may need restarting after palette changes.
