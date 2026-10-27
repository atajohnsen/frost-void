#!/usr/bin/env bash
# Install the Void glibc desktop described in INSTALL.md.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
dry_run=false
assume_yes=false
user_only=false
skip_packages=false
skip_keyd=false
bash_prompt=false
user_backup=
system_backup=
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/frost
SERVICE_DIR=/var/service
SV_DIR=/etc/sv
KEYD_DIR=/etc/keyd
LOCALES_FILE=/etc/default/libc-locales
audio_sources=(
    /usr/share/examples/wireplumber/10-wireplumber.conf
    /usr/share/examples/pipewire/20-pipewire-pulse.conf
)
services=(dbus elogind NetworkManager)
conflicts=(dhcpcd wpa_supplicant connmand wicd acpid)

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]
Run as your desktop user, without sudo, on Void Linux (glibc).

  --dry-run        Print actions without changing files or running sudo
  --yes, -y        Accept installation, including the network service switch
  --skip-packages  Use already-installed packages; skip XBPS updates/install
  --user-only      Deploy dotfiles and user audio links; no sudo/system changes
  --skip-keyd      Keep existing keyd configuration/service; merge keys manually
  --bash-prompt    Add the optional Frost prompt to ~/.bashrc once
  --help, -h       Show this help

Full installation updates Void, installs packages.txt, backs up and deploys
dotfiles, configures audio/locales/groups/keyd/elogind, disables competing
network/power services, and enables dbus, elogind, NetworkManager and keyd.
Switching network services may disconnect you. Run from a local TTY.
The script never reboots automatically. See INSTALL.md for backup details.
EOF
}

die() { printf 'Install failed: %s\n' "$*" >&2; exit 1; }

run() {
    printf '  +'; printf ' %q' "$@"; printf '\n'
    if ! $dry_run; then "$@"; fi
}

check_host() {
    (( EUID != 0 )) || die 'Run as your desktop user, without sudo.'
    if ! $user_only; then
        [[ -r /etc/os-release ]] || die 'Cannot identify this system.'
        local ID=
        . /etc/os-release
        [[ $ID == void ]] || die 'Full installation requires Void Linux (glibc). Use --dry-run to preview.'
        [[ $(getconf GNU_LIBC_VERSION 2>/dev/null || true) == glibc* ]] || die 'This bundle requires glibc, not musl.'
        [[ -d $SERVICE_DIR ]] || die 'Run on a booted Void system with runit.'
        command -v sudo >/dev/null || die 'sudo is required for system setup.'
        command -v xbps-install >/dev/null || die 'XBPS is missing.'
    fi
}

check_keyd() {
    $skip_keyd && return 0
    local file
    # The bundled wildcard mapping could overlap any existing keyboard config.
    for file in "$KEYD_DIR"/*.conf; do
        [[ -e $file || -L $file ]] || continue
        if [[ $file != "$KEYD_DIR/frost.conf" ]] || ! cmp -s -- "$ROOT/system/keyd/frost.conf" "$file"; then
            die "Existing keyd config: $file. Use --skip-keyd and merge the Super mappings manually."
        fi
    done
}

check_dependencies() {
    command -v python3 >/dev/null || die 'python3 is missing; install packages first.'
    python3 -c 'from PIL import Image; import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' \
        || die 'Python Pillow / GTK3 dependencies are missing.'
    command -v fc-cache >/dev/null || die 'fontconfig is missing.'
    local source service
    for source in "${audio_sources[@]}"; do
        [[ -f $source ]] || die "Missing package-supplied audio config: $source"
    done
    if ! $user_only; then
        for source in /usr/share/alsa/alsa.conf.d/{50-pipewire,99-pipewire-default}.conf "$LOCALES_FILE"; do
            [[ -f $source ]] || die "Missing package-supplied config: $source"
        done
        for service in "${services[@]}"; do
            [[ -d $SV_DIR/$service ]] || die "Missing runit service: $service"
            [[ ! -e $SV_DIR/$service/down ]] || die "Service $service is administratively down; review $SV_DIR/$service/down first."
        done
        for service in network video; do
            getent group "$service" >/dev/null || die "Missing group: $service"
        done
    fi
}

backup_path() {
    local scope=$1 path=$2 base
    local -a privilege=()
    if [[ $scope == system ]]; then
        base=$system_backup
        privilege=(sudo)
    else
        base=$user_backup
    fi
    # Never replace directories with links/files, even if ln would allow it.
    [[ ! -d $path || -L $path ]] || die "Expected a file or symlink, found directory: $path"
    if [[ -e $path || -L $path ]]; then
        run "${privilege[@]}" cp -a --parents -- "$path" "$base"
    else
        printf '  New path: %s\n' "$path"
        if ! $dry_run; then
            printf '%s\n' "$path" | "${privilege[@]}" tee -a "$base/absent-paths.txt" >/dev/null
        fi
    fi
}

configure_user() {
    run python3 "$ROOT/deploy.py"
    local source dest
    run mkdir -p -- "$CONFIG/pipewire/pipewire.conf.d"
    for source in "${audio_sources[@]}"; do
        dest=$CONFIG/pipewire/pipewire.conf.d/${source##*/}
        backup_path user "$dest"
        run ln -sfnT -- "$source" "$dest"
    done
    if $bash_prompt; then
        local line='[ -r "$HOME/.config/frost/prompt.bash" ] && . "$HOME/.config/frost/prompt.bash"'
        # Respect XDG_CONFIG_HOME, as deploy.py does.
        if [[ $CONFIG != "$HOME/.config" ]]; then
            printf -v line '[ -r %q ] && . %q' "$CONFIG/frost/prompt.bash" "$CONFIG/frost/prompt.bash"
        fi
        if ! grep -Fxq -- "$line" "$HOME/.bashrc" 2>/dev/null; then
            backup_path user "$HOME/.bashrc"
            printf '  Add Frost prompt to %s\n' "$HOME/.bashrc"
            if ! $dry_run; then printf '\n%s\n' "$line" >> "$HOME/.bashrc"; fi
        fi
    fi
}

