"""Frost's GTK3 layer-shell islands, launcher, live wallpaper picker and popups."""
from __future__ import annotations
import calendar
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib, GtkLayerShell, Pango
from core import (CONFIG, DATA, CACHE, STATE, RUNTIME, FROST, GENERATED, ROOT,
                  settings, state, read_json, run, spawn, ipc, command, receive,
                  quote, walk, notify)
import theme
from tray import Tray


def later(fn, *args):
    def call():
        fn(*args)
        return False
    GLib.idle_add(call)


def thread(fn, *args):
    threading.Thread(target=fn,args=args,daemon=True).start()


def style(widget, *classes):
    for name in classes:
        widget.get_style_context().add_class(name)
    return widget


def icon(name, size=18):
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.MENU)
    image.set_pixel_size(size)
    return image


def button(name, tooltip, callback):
    b = style(Gtk.Button(), "icon-button")
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.add(icon(name))
    b.set_tooltip_text(tooltip)
    b.connect("clicked", lambda *_: callback())
    return b


def text_button(text, callback, *classes):
    b = style(Gtk.Button(label=text), *classes)
    b.connect("clicked", lambda *_: callback())
    return b


def image_file(path, width, height):
    try:
        return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),width,height,True))
    except (GLib.Error, OSError):
        return icon("image-missing-symbolic",48)


def transparent(window):
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        window.set_visual(visual)
    window.set_app_paintable(True)
    style(window,"frost-root")


def layer(window, monitor, namespace, keyboard=False, side=None):
    transparent(window)
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window,namespace)
    GtkLayerShell.set_monitor(window,monitor)
    GtkLayerShell.set_layer(window,GtkLayerShell.Layer.OVERLAY if keyboard else GtkLayerShell.Layer.TOP)
    GtkLayerShell.set_anchor(window,GtkLayerShell.Edge.TOP,True)
    GtkLayerShell.set_margin(window,GtkLayerShell.Edge.TOP,62 if keyboard else 10)
    GtkLayerShell.set_keyboard_mode(window,GtkLayerShell.KeyboardMode.EXCLUSIVE if keyboard else GtkLayerShell.KeyboardMode.NONE)
    GtkLayerShell.set_exclusive_zone(window,-1 if keyboard else 0)
    if side:
        edge = GtkLayerShell.Edge.LEFT if side=="left" else GtkLayerShell.Edge.RIGHT
        GtkLayerShell.set_anchor(window,edge,True)
        GtkLayerShell.set_margin(window,edge,12)


