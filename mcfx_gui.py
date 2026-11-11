"""Desktop interface for converting saved CEWE MCFX projects."""
import math
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mcfx_to_indesign import convert


def validate_inputs(source, output, unit):
    if not str(source).strip():
        raise ValueError('Choose a saved MCFX project.')
    src = Path(source).expanduser().resolve()
    if not src.is_file() or src.suffix.lower() != '.mcfx':
        raise ValueError('Choose an existing .mcfx file.')
    if not str(output).strip():
        raise ValueError('Choose a new output folder.')
    dst = Path(output).expanduser().resolve()
    if dst.exists():
        raise ValueError('The output folder already exists. Choose a new folder name.')
    if not dst.parent.is_dir():
        raise ValueError('The parent of the output folder does not exist.')
    try:
        value = float(unit)
    except ValueError:
        raise ValueError('The coordinate unit must be a number.') from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError('The coordinate unit must be a positive, finite number.')
    return src, dst, value


def run_conversion(source, output, unit, events):
    """Run on a worker thread; all Tk operations stay on the main thread."""
    try:
        report = convert(source, output, unit, progress=lambda message: events.put(('progress', message)))
        events.put(('success', report))
    except Exception as exc:
        events.put(('error', f'{type(exc).__name__}: {exc}'))


class ConverterWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('MCFX to InDesign')
        self.root.minsize(700, 560)
        self.root.geometry('820x660')
        self.events = queue.Queue()
        self.worker = None
        self.last_output = None
        self.suggested_output = None
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.unit = tk.StringVar(value='0.1')
        self.status = tk.StringVar(value='Choose a saved project to get started.')

        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main = ttk.Frame(root, padding=24)
        main.grid(sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(6, weight=1)

        ttk.Label(main, text='MCFX to InDesign', font=('Segoe UI', 20, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Label(main, text='Turn a saved CEWE photo book into editable InDesign image frames.',
                  wraplength=730).grid(row=1, column=0, sticky='w', pady=(5, 18))

        source_box = ttk.LabelFrame(main, text='  1  ·  Saved MCFX project  ', padding=12)
        source_box.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        source_box.columnconfigure(0, weight=1)
        self.source_entry = ttk.Entry(source_box, textvariable=self.source)
        self.source_entry.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.source_browse = ttk.Button(source_box, text='Browse...', command=self.choose_source)
        self.source_browse.grid(row=0, column=1)
        ttk.Label(source_box, text='Save and close the project in CEWE before converting.',
                  wraplength=700).grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))

        output_box = ttk.LabelFrame(main, text='  2  ·  New output folder  ', padding=12)
        output_box.grid(row=3, column=0, sticky='ew', pady=(0, 12))
        output_box.columnconfigure(0, weight=1)
        self.output_entry = ttk.Entry(output_box, textvariable=self.output)
        self.output_entry.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.output_browse = ttk.Button(output_box, text='Choose parent...', command=self.choose_output_parent)
        self.output_browse.grid(row=0, column=1)
        ttk.Label(output_box, text='The converter creates this folder; it must not already exist.',
                  wraplength=700).grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))

        settings = ttk.Frame(main)
        settings.grid(row=4, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(settings, text='Coordinate unit (mm):').pack(side='left')
        self.unit_entry = ttk.Entry(settings, textvariable=self.unit, width=9)
        self.unit_entry.pack(side='left', padx=(8, 12))
        ttk.Label(settings, text='Default 0.1; confirm the page size before printing.').pack(side='left')

        controls = ttk.Frame(main)
        controls.grid(row=5, column=0, sticky='ew', pady=(0, 12))
        controls.columnconfigure(1, weight=1)
        self.convert_button = ttk.Button(controls, text='Convert project', command=self.start)
        self.convert_button.grid(row=0, column=0, sticky='w')
        self.open_button = ttk.Button(controls, text='Open output folder', command=self.open_output, state='disabled')
        self.open_button.grid(row=0, column=2, sticky='e')

        log_box = ttk.LabelFrame(main, text='  Progress  ', padding=10)
        log_box.grid(row=6, column=0, sticky='nsew')
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=7, wrap='word', state='disabled', relief='flat')
        self.log.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(log_box, orient='vertical', command=self.log.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)
        self.progress = ttk.Progressbar(main, mode='indeterminate')
        self.progress.grid(row=7, column=0, sticky='ew', pady=(10, 4))
        ttk.Label(main, textvariable=self.status, wraplength=730).grid(row=8, column=0, sticky='w')
        ttk.Label(main, text='Creates a preview and an InDesign script. Adobe InDesign is required to create the editable documents.',
                  wraplength=730).grid(row=9, column=0, sticky='w', pady=(10, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def choose_source(self):
        name = filedialog.askopenfilename(title='Select a saved CEWE project',
                                          filetypes=[('CEWE project', '*.mcfx'), ('All files', '*.*')])
        if not name:
            return
        previous = self.suggested_output
        self.source.set(name)
        self.suggested_output = str(Path(name).with_name(Path(name).stem + '-InDesign'))
        if not self.output.get().strip() or self.output.get() == previous:
            self.output.set(self.suggested_output)

    def choose_output_parent(self):
        parent = filedialog.askdirectory(title='Choose the parent directory for the new output folder')
        if not parent:
            return
        filename = Path(self.output.get()).name if self.output.get().strip() else ''
        if not filename:
            filename = (Path(self.source.get()).stem or 'Photo-book') + '-InDesign'
        self.output.set(str(Path(parent) / filename))

    def set_running(self, running):
        state = 'disabled' if running else 'normal'
        for widget in (self.source_entry, self.source_browse, self.output_entry,
                       self.output_browse, self.unit_entry, self.convert_button):
            widget.configure(state=state)
        if running:
            self.open_button.configure(state='disabled')
            self.progress.start(12)
        else:
            self.progress.stop()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            src, dst, unit = validate_inputs(self.source.get(), self.output.get(), self.unit.get())
        except ValueError as exc:
            messagebox.showerror('Check your selection', str(exc), parent=self.root)
            return
        self.last_output = dst
        self.set_running(True)
        self.status.set('Converting. Large books may take several minutes.')
        self.append('Starting conversion...')
        self.worker = threading.Thread(target=run_conversion, args=(src, dst, unit, self.events), daemon=True)
        self.worker.start()

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    self.append(payload)
                elif kind == 'success':
                    self.worker = None
                    self.set_running(False)
                    self.open_button.configure(state='normal')
                    self.status.set(f"Done: {payload['interior_pages']} interior pages. Open the output folder for the next step.")
                    self.append('Next: open the output folder and run the generated JSX from the InDesign Scripts panel.')
                elif kind == 'error':
                    self.worker = None
                    self.set_running(False)
                    self.status.set('Conversion stopped. See the message above.')
                    self.append('ERROR: ' + payload)
                    self.append('If a partial output folder was created, choose a new output folder for a retry.')
                    messagebox.showerror('Conversion stopped', payload, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def open_output(self):
        if not self.last_output or not self.last_output.is_dir():
            return
        try:
            if sys.platform == 'win32':
                os.startfile(self.last_output)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(self.last_output)])
            else:
                subprocess.Popen(['xdg-open', str(self.last_output)])
        except OSError as exc:
            messagebox.showerror('Could not open folder', str(exc), parent=self.root)

    def close(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('Conversion in progress', 'Please wait for the current conversion to finish.', parent=self.root)
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    ConverterWindow(root)
    root.mainloop()


if __name__ == '__main__':
    main()
