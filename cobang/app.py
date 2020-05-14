from typing import Optional

import gi
import cairo
from logbook import Logger
from logbook.more import ColorizedStderrHandler

gi.require_version("Gtk", "3.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("GstGL", "1.0")
gi.require_version("Cheese", "3.0")
from gi.repository import Gtk, Gio, Gdk, Gst, GstBase, GstVideo, GstGL, Cheese  # noqa

from .resources import get_ui_filepath


logger = Logger(__name__)
Gst.init(None)
ColorizedStderrHandler().push_application()

# Require: gstreamer1.0-plugins-bad, gir1.2-gst-plugins-bad-1.0
# Ref:
# https://github.com/sreerenjb/gst-wayland
# https://github.com/GStreamer/gst-plugins-bad/blob/master/tests/examples/waylandsink/main.c
# https://gist.github.com/jonasl/92c1ef32cfd87047e15f5ae24c6b510e
# Some Gstreamer CLI examples
# gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! waylandsink
# gst-launch-1.0 playbin3 uri=v4l2:///dev/video0 video-sink=waylandsink


class CoBangApplication(Gtk.Application):
    window = None
    main_grid = None
    area_webcam: Optional[Gtk.Widget] = None
    old_pipeline = None
    stack_img_source: Optional[Gtk.Stack] = None
    camera_devices = {}

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, application_id="vn.hoabinh.quan.cobang", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE, **kwargs
        )

    def do_startup(self):
        Gtk.Application.do_startup(self)
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.quit_from_action)
        self.add_action(action)
        # self.old_pipeline = Gst.parse_launch("playbin3 uri=v4l2:///dev/video0 video-sink=waylandsink")
        self.gst_pipeline = Gst.Pipeline.new('main')
        gst_source = Gst.ElementFactory.make('v4l2src')
        gst_source.set_property('device', '/dev/video0')
        # gst_filter = Gst.Caps.new_empty_simple('video/x-raw')
        gst_sink = Gst.ElementFactory.make('gtksink', 'gtksink')
        area = gst_sink.get_property('widget')
        logger.debug('GtkSink widget: {}', area)
        Cheese.CameraDeviceMonitor.new_async(None, self.camera_monitor_started)
        self.camera_devices = {}
        self.gst_pipeline.add(gst_source)
        self.gst_pipeline.add(Gst.ElementFactory.make('videoconvert'))
        self.gst_pipeline.add(gst_sink)
        # gst_source.link_filtered(gst_sink, gst_filter)
        ex_pipeline: Gst.Pipeline = Gst.parse_launch('v4l2src device=/dev/video0 ! videoconvert ! gtksink')
        logger.debug('Exp: {}', ex_pipeline)
        itr = ex_pipeline.iterate_elements()
        logger.debug('Itr: {}', itr)
        itr.foreach(lambda x: print(x))
        self.gst_pipeline.iterate_elements().foreach(lambda x: print(x))

    def build_main_window(self):
        source = get_ui_filepath("main.glade")
        builder: Gtk.Builder = Gtk.Builder.new_from_file(str(source))
        handlers = self.signal_handlers_for_glade()
        builder.connect_signals(handlers)
        window: Gtk.Window = builder.get_object("main-window")
        builder.get_object("main-grid")
        window.set_application(self)
        self.set_accels_for_action("app.quit", ("<Ctrl>Q",))
        self.stack_img_source = builder.get_object("stack-img-source")
        return window

    def signal_handlers_for_glade(self):
        return {"on_area_webcam_realize": self.pass_window_to_gstreamer, "on_btn_quit_clicked": self.quit_from_widget}

    def pass_window_to_gstreamer(self, area_webcam: Gtk.DrawingArea):
        window: Gdk.Window = area_webcam.get_window()
        is_native = window.ensure_native()
        if not is_native:
            logger.error("DrawingArea {} is not a native window", area_webcam.get_name())
            return
        # https://gist.github.com/jonasl/92c1ef32cfd87047e15f5ae24c6b510e
        if window.__class__.__name__ != "GdkWaylandWindow":
            # X11
            logger.error("Implement later")
        logger.debug("Area for webcam is realized")

    def do_activate(self):
        if not self.window:
            self.window = self.build_main_window()
        self.window.present()
        logger.debug("Window {} is shown", self.window)

    def do_command_line(self, command_line):
        self.activate()
        return 0

    def camera_monitor_started(self, monitor: Cheese.CameraDeviceMonitor, result: Gio.AsyncResult):
        monitor = Cheese.CameraDeviceMonitor.new_finish(result)
        monitor.connect("added", self.on_camera_added)
        monitor.connect("removed", self.on_camera_removed)
        monitor.coldplug()

    def on_camera_added(self, monitor: Cheese.CameraDeviceMonitor, device: Cheese.CameraDevice):
        logger.info("Added {}", device)
        # GstV4l2Src type, but don't know where to import
        src: GstBase.PushSrc = device.get_src()
        loc: str = src.get_property("device")
        self.camera_devices[loc] = device
        sink = self.gst_pipeline.get_by_name('gtksink')
        area = sink.get_property('widget')
        old_area = self.stack_img_source.get_child_by_name('src_webcam')
        logger.debug('Old area: {}', old_area)
        self.stack_img_source.remove(old_area)
        self.stack_img_source.add_titled(area, 'src_webcam', 'Webcam')
        area.show()
        self.stack_img_source.set_visible_child(area)
        logger.debug('Play {}', self.gst_pipeline)
        self.gst_pipeline.set_state(Gst.State.PLAYING)

    def on_camera_removed(self, monitor: Cheese.CameraDeviceMonitor, device: Cheese.CameraDevice):
        logger.info("Removed {}", device)
        src: GstBase.PushSrc = device.get_src()
        loc: str = src.get_property("device")
        self.camera_devices.pop(loc)
        # if not self.camera_devices:
        #     self.old_pipeline.set_state(Gst.State.NULL)

    def set_rectangle_webcam_display(self, drawing_area: Gtk.DrawingArea, cr: cairo.Context, sink: Gst.Bin):
        logger.debug('Set rectangle on redraw')
        allocation = drawing_area.get_allocation()
        x, y, w, h = allocation.x, allocation.y, allocation.width, allocation.height
        logger.debug('Sink: {}', sink)
        logger.debug("Rectangle: ({}, {}), {} x {}", x, y, w, h)
        sink.set_render_rectangle(x, y, w, h)
        # Disconnect signal
        drawing_area.disconnect_by_func(self.set_rectangle_webcam_display)
        return False

    def quit_from_widget(self, widget: Gtk.Widget):
        self.quit()

    def quit_from_action(self, action, param):
        self.quit()
