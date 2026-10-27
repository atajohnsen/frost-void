"""Shared paths, atomic state and Sway IPC. No desktop libraries required."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "frost"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "frost"
FROST = CONFIG / "frost"
GENERATED = FROST / "generated"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", CACHE)) / "frost"
ROOT = Path(__file__).resolve().parent


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".frost-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def settings():
    return {
        "wallpapers": "~/Pictures/wallpapers",
        "minimum_workspaces": 4,
        "blur_strength": 0.75,
        "surface_opacity": 0.83,
        "terminal_opacity": 0.90,
        "window_opacity": 0.97,
        "font": "JetBrains Mono",
        "font_size": 11,
        "natural_scroll": True,
        **read_json(FROST / "settings.json", {}),
    }


def state():
    return {"mode": "dark", "wallpaper": None, **read_json(STATE / "state.json", {})}


def run(argv, timeout=4):
    try:
        p = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                           timeout=timeout, check=False)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def spawn(argv):
    try:
        return subprocess.Popen([str(a) for a in argv], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def notify(title, body=""):
    spawn(["notify-send", "-a", "Frost", title, body])


def receive(sock):
    def exact(n):
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Sway IPC disconnected")
            data += chunk
        return data
    header = exact(14)
    if header[:6] != b"i3-ipc":
        raise ConnectionError("Invalid Sway IPC header")
    size, kind = struct.unpack("=II", header[6:])
    if size > 32 * 1024 * 1024:
        raise ConnectionError("Oversized Sway IPC message")
    return kind, json.loads(exact(size))


def ipc(kind=0, payload=""):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(os.environ["SWAYSOCK"])
        data = payload.encode()
        sock.sendall(b"i3-ipc" + struct.pack("=II", len(data), kind) + data)
        return receive(sock)[1]


def command(text):
    try:
        return ipc(0, text)
    except (OSError, KeyError, ValueError, ConnectionError):
        return []


def quote(value):
    """Sway command argument, including paths with quotes or command separators."""
    value = str(value)
    if any(c in value for c in "\n\r\x00"):
        raise ValueError("Newlines and NUL are unsupported in Sway arguments")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def walk(tree):
    yield tree
    for node in tree.get("nodes", []) + tree.get("floating_nodes", []):
        yield from walk(node)
