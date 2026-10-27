# Frost — Void / SwayFX

Three floating glass pills. Wallpaper-derived, single-hue accents. Light and dark
modes, a live wallpaper picker, workspace circles, and hover media controls.
Built for your Intel ThinkPad L480; native screen resolution is detected.

The left pill holds the Void launcher, at least four workspace circles, and
scrolling artist/title text. Hover the media area for playback, seeking and time.
The middle pill shows `14:22 Sat. 22 Oct`. The right pill holds the tray,
notifications, theme/wallpaper buttons, Wi-Fi, sound, battery and power.

## 1. Install packages

Run commands on your laptop. Package names are case-sensitive. Use your normal
desktop account; use `sudo` only where shown. `sudo` can be replaced by your
existing root-command method.

```sh
sudo xbps-install -Su
sudo xbps-install -S swayfx kitty firefox python3 python3-gobject python3-Pillow \
  gtk+3 gtk-layer-shell librsvg papirus-icon-theme adwaita-icon-theme \
  pipewire wireplumber alsa-pipewire alsa-utils pulseaudio-utils pavucontrol \
  NetworkManager network-manager-applet polkit-gnome dbus elogind \
  SwayNotificationCenter swayidle swaylock wl-clipboard cliphist playerctl \
  brightnessctl grim slurp keyd libnotify procps-ng fontconfig \
  xdg-desktop-portal xdg-desktop-portal-wlr xdg-desktop-portal-gtk \
  qt5ct qt6ct gsettings-desktop-schemas glibc-locales
```

If XBPS updates itself and asks you to rerun the update, do that first. The bundle
includes JetBrains Mono 2.304 Regular, Bold and Italic with its OFL license.
There are no pip dependencies, downloaded install scripts, or build steps.

## 2. Copy the dotfiles

Extract this ZIP, open a terminal in its `frost-void` directory, then run:

```sh
python3 deploy.py
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/Pictures/wallpapers"
```

This copies user files, installs the bundled fonts and generates a starting
palette. It prints a timestamped backup folder and the exact restore command.
It does not install packages or change system services. Put your own images in
`~/Pictures/wallpapers`. The initial background is a plain solid color.

For the two-line terminal prompt, add this line once to `~/.bashrc`:

```sh
[ -r "$HOME/.config/frost/prompt.bash" ] && . "$HOME/.config/frost/prompt.bash"
```

It preserves your current shell. The prompt customization is for Bash; if you use
another shell, the desktop works without sourcing that file.

## 3. Set up audio and the session

PipeWire runs as your user. Let it start WirePlumber and the PulseAudio interface
using Void's supplied example snippets:

```sh
mkdir -p "$HOME/.config/pipewire/pipewire.conf.d"
ln -sfn /usr/share/examples/wireplumber/10-wireplumber.conf \
  "$HOME/.config/pipewire/pipewire.conf.d/10-wireplumber.conf"
ln -sfn /usr/share/examples/pipewire/20-pipewire-pulse.conf \
  "$HOME/.config/pipewire/pipewire.conf.d/20-pipewire-pulse.conf"
sudo mkdir -p /etc/alsa/conf.d
sudo ln -sfn /usr/share/alsa/alsa.conf.d/50-pipewire.conf /etc/alsa/conf.d/50-pipewire.conf
sudo ln -sfn /usr/share/alsa/alsa.conf.d/99-pipewire-default.conf /etc/alsa/conf.d/99-pipewire-default.conf
sudo usermod -aG network,video "$USER"
```

Do not start `wireplumber` or `pipewire-pulse` separately. The session supervisor
starts `pipewire`; those snippets handle the other two. WirePlumber's normal
route/device restoration handles saved volumes and the analog headphone jack.
Do not run a separate PulseAudio daemon alongside this setup.

Install the bare-Super tap mapping and laptop power policy:

```sh
sudo mkdir -p /etc/keyd /etc/elogind/logind.conf.d
sudo cp system/keyd/frost.conf /etc/keyd/frost.conf
sudo keyd check /etc/keyd/frost.conf
sudo cp system/elogind/logind.conf.d/50-frost.conf /etc/elogind/logind.conf.d/50-frost.conf
```

The keyd file maps a short Super tap to F13. Holding Super for 180 ms, or using a
keyboard chord, produces normal Super behavior. Hold Super briefly before
scrolling to switch workspaces. Super+Space also toggles the launcher. If you
already have a keyd config matching this keyboard, merge the two mappings into
it instead of installing a second matching config.

