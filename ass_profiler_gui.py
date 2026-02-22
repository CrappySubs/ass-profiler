import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
import subprocess
import csv
import re
import os
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FuncFormatter
from collections import namedtuple

# --- Logic from graph_statistics_csv.py ---

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

def graph_libass_stats(samples, title, fps=23.976):
    zs = list(zip(*samples))
    time_domain = [str2s(t) for t in zs[0]]
    datasets = zs[1:]

    plt.style.use('dark_background')
    fig, subplots = plt.subplots(len(datasets), 1, constrained_layout=True)
    fig.canvas.manager.set_window_title(f'Analytics for {re.sub(".*/","",title)}') # Set window title
    fig.suptitle(f'Analytics for {re.sub(".*/","",title)}')

    for subplot, dataset, graph_label, y_label in zip(subplots, datasets, frame_graph_labels, frame_stat_y_axis_labels):
        float_data = [float(a) for a in dataset]
        max_y = max(float_data) if float_data else 0
        subplot.ticklabel_format(style='plain')
        subplot.xaxis.set_major_locator(MultipleLocator(60))
        subplot.xaxis.set_minor_locator(MultipleLocator(15))
        subplot.xaxis.set_major_formatter(FuncFormatter(lambda x,pos: sec_to_mm_ss_str(x)))
        subplot.grid(visible=True, which='major', axis='x', color='#333333')
        if y_label == "bytes":
            subplot.yaxis.set_major_formatter(Base10BytesFormatter(max_y))
        else:
            subplot.set(xlabel=None, ylabel=y_label)
        if graph_label == "frame render time":
            # Avoid division by zero if fps is 0 (though unlikely)
            calc_fps = fps if fps > 0 else 23.976
            subplot.axhline(y = 1000 / calc_fps, color='r', linestyle = 'dashed')
            subplot.axhline(y = (1000 / calc_fps) / 2, color='w', linestyle = 'dashed')
        else:
            pass
        if time_domain:
            subplot.set_xlim([time_domain[0], time_domain[-1]])
        subplot.set_ylim([0, max_y * 1.1 if max_y > 0 else 1]) # Add some headroom
        subplot.plot(time_domain, float_data)
        subplot.set_title(graph_label)
        plt.setp(subplot.get_xticklabels(), rotation=0, ha="left")
    
    # Non-blocking show for the GUI, but we want the user to see it.
    plt.show()

# --- GUI Application ---

class AssProfilerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ASS Profiler & Grapher")
        self.root.geometry("400x300")
        
        # Configure style
        self.root.configure(bg="#2d2d2d")
        
        # Main Frame
        self.frame = tk.Frame(root, bg="#2d2d2d")
        self.frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
        
        # Instructions Label
        self.label = tk.Label(
            self.frame, 
            text="Drag and Drop .ass file here\nor use the button below",
            bg="#2d2d2d", 
            fg="#ffffff",
            font=("Arial", 12),
            pady=20
        )
        self.label.pack()
        
        # Select Button
        self.btn_select = tk.Button(
            self.frame,
            text="Select .ass File",
            command=self.select_file,
            bg="#4a4a4a",
            fg="white",
            font=("Arial", 10),
            activebackground="#666666",
            activeforeground="white",
            relief=tk.FLAT,
            padx=15,
            pady=5
        )
        self.btn_select.pack(pady=10)
        
        # Status Label
        self.status = tk.Label(
            self.frame,
            text="Ready",
            bg="#2d2d2d",
            fg="#aaaaaa",
            font=("Arial", 9)
        )
        self.status.pack(side=tk.BOTTOM, pady=10)
        
        # DnD setup
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.drop)
        
    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("ASS Files", "*.ass"), ("All Files", "*.*")])
        if file_path:
            self.process_file(file_path)

    def drop(self, event):
        file_path = event.data
        # TkinterDnD passes paths inside braces if they contain spaces {path/to/file}
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]
        
        # Handle multiple files (just take the first one if multiple dropped)
        # Windows DnD might give a list of files
        # Only process if it ends with .ass (case insensitive)
        if hasattr(self.root, 'tk'): # Just some safety check, unnecessary really
             pass
             
        # Just simple cleanup. 
        # Sometimes event.data can be list of files separated by space, but handling complex paths with spaces is tricky.
        # Assuming single file drop for now or regex matching.
        
        # Regex to match paths potentially in braces
        # But for single file drop on Windows usually straightforward
        
        # If user drops multiple files, event.data looks like: "{C:/Format 1.txt} C:/Format2.txt"
        # We will try to take the first valid .ass file
        
        # Improved parsing
        files = self.root.tk.splitlist(event.data)
        for f in files:
            if f.lower().endswith('.ass'):
                self.process_file(f)
                return # Only process one
        
        # If execution reaches here, maybe it was a single path without braces that split didn't catch 
        # (though splitlist handles it well usually)
        if file_path.lower().endswith('.ass') and os.path.exists(file_path):
             self.process_file(file_path)
             return

        self.status.config(text="No .ass file detected in drop.")

    def process_file(self, filepath):
        self.status.config(text=f"Processing: {os.path.basename(filepath)}")
        self.root.update()
        
        profiler_exe = "libass_profiler.exe"
        # Ensure executable is found. Assuming it's in the same directory as script or in PATH.
        # If script is run from same dir as exe.
        
        output_csv = "output.csv"
        
        try:
            # 1. Run libass_profiler
            # Command: libass_profiler.exe <filepath> <output_csv>
            
            # Using absolute path for exe if valid
            script_dir = os.path.dirname(os.path.abspath(__file__))
            exe_path = os.path.join(script_dir, profiler_exe)
            if not os.path.exists(exe_path):
                # Try relative (cwd)
                exe_path = profiler_exe
            
            cmd = [exe_path, filepath, output_csv]
            
            # Using subprocess.run
            # Note: Startup info to hide console window on Windows?
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            
            if proc.returncode != 0:
                self.status.config(text="Profiler failed.")
                messagebox.showerror("Error", f"libass_profiler failed:\n{proc.stderr}")
                return
            
            # 2. Parse CSV and Graph
            self.generate_graph(output_csv)
            self.status.config(text="Done.")
            
        except Exception as e:
            self.status.config(text="Error occurred.")
            messagebox.showerror("Error", str(e))

    def generate_graph(self, csv_file):
        try:
            data_list = []
            with open(csv_file, newline='') as f:
                reader = csv.reader(f)
                try:
                    title_row = next(reader)
                    if not title_row:
                        raise ValueError("CSV is empty/invalid")
                    title = title_row[0]
                    next(reader) # Skip header
                    for row in reader:
                        row[4] = float(row[4]) * 1000
                        data = Frame_Statistics(*row)
                        data_list.append(data)
                except StopIteration:
                     pass

            if not data_list:
                raise ValueError("No data found in output CSV.")
                
            graph_libass_stats(data_list, title)
            
        except Exception as e:
            messagebox.showerror("Graph Error", f"Failed to generate graph: {e}")

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = AssProfilerApp(root)
    root.mainloop()