class Popup:
    def __init__(self, shell, title, monitor=None, side=None, hover=False):
        self.shell = shell
        self.hover = hover
        self.closed = False
        self.on_close = None
        self.window = Gtk.Window(title=title)
        self.window.set_resizable(False)
        self.body = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12),"popup")
        self.window.add(self.body)
        monitor = monitor or shell.current_monitor()
        layer(self.window,monitor,"frost-popup",not hover,side)
        if hover:
            GtkLayerShell.set_layer(self.window,GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_margin(self.window,GtkLayerShell.Edge.TOP,54)
            self.window.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.window.connect("enter-notify-event",lambda *_: self.keep_open())
            self.window.connect("leave-notify-event",lambda *_: self.delay_close())
        else:
            self.window.connect("key-press-event",self.key)
        self.window.connect("destroy",lambda *_: self.cleanup())
        self.close_timer = None

    def key(self, window, event):
        if event.keyval in (Gdk.KEY_Escape,Gdk.KEY_F13):
            self.close()
            return True
        return False

    def title(self, title, detail=None):
        label = style(Gtk.Label(label=title,xalign=0),"heading")
        self.body.pack_start(label,False,False,0)
        if detail:
            label = style(Gtk.Label(label=detail,xalign=0),"muted")
            label.set_line_wrap(True)
            self.body.pack_start(label,False,False,0)

    def show(self):
        self.window.show_all()
        self.window.present()

    def close(self):
        if not self.closed:
            self.window.destroy()

    def cleanup(self):
        if self.closed:
            return
        self.closed = True
        self.keep_open()
        if self.on_close:
            self.on_close()
        if self.shell.popup is self:
            self.shell.popup = None

    def keep_open(self):
        if self.close_timer:
            GLib.source_remove(self.close_timer)
            self.close_timer = None
        return False

    def delay_close(self):
        self.keep_open()
        def close():
            self.close_timer = None
            self.close()
            return False
        self.close_timer = GLib.timeout_add(350,close)
        return False


class Island:
    def __init__(self,shell,monitor,side):
        self.shell,self.monitor,self.side = shell,monitor,side
        self.window = Gtk.Window(title="Frost " + side)
        self.window.set_resizable(False)
        layer(self.window,monitor,"frost-panel",side=side if side!="center" else None)
        self.box = style(Gtk.Box(spacing=2),"island")
        self.box.set_size_request(-1,40)
        self.window.add(self.box)
        if side=="center":
            GtkLayerShell.set_exclusive_zone(self.window,58)
            self.clock = style(Gtk.Label(),"clock")
            self.box.pack_start(self.clock,False,False,0)
        elif side=="left":
            self.logo = Gtk.Image()
            self.os = style(Gtk.Button(),"icon-button","os-button")
            self.os.add(self.logo)
            self.os.set_tooltip_text("Applications · Super")
            self.os.connect("clicked",lambda *_: shell.toggle("launcher",monitor))
            self.box.pack_start(self.os,False,False,0)
            self.workspaces = style(Gtk.Box(spacing=0),"workspaces")
            self.box.pack_start(self.workspaces,False,False,0)
            self.music = style(Gtk.Button(),"media-button")
            music_box = Gtk.Box(spacing=7)
            music_box.pack_start(icon("audio-x-generic-symbolic",16),False,False,0)
            self.track = Gtk.Label(label="Spotify")
            self.track.set_xalign(0)
            music_box.pack_start(self.track,False,False,0)
            self.music.add(music_box)
            self.music.set_tooltip_text("Media controls")
            self.music.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.music.connect("enter-notify-event",self.music_enter)
            self.music.connect("leave-notify-event",self.music_leave)
            self.music.connect("clicked",lambda *_: shell.media_popup(monitor))
            self.box.pack_start(self.music,False,False,0)
            self.workspace_signature = None
        else:
            if shell.tray:
                self.box.pack_start(shell.tray.box(),False,False,0)
            self.bell = button("preferences-system-notifications-symbolic","Notifications",lambda:spawn(["swaync-client","-t","-sw"]))
            self.mode = button("weather-clear-night-symbolic","Switch light / dark · Super+O",lambda:thread(shell.change_mode))
            self.wall = button("preferences-desktop-wallpaper-symbolic","Wallpapers",lambda:shell.toggle("wallpaper",monitor))
            self.wifi = button("network-wireless-signal-none-symbolic","Wi-Fi",lambda:shell.toggle("wifi",monitor))
            self.audio = button("audio-volume-high-symbolic","Sound",lambda:spawn(["pavucontrol"]))
            self.audio.add_events(Gdk.EventMask.SCROLL_MASK|Gdk.EventMask.BUTTON_PRESS_MASK)
            self.audio.connect("scroll-event",self.volume_scroll)
            self.audio.connect("button-press-event",self.audio_middle)
            self.battery = button("battery-level-80-symbolic","Battery",lambda:shell.toggle("battery",monitor))
            self.power = button("system-shutdown-symbolic","Power",lambda:shell.toggle("power",monitor))
            for b in (self.bell,self.mode,self.wall,self.wifi,self.audio,self.battery,self.power):
                self.box.pack_start(b,False,False,0)
        self.window.show_all()

    def music_enter(self,*_):
        if self.shell.popup and self.shell.popup.hover:
            self.shell.popup.keep_open()
        elif not self.shell.popup:
            self.shell.media_popup(self.monitor)
        return False

    def music_leave(self,*_):
        if self.shell.popup and self.shell.popup.hover:
            self.shell.popup.delay_close()
        return False

    def volume_scroll(self,widget,event):
        up = event.direction == Gdk.ScrollDirection.UP or (event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y<0)
        spawn(["wpctl","set-volume","-l","1.0","@DEFAULT_AUDIO_SINK@","3%+" if up else "3%-"])
        return True

    def audio_middle(self,widget,event):
        if event.button==2:
            spawn(["wpctl","set-mute","@DEFAULT_AUDIO_SINK@","toggle"])
            return True
        return False

    def update(self,snapshot):
        name = self.shell.monitor_name(self.monitor)
        hidden = name in snapshot.get('fullscreen',set()) or snapshot.get('global_fullscreen',False)
        if hidden:
            if self.side=="center":
                GtkLayerShell.set_exclusive_zone(self.window,0)
            self.window.hide()
            return
        self.window.show()
        if self.side=="center":
            GtkLayerShell.set_exclusive_zone(self.window,58)
            now = datetime.datetime.now()
            self.clock.set_text(f"{now:%H:%M} {calendar.day_abbr[now.weekday()]}. {now.day:02} {calendar.month_abbr[now.month]}")
        elif self.side=="left":
            self.update_workspaces(snapshot,name)
            title = snapshot.get('media',{}).get('title','')
            artist = snapshot.get('media',{}).get('artist','')
            text = f"{artist} — {title}" if artist and title else title or "Spotify"
            # Leave room for a centered date and a full right-hand utility island.
            count = len(self.workspaces.get_children())
            width = self.monitor.get_geometry().width
            limit = max(8,min(26,int((width/2-210-38-count*26)/8)))
            if len(text)>limit:
                cycle = text + "     "
                offset = int(time.monotonic()/0.32)%len(cycle)
                text = (cycle+cycle)[offset:offset+limit]
            self.track.set_text(text)
            self.track.set_width_chars(limit)
        else:
            s = snapshot
            signal = s.get('wifi_signal',0)
            level = 'excellent' if signal>=80 else 'good' if signal>=55 else 'ok' if signal>=30 else 'weak' if signal>0 else 'none'
            self.wifi.get_child().set_from_icon_name('network-wireless-signal-'+level+'-symbolic',Gtk.IconSize.MENU)
            self.wifi.set_tooltip_text(s.get('wifi_name') or 'Wi-Fi disconnected')
            volume = s.get('volume',0)
            muted = s.get('muted',False)
            self.audio.get_child().set_from_icon_name('audio-volume-'+('muted' if muted else 'high' if volume>65 else 'medium' if volume>25 else 'low')+'-symbolic',Gtk.IconSize.MENU)
            self.audio.set_tooltip_text(f"{'Muted · ' if muted else ''}{volume}% · click for sound settings")
            battery = s.get('battery',{})
            percent = battery.get('percent',0)
            self.battery.get_child().set_from_icon_name(f"battery-level-{min(100,int(percent/10)*10)}{'-charging' if battery.get('status')=='Charging' else ''}-symbolic",Gtk.IconSize.MENU)
            self.battery.set_tooltip_text(f"{percent}% · {battery.get('status','Battery unavailable')}")
            p = read_json(GENERATED/'palette.json',{'mode':'dark'})
            self.mode.get_child().set_from_icon_name('weather-clear-symbolic' if p['mode']=='dark' else 'weather-clear-night-symbolic',Gtk.IconSize.MENU)
            self.bell.set_tooltip_text(f"Notifications · {s.get('notification_count','0')} · {'Do Not Disturb on' if s.get('dnd') else 'Do Not Disturb off'}")
            self.bell.get_child().set_from_icon_name('notifications-disabled-symbolic' if s.get('dnd') else 'preferences-system-notifications-symbolic',Gtk.IconSize.MENU)

    def update_workspaces(self,snapshot,name):
        all_workspaces = snapshot.get('workspaces',[])
        # At least four numbered circles on every output; existing workspaces on
        # any output stay represented and switch correctly when clicked.
        existing = {w['name']:w for w in all_workspaces}
        names = set(existing) | {str(i) for i in range(1,settings()['minimum_workspaces']+1)}
        def sort_key(n):
            number = existing.get(n,{}).get('num',int(n) if n.isdigit() else -1)
            return (number<0, number if number>=0 else 0, n)
        signature = tuple((n,existing.get(n,{}).get('focused'),existing.get(n,{}).get('visible'),
                           existing.get(n,{}).get('output')) for n in sorted(names,key=sort_key))
        if signature==self.workspace_signature:
            return
        self.workspace_signature = signature
        for child in self.workspaces.get_children():
            child.destroy()
        for n, focused, visible, output in signature:
            b = style(Gtk.Button(),"workspace")
            dot = style(Gtk.Label(label="●"),"workspace-dot")
            if n in snapshot.get('occupied',set()):
                style(b,"occupied")
            if focused or (visible and output==name):
                style(b,"focused")
            b.add(dot)
            b.set_tooltip_text("Workspace " + n)
            b.connect("clicked",lambda _,n=n:command("workspace "+quote(n)))
            self.workspaces.pack_start(b,False,False,0)
        self.workspaces.show_all()


class WallpaperPicker(Popup):
    def __init__(self,shell,monitor=None):
        super().__init__(shell,"Wallpapers",monitor)
        self.original = state()
        self.committed = False
        self.chosen = None
        self.preview_queue = queue.Queue()
        self.paths = []
        self.cards = []
        folder = Path(settings()['wallpapers']).expanduser()
        folder.mkdir(parents=True,exist_ok=True)
        supported = {'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'}
        self.paths = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in supported),key=lambda p:p.name.casefold())
        self.title("Wallpapers","Arrow keys or scroll to preview · Enter to keep · Esc to restore")
        self.caption = style(Gtk.Label(label=str(folder),xalign=0),"muted")
        self.caption.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.body.pack_start(self.caption,False,False,0)
        monitor = monitor or shell.current_monitor()
        width = min(780,monitor.get_geometry().width-80)
        height = min(490,monitor.get_geometry().height-180)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_size_request(width,height)
        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.flow.set_max_children_per_line(3)
        self.flow.set_min_children_per_line(3)
        self.flow.set_row_spacing(10)
        self.flow.set_column_spacing(10)
        self.flow.set_activate_on_single_click(False)
        self.flow.connect('selected-children-changed',self.selected)
        self.flow.connect('child-activated',lambda *_:self.commit())
        self.scroller.add(self.flow)
        self.scroller.connect('scroll-event',self.scroll)
        self.body.pack_start(self.scroller,True,True,0)
        if self.paths:
            self.scroller.set_size_request(width,min(height,((len(self.paths)+2)//3)*175))
        for path in self.paths:
            card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=7),"wallpaper-card")
            preview = Gtk.Image()
            preview.set_size_request(int((width-60)/3),114)
            card.pack_start(preview,False,False,0)
            label = Gtk.Label(label=path.stem)
            label.set_max_width_chars(23)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            card.pack_start(label,False,False,0)
            self.flow.add(card)
            self.cards.append(preview)
        if not self.paths:
            label = Gtk.Label(label="Add your images to this folder, then reopen the picker.")
            self.body.pack_start(label,False,False,0)
        controls = Gtk.Box(spacing=8)
        controls.pack_end(text_button("Keep wallpaper",self.commit,"primary"),False,False,0)
        controls.pack_end(text_button("Cancel",self.close),False,False,0)
        self.body.pack_start(controls,False,False,0)
        self.on_close = self.stop
        thread(self.load_thumbnails)
        thread(self.preview_worker)
        self.show()
        if self.paths:
            current = self.original.get('wallpaper')
            selected = next((i for i,p in enumerate(self.paths) if str(p.resolve())==current),0)
            self.flow.select_child(self.flow.get_child_at_index(selected))
            self.flow.grab_focus()

    def load_thumbnails(self):
        from PIL import Image, ImageOps
        for i,path in enumerate(self.paths):
            if self.closed:
                break
            try:
                stat = path.stat()
                key = hashlib.sha256(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
                thumb = CACHE/'thumbnails'/(key+'.png')
                if not thumb.exists():
                    thumb.parent.mkdir(parents=True,exist_ok=True)
                    with Image.open(path) as im:
                        im = ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'),(440,240))
                        im.save(thumb)
                later(self.set_thumbnail,i,thumb)
            except (OSError,ValueError):
                pass

    def set_thumbnail(self,i,path):
        if not self.closed:
            self.cards[i].set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),220,120,True))

    def selected(self,*_):
        selection = self.flow.get_selected_children()
        if selection:
            index = selection[0].get_index()
            self.chosen = self.paths[index]
            self.caption.set_text(self.chosen.name)
            self.preview_queue.put(("preview",self.chosen))

    def scroll(self,widget,event):
        if not self.paths:
            return False
        if event.direction==Gdk.ScrollDirection.SMOOTH:
            delta = getattr(self,'scroll_delta',0)+event.delta_y
            self.scroll_delta = delta
            if abs(delta)<1:
                return True
            step = 1 if delta>0 else -1
            self.scroll_delta = 0
        else:
            step = -1 if event.direction==Gdk.ScrollDirection.UP else 1
        selected = self.flow.get_selected_children()
        index = selected[0].get_index() if selected else 0
        child = self.flow.get_child_at_index(max(0,min(len(self.paths)-1,index+step)))
        self.flow.select_child(child)
        child.grab_focus()
        return True

    def key(self,window,event):
        if event.keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter):
            self.commit()
            return True
        return super().key(window,event)

    def commit(self):
        if self.chosen:
            self.committed = True
        self.close()

    def stop(self):
        self.preview_queue.put(("commit" if self.committed else "restore",self.chosen))

    def preview_worker(self):
        while True:
            kind,path = self.preview_queue.get()
            # Skip obsolete requests while navigating rapidly.
            while not self.preview_queue.empty() and kind=='preview':
                kind,path = self.preview_queue.get()
            try:
                if kind=='preview':
                    theme.apply(str(path),self.original['mode'],persist=False)
                elif kind=='commit':
                    theme.apply(str(path),self.original['mode'],persist=True)
                    return
                else:
                    theme.apply(self.original.get('wallpaper'),self.original['mode'],persist=True)
                    if not self.original.get('wallpaper'):
                        command('output * bg '+theme.palette('#91b6a4',self.original['mode'])['background']+' solid_color')
                    return
            except Exception as error:
                later(self.preview_error,str(error))
                if kind!='preview':
                    return

    def preview_error(self,message):
        if not self.closed:
            self.caption.set_text("Could not load image: " + message)
        else:
            notify("Wallpaper could not be applied",message)