Use elogind for the session and lid events, and NetworkManager for Wi-Fi. Inspect
currently enabled services first:

```sh
ls -1 /var/service
```

Disable competing network managers and acpid if enabled; this briefly interrupts
your connection. NetworkManager will manage it after the next step:

```sh
for svc in dhcpcd wpa_supplicant connmand wicd acpid; do
  if [ -L "/var/service/$svc" ]; then
    sudo sv down "$svc"
    sudo rm "/var/service/$svc"
  fi
done
for svc in dbus elogind NetworkManager keyd; do
  [ -e "/var/service/$svc" ] || sudo ln -s "/etc/sv/$svc" "/var/service/$svc"
done
```

If any disabled service was providing your connection, reconnect using `nmtui`
on the TTY or the bar's Wi-Fi window after starting the desktop.

Enable `en_US.UTF-8 UTF-8` and `nb_NO.UTF-8 UTF-8` by uncommenting those two lines
in `/etc/default/libc-locales`, then run:

```sh
sudo xbps-reconfigure -f glibc-locales
```

The session uses your existing language setting, with an English-format clock.
The keyboard layout is Norwegian only. Both locales are available to programs.

## 4. Start it

Reboot once so group membership, elogind and the service changes take effect.
Log into your TTY as your normal user, then run:

```sh
~/.local/bin/frost-session
```

Use this wrapper instead of plain `sway`: it provides the session environment
and a D-Bus session. There is no display manager or automatic TTY login.

In Kitty, verify the running session:

```sh
frostctl doctor
wpctl status
pactl info
sway --validate --config "$HOME/.config/sway/config"
```

Open the wallpaper picker and select your first image. Arrow keys, scroll or a
single thumbnail click preview immediately. Enter / **Keep wallpaper** commits;
Esc / **Cancel** restores the previous wallpaper and theme. Double-click commits.

## Controls

| Action | Shortcut / control |
| --- | --- |
| Toggle launcher | Tap Super; Super+Space also works |
| Browser / terminal / existing directory handler | Super+W / Super+Enter / Super+E |
| Toggle light/dark | Super+O or sun/moon button |
| Wallpapers | Super+Shift+W or wallpaper button |
| Workspaces 1–9 | Super+1–9; hold Super + scroll also cycles |
| Move a window to workspace 1–9 | Super+Shift+1–9 |
| Touchpad workspace switch | Three-finger swipe left/right |
| Focus / move windows | Super+arrows or HJKL / Super+Shift+arrows |
| Fullscreen / floating | Super+F / Super+Shift+Space |
| Close / reload configuration | Super+Shift+Q / Super+Shift+C |
| Screenshot region | Super+Shift+S; saves PNG and copies it |
| Clipboard history | Super+V |
| Notifications / Do Not Disturb | Super+N / Super+Shift+N; bell opens the DND GUI |
| Power menu / lock | Super+Esc / Super+Ctrl+L |
| Media controls | Hover artist/title; previous/next, ±10 s, play/pause and seek |
| Volume / mute | Hardware keys; scroll / middle-click sound icon |
| Wi-Fi / battery and brightness / sound settings | Click the corresponding icon |

Screenshots go to `~/Pictures/Screenshots`. Clipboard history stores text and
images; choose an entry to copy it. The right tray supports StatusNotifierItem /
AppIndicator applications and their menus. Empty tray space collapses naturally.

## Tuning and app coverage

Edit `~/.config/frost/settings.json`, then run `frostctl theme toggle` twice to
regenerate the same mode, or `frostctl init` followed by `swaymsg reload`.

- `blur_strength: 0.75` maps to 3 blur passes and radius 8. SwayFX does not have
  a native 0–1 strength scale. Try `0.4` if Intel graphics feels sluggish.
- `surface_opacity: 0.83`, `terminal_opacity: 0.90`, and `window_opacity: 0.97`
  keep surfaces lightly transparent. Text in ordinary apps shares compositor
  opacity; Kitty's background has separate transparency.
- `natural_scroll` changes two-finger scrolling. Pointer acceleration is flat.
- `minimum_workspaces` sets the permanent circles; additional workspaces expand
  the left pill. Very large workspace/tray counts can outgrow a small screen.
- Accent extraction uses Pillow palette quantization, favors populated chromatic
  colors, then derives same-hue tones with checked accent/surface contrast.
  Grayscale wallpapers stay grayscale. All terminal ANSI colors are monochrome.

