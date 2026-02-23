#!/usr/bin/env python3
import sys
import os
import subprocess
import csv
import re
import threading
import json
import math
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gio, GLib, Gdk, Adw, Pango, PangoCairo

# --- Config Logic ---
CONFIG_FILE = os.path.expanduser("~/.config/ass-profiler/config.json")

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except Exception:
        pass

# --- Data Structures ---
frame_stat_names = ['time','total_image_size', 'largest_image_size','image_count','time_benchmark']
from collections import namedtuple
Frame_Statistics = namedtuple('Frame_Statistics', frame_stat_names)

# --- Helper Functions ---
def str2s(hmrstr):
    mre = re.match("([0-9]+):([0-9]{2}):([0-9.]+)", hmrstr)
    if not mre: return 0
    h, m, s = int(mre[1]), int(mre[2]), float(mre[3])
    return (h * 3600) + (m * 60) + s

def format_time(sec):
    sec = max(0, sec)
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"

def format_bytes(n):
    n = max(0, n)
    if n >= 10**9: return f"{n/10**9:.1f} GB"
    if n >= 10**6: return f"{n/10**6:.1f} MB"
    if n >= 10**3: return f"{n/10**3:.1f} kB"
    return f"{int(n)} B"

# --- Native GTK4 Graph Widget ---