class Shell:
    def __init__(self):
        self.popup = None
        self.snapshot = {}
        self.islands = []
        self.running = True
        self.style_provider = Gtk.CssProvider()
        self.tray = Tray()
        self.load_css()
        self.palette_stamp = None
        self.display = Gdk.Display.get_default()
        self.display.connect('monitor-added',lambda *_:self.rebuild())
        self.display.connect('monitor-removed',lambda *_:self.rebuild())
        self.rebuild()
        thread(self.poll)
        thread(self.events)
        thread(self.server)
        GLib.timeout_add(320,self.tick)

    def current_monitor(self):
        focused = next((w['output'] for w in self.snapshot.get('workspaces',[]) if w.get('focused')),None)
        for i in range(self.display.get_n_monitors()):
            monitor = self.display.get_monitor(i)
            if self.monitor_name(monitor)==focused:
                return monitor
        return self.display.get_primary_monitor() or self.display.get_monitor(0)

    def monitor_name(self,monitor):
        geo = monitor.get_geometry()
        for output in self.snapshot.get('outputs',[]):
            r = output.get('rect',{})
            if r.get('x')==geo.x and r.get('y')==geo.y:
                return output['name']
        # Single-output fallback before the first snapshot.
        return (self.snapshot.get('outputs') or [{}])[0].get('name','')

    def rebuild(self):
        for island in self.islands:
            island.window.destroy()
        self.islands = []
        for i in range(self.display.get_n_monitors()):
            for side in ('left','center','right'):
                self.islands.append(Island(self,self.display.get_monitor(i),side))

    def load_css(self):
        colors = (GENERATED/'colors.css').read_text()
        base = (FROST/'style.css').read_text()
        self.style_provider.load_from_data((colors+'\n'+base).encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),self.style_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1)
        p = read_json(GENERATED/'palette.json',{'mode':'dark'})
        Gtk.Settings.get_default().set_property('gtk-icon-theme-name','Papirus-Dark' if p['mode']=='dark' else 'Papirus-Light')
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme',p['mode']=='dark')

    def tick(self):
        try:
            stamp = (GENERATED/'colors.css').stat().st_mtime_ns
            if stamp!=self.palette_stamp:
                self.palette_stamp = stamp
                self.load_css()
                for island in self.islands:
                    if island.side=='left':
                        path = GENERATED/'void.svg'
                        if path.exists():
                            island.logo.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),23,23,True))
                        else:
                            island.logo.set_from_icon_name('start-here-symbolic',Gtk.IconSize.MENU)
            for island in self.islands:
                island.update(self.snapshot)
            if self.popup and getattr(self.popup,'refresh',None):
                self.popup.refresh()
        except Exception:
            traceback.print_exc()
        return self.running

    def poll(self):
        count = 0
        while self.running:
            try:
                current = dict(self.snapshot)
                current['workspaces'] = ipc(1)
                current['outputs'] = [o for o in ipc(3) if o.get('active')]
                current.update(self.tree_state(ipc(4),current['workspaces']))
                volume = run(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@']).split()
                current['volume'] = round(float(volume[1])*100) if len(volume)>1 else 0
                current['muted'] = '[MUTED]' in volume
                metadata = run(['playerctl','--player=spotify,%any','metadata','--format',
                                '{{artist}}\x1f{{title}}\x1f{{mpris:length}}\x1f{{status}}'])
                parts = metadata.split('\x1f')
                if len(parts)==4:
                    try:
                        length = float(parts[2] or 0)/1000000
                    except ValueError:
                        length = 0
                    current['media'] = dict(artist=parts[0],title=parts[1],length=length,status=parts[3],
                        position=float(run(['playerctl','--player=spotify,%any','position']) or 0))
                else:
                    current['media'] = {}
                if count%4==0:
                    wireless = run(['nmcli','-t','--escape','no','-f','IN-USE,SIGNAL,SSID','device','wifi','list','--rescan','no'])
                    active = next((line.split(':',2) for line in wireless.splitlines() if line.startswith('*:')),None)
                    current['wifi_signal'] = int(active[1]) if active else 0
                    current['wifi_name'] = active[2] if active else ''
                    current['battery'] = self.battery_state()
                    current['notification_count'] = run(['swaync-client','-c']) or '0'
                    current['dnd'] = run(['swaync-client','-D']).lower()=='true'
                self.snapshot = current
                count += 1
            except (OSError,ValueError,KeyError,ConnectionError):
                pass
            # Background wait; GTK stays responsive to input and commands.
            for _ in range(10):
                if not self.running:
                    return
                time.sleep(.2)

    def tree_state(self,tree,workspaces=None):
        fullscreen = set()
        occupied = set()
        for output in tree.get('nodes',[]):
            for workspace in output.get('nodes',[]):
                if workspace.get('type')!='workspace':
                    continue
                if any(n.get('app_id') or n.get('window') for n in walk(workspace)):
                    occupied.add(workspace['name'])
                visible = any(w.get('visible') and w['name']==workspace['name'] for w in (workspaces if workspaces is not None else self.snapshot.get('workspaces',[])))
                if visible and any(n.get('fullscreen_mode') for n in walk(workspace)):
                    fullscreen.add(output['name'])
        return dict(fullscreen=fullscreen,occupied=occupied,global_fullscreen=any(n.get('fullscreen_mode')==2 for n in walk(tree)))

    @staticmethod
    def battery_state():
        for path in Path('/sys/class/power_supply').glob('*'):
            try:
                if (path/'type').read_text().strip()=='Battery':
                    return dict(percent=int((path/'capacity').read_text()),status=(path/'status').read_text().strip())
            except (OSError,ValueError):
                pass
        return {}

    def events(self):
        while self.running:
            try:
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.connect(os.environ['SWAYSOCK'])
                    payload = b'["window","workspace","output","shutdown"]'
                    sock.sendall(b'i3-ipc'+struct.pack('=II',len(payload),2)+payload)
                    receive(sock)
                    while self.running:
                        kind,event = receive(sock)
                        if kind==0x80000006 and event.get('change')=='exit':
                            self.running=False
                            later(Gtk.main_quit)
                            return
                        try:
                            current = dict(self.snapshot)
                            current['workspaces'] = ipc(1)
                            tree = ipc(4)
                            current.update(self.tree_state(tree,current['workspaces']))
                            self.snapshot = current
                            if kind==0x80000003 and event.get('change') in ('focus','new','floating'):
                                self.autotile(tree)
                        except (OSError,KeyError,ValueError,ConnectionError):
                            pass
            except (OSError,KeyError,ValueError,ConnectionError):
                time.sleep(1)

    @staticmethod
    def autotile(tree):
        for node in walk(tree):
            if node.get('focused') and (node.get('app_id') or node.get('window')):
                if node.get('floating') in ('user_on','auto_on') or node.get('fullscreen_mode'):
                    return
                rect = node['rect']
                command(f"[con_id={node['id']}] split{'h' if rect['width']>=rect['height'] else 'v'}")
                return

    def server(self):
        path = RUNTIME/'control.sock'
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(path))
            os.chmod(path,0o600)
            sock.listen(5)
            sock.settimeout(1)
            while self.running:
                try:
                    conn,_ = sock.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(1)
                    try:
                        action = conn.recv(4096).decode().strip()
                        if action in ('launcher','wallpaper','wifi','battery','power','clipboard','close'):
                            later(self.toggle,action)
                    except (OSError,UnicodeError):
                        pass
        path.unlink(missing_ok=True)

    def toggle(self,action,monitor=None):
        if self.popup:
            previous = self.popup.window.get_title().lower()
            self.popup.close()
            if action=='close' or (action=='wallpaper' and previous=='wallpapers') or previous==action or (action=='launcher' and previous=='applications'):
                return
        if action=='wallpaper':
            self.popup = WallpaperPicker(self,monitor)
        elif action=='launcher':
            self.launcher(monitor)
        elif action=='power':
            self.power(monitor)
        elif action=='wifi':
            self.wifi(monitor)
        elif action=='battery':
            self.battery(monitor)
        elif action=='clipboard':
            self.clipboard(monitor)

    def change_mode(self):
        try:
            theme.apply(mode='light' if state()['mode']=='dark' else 'dark')
        except Exception as error:
            notify('Could not change theme',str(error))

    def launcher(self,monitor):
        p = Popup(self,'Applications',monitor,side='left')
        self.popup = p
        p.title('Applications')
        entry = Gtk.SearchEntry(placeholder_text='Open an application…')
        p.body.pack_start(entry,False,False,0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(440,420)
        scroller.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        apps = Gtk.ListBox()
        apps.set_selection_mode(Gtk.SelectionMode.SINGLE)
        rows = []
        for app in sorted(Gio.AppInfo.get_all(),key=lambda a:a.get_display_name().casefold()):
            if not app.should_show():
                continue
            row = Gtk.ListBoxRow()
            box = style(Gtk.Box(spacing=14),'app-row')
            image = Gtk.Image.new_from_gicon(app.get_icon(),Gtk.IconSize.DND) if app.get_icon() else icon('application-x-executable',32)
            box.pack_start(image,False,False,0)
            box.pack_start(Gtk.Label(label=app.get_display_name(),xalign=0),True,True,0)
            row.add(box)
            row.app = app
            row.search = (app.get_display_name()+' '+(app.get_executable() or '')).casefold()
            apps.add(row)
            rows.append(row)
        def launch(row):
            if not row:
                return
            try:
                row.app.launch([],Gdk.Display.get_default().get_app_launch_context())
            except GLib.Error as error:
                notify('Could not open application',str(error))
            p.close()
        def filtered(*_):
            term=entry.get_text().casefold()
            for row in rows:
                row.set_visible(term in row.search)
            first=next((row for row in rows if row.get_visible()),None)
            if first:
                apps.select_row(first)
        def keys(widget,event):
            if event.keyval==Gdk.KEY_Down:
                selected=apps.get_selected_row()
                visible=[r for r in rows if r.get_visible()]
                if visible:
                    selected=visible[min(len(visible)-1,visible.index(selected)+1)] if selected in visible else visible[0]
                    apps.select_row(selected)
                    selected.grab_focus()
                return True
            return False
        entry.connect('search-changed',filtered)
        entry.connect('activate',lambda *_:launch(apps.get_selected_row()))
        entry.connect('key-press-event',keys)
        apps.connect('row-activated',lambda _,row:launch(row))
        scroller.add(apps)
        p.body.pack_start(scroller,True,True,0)
        p.show()
        filtered()
        entry.grab_focus()

    def media_popup(self,monitor):
        if self.popup:
            if self.popup.hover:
                self.popup.keep_open()
            return
        p = Popup(self,'Media',monitor,side='left',hover=True)
        self.popup = p
        owner = next((i for i in self.islands if i.side=='left' and i.monitor==monitor),None)
        if owner:
            GtkLayerShell.set_margin(p.window,GtkLayerShell.Edge.LEFT,12+owner.music.get_allocation().x)
        title = style(Gtk.Label(xalign=0),'heading')
        title.set_max_width_chars(36)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        artist = style(Gtk.Label(xalign=0),'muted')
        artist.set_max_width_chars(36)
        artist.set_ellipsize(Pango.EllipsizeMode.END)
        progress=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,1,1)
        progress.set_draw_value(False)
        progress.set_size_request(320,-1)
        times=style(Gtk.Label(xalign=1),'muted')
        controls=Gtk.Box(spacing=10,halign=Gtk.Align.CENTER)
        def media(action):
            spawn(['playerctl','--player=spotify,%any']+action)
        for name,tip,action in [('media-skip-backward-symbolic','Previous',['previous']),
                                 ('media-seek-backward-symbolic','Back 10 seconds',['position','10-'])]:
            controls.pack_start(button(name,tip,lambda a=action:media(a)),False,False,0)
        play=button('media-playback-start-symbolic','Play / pause',lambda:media(['play-pause']))
        controls.pack_start(play,False,False,0)
        for name,tip,action in [('media-seek-forward-symbolic','Forward 10 seconds',['position','10+']),
                                 ('media-skip-forward-symbolic','Next',['next'])]:
            controls.pack_start(button(name,tip,lambda a=action:media(a)),False,False,0)
        for widget in (title,artist,progress,times,controls):
            p.body.pack_start(widget,False,False,0)
        def seek(widget,event):
            media(['position',str(widget.get_value())])
            return False
        progress.connect('button-release-event',seek)
        def refresh():
            m=self.snapshot.get('media',{})
            title.set_text(m.get('title') or 'No active media')
            artist.set_text(m.get('artist') or 'Open Spotify or another MPRIS player')
            length=max(1,m.get('length',1))
            progress.set_range(0,length)
            if not progress.get_state_flags() & Gtk.StateFlags.ACTIVE:
                progress.set_value(m.get('position',0))
            def fmt(v):
                return f'{int(v)//60}:{int(v)%60:02}'
            times.set_text(fmt(m.get('position',0))+' / '+fmt(m.get('length',0)))
            play.get_child().set_from_icon_name('media-playback-pause-symbolic' if m.get('status')=='Playing' else 'media-playback-start-symbolic',Gtk.IconSize.MENU)
        p.refresh=refresh
        p.show()
        refresh()

    def wifi(self,monitor):
        p=Popup(self,'Wi-Fi',monitor,side='right')
        self.popup=p
        p.title('Wi-Fi','Choose a network. Saved networks reconnect without a password.')
        status=style(Gtk.Label(label='Scanning…',xalign=0),'muted')
        networks=Gtk.ListBox()
        scroller=Gtk.ScrolledWindow()
        scroller.set_size_request(400,240)
        scroller.add(networks)
        password=Gtk.Entry(placeholder_text='Password for a new secured network')
        password.set_visibility(False)
        p.body.pack_start(status,False,False,0)
        p.body.pack_start(scroller,True,True,0)
        p.body.pack_start(password,False,False,0)
        chosen={}
        def connected(ok,message):
            if not p.closed:
                status.set_text('Connected' if ok else message)
        def connect_network(ssid):
            if not ssid:
                return
            status.set_text('Connecting to '+ssid+'…')
            secret=password.get_text()
            def worker():
                argv=['nmcli','--wait','25','device','wifi','connect',ssid]
                if secret:
                    argv+=['password',secret]
                try:
                    result=subprocess.run(argv,capture_output=True,text=True,timeout=30)
                    later(connected,result.returncode==0,(result.stderr.strip() or 'Could not connect. Check the password.')[:180])
                except (OSError,subprocess.TimeoutExpired) as error:
                    later(connected,False,str(error))
            thread(worker)
        def selected(_,row):
            if row:
                chosen['ssid']=row.ssid
                status.set_text(row.ssid+' · Enter or Connect')
        networks.connect('row-selected',selected)
        networks.connect('row-activated',lambda _,row:connect_network(row.ssid))
        password.connect('activate',lambda *_:connect_network(chosen.get('ssid')))
        controls=Gtk.Box(spacing=8)
        controls.pack_start(text_button('Advanced',lambda:spawn(['nm-connection-editor'])),False,False,0)
        controls.pack_end(text_button('Connect',lambda:connect_network(chosen.get('ssid')),'primary'),False,False,0)
        p.body.pack_start(controls,False,False,0)
        def populated(rows):
            if p.closed:
                return
            for ssid,signal,secure,active in rows:
                row=Gtk.ListBoxRow()
                row.ssid=ssid
                box=style(Gtk.Box(spacing=10),'app-row')
                box.pack_start(icon('network-wireless-signal-excellent-symbolic' if signal>70 else 'network-wireless-signal-ok-symbolic'),False,False,0)
                label=Gtk.Label(label=ssid+(' · connected' if active else ''),xalign=0)
                label.set_max_width_chars(30)
                label.set_ellipsize(Pango.EllipsizeMode.END)
                box.pack_start(label,True,True,0)
                if secure:
                    box.pack_end(icon('network-wireless-encrypted-symbolic',14),False,False,0)
                row.add(box)
                networks.add(row)
            networks.show_all()
            status.set_text('Choose a network' if rows else 'No networks found. Check rfkill or use Advanced.')
        def scan():
            output=run(['nmcli','-t','--escape','no','-f','SSID,SIGNAL,SECURITY,IN-USE','device','wifi','list','--rescan','yes'],timeout=20)
            found={}
            for line in output.splitlines():
                parts=line.rsplit(':',3)
                if len(parts)==4 and parts[0]:
                    ssid,strength,security,active=parts
                    try:
                        value=(ssid,int(strength),security not in ('','--'),active=='*')
                        if ssid not in found or value[1]>found[ssid][1]:
                            found[ssid]=value
                    except ValueError:
                        pass
            later(populated,sorted(found.values(),key=lambda r:(not r[3],-r[1],r[0])))
        thread(scan)
        p.show()

    def battery(self,monitor):
        p=Popup(self,'Battery',monitor,side='right')
        self.popup=p
        battery=self.snapshot.get('battery',{})
        p.title('Battery',f"{battery.get('percent','?')}% · {battery.get('status','Unavailable')}")
        p.body.pack_start(Gtk.Label(label='Brightness',xalign=0),False,False,0)
        brightness=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,5,100,1)
        brightness.set_size_request(300,-1)
        current=run(['brightnessctl','-m'])
        try:
            brightness.set_value(float(current.split(',')[3].rstrip('%')))
        except (ValueError,IndexError):
            brightness.set_value(70)
        brightness.connect('button-release-event',lambda b,e:spawn(['brightnessctl','set',str(round(b.get_value()))+'%']) and False)
        brightness.connect('key-release-event',lambda b,e:spawn(['brightnessctl','set',str(round(b.get_value()))+'%']) and False)
        p.body.pack_start(brightness,False,False,0)
        p.body.pack_start(text_button('Lock screen',lambda:(p.close(),spawn(['frostctl','lock']))),False,False,0)
        p.show()

    def power(self,monitor):
        p=Popup(self,'Power',monitor,side='right')
        self.popup=p
        p.title('Power')
        for name,action in [('Lock','lock'),('Suspend','suspend'),('Log out','logout'),('Restart','reboot'),('Shut down','poweroff')]:
            def activate(action=action):
                if action in ('lock','suspend'):
                    p.close()
                    spawn(['frostctl',action])
                else:
                    for child in p.body.get_children():
                        child.destroy()
                    p.title({'logout':'Log out?','reboot':'Restart?','poweroff':'Shut down?'}[action])
                    p.body.pack_start(text_button('Confirm',lambda:(p.close(),spawn(['frostctl',action])),'primary'),False,False,0)
                    p.body.pack_start(text_button('Cancel',p.close),False,False,0)
                    p.window.show_all()
            p.body.pack_start(text_button(name,activate),False,False,0)
        p.show()

    def clipboard(self,monitor):
        p=Popup(self,'Clipboard',monitor,side='right')
        self.popup=p
        p.title('Clipboard')
        scroller=Gtk.ScrolledWindow()
        scroller.set_size_request(460,360)
        entries=Gtk.ListBox()
        for line in run(['cliphist','list']).splitlines()[:100]:
            row=Gtk.ListBoxRow()
            row.value=line
            label=Gtk.Label(label=line.split('\t',1)[-1],xalign=0)
            label.set_max_width_chars(45)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            style(label,'app-row')
            row.add(label)
            entries.add(row)
        def copy(_,row):
            def worker():
                try:
                    decoded=subprocess.run(['cliphist','decode'],input=row.value.encode(),capture_output=True,timeout=5,check=True)
                    subprocess.run(['wl-copy'],input=decoded.stdout,timeout=5,check=True)
                except (OSError,subprocess.SubprocessError):
                    notify('Could not copy clipboard item')
            thread(worker)
            p.close()
        entries.connect('row-activated',copy)
        scroller.add(entries)
        p.body.pack_start(scroller,True,True,0)
        p.show()


def main():
    Gtk.init(None)
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(RUNTIME/'panel.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        return
    # A crashed picker must not leave a temporary preview as the next session's
    # theme. Reapply the last committed selection whenever the shell starts.
    theme.apply(reload=bool(os.environ.get('SWAYSOCK')))
    shell=Shell()
    try:
        Gtk.main()
    finally:
        shell.running=False
        if shell.popup:
            shell.popup.close()


if __name__=='__main__':
    main()