The bar, popups, Kitty, Sway borders/shadows, lock screen, notifications and GTK
theme share the generated palette. Qt5/Qt6 use the generated qt5ct/qt6ct Fusion
palettes; restart Qt apps after a change. Wrappers `frost-qt5 APP` and
`frost-qt6 APP` are available for explicit per-app selection. GTK applications
may need reopening; libadwaita apps and web page content can enforce their own
colors. The compositor still supplies their slight transparency and blur.

Firefox uses Wayland and the desktop light/dark preference. Optional matching
browser chrome takes a minute: open `about:support`, find **Profile Directory**,
create `chrome/userChrome.css` there, and put this line in it, replacing `YOURUSER`:

```css
@import url("file:///home/YOURUSER/.config/frost/generated/firefox-colors.css");
```

In `about:config`, set `toolkit.legacyUserProfileCustomizations.stylesheets` to
`true`, then restart Firefox. This optional CSS needs a Firefox restart to
reflect a newly generated palette. No profile or browser extensions are changed
automatically. Pinch-to-zoom is left to native app support, including Firefox;
the desktop does not intercept pinch gestures.

SwayFX remains the compositor. Automatic longer-edge splitting approximates
Hyprland's dwindle layout; its resizing, grouping and animations remain SwayFX's.
Super+E opens your existing directory handler. With none installed, it opens your
home directory in Kitty. No file manager or Spotify client is installed. The media
widget uses Spotify's MPRIS interface, falling back to another available player;
the Spotify web player may expose limited controls through Firefox.

After 40 minutes of inactivity, the screen locks. It never automatically dims,
turns off or suspends. Closing the lid suspends, with swayidle locking before
sleep. The power key opens the menu. The menu confirms logout/restart/shutdown.

## Troubleshooting and restore

Logs: `~/.cache/frost/session.log`. Start with `frostctl doctor` and inspect that
log. The session supervisor restarts failed desktop processes. For a direct
panel error, run `frostctl panel` from a terminal in a session without an already
running Frost panel.

For silent sound, check `wpctl status` and `pactl info`, then use `pavucontrol` to
select **Analog Stereo Duplex**, the internal sound card and the desired port.
Run `alsamixer`, select the Intel card with F6, and unmute Master/Speaker/Headphone
if needed. Set a moderate volume. A dummy-only output usually means checking
session access, kernel/firmware or WirePlumber; inspect `aplay -l` and the log.

If Wi-Fi authorization fails, verify the `network` group, system D-Bus,
NetworkManager service and the polkit agent. For enterprise/hidden networks use
**Advanced** in the Wi-Fi window. If a glyph/icon is missing, check
`fc-match 'JetBrains Mono'`, Papirus, librsvg and `frostctl doctor`.

To restore, log out to the TTY and run the exact command printed by deployment:

```sh
python3 deploy.py --restore "$HOME/.local/state/frost/backups/TIMESTAMP"
```

Remove the added prompt line from `~/.bashrc`. To undo the system-specific parts,
remove `/etc/keyd/frost.conf` and `/etc/elogind/logind.conf.d/50-frost.conf`, reload
keyd, and restore any services you disabled. User-file restoration does not
change system services, packages, the manual PipeWire/ALSA links or group membership.

## References and validation

Package names and configuration were checked against upstream/Void sources on
2026-10-27. See `VALIDATION.md` for the checks actually run and their limits.

- [Void PipeWire handbook](https://docs.voidlinux.org/config/media/pipewire.html)
- [Void session management](https://docs.voidlinux.org/config/session-management.html)
- [Void NetworkManager](https://docs.voidlinux.org/config/network/networkmanager.html)
- [Void power management](https://docs.voidlinux.org/config/power-management.html)
- [SwayFX 0.6 documentation](https://github.com/wlrfx/swayfx/tree/0.6)
- [keyd documentation](https://github.com/rvaiya/keyd/blob/master/docs/keyd.scdoc)
- [Kitty configuration](https://sw.kovidgoyal.net/kitty/conf/)
- [SwayNotificationCenter schema](https://github.com/ErikReider/SwayNotificationCenter/blob/main/src/configSchema.json)

Frost code is MIT licensed. JetBrains Mono retains its OFL license. The Void
button uses the symbol extracted from [Void's published logo](https://repo-default.voidlinux.org/logos/void.svg), recolored to match the accent.
