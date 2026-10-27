"""Wallpaper quantization and a single-hue, contrast-checked tonal palette."""
from __future__ import annotations
import colorsys
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
from PIL import Image, ImageOps
from core import (CONFIG, DATA, CACHE, STATE, GENERATED, RUNTIME, FROST, ROOT,
                  atomic_write, write_json, read_json, settings, state, run,
                  command, quote)


def rgb(value):
    return tuple(int(value[i:i+2], 16) / 255 for i in (1, 3, 5))


def hex_color(value):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in value)


def mix(a, b, amount):
    return hex_color(tuple(x * (1-amount) + y * amount for x, y in zip(rgb(a), rgb(b))))


def luminance(color):
    def linear(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(v) for v in rgb(color))
    return .2126*r + .7152*g + .0722*b


def contrast(a, b):
    x, y = sorted((luminance(a), luminance(b)))
    return (y + .05) / (x + .05)


def tone(seed, lightness, saturation_scale=1):
    h, _, s = colorsys.rgb_to_hls(*rgb(seed))
    return hex_color(colorsys.hls_to_rgb(h, lightness, min(1, s*saturation_scale)))


def legible(color, background, dark, minimum=4.5):
    if contrast(color, background) >= minimum:
        return color
    h, light, sat = colorsys.rgb_to_hls(*rgb(color))
    for _ in range(101):
        light = max(0, min(1, light + (.01 if dark else -.01)))
        color = hex_color(colorsys.hls_to_rgb(h, light, sat))
        if contrast(color, background) >= minimum:
            return color
    return "#ffffff" if dark else "#000000"