class ProfilerGraph(Gtk.DrawingArea):
    def __init__(self, data_points, title, y_label_type='count'):
        super().__init__()
        self.data = data_points 
        self.title = title
        self.y_label_type = y_label_type 
        
        # View State
        if data_points:
            self.min_x = 0
            self.max_x = max(p[0] for p in data_points)
            self.min_y = 0
            raw_max_y = max(p[1] for p in data_points) if data_points else 1
            self.max_y = 60 if y_label_type == 'ms' else raw_max_y * 1.2
        else:
            self.min_x, self.max_x, self.min_y, self.max_y = 0, 100, 0, 100

        self.set_draw_func(self.on_draw)
        
        # Interaction Controllers
        scroll_controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect("scroll", self.on_scroll)
        self.add_controller(scroll_controller)
        
        drag_controller = Gtk.GestureDrag.new()
        drag_controller.connect("drag-begin", self.on_drag_begin)
        drag_controller.connect("drag-update", self.on_drag_update)
        self.add_controller(drag_controller)

    def on_draw(self, area, cr, width, height):
        # Dynamically fetch theme colors from Adwaita Style Manager
        style_manager = Adw.StyleManager.get_default()
        is_dark = style_manager.get_dark()
        
        if is_dark:
            # Official Adwaita Dark Palette
            bg_color = (0.141, 0.141, 0.141)    # window_bg_color
            grid_color = (0.22, 0.22, 0.22)     # Subtle grid
            text_color = (1.0, 1.0, 1.0)        # window_fg_color
            line_color = (0.21, 0.52, 0.89)     # accent_bg_color (blue)
            limit_color = (0.75, 0.15, 0.15)    # error_bg_color (red)
        else:
            # Official Adwaita Light Palette
            bg_color = (1.0, 1.0, 1.0)          # window_bg_color
            grid_color = (0.92, 0.92, 0.92)     # Subtle grid
            text_color = (0.0, 0.0, 0.0)        # window_fg_color
            line_color = (0.11, 0.44, 0.82)     # accent_bg_color
            limit_color = (0.75, 0.15, 0.15)    # error_bg_color

        # Clear Background
        cr.set_source_rgb(*bg_color)
        cr.paint()

        padding_l, padding_r, padding_t, padding_b = 75, 20, 45, 45
        graph_w = width - padding_l - padding_r
        graph_h = height - padding_t - padding_b

        if graph_w <= 0 or graph_h <= 0 or not self.data:
            return

        # Clamp view range (Never show negative)
        self.min_x = max(0, self.min_x)
        self.min_y = max(0, self.min_y)
        if self.max_x <= self.min_x: self.max_x = self.min_x + 1
        if self.max_y <= self.min_y: self.max_y = self.min_y + 1

        # Coordinate Mappers
        def to_screen(x, y):
            sx = padding_l + ((x - self.min_x) / (self.max_x - self.min_x)) * graph_w
            sy = padding_t + (1 - (y - self.min_y) / (self.max_y - self.min_y)) * graph_h
            return sx, sy

        # Draw Grid & Labels
        cr.set_line_width(1.0)
        
        # Y Axis Ticks
        steps = 5
        for i in range(steps + 1):
            y_val = self.min_y + (self.max_y - self.min_y) * (i / steps)
            sx, sy = to_screen(self.min_x, y_val)
            
            cr.set_source_rgb(*grid_color)
            cr.move_to(padding_l, sy)
            cr.line_to(width - padding_r, sy)
            cr.stroke()
            
            # Y Label
            label_text = ""
            if self.y_label_type == 'bytes': label_text = format_bytes(y_val)
            elif self.y_label_type == 'ms': label_text = f"{int(y_val)}ms"
            else: label_text = str(int(y_val))
            
            self.draw_text(cr, label_text, padding_l - 10, sy, text_color, align='right')

        # X Axis Ticks (Every 60s)
        start_tick = math.floor(self.min_x / 60) * 60
        tick = start_tick
        while tick <= self.max_x:
            sx, sy = to_screen(tick, self.min_y)
            if sx >= padding_l:
                cr.set_source_rgb(*grid_color)
                cr.move_to(sx, padding_t)
                cr.line_to(sx, height - padding_b)
                cr.stroke()
                self.draw_text(cr, format_time(tick), sx, height - padding_b + 5, text_color, align='center')
            tick += 60

        # Draw Title
        self.draw_text(cr, self.title, width / 2, 15, text_color, align='center', bold=True)

        # Clipping for Data
        cr.save()
        cr.rectangle(padding_l, padding_t, graph_w, graph_h)
        cr.clip()

        # Draw Benchmark lines for ms graph
        if self.y_label_type == 'ms':
            # 24fps limit (~41.6ms)
            _, sy_limit = to_screen(self.min_x, 1000/23.976)
            cr.set_source_rgb(*limit_color)
            cr.set_dash([4.0, 4.0])
            cr.move_to(padding_l, sy_limit)
            cr.line_to(width-padding_r, sy_limit)
            cr.stroke()
            cr.set_dash([])

        # Draw Data Line
        cr.set_source_rgb(*line_color)
        cr.set_line_width(1.8)
        first = True
        
        for x, y in self.data:
            if x < self.min_x - (self.max_x - self.min_x): continue
            if x > self.max_x + (self.max_x - self.min_x): break
            
            sx, sy = to_screen(x, y)
            if first:
                cr.move_to(sx, sy)
                first = False
            else:
                cr.line_to(sx, sy)
        cr.stroke()
        cr.restore()

    def draw_text(self, cr, text, x, y, color, align='left', bold=False):
        layout = self.create_pango_layout(text)
        desc = Pango.FontDescription.from_string("Sans 9")
        if bold: desc.set_weight(Pango.Weight.BOLD)
        layout.set_font_description(desc)
        
        cr.set_source_rgb(*color)
        logical_rect = layout.get_pixel_extents()[1]
        
        tx, ty = x, y
        if align == 'center': tx -= logical_rect.width / 2
        elif align == 'right': tx -= logical_rect.width
        
        cr.move_to(tx, ty - logical_rect.height / 2 if align != 'center' else ty)
        PangoCairo.show_layout(cr, layout)

    def on_scroll(self, controller, dx, dy):
        state = controller.get_current_event().get_modifier_state()
        zoom_factor = 1.15
        pan_factor = 0.1
        range_x = self.max_x - self.min_x
        
        if state & Gdk.ModifierType.CONTROL_MASK:
            # Zoom X (centered)
            scale = zoom_factor if dy > 0 else (1/zoom_factor)
            new_range = range_x * scale
            mid_x = (self.min_x + self.max_x) / 2
            self.min_x = max(0, mid_x - new_range / 2)
            self.max_x = self.min_x + new_range
        elif state & Gdk.ModifierType.SHIFT_MASK:
            # Zoom Y: Lock bottom at 0, only scale the top
            scale = zoom_factor if dy > 0 else (1/zoom_factor)
            self.max_y = max(0.01, self.max_y * scale)
            self.min_y = 0
        else:
            # Pan X
            shift = range_x * pan_factor * (1 if dy > 0 else -1)
            self.min_x = max(0, self.min_x + shift)
            self.max_x = self.min_x + range_x
            
        self.queue_draw()

    def on_drag_begin(self, gesture, start_x, start_y):
        self.drag_start_min_x = self.min_x
        self.drag_start_max_x = self.max_x
        self.drag_start_min_y = self.min_y
        self.drag_start_max_y = self.max_y

    def on_drag_update(self, gesture, offset_x, offset_y):
        width = self.get_width() - 95
        height = self.get_height() - 90
        if width <= 0 or height <= 0: return
        
        range_x = self.drag_start_max_x - self.drag_start_min_x
        range_y = self.drag_start_max_y - self.drag_start_min_y
        
        dx = -(offset_x / width) * range_x
        dy = (offset_y / height) * range_y
        
        self.min_x = max(0, self.drag_start_min_x + dx)
        self.max_x = self.min_x + range_x
        
        self.min_y = max(0, self.drag_start_min_y + dy)
        self.max_y = self.min_y + range_y
        self.queue_draw()

# --- Application Windows ---

