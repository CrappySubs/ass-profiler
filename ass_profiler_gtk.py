#!/usr/bin/env python3
import sys
import os
import subprocess
import csv
import re
import threading
import json
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Gdk, Adw

import matplotlib
# Use GTK4Agg for interactive plots
try:
    matplotlib.use('GTK4Agg')
except ImportError:
    # Fallback if somehow still missing, though we expect it to work
    print("Warning: GTK4Agg backend not found, falling back to Agg (non-interactive)")
    matplotlib.use('Agg')

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FuncFormatter
from matplotlib.backends.backend_gtk4agg import FigureCanvasGTK4Agg
from matplotlib.backends.backend_gtk4 import NavigationToolbar2GTK4
from matplotlib.backend_bases import MouseButton
from collections import namedtuple

# --- Config Logic ---
CONFIG_FILE = os.path.expanduser("~/.config/ass-profiler/config.json")

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
    return {}

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        print(f"Error saving config: {e}")

# --- Graph Logic ---

frame_stat_names = ['time','total_image_size', 'largest_image_size','image_count','time_benchmark']
Frame_Statistics = namedtuple('Frame_Statistics', frame_stat_names)
frame_graph_labels = [
    'total bitmap sizes for frame',
    'largest bitmap size in frame',
    'bitmap counts',
    'frame render time',
]
frame_stat_y_axis_labels = [
    'bytes',
    'bytes',
    'counts',
    'milliseconds',
]

def sec_to_mm_ss_str(sec):
    rs = round(sec, 2)
    s = '{0:02.0f}'.format(rs%60)
    return f"{int(rs / 60):02d}:{s}"

def str2s(hmrstr):
    mre = re.match("([0-9]+):([0-9]{2}):([0-9.]+)",hmrstr)
    if not mre: return 0
    h = int(mre[1])
    m = int(mre[2])
    s = float(mre[3])
    return ((h*60) + m ) * 60 + s

def Base10BytesFormatter(max_y):
    if max_y > 1000**3:
        return lambda y,pos: f"{'{:.1f}'.format(y/1000**3)} GB"
    elif max_y > 1000**2:
        return lambda y,pos: f"{'{:.1f}'.format(y/1000**2)} MB"
    elif max_y > 1000:
        return lambda y,pos: f"{'{:.1f}'.format(y/1000)} kB"
    else:
        return lambda y,pos: f"{int(y)}"

def get_theme_colors():
    """
    Returns theme colors based on Adwaita style preference.
    """
    manager = Adw.StyleManager.get_default()
    is_dark = manager.get_dark()
    
    if is_dark:
        return {
            'bg': '#242424', # Adwaita Dark BG
            'fg': '#ffffff', # Adwaita Dark FG
            'grid': '#ffffff',
        }
    else:
        return {
            'bg': '#fafafa', # Adwaita Light BG
            'fg': '#000000', # Adwaita Light FG
            'grid': '#000000',
        }