def extract(path):
    """Pillow median-cut palette; populous chromatic colors beat tiny bright details.

    Near-grayscale pictures stay grayscale. No synthetic blue/green fallback is
    imposed on a supplied image. Cache is keyed by path, size and nanosecond mtime.
    """
    path = Path(path).expanduser().resolve()
    stat = path.stat()
    key = hashlib.sha256(f"{path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
    cache = CACHE / "palettes" / (key + ".json")
    found = read_json(cache)
    if found:
        return found["seed"]
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((160, 160))
        quantized = im.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        choices = []
        for count, index in quantized.getcolors():
            color = tuple(v / 255 for v in palette[index*3:index*3+3])
            h, light, saturation = colorsys.rgb_to_hls(*color)
            # Moderate chroma and middle tones, while retaining population.
            score = math.sqrt(count) * (.08 + saturation) * (.15 + math.sin(math.pi*light)**2)
            choices.append((score, count, saturation, color))
        if max(c[2] for c in choices) < .09:
            seed = hex_color(max(choices, key=lambda c: c[1])[3])
        else:
            seed = hex_color(max(choices, key=lambda c: c[0])[3])
    write_json(cache, {"seed": seed})
    return seed


def palette(seed, mode):
    dark = mode == "dark"
    surface = mix("#111315" if dark else "#f9fafb", seed, .035)
    background = mix("#101214" if dark else "#f4f6f8", seed, .025)
    accent = legible(tone(seed, .74 if dark else .36), surface, dark)
    secondary = legible(tone(seed, .66 if dark else .29, .55), surface, dark)
    tertiary = legible(tone(seed, .83 if dark else .42, .30), surface, dark)
    return dict(seed=seed, mode=mode, surface=surface, background=background,
                foreground="#edf0f3" if dark else "#1b2025",
                muted="#adb5bd" if dark else "#535d67", accent=accent,
                secondary=secondary, tertiary=tertiary,
                raised=mix(surface, "#ffffff" if dark else "#000000", .055),
                border=mix(surface, accent, .24),
                highlight="#ffffff" if dark else "#ffffff")


def rgba(color, alpha):
    return "rgba(%d, %d, %d, %.3f)" % (*[round(v * 255) for v in rgb(color)], alpha)


def render(p, wallpaper=None):
    s = settings()
    GENERATED.mkdir(parents=True, exist_ok=True)
    write_json(GENERATED / "palette.json", p)
    values = "\n".join(f"@define-color {k} {p[k]};" for k in
                        ("surface", "foreground", "muted", "accent", "secondary", "tertiary", "raised", "border"))
    values += f"\n@define-color glass {rgba(p['surface'], s['surface_opacity'])};\n"
    values += f"@define-color shine {rgba(p['highlight'], .20 if p['mode']=='dark' else .80)};\n"
    atomic_write(GENERATED / "colors.css", values)
    atomic_write(GENERATED / "wallpaper.conf",
                 'output * bg ' + (quote(wallpaper) + ' fill' if wallpaper else p['background']+' solid_color') + '\n')
    opacity = max(.75, min(1, float(s["window_opacity"])))
    # Use #RRGGBB Sway colors and alpha-bearing shadow colors.
    atomic_write(GENERATED / "sway-colors.conf", f"""# Generated by frostctl. Change settings.json instead.
client.focused {p['accent']} {p['surface']} {p['foreground']} {p['accent']} {p['accent']}
client.focused_inactive {p['border']} {p['surface']} {p['muted']} {p['border']} {p['border']}
client.unfocused {p['border']} {p['surface']} {p['muted']} {p['border']} {p['border']}
client.urgent {p['accent']} {p['surface']} {p['foreground']} {p['accent']} {p['accent']}
client.background {p['background']}
shadow_color {p['accent']}65
shadow_inactive_color #00000026
for_window [app_id=".*"] opacity {opacity:.2f}
for_window [class=".*"] opacity {opacity:.2f}
# Kitty manages its own background alpha; text stays opaque.
for_window [app_id="kitty"] opacity 1
""")
    blur = max(0, min(1, float(s["blur_strength"])))
    atomic_write(GENERATED / "effects.conf", f"""# Perceptual mapping; SwayFX has no normalized blur-strength setting.
blur {'enable' if blur else 'disable'}
blur_passes {max(1, round(blur*4))}
blur_radius {max(1, round(blur*10))}
blur_noise 0.015
blur_brightness 1.0
blur_contrast 1.0
blur_saturation 1.0
input type:touchpad natural_scroll {'enabled' if s['natural_scroll'] else 'disabled'}
""")
    colors = []
    # All ANSI entries use the same hue. Brightness still distinguishes entries.
    for lightness in ([.18,.61,.66,.72,.75,.68,.80,.88] if p['mode']=='dark'
                      else [.15,.31,.36,.41,.29,.37,.33,.77]):
        colors.append(tone(p['seed'], lightness, .50))
    colors[0] = p["surface"]
    colors[7] = p["foreground"]
    bright = [mix(c, "#ffffff" if p['mode']=='dark' else "#000000", .16) for c in colors]
    kitty = f"background {p['background']}\nforeground {p['foreground']}\ncursor {p['accent']}\n"
    kitty += f"selection_background {p['accent']}\nselection_foreground {p['surface']}\n"
    kitty += f"background_opacity {s['terminal_opacity']}\n"
    kitty += "\n".join(f"color{i} {v}" for i,v in enumerate(colors+bright)) + "\n"
    atomic_write(GENERATED / "kitty.conf", kitty)
    atomic_write(GENERATED / "swaylock.conf", f"""color={p['background'][1:]}
font=JetBrains Mono
font-size=22
indicator-radius=50
indicator-thickness=3
inside-color={p['surface'][1:]}dd
ring-color={p['border'][1:]}
key-hl-color={p['accent'][1:]}
ring-ver-color={p['accent'][1:]}
text-color={p['foreground'][1:]}
line-color=00000000
separator-color=00000000
show-failed-attempts
""")
    # A lightweight GTK theme. App content can override it (notably libadwaita).
    gtk = values + f"""
* {{ font-family: "{s['font']}"; font-size: {s['font_size']}pt; }}
window, dialog, .background {{ background-color: {rgba(p['surface'], .96)}; color: @foreground; }}
headerbar, .titlebar, toolbar, menubar {{ background-image: none; background-color: @glass; color: @foreground; box-shadow: inset 0 1px @shine; border-color: @border; }}
button {{ background-image: none; background-color: @raised; color: @foreground; border: 1px solid @border; border-radius: 7px; box-shadow: none; text-shadow: none; }}
button:hover {{ border-color: @accent; }}
button:checked, selection, *:selected {{ background-color: @accent; color: @surface; }}
entry, textview, textview text, treeview, list, row {{ background-color: @surface; color: @foreground; }}
entry {{ border: 1px solid @border; border-radius: 7px; padding: 7px; }}
tooltip, menu, popover {{ background-color: @surface; color: @foreground; border: 1px solid @border; border-radius: 9px; }}
scrollbar {{ background-color: transparent; }}
scrollbar slider {{ background-color: @border; border-radius: 5px; min-width: 5px; min-height: 5px; }}
scale highlight, progressbar progress {{ background-color: @accent; }}
"""
    theme_dir = DATA / "themes/Frost"
    for version in ("gtk-3.0", "gtk-4.0"):
        atomic_write(theme_dir / version / "gtk.css", gtk)
        atomic_write(CONFIG / version / "settings.ini", f"""[Settings]
gtk-theme-name=Frost
gtk-icon-theme-name=Papirus{'-Dark' if p['mode']=='dark' else '-Light'}
gtk-font-name={s['font']} {s['font_size']}
gtk-application-prefer-dark-theme={1 if p['mode']=='dark' else 0}
gtk-cursor-theme-name=Adwaita
gtk-cursor-theme-size=24
""")
    # GTK4 apps which consult user CSS still receive the palette without forcing
    # unsupported transparency on libadwaita's internal content widgets.
    atomic_write(CONFIG / "gtk-4.0/gtk.css", f"@import url(\"{theme_dir / 'gtk-4.0/gtk.css'}\");\n")
    # Qt5/6 QPalette role order: WindowText ... PlaceholderText, Qt6 Accent.
    q = [p['foreground'],p['raised'],p['shine'] if 'shine' in p else '#ffffff',p['border'],p['border'],p['border'],
         p['foreground'],'#ffffff',p['foreground'],p['surface'],p['background'],'#000000',
         p['accent'],p['surface'],p['accent'],p['secondary'],p['raised'],p['border'],
         p['surface'],p['foreground'],p['muted'],p['muted'],p['accent']]
    for version, length in (("qt5ct",22),("qt6ct",23)):
        colorfile = CONFIG / version / "colors/Frost.conf"
        row = ", ".join(q[:length])
        disabled = [p['muted'] if i in (0,6,8) else v for i,v in enumerate(q[:length])]
        atomic_write(colorfile, f"[ColorScheme]\nactive_colors={row}\ninactive_colors={row}\ndisabled_colors={', '.join(disabled)}\n")
        atomic_write(CONFIG / version / (version+".conf"), f"""[Appearance]
color_scheme_path={colorfile}
custom_palette=true
icon_theme=Papirus{'-Dark' if p['mode']=='dark' else '-Light'}
standard_dialogs=default
style=Fusion
""")
    source = ROOT / "assets/void.svg"
    if source.exists():
        atomic_write(GENERATED / "void.svg", source.read_text().replace("#478061",p['accent']))
    atomic_write(GENERATED / "firefox-colors.css", f"""/* Optional: see README. Restart Firefox after changing modes. */
:root {{ --toolbar-bgcolor: {p['surface']} !important; --toolbar-color: {p['foreground']} !important;
--lwt-accent-color: {p['background']} !important; --lwt-text-color: {p['foreground']} !important;
--lwt-toolbarbutton-icon-fill: {p['accent']} !important; --tab-selected-bgcolor: {p['raised']} !important;
--toolbar-field-background-color: {p['raised']} !important; --toolbar-field-color: {p['foreground']} !important;
--lwt-tab-line-color: {p['accent']} !important; }}
#navigator-toolbox {{ background-color: {p['surface']} !important; }}
""")


def apply(wallpaper=None, mode=None, persist=True, reload=True):
    STATE.mkdir(parents=True, exist_ok=True)
    # Serializes CLI mode changes and picker previews; each complete generation
    # is visible before a reload. The picker itself coalesces rapid navigation.
    with (STATE / "theme.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = state()
        mode = mode or previous['mode']
        if mode not in ("dark", "light"):
            raise ValueError("Mode must be dark or light")
        explicit_wallpaper = wallpaper is not None
        wallpaper = wallpaper if explicit_wallpaper else previous.get('wallpaper')
        if wallpaper and not Path(wallpaper).expanduser().is_file() and not explicit_wallpaper:
            wallpaper = None
        if wallpaper:
            wallpaper = str(Path(wallpaper).expanduser().resolve())
            seed = extract(wallpaper)
        else:
            seed = "#91b6a4"  # Neutral startup accent until a wallpaper is supplied.
        p = palette(seed, mode)
        render(p, wallpaper)
        if persist:
            write_json(STATE / "state.json", {"mode":mode, "wallpaper":wallpaper})
        if reload and os.environ.get("SWAYSOCK"):
            command("reload")
            run(["gsettings","set","org.gnome.desktop.interface","color-scheme",
                 "prefer-dark" if mode=="dark" else "prefer-light"])
            run(["gsettings","set","org.gnome.desktop.interface","gtk-theme","Frost"])
            run(["gsettings","set","org.gnome.desktop.interface","icon-theme",
                 "Papirus-Dark" if mode=="dark" else "Papirus-Light"])
            run(["swaync-client","-rs"])
            for value in run(['pgrep','-u',str(os.getuid()),'-x','kitty']).splitlines():
                try:
                    pid = int(value)
                    if Path(f"/proc/{pid}/comm").read_text().strip() == "kitty":
                        os.kill(pid, signal.SIGUSR1)
                except (OSError,ValueError):
                    pass
        return p