class GraphWindow(Gtk.Window):
    def __init__(self, data_list, title):
        super().__init__(title=f"Analytics - {title}")
        self.set_default_size(950, 850)
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        times = [str2s(d.time) for d in data_list]
        series = [
            (list(zip(times, [float(d.total_image_size) for d in data_list])), 'Total Bitmap Size', 'bytes'),
            (list(zip(times, [float(d.largest_image_size) for d in data_list])), 'Largest Bitmap Size', 'bytes'),
            (list(zip(times, [float(d.image_count) for d in data_list])), 'Bitmap Counts', 'count'),
            (list(zip(times, [float(d.time_benchmark) * 1000 for d in data_list])), 'Frame Render Time', 'ms')
        ]
        
        for data, label, ltype in series:
            graph = ProfilerGraph(data, label, ltype)
            graph.set_vexpand(True)
            main_box.append(graph)

class AssProfilerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("ASS Profiler")
        self.set_default_size(400, 200)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ['top', 'bottom', 'start', 'end']:
            getattr(self.box, f"set_margin_{m}")(24)
        self.set_child(self.box)

        self.label = Gtk.Label(label="Select an .ass file to profile")
        self.box.append(self.label)

        self.button = Gtk.Button(label="Select File")
        self.button.set_halign(Gtk.Align.CENTER)
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self.on_select_file)
        self.box.append(self.button)

        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        self.box.append(self.progress)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.add_css_class("dim-label")
        self.box.append(self.status_label)

    def on_select_file(self, button):
        dialog = Gtk.FileDialog(title="Open .ass File")
        config = load_config()
        last_dir = config.get("last_directory")
        if last_dir and os.path.exists(last_dir):
            try:
                dialog.set_initial_folder(Gio.File.new_for_path(last_dir))
            except Exception: pass

        filter_ass = Gtk.FileFilter()
        filter_ass.set_name("ASS Files")
        filter_ass.add_pattern("*.ass")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_ass)
        dialog.set_filters(filters)
        dialog.open(self, None, self.on_file_dialog_open_done)

    def on_file_dialog_open_done(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                filepath = file.get_path()
                config = load_config()
                config["last_directory"] = os.path.dirname(filepath)
                save_config(config)
                self.process_file(filepath)
        except Exception: pass

    def process_file(self, filepath):
        self.status_label.set_text(f"Processing: {os.path.basename(filepath)}...")
        self.button.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0.1)
        threading.Thread(target=self.run_profiler_thread, args=(filepath,), daemon=True).start()

    def run_profiler_thread(self, filepath):
        profiler_exe = "libass_profiler.exe"
        output_csv = "output.csv"
        exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), profiler_exe)
        if not os.path.exists(exe_path): exe_path = os.path.abspath(profiler_exe)

        try:
            abs_filepath = os.path.abspath(filepath)
            wp = subprocess.run(['winepath', '-w', abs_filepath], capture_output=True, text=True, timeout=5)
            win_filepath = wp.stdout.strip() if wp.returncode == 0 else abs_filepath

            abs_out = os.path.abspath(output_csv)
            wp_out = subprocess.run(['winepath', '-w', abs_out], capture_output=True, text=True, timeout=5)
            win_out = wp_out.stdout.strip() if wp_out.returncode == 0 else output_csv

            GLib.idle_add(self.update_ui, 0.4, "Executing Wine...")
            subprocess.run(['wine', exe_path, win_filepath, win_out], capture_output=True)

            GLib.idle_add(self.update_ui, 0.8, "Loading Data...")
            data_list, title = self.load_csv(abs_out)
            
            GLib.idle_add(self.show_results, data_list, title)
        except Exception as e:
            GLib.idle_add(self.show_error, str(e))
        
        GLib.idle_add(self.reset_ui)

    def update_ui(self, fraction, status):
        self.progress.set_fraction(fraction)
        self.status_label.set_text(status)
        return False

    def show_results(self, data_list, title):
        win = GraphWindow(data_list, title)
        win.set_transient_for(self)
        win.present()
        self.status_label.set_text("Done.")
        return False

    def load_csv(self, csv_file):
        data_list = []
        with open(csv_file, newline='') as f:
            reader = csv.reader(f)
            title = next(reader)[0]
            next(reader)
            for row in reader:
                if len(row) < 5: continue
                data_list.append(Frame_Statistics(*row))
        return data_list, title

    def show_error(self, msg):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text="Error")
        dialog.props.secondary_text = msg
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.show()
        return False

    def reset_ui(self):
        self.button.set_sensitive(True)
        self.progress.set_visible(False)
        return False

class AssProfilerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.AssProfiler")
    def do_activate(self):
        AssProfilerWindow(self).present()

if __name__ == "__main__":
    AssProfilerApp().run(sys.argv)