def create_interactive_figure(samples, title, colors, fps=23.976):
    zs = list(zip(*samples))
    time_domain = [str2s(t) for t in zs[0]]
    datasets = zs[1:]

    bg_color = colors['bg']
    text_color = colors['fg']
    grid_color = colors['fg']

    plt.rcParams.update({
        'figure.facecolor': bg_color,
        'axes.facecolor': bg_color,
        'axes.edgecolor': text_color,
        'axes.labelcolor': text_color,
        'xtick.color': text_color,
        'ytick.color': text_color,
        'grid.color': grid_color,
        'grid.alpha': 0.2,
        'text.color': text_color,
        'axes.titlecolor': text_color,
        'path.simplify': True,
        'path.simplify_threshold': 1.0,
        'agg.path.chunksize': 10000,
    })

    fig, subplots = plt.subplots(len(datasets), 1, figsize=(10, 8))
    
    safe_title = re.sub(r".*[/\\]", "", title)
    fig.suptitle(f'Analytics for {safe_title}')

    for subplot, dataset, graph_label, y_label in zip(subplots, datasets, frame_graph_labels, frame_stat_y_axis_labels):
        float_data = [float(a) for a in dataset]
        max_y = max(float_data) if float_data else 0
        subplot.ticklabel_format(style='plain')
        subplot.xaxis.set_major_locator(MultipleLocator(60))
        subplot.xaxis.set_minor_locator(MultipleLocator(15))
        subplot.xaxis.set_major_formatter(FuncFormatter(lambda x,pos: sec_to_mm_ss_str(x)))
        subplot.grid(visible=True, which='major', axis='x')
        
        if y_label == "bytes":
            subplot.yaxis.set_major_formatter(Base10BytesFormatter(max_y))
        else:
            subplot.set(xlabel=None, ylabel=y_label)
            
        if graph_label == "frame render time":
            calc_fps = fps if fps > 0 else 23.976
            subplot.axhline(y = 1000 / calc_fps, color='r', linestyle = 'dashed')
            subplot.axhline(y = (1000 / calc_fps) / 2, color='w', linestyle = 'dashed')
            subplot.set_ylim([0, 60])
        else:
            subplot.set_ylim([0, max_y * 1.1 if max_y > 0 else 1]) 
        
        if time_domain:
            subplot.set_xlim([time_domain[0], time_domain[-1]])
        
        subplot.plot(time_domain, float_data, linewidth=1)
        subplot.set_title(graph_label)
    
    fig.tight_layout()
    return fig

# --- GTK4 Application ---

class GraphWindow(Gtk.Window):
    def __init__(self, figure, title):
        super().__init__(title=title)
        self.set_default_size(1000, 800)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(box)
        
        self.canvas = FigureCanvasGTK4Agg(figure)
        self.canvas.set_vexpand(True)
        self.canvas.set_hexpand(True)
        box.append(self.canvas)
        
        # Connect Scroll Event
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        
        self.toolbar = NavigationToolbar2GTK4(self.canvas)
        box.append(self.toolbar)

    def on_scroll(self, event):
        ax = event.inaxes
        if ax is None: return

        # Constants (Increased for "faster" feel)
        zoom_base = 1.25
        pan_amount = 0.15 

        # Check modifiers
        # Matplotlib 'key' attribute contains the key pressed during event
        # 'control' for Ctrl, 'shift' for Shift.
        
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        
        xdata = event.xdata
        ydata = event.ydata
        
        if event.key == 'control':
            # ZOOM X
            if event.button == 'up': # Zoom In
                scale = 1 / zoom_base
            else: # Zoom Out
                scale = zoom_base
            
            # Zoom centered on cursor X
            new_width = (cur_xlim[1] - cur_xlim[0]) * scale
            rel_x = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
            new_x1 = xdata - new_width * (1 - rel_x)
            new_x2 = xdata + new_width * rel_x
            ax.set_xlim([new_x1, new_x2])

        elif event.key == 'shift':
            # ZOOM Y
            if event.button == 'up': # Zoom In
                scale = 1 / zoom_base
            else:
                scale = zoom_base
            
            new_height = (cur_ylim[1] - cur_ylim[0]) * scale
            rel_y = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
            new_y1 = ydata - new_height * (1 - rel_y)
            new_y2 = ydata + new_height * rel_y
            ax.set_ylim([new_y1, new_y2])

        else:
            # PAN X
            # Move along X axis
            # Button up: Scroll Left (move view left -> subtract) ? 
            # Typically Scroll Up -> Pan Right? Or Scroll Up -> Move Left?
            # Standard conventions vary. Let's assume Scroll Up = Move Left (Time back)
            
            width = cur_xlim[1] - cur_xlim[0]
            step = width * pan_amount
            
            if event.button == 'up':
                # Move left (back in time)
                new_x1 = cur_xlim[0] - step
                new_x2 = cur_xlim[1] - step
            else:
                # Move right (forward in time)
                new_x1 = cur_xlim[0] + step
                new_x2 = cur_xlim[1] + step
                
            ax.set_xlim([new_x1, new_x2])

        event.canvas.draw_idle()


class AssProfilerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("ASS Profiler")
        self.set_default_size(400, 200)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.box.set_margin_top(24)
        self.box.set_margin_bottom(24)
        self.box.set_margin_start(24)
        self.box.set_margin_end(24)
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
                folder = Gio.File.new_for_path(last_dir)
                dialog.set_initial_folder(folder)
            except Exception as e:
                print(f"Failed to set initial folder: {e}")

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
        except Exception:
            pass

    def process_file(self, filepath):
        self.status_label.set_text(f"Processing: {os.path.basename(filepath)}...")
        self.button.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_fraction(0.1)
        
        thread = threading.Thread(target=self.run_profiler_thread, args=(filepath,))
        thread.daemon = True
        thread.start()

    def run_profiler_thread(self, filepath):
        print(f"Thread started for: {filepath}")
        profiler_exe = "libass_profiler.exe"
        output_csv = "output.csv"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        exe_path = os.path.join(script_dir, profiler_exe)
        
        if not os.path.exists(exe_path):
            exe_path = os.path.abspath(profiler_exe)

        try:
            abs_filepath = os.path.abspath(filepath)
            # ... winepath logic ...
            try:
                wp = subprocess.run(['winepath', '-w', abs_filepath], capture_output=True, text=True, timeout=5)
                win_filepath = wp.stdout.strip() if wp.returncode == 0 else abs_filepath
            except subprocess.TimeoutExpired:
                win_filepath = abs_filepath

            abs_out = os.path.abspath(output_csv)
            try:
                wp_out = subprocess.run(['winepath', '-w', abs_out], capture_output=True, text=True, timeout=5)
                win_out = wp_out.stdout.strip() if wp_out.returncode == 0 else output_csv
            except subprocess.TimeoutExpired:
                win_out = output_csv

            cmd = ['wine', exe_path, win_filepath, win_out]
            print(f"Executing: {cmd}")
            
            GLib.idle_add(self.update_progress, 0.4)
            
            proc = subprocess.run(cmd, capture_output=True, text=True)
            
            if proc.returncode != 0:
                GLib.idle_add(self.show_error, "Profiler failed", proc.stderr)
                GLib.idle_add(self.reset_ui)
                return

            GLib.idle_add(self.update_progress, 0.7)
            GLib.idle_add(self.update_status, "Generating Graph...")
            
            data_list, title = self.load_csv(abs_out)
            
            # Defer figure creation to main thread to capture theme colors correctly?
            # OR capture colors here? We can't access widget methods safely from thread.
            # So we pass data to main thread function.
            
            GLib.idle_add(self.show_interactive_graph, data_list, title)
            GLib.idle_add(self.update_status, "Done.")

        except Exception as e:
            print(f"Exception: {e}")
            GLib.idle_add(self.show_error, "Error", str(e))
        
        GLib.idle_add(self.reset_ui)

    def show_interactive_graph(self, data_list, title):
        try:
            # Get theme colors
            colors = get_theme_colors()
            
            fig = create_interactive_figure(data_list, title, colors)
            graph_win = GraphWindow(fig, f"Analytics - {title}")
            graph_win.set_transient_for(self)
            graph_win.present()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.show_error("Graph Error", str(e))
        return False

    def update_progress(self, fraction):
        self.progress.set_fraction(fraction)
        return False

    def update_status(self, text):
        self.status_label.set_text(text)
        return False

    def load_csv(self, csv_file):
        data_list = []
        with open(csv_file, newline='') as f:
            reader = csv.reader(f)
            title = next(reader)[0]
            next(reader) 
            for row in reader:
                if len(row) < 5: continue
                row[4] = float(row[4]) * 1000
                data_list.append(Frame_Statistics(*row))
        return data_list, title

    def show_error(self, title, msg):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
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
        super().__init__(application_id="com.example.AssProfiler", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = AssProfilerWindow(self)
        window.present()

if __name__ == "__main__":
    app = AssProfilerApp()
    app.run(sys.argv)
