#!/usr/bin/env python3
import sys
import os
import subprocess
import csv
import re
import threading
import json
import math
import hashlib
import shlex
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gio, GLib, Gdk, Adw, Pango, PangoCairo

# --- Config & Cache Paths ---
CONFIG_DIR = os.path.expanduser("~/.config/ass-profiler")
CACHE_DIR = os.path.expanduser("~/.cache/ass-profiler")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

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
            self.abs_max_x = max(p[0] for p in data_points)
            self.max_x = self.abs_max_x
            self.min_y = 0
            raw_max_y = max(p[1] for p in data_points) if data_points else 1
            self.max_y = 60 if y_label_type == 'ms' else raw_max_y * 1.2
        else:
            self.min_x, self.max_x, self.min_y, self.max_y = 0, 100, 0, 100
            self.abs_max_x = 100

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
        # Dynamically fetch theme colors
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

        cr.set_source_rgb(*bg_color)
        cr.paint()

        padding_l, padding_r, padding_t, padding_b = 75, 20, 45, 45
        graph_w = width - padding_l - padding_r
        graph_h = height - padding_t - padding_b

        if graph_w <= 0 or graph_h <= 0 or not self.data:
            return

        # Clamp view range
        self.min_x = max(0, self.min_x)
        self.max_x = min(self.abs_max_x, self.max_x)
        self.min_y = max(0, self.min_y)
        if self.max_x <= self.min_x: self.max_x = self.min_x + 0.001
        if self.max_y <= self.min_y: self.max_y = self.min_y + 1

        def to_screen(x, y):
            sx = padding_l + ((x - self.min_x) / (self.max_x - self.min_x)) * graph_w
            sy = padding_t + (1 - (y - self.min_y) / (self.max_y - self.min_y)) * graph_h
            return sx, sy

        cr.set_line_width(1.0)
        steps = 5
        for i in range(steps + 1):
            y_val = self.min_y + (self.max_y - self.min_y) * (i / steps)
            sx, sy = to_screen(self.min_x, y_val)
            cr.set_source_rgb(*grid_color)
            cr.move_to(padding_l, sy)
            cr.line_to(width - padding_r, sy)
            cr.stroke()
            
            label_text = ""
            if self.y_label_type == 'bytes': label_text = format_bytes(y_val)
            elif self.y_label_type == 'ms': label_text = f"{int(y_val)}ms"
            else: label_text = str(int(y_val))
            self.draw_text(cr, label_text, padding_l - 10, sy, text_color, align='right')

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

        self.draw_text(cr, self.title, width / 2, 15, text_color, align='center', bold=True)

        cr.save()
        cr.rectangle(padding_l, padding_t, graph_w, graph_h)
        cr.clip()

        if self.y_label_type == 'ms':
            _, sy_limit = to_screen(self.min_x, 1000/23.976)
            cr.set_source_rgb(*limit_color)
            cr.set_dash([4.0, 4.0])
            cr.move_to(padding_l, sy_limit)
            cr.line_to(width-padding_r, sy_limit)
            cr.stroke()
            cr.set_dash([])

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
        desc = Pango.FontDescription.from_string("Sans 8")
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
        range_x = self.max_x - self.min_x
        if state & Gdk.ModifierType.CONTROL_MASK:
            scale = zoom_factor if dy > 0 else (1/zoom_factor)
            new_range = min(self.abs_max_x, range_x * scale)
            mid_x = (self.min_x + self.max_x) / 2
            
            self.min_x = mid_x - new_range / 2
            self.max_x = mid_x + new_range / 2
            
            if self.min_x < 0:
                self.max_x -= self.min_x
                self.min_x = 0
            if self.max_x > self.abs_max_x:
                self.min_x = max(0, self.min_x - (self.max_x - self.abs_max_x))
                self.max_x = self.abs_max_x
        elif state & Gdk.ModifierType.SHIFT_MASK:
            # Zoom Y: Lock bottom at 0
            scale = zoom_factor if dy > 0 else (1/zoom_factor)
            self.max_y = max(0.01, self.max_y * scale)
            self.min_y = 0
        else:
            # Pan X
            shift = range_x * 0.1 * (1 if dy > 0 else -1)
            self.min_x = max(0, min(self.abs_max_x - range_x, self.min_x + shift))
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
        rx, ry = self.drag_start_max_x - self.drag_start_min_x, self.drag_start_max_y - self.drag_start_min_y
        
        self.min_x = self.drag_start_min_x - (offset_x / width) * rx
        self.max_x = self.min_x + rx
        
        if self.min_x < 0:
            self.min_x = 0
            self.max_x = rx
        elif self.max_x > self.abs_max_x:
            self.max_x = self.abs_max_x
            self.min_x = max(0, self.max_x - rx)

        self.min_y = max(0, self.drag_start_min_y + (offset_y / height) * ry)
        self.max_y = self.min_y + ry
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
        for m in ['top', 'bottom', 'start', 'end']: getattr(self.box, f"set_margin_{m}")(24)
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
            try: dialog.set_initial_folder(Gio.File.new_for_path(last_dir))
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
        except GLib.Error: pass # Cancelled

    def process_file(self, filepath):
        self.status_label.set_text(f"Processing: {os.path.basename(filepath)}...")
        self.button.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0.1)
        threading.Thread(target=self.run_profiler_thread, args=(filepath,), daemon=True).start()

    def run_profiler_thread(self, filepath):
        # Content-based hashing
        try:
            hasher = hashlib.md5()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()
        except Exception as e:
            GLib.idle_add(self.show_error, f"Failed to hash file: {e}")
            GLib.idle_add(self.reset_ui)
            return

        cache_file = os.path.join(CACHE_DIR, f"{file_hash}.csv")
        
        needs_profile = not os.path.exists(cache_file)
        if not needs_profile:
            print(f"Using cached results: {cache_file}")

        try:
            if needs_profile:
                profiler_exe = "libass_profiler.exe"
                script_dir = os.path.dirname(os.path.abspath(__file__))
                exe_path = os.path.join(script_dir, profiler_exe)
                if not os.path.exists(exe_path): exe_path = os.path.abspath(profiler_exe)
                if not os.path.exists(exe_path): raise Exception(f"Profiler not found: {profiler_exe}")

                # Use a dedicated temp directory for this run to avoid collisions
                import tempfile, shutil
                with tempfile.TemporaryDirectory(dir=os.getcwd(), prefix="prof_") as tmpdir:
                    # 1. Prepare input
                    abs_filepath = os.path.abspath(filepath)
                    tmp_ass = os.path.join(tmpdir, "input.ass")
                    shutil.copy(abs_filepath, tmp_ass)
                    
                    # 2. Prepare paths for Wine
                    wp = subprocess.run(['winepath', '-w', tmp_ass], capture_output=True, text=True)
                    win_filepath = wp.stdout.strip().splitlines()[-1]
                    
                    GLib.idle_add(self.update_ui, 0.4, "Executing Wine...")
                    
                    # 3. Run Wine with NO output argument (it will write to 'output.csv' in tmpdir)
                    # We must run it with cwd=tmpdir
                    cmd = ['wine', exe_path, win_filepath]
                    print(f"Executing: {shlex.join(cmd)} in {tmpdir}")
                    
                    proc = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)
                    
                    if proc.returncode != 0:
                        raise Exception(f"Profiler failed (code {proc.returncode}):\n{proc.stderr}")
                    
                    generated_out = os.path.join(tmpdir, "output.csv")
                    if not os.path.exists(generated_out):
                        # Try to see if it wrote to a different default name or if we need to list dir
                        files = os.listdir(tmpdir)
                        raise Exception(f"Wine reported success, but 'output.csv' was not created.\nFiles in tmpdir: {files}\nStdout: {proc.stdout}")

                    # 4. Move to cache
                    os.replace(generated_out, cache_file)

            GLib.idle_add(self.update_ui, 0.8, "Loading Data...")
            data_list, title = self.load_csv(cache_file)
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
            try:
                line = next(reader)
                title = line[0] if line else "Untitled"
                next(reader)
            except StopIteration:
                raise Exception("CSV is empty.")
            
            for row in reader:
                if len(row) < 5: continue
                data_list.append(Frame_Statistics(*row))
        if not data_list: raise Exception("No data points.")
        return data_list, title

    def show_error(self, msg):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK, text="Error")
        dialog.props.secondary_text = msg
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()
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
