"""StatusNotifierItem tray and DBusMenu support using Gio, shared by all outputs.

No XEmbed bridge: contemporary Wayland/AppIndicator applications use SNI.
"""
import time
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Gdk, GdkPixbuf

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
<signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
<signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
<signal name="StatusNotifierHostRegistered"/>
</interface></node>"""


class Tray:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.items = {}
        self.boxes = []
        self.info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.registration = self.bus.register_object(
            "/StatusNotifierWatcher", self.info.interfaces[0], self.method, self.prop, None)
        self.owner = Gio.bus_own_name_on_connection(
            self.bus, WATCHER, Gio.BusNameOwnerFlags.NONE, None, None)
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                  "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                  Gio.DBusSignalFlags.NONE, self.owner_changed)
        self.bus.signal_subscribe(None, ITEM, None, None, None,
                                  Gio.DBusSignalFlags.NONE, self.item_changed)

    def box(self):
        box = Gtk.Box(spacing=2)
        box.get_style_context().add_class("tray")
        self.boxes.append(box)
        box.connect("destroy", lambda b: self.boxes.remove(b) if b in self.boxes else None)
        self.redraw()
        return box

    def signal(self, signal, identity):
        self.bus.emit_signal(None, "/StatusNotifierWatcher", WATCHER, signal,
                             GLib.Variant("(s)", (identity,)))

    def prop(self, conn, sender, path, interface, name):
        if name == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", list(self.items))
        if name == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if name == "ProtocolVersion":
            return GLib.Variant("i", 0)

    def method(self, conn, sender, path, interface, method, params, invocation):
        service = params.unpack()[0]
        if method == "RegisterStatusNotifierHost":
            invocation.return_value(None)
            return
        busname, itempath = (sender, service) if service.startswith("/") else (service, "/StatusNotifierItem")
        if not Gio.dbus_is_name(busname) or not GLib.Variant.is_object_path(itempath):
            invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", "Invalid item")
            return
        identity = busname + itempath
        self.items[identity] = dict(bus=busname, path=itempath, properties={}, owner=sender)
        self.refresh(identity)
        self.signal("StatusNotifierItemRegistered", identity)
        invocation.return_value(None)

    def owner_changed(self, conn, sender, path, interface, signal, params):
        name, old, new = params.unpack()
        if old and not new:
            for identity, item in list(self.items.items()):
                if name in (item['bus'], item['owner']):
                    self.items.pop(identity, None)
                    self.signal("StatusNotifierItemUnregistered", identity)
            self.redraw()

    def item_changed(self, conn, sender, path, interface, signal, params):
        for identity, item in self.items.items():
            if item['path'] == path and sender == item['owner']:
                self.refresh(identity)

    def refresh(self, identity):
        item = self.items.get(identity)
        if not item:
            return
        def complete(conn, result):
            try:
                props = conn.call_finish(result).unpack()[0]
                if identity in self.items:
                    self.items[identity]['properties'] = props
                    self.redraw()
            except GLib.Error:
                pass
        self.bus.call(item['bus'], item['path'], "org.freedesktop.DBus.Properties", "GetAll",
                      GLib.Variant("(s)", (ITEM,)), GLib.VariantType.new("(a{sv})"),
                      Gio.DBusCallFlags.NONE, 1500, None, complete)

    def image(self, props):
        image = Gtk.Image()
        name = props.get("AttentionIconName") if props.get("Status") == "NeedsAttention" else None
        name = name or props.get("IconName")
        if name:
            extra = props.get("IconThemePath")
            if extra and extra not in Gtk.IconTheme.get_default().get_search_path():
                Gtk.IconTheme.get_default().append_search_path(extra)
            if name.startswith("/"):
                try:
                    image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(name, 18, 18, True))
                    return image
                except GLib.Error:
                    pass
            else:
                image.set_from_icon_name(name, Gtk.IconSize.MENU)
                image.set_pixel_size(18)
                return image
        pixmaps = props.get("IconPixmap", [])
        if pixmaps:
            width, height, raw = min(pixmaps, key=lambda p: abs(p[0]-24))
            if 0 < width <= 1024 and 0 < height <= 1024 and len(raw) == width*height*4:
                raw = bytes(raw)
                rgba = bytearray(len(raw))
                for i in range(0,len(raw),4):
                    rgba[i:i+4] = raw[i+1:i+4] + raw[i:i+1]
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)),
                    GdkPixbuf.Colorspace.RGB, True, 8, width, height, width*4)
                image.set_from_pixbuf(pixbuf.scale_simple(18,18,GdkPixbuf.InterpType.BILINEAR))
                return image
        image.set_from_icon_name("application-x-executable-symbolic", Gtk.IconSize.MENU)
        return image

    def redraw(self):
        for box in self.boxes:
            for child in box.get_children():
                child.destroy()
            for identity, item in self.items.items():
                p = item['properties']
                if p.get('Status') == 'Passive':
                    continue
                button = Gtk.Button()
                button.set_relief(Gtk.ReliefStyle.NONE)
                button.add(self.image(p))
                tooltip = p.get('ToolTip', ('','',p.get('Title',''),''))
                title = tooltip[2] if len(tooltip)>2 else p.get('Title','Application')
                button.set_tooltip_text(title or p.get('Title','Application'))
                button.connect("button-press-event", self.clicked, identity)
                button.connect("scroll-event", self.scrolled, identity)
                box.pack_start(button,False,False,0)
            box.show_all()

    def call(self, item, method, params):
        self.bus.call(item['bus'], item['path'], ITEM, method, params, None,
                      Gio.DBusCallFlags.NONE, 1500, None, None)

    def clicked(self, button, event, identity):
        item = self.items.get(identity)
        if not item:
            return True
        if event.button == 3 or item['properties'].get('ItemIsMenu'):
            self.open_menu(button, event, item)
        else:
            method = "SecondaryActivate" if event.button == 2 else "Activate"
            self.call(item, method, GLib.Variant("(ii)", (int(event.x_root),int(event.y_root))))
        return True

    def scrolled(self, button, event, identity):
        if identity in self.items:
            delta = 120 if event.direction == Gdk.ScrollDirection.UP else -120
            self.call(self.items[identity], "Scroll", GLib.Variant("(is)", (delta,"vertical")))
        return True

    def open_menu(self, button, event, item):
        path = item['properties'].get('Menu')
        if not path or path == '/':
            self.call(item,"ContextMenu",GLib.Variant("(ii)",(int(event.x_root),int(event.y_root))))
            return
        # Ask the application to refresh dynamic menu contents before GetLayout.
        def layout(conn, result):
            try:
                _, root = conn.call_finish(result).unpack()
                menu = self.build_menu(item, path, root[2])
                menu.show_all()
                menu.attach_to_widget(button,None)
                menu.popup_at_widget(button,Gdk.Gravity.SOUTH_EAST,Gdk.Gravity.NORTH_EAST,event)
            except GLib.Error:
                pass
        def ready(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error:
                pass
            conn.call(item['bus'],path,MENU,"GetLayout",GLib.Variant("(iias)",(0,-1,[])),
                      None,Gio.DBusCallFlags.NONE,1500,None,layout)
        self.bus.call(item['bus'],path,MENU,"AboutToShow",GLib.Variant("(i)",(0,)),
                      None,Gio.DBusCallFlags.NONE,1500,None,ready)

    def build_menu(self, item, path, entries):
        menu = Gtk.Menu()
        for entry in entries:
            if isinstance(entry, GLib.Variant):
                entry = entry.unpack()
            ident, props, children = entry
            if not props.get('visible',True):
                continue
            if props.get('type') == 'separator':
                widget = Gtk.SeparatorMenuItem()
            elif props.get('toggle-type'):
                widget = Gtk.CheckMenuItem.new_with_mnemonic(props.get('label',''))
                widget.set_active(props.get('toggle-state',0)==1)
                widget.set_draw_as_radio(props['toggle-type']=='radio')
            else:
                widget = Gtk.MenuItem.new_with_mnemonic(props.get('label',''))
            widget.set_sensitive(props.get('enabled',True))
            if children:
                widget.set_submenu(self.build_menu(item,path,children))
            else:
                def clicked(w, ident=ident):
                    self.bus.call(item['bus'],path,MENU,"Event",
                        GLib.Variant("(isvu)",(ident,"clicked",GLib.Variant("i",0),int(time.time()*1000)&0xffffffff)),
                        None,Gio.DBusCallFlags.NONE,1500,None,None)
                widget.connect('activate',clicked)
            menu.append(widget)
        return menu
