# Install Frost

For your Void glibc laptop with SwayFX. Run this from the extracted `frost-void`
folder as your normal user. The steps use `sudo`; if unavailable, run root
commands from a root TTY and replace `$USER` with your desktop username.
More explanation, controls and troubleshooting are in `README.md`.

## 1. Packages and user files

```sh
sudo xbps-install -Su
xargs sudo xbps-install -S < packages.txt
python3 deploy.py
export PATH="$HOME/.local/bin:$PATH"
```

If XBPS updates itself, rerun the update before installing the package list.
Deployment prints your backup location and restore command. Add your wallpapers
to `~/Pictures/wallpapers`.

Optional Bash prompt: add this line once to `~/.bashrc`:

```sh
[ -r "$HOME/.config/frost/prompt.bash" ] && . "$HOME/.config/frost/prompt.bash"
```

## 2. Audio

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

The desktop starts PipeWire as your user. Do not start WirePlumber or
pipewire-pulse separately, or run a separate PulseAudio daemon.

## 3. Super key, session and networking

```sh
sudo mkdir -p /etc/keyd /etc/elogind/logind.conf.d
sudo cp system/keyd/frost.conf /etc/keyd/frost.conf
sudo keyd check /etc/keyd/frost.conf
sudo cp system/elogind/logind.conf.d/50-frost.conf /etc/elogind/logind.conf.d/50-frost.conf
ls -1 /var/service
```

If you already use keyd, merge these two Super mappings into the existing config.
Next, switch to NetworkManager and elogind. This briefly disconnects networking:

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

Uncomment `en_US.UTF-8 UTF-8` and `nb_NO.UTF-8 UTF-8` in
`/etc/default/libc-locales`, then run:

```sh
sudo xbps-reconfigure -f glibc-locales
```

## 4. Reboot and launch

Reboot, log into your TTY as your normal user, and run:

```sh
~/.local/bin/frost-session
```

Tap **Super** for apps. **Super+O** switches light/dark. **Super+Shift+W** opens
wallpapers; arrows/scroll preview, Enter keeps, Esc restores. **Super+Enter**
opens Kitty; **Super+W** opens Firefox. Click Wi-Fi to connect, or use `nmtui`
from a TTY. Hover the media text for playback controls.

In Kitty, check:

```sh
frostctl doctor
wpctl status
pactl info
sway --validate --config "$HOME/.config/sway/config"
```

For silent speakers, open `pavucontrol`; also check/unmute the Intel card in
`alsamixer` with F6. The desktop locks after 40 idle minutes; closing the lid
locks and suspends. Logs are at `~/.cache/frost/session.log`.

Restore user files from a TTY with the exact command printed by `deploy.py`.
System-service rollback and optional Firefox styling are covered in `README.md`.