configure_system() {
    local source dest
    run sudo mkdir -p /etc/alsa/conf.d /etc/elogind/logind.conf.d
    for source in /usr/share/alsa/alsa.conf.d/{50-pipewire,99-pipewire-default}.conf; do
        dest=/etc/alsa/conf.d/${source##*/}
        backup_path system "$dest"
        run sudo ln -sfnT -- "$source" "$dest"
    done
    dest=/etc/elogind/logind.conf.d/50-frost.conf
    backup_path system "$dest"
    run sudo cp -- "$ROOT/system/elogind/logind.conf.d/50-frost.conf" "$dest"
    if ! $skip_keyd; then
        run sudo keyd check "$ROOT/system/keyd/frost.conf"
        run sudo mkdir -p -- "$KEYD_DIR"
        backup_path system "$KEYD_DIR/frost.conf"
        run sudo cp -- "$ROOT/system/keyd/frost.conf" "$KEYD_DIR/frost.conf"
    fi
    run sudo usermod -aG network,video "$(id -un)"
    backup_path system "$LOCALES_FILE"
    # Uncomment matching entries, or append if the template omitted them.
    run sudo sed -i -E \
        -e 's/^[[:space:]]*#?[[:space:]]*(en_US\.UTF-8[[:space:]]+UTF-8)[[:space:]]*$/\1/' \
        -e 's/^[[:space:]]*#?[[:space:]]*(nb_NO\.UTF-8[[:space:]]+UTF-8)[[:space:]]*$/\1/' "$LOCALES_FILE"
    local locale
    for locale in en_US.UTF-8 nb_NO.UTF-8; do
        if $dry_run; then
            printf '  Ensure locale entry: %s UTF-8\n' "$locale"
        elif ! grep -Fxq "$locale UTF-8" "$LOCALES_FILE"; then
            printf '%s UTF-8\n' "$locale" | sudo tee -a "$LOCALES_FILE" >/dev/null
        fi
    done
    run sudo xbps-reconfigure -f glibc-locales
}

configure_services() {
    local service path
    # Back up the entire planned switch before stopping any service.
    for service in "${conflicts[@]}" "${services[@]}"; do
        backup_path system "$SERVICE_DIR/$service"
    done
    for service in "${conflicts[@]}"; do
        path=$SERVICE_DIR/$service
        if [[ -L $path ]]; then
            if [[ -e $path ]]; then run sudo sv down "$path"; fi
            run sudo rm -- "$path"
        fi
    done
    for service in "${services[@]}"; do
        path=$SERVICE_DIR/$service
        if [[ ! -e $path && ! -L $path ]]; then
            run sudo ln -s -- "$SV_DIR/$service" "$path"
        elif [[ ! -L $path || $(readlink -f -- "$path") != "$(readlink -f -- "$SV_DIR/$service")" ]]; then
            die "Unexpected service entry: $path; review it before rerunning."
        fi
        run sudo sv up "$path"
    done
}

main() {
    while (( $# )); do
        case $1 in
            --dry-run) dry_run=true ;;
            --yes|-y) assume_yes=true ;;
            --user-only) user_only=true; skip_packages=true ;;
            --skip-packages) skip_packages=true ;;
            --skip-keyd) skip_keyd=true ;;
            --bash-prompt) bash_prompt=true ;;
            --help|-h) usage; return 0 ;;
            *) usage >&2; die "Unknown option: $1" ;;
        esac
        shift
    done
    [[ $HOME == /* && $CONFIG == /* && $STATE == /* ]] || die 'HOME and XDG paths must be absolute.'
    [[ -f $ROOT/deploy.py && -s $ROOT/packages.txt ]] || die 'Keep install.sh inside the complete frost-void folder.'
    if ! $skip_keyd; then services+=(keyd); fi
    if ! $dry_run; then
        check_host
        if ! $user_only; then check_keyd; fi
    fi
    printf 'Frost installer: user=%s, user-only=%s, dry-run=%s\n' "$(id -un)" "$user_only" "$dry_run"
    if ! $user_only; then
        printf 'Will update/install packages (unless skipped), configure the system and switch network services.\n'
        printf 'Networking may disconnect. Use a local TTY; reconnect with nmtui.\n'
    fi
    if ! $dry_run && ! $assume_yes; then
        [[ -t 0 ]] || die 'Noninteractive installation requires --yes; preview with --dry-run.'
        local answer
        read -r -p 'Install Frost and back up existing files? [y/N] ' answer
        case $answer in y|Y|yes|YES) ;; *) printf 'Cancelled.\n'; return 0 ;; esac
    fi
    if ! $user_only; then run sudo -v; fi
    if ! $skip_packages; then
        local -a packages=() xbps_flags=()
        local package
        while IFS= read -r package || [[ -n $package ]]; do
            [[ -z $package || $package == \#* ]] && continue
            [[ $package =~ ^[a-zA-Z0-9][a-zA-Z0-9+_.-]*$ ]] || die "Invalid package name: $package"
            packages+=("$package")
        done < "$ROOT/packages.txt"
        (( ${#packages[@]} )) || die 'packages.txt contains no packages.'
        if $assume_yes; then xbps_flags=(-y); fi
        # XBPS self-updates need their own transaction; the second run finishes it.
        run sudo xbps-install "${xbps_flags[@]}" -Su
        run sudo xbps-install "${xbps_flags[@]}" -Su
        run sudo xbps-install "${xbps_flags[@]}" -S "${packages[@]}"
    fi
    if ! $dry_run; then check_dependencies; fi
    if $dry_run; then
        user_backup=$STATE/installer-backups/DRY-RUN
        system_backup=/var/backups/frost-DRY-RUN
    else
        mkdir -p -- "$STATE/installer-backups"
        user_backup=$(mktemp -d "$STATE/installer-backups/install-XXXXXXXX")
        if ! $user_only; then
            sudo mkdir -p /var/backups
            system_backup=$(sudo mktemp -d /var/backups/frost-XXXXXXXX)
        fi
    fi
    printf 'Additional user-file backup: %s\n' "$user_backup"
    if ! $user_only; then printf 'System backup: %s\n' "$system_backup"; fi
    configure_user
    if ! $user_only; then configure_system; configure_services; fi
    if $dry_run; then
        printf '\nDry run complete. No changes made; host/dependency checks deferred to installation.\n'
    else
        printf '\nFrost installed. User dotfile restore command was printed by deploy.py above.\n'
        printf 'Reboot when ready, log into your TTY, then run: ~/.local/bin/frost-session\n'
        if $skip_keyd; then printf 'Merge system/keyd/frost.conf into your keyd config to enable bare-Super tap.\n'; fi
        printf 'Add wallpaper images to ~/Pictures/wallpapers. See INSTALL.md for checks and rollback.\n'
    fi
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    trap 'printf "Installation stopped at line %s. Completed steps were not rolled back; keep the backup paths printed above.\n" "$LINENO" >&2' ERR
    main "$@"
fi
