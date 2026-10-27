"""The frostctl CLI. All system configuration remains manual in README.md."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from core import (CONFIG, DATA, CACHE, STATE, RUNTIME, GENERATED, ROOT,
                  settings, state, run, spawn, command, ipc, notify)


def send(action):
    for attempt in range(15):
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(1)
                sock.connect(str(RUNTIME/'control.sock'))
                sock.sendall(action.encode())
            return
        except OSError:
            if attempt==0:
                spawn([str(DATA/'frost/frostctl'),'panel'])
            time.sleep(.15)
    raise RuntimeError('The Frost panel could not start. Run frostctl panel in Kitty to see the error.')


def lock():
    if run(['pgrep','-u',str(os.getuid()),'-x','swaylock']):
        return
    argv=['swaylock','--daemonize','--config',str(GENERATED/'swaylock.conf')]
    wallpaper=state().get('wallpaper')
    if wallpaper and Path(wallpaper).exists():
        # swaylock uses output:path. No shell is involved.
        argv+=['--image',wallpaper,'--scaling','fill']
    subprocess.run(argv,check=True)


def screenshot():
    selection=run(['slurp'],timeout=120)
    if not selection:
        return
    folder=Path.home()/'Pictures/Screenshots'
    folder.mkdir(parents=True,exist_ok=True)
    from datetime import datetime
    target=folder/('Screenshot-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.png')
    subprocess.run(['grim','-g',selection,str(target)],check=True)
    with target.open('rb') as image:
        subprocess.run(['wl-copy','--type','image/png'],stdin=image,check=True)
    notify('Screenshot saved and copied',str(target))


def doctor():
    required=['sway','kitty','firefox','pipewire','wireplumber','wpctl','pactl',
              'swaync','swaync-client','swayidle','swaylock','nmcli','nm-connection-editor',
              'pavucontrol','playerctl','wl-copy','wl-paste','cliphist','brightnessctl',
              'grim','slurp','dbus-run-session','loginctl','keyd']
    failed=False
    for name in required:
        found=shutil.which(name)
        print(('OK     ' if found else 'MISSING')+' '+name)
        failed |= not bool(found)
    try:
        import gi
        gi.require_version('Gtk','3.0')
        gi.require_version('GtkLayerShell','0.1')
        from gi.repository import Gtk, GtkLayerShell
        from PIL import Image
        print('OK      GTK3, GtkLayerShell, Pillow')
    except (ImportError,ValueError) as error:
        print('MISSING Python desktop dependency:',error)
        failed=True
    for name in ('XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','WAYLAND_DISPLAY','SWAYSOCK'):
        print(('OK     ' if os.environ.get(name) else 'SESSION')+' '+name)
    if os.environ.get('SWAYSOCK'):
        print('\nSway:',run(['sway','--version']))
        print('Audio:',run(['pactl','info']) or 'Not available; inspect session.log')
        print('Wi-Fi:',run(['nmcli','general','status']) or 'Not available')
    print('\nLog:',CACHE/'session.log')
    print('Settings:',CONFIG/'frost/settings.json')
    return 1 if failed else 0


def main():
    parser=argparse.ArgumentParser(description='Frost desktop controls')
    parser.add_argument('action',choices=['panel','launcher','wallpaper','wifi','battery','power',
        'clipboard','close','theme','apply','init','lock','suspend','logout','reboot','poweroff',
        'screenshot','files','terminal','doctor'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args()
    action=args.action
    if action in ('launcher','wallpaper','wifi','battery','power','clipboard','close'):
        send(action)
    elif action=='panel':
        from panel import main as panel_main
        panel_main()
    elif action in ('init','theme','apply'):
        import theme
        if action=='theme':
            mode=args.value or 'toggle'
            if mode=='toggle':
                mode='light' if state()['mode']=='dark' else 'dark'
            theme.apply(mode=mode)
        elif action=='apply':
            if not args.value:
                parser.error('apply requires an image path')
            theme.apply(wallpaper=args.value)
        else:
            theme.apply(reload=False)
    elif action=='lock':
        lock()
    elif action=='suspend':
        lock()
        subprocess.run(['loginctl','suspend'],check=True)
    elif action=='logout':
        command('exit')
    elif action in ('reboot','poweroff'):
        subprocess.run(['loginctl',action],check=True)
    elif action=='screenshot':
        screenshot()
    elif action=='files':
        import gi
        from gi.repository import Gio
        app=Gio.AppInfo.get_default_for_type('inode/directory',False)
        if app:
            app.launch([Gio.File.new_for_path(str(Path.home()))],None)
        else:
            spawn(['frostctl','terminal',str(Path.home())])
    elif action=='terminal':
        RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
        pid=os.getpid()
        (RUNTIME/f'kitty-{pid}.pid').write_text(str(pid))
        argv=['kitty']
        if args.value:
            argv+=['--directory',args.value]
        os.execvp('kitty',argv)
    elif action=='doctor':
        return doctor()
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (RuntimeError,OSError,ValueError,subprocess.SubprocessError) as error:
        print('frostctl:',error,file=sys.stderr)
        sys.exit(1)
