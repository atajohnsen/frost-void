#!/usr/bin/env python3
"""Copy user files with a timestamped backup. Never installs packages/services."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
CONFIG=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
DATA=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))
STATE=Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'frost'
BIN=Path.home()/'.local/bin'


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def targets():
    return ([CONFIG/name for name in ('sway','kitty','frost','swaync')]
        + [CONFIG/'xdg-desktop-portal/portals.conf']
        + [CONFIG/'gtk-3.0/settings.ini',CONFIG/'gtk-4.0/settings.ini',CONFIG/'gtk-4.0/gtk.css']
        + [CONFIG/f'{qt}/{qt}.conf' for qt in ('qt5ct','qt6ct')]
        + [CONFIG/f'{qt}/colors/Frost.conf' for qt in ('qt5ct','qt6ct')]
        + [DATA/'frost',DATA/'themes/Frost',DATA/'fonts/frost',STATE/'state.json']
        + [BIN/p.name for p in sorted((ROOT/'bin').iterdir())])


def deploy():
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=STATE/'backups'/stamp
    backup.mkdir(parents=True)
    records=[]
    for index,path in enumerate(targets()):
        entry=dict(destination=str(path),backup=None)
        if path.exists() or path.is_symlink():
            saved=backup/str(index)
            saved.parent.mkdir(parents=True,exist_ok=True)
            if path.is_symlink():
                saved.symlink_to(os.readlink(path))
            elif path.is_dir():
                shutil.copytree(path,saved,symlinks=True)
            else:
                shutil.copy2(path,saved)
            entry['backup']=str(saved)
        records.append(entry)
    manifest=backup/'manifest.json'
    manifest.write_text(json.dumps(records,indent=2)+'\n')
    # Keep the manifest durable before any existing files are replaced.
    for name in ('sway','kitty','frost','swaync'):
        remove(CONFIG/name)
        shutil.copytree(ROOT/'config'/name,CONFIG/name)
    portal=CONFIG/'xdg-desktop-portal/portals.conf'
    portal.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'config/xdg-desktop-portal/portals.conf',portal)
    remove(DATA/'frost')
    shutil.copytree(ROOT/'share/frost',DATA/'frost',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'assets',DATA/'frost/assets',ignore=shutil.ignore_patterns('fonts'))
    for source in (ROOT/'bin').iterdir():
        dest=DATA/'frost'/source.name
        shutil.copy2(source,dest)
        dest.chmod(0o755)
        BIN.mkdir(parents=True,exist_ok=True)
        link=BIN/source.name
        remove(link)
        link.symlink_to(dest)
    remove(DATA/'fonts/frost')
    shutil.copytree(ROOT/'assets/fonts',DATA/'fonts/frost')
    (Path.home()/'Pictures/wallpapers').mkdir(parents=True,exist_ok=True)
    result=subprocess.run([sys.executable,str(DATA/'frost/frostctl'),'init'])
    subprocess.run(['fc-cache','-f',str(DATA/'fonts/frost')],check=False)
    print('\nDotfiles copied. Backup:',backup)
    print('Restore with: python3 deploy.py --restore '+str(backup))
    print('Continue the manual steps in README.md before launching frost-session.')
    return result.returncode


def restore(backup):
    backup=Path(backup).expanduser().resolve()
    records=json.loads((backup/'manifest.json').read_text())
    allowed={str(p) for p in targets()}
    for entry in records:
        if entry['destination'] not in allowed:
            raise RuntimeError('Manifest contains an unexpected target; no files restored.')
        saved=entry['backup']
        if saved and not (Path(saved).exists() or Path(saved).is_symlink()):
            raise RuntimeError('A saved backup is missing; no files restored.')
        if saved and not Path(saved).resolve().is_relative_to(backup):
            # A saved symlink may point outside the backup; its own path is safe.
            if not Path(saved).absolute().is_relative_to(backup) or not Path(saved).is_symlink():
                raise RuntimeError('Invalid backup path')
    # Restore the CLI last, so the complete active session can be exited first.
    for entry in reversed(records):
        dest=Path(entry['destination'])
        remove(dest)
        saved=entry['backup']
        if saved:
            source=Path(saved)
            dest.parent.mkdir(parents=True,exist_ok=True)
            if source.is_symlink():
                dest.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source,dest,symlinks=True)
            else:
                shutil.copy2(source,dest)
    print('Previous user files restored. System services/packages are managed separately; see README.md.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore',metavar='BACKUP_FOLDER')
    args=parser.parse_args()
    if os.getuid()==0:
        parser.error('Run as your desktop user, without sudo.')
    try:
        if args.restore:
            restore(args.restore)
        else:
            sys.exit(deploy())
    except (OSError,ValueError,RuntimeError) as error:
        print('Deploy failed:',error,file=sys.stderr)
        sys.exit(1)
