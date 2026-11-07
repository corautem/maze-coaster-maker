# Maze Coaster Maker: circular-maze coasters for 3D printing.
# Copyright (C) 2026 corautem
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
"""Maze Coaster Maker: a window around coaster_gen.py.

Pick a shape and pattern, click Generate preview to see it, then Save to write a
3MF for printing (plus a DXF drawing and an SVG picture if ticked) to the output
folder. Runs on Windows, macOS and Linux, from source (python coaster_app.py) or
as the packaged app built by tools/build.py.
"""
import ctypes
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from dataclasses import replace
from tkinter import filedialog, messagebox, ttk

import coaster_gen as cg

APP_NAME = "Maze Coaster Maker"
APP_VERSION = "2.0.0"
COPYRIGHT = "Copyright © 2026 corautem"
SOURCE_URL = "https://github.com/corautem/maze-coaster-maker"

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
SHORTCUT = ("Command", "Cmd") if MAC else ("Control", "Ctrl")  # (Tk event modifier, menu label)


def settings_dir() -> Path:
    if WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    if MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "maze-coaster-maker"


SETTINGS_FILE = settings_dir() / "settings.json"

SHAPES = {"Circle": "circle", "Hexagon": "hexagon", "Octagon": "octagon",
          "Rounded square": "rounded-square", "Flower": "flower", "Custom outline (DXF file)": "custom"}
ALGOS = {"Long winding corridors": "dfs", "Bushy, many short dead ends": "prim"}
BIASES = {"Balanced": "none", "Around the rings (spiral look)": "ring", "Outward (sunburst look)": "radial"}
CORNER_DEFAULT = {"hexagon": 4.0, "octagon": 4.0, "rounded-square": 12.0}
CENTER_DEFAULT = {"theta": "6", "classical": "16"}  # mm, matches Design.default_center() at 1 mm walls/gaps
STAT_LABELS = {"cells": "maze cells", "centre_d": "centre diameter (mm)"}

WOOD, WOOD_EDGE, CHANNEL = "#e6d7b9", "#8a7556", "#3a2e27"
PREVIEW_STEP = math.radians(2)  # coarser arcs than the DXF; plenty for the screen

SETTINGS_HELP = """\
Shape: the coaster's outline. Custom outline uses the largest closed shape in a DXF file drawn in mm.
Size: overall width in mm (across the flat sides for polygons).
Solid border: plain rim between the outline and the maze.
Centre diameter: the round goal in the middle. It can come out up to 2 x (wall + gap) bigger, so the rings fill the coaster exactly to the border.

Random maze: a new maze for every seed. Same seed and settings = same maze.
  Corridors: long winding paths, or a bushier maze with many short dead ends.
  Direction: prefer running around the rings (spiral look) or outward (sunburst look).
Classical labyrinth: a single path to the centre with no dead ends. Seed and style don't change it.

Wall thickness / Gap width: 1 mm each prints well with a 0.4 mm nozzle.
Base thickness: the solid floor under the maze. Wall height: how far the walls stand above the floor. The coaster is base + wall height thick (2 + 2 = 4 mm by default). For walls in a second colour, add a filament change in your slicer at the base height.

Save writes the ticked files:
  3MF: the finished 3D model. Open it in your slicer (PrusaSlicer, Bambu Studio, OrcaSlicer, Cura…) and print.
  STL: the same 3D model for programs that don't read 3MF.
  STEP: an exact solid for CAD programs such as FreeCAD, Fusion and Onshape, to edit the coaster further (add a name, a logo, a recess…).
  DXF: the flat 2D drawing, for CAD or laser-cutting programs.
  SVG: a picture, shown by Open gallery.

After each preview the checks line should be all ✓: every wall and gap is at least the set width \
and the maze stays inside the border."""


def bundled(*parts):
    """Path to a file shipped with the app (inside the PyInstaller bundle when frozen)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).joinpath(*parts)


def documents_dir():
    if WINDOWS:
        try:
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                return Path(buf.value)
        except (AttributeError, OSError):
            pass
    elif not MAC:
        try:  # Linux desktops can rename or move Documents; xdg-user-dir knows where it is
            found = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, timeout=5,
                                   env=system_env())
            if found.returncode == 0 and found.stdout.strip() and found.stdout.strip() != str(Path.home()):
                return Path(found.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Documents"


def system_env():
    """Environment for starting system programs from the packaged Linux app.

    The packaged app points LD_LIBRARY_PATH at its own libraries, which can break
    programs such as xdg-open; PyInstaller keeps the original in LD_LIBRARY_PATH_ORIG.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False) and not WINDOWS and not MAC:
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def open_path(path):
    """Show a folder or open a file with the system's default program."""
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["open" if MAC else "xdg-open", str(path)], env=system_env(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        dpi = 1.0 if MAC else self.winfo_fpixels("1i") / 96  # macOS sizes windows in points already
        w = min(int(1120 * dpi), self.winfo_screenwidth() - 40)
        h = min(int(780 * dpi), self.winfo_screenheight() - int(110 * dpi))  # keep clear of the taskbar
        self.geometry(f"{w}x{h}+20+10")
        self.minsize(min(int(900 * dpi), w), min(int(640 * dpi), h))
        self.set_icon()

        style = ttk.Style(self)
        if not WINDOWS and not MAC and "clam" in style.theme_names():
            style.theme_use("clam")  # Tk's plain Linux theme looks dated next to clam
        base_font = tkfont.nametofont("TkDefaultFont").actual()
        self.fonts = {
            "body": tkfont.Font(self, family=base_font["family"], size=base_font["size"]),
            "big": tkfont.Font(self, family=base_font["family"], size=abs(base_font["size"]) + 2),
            "bold": tkfont.Font(self, family=base_font["family"], size=abs(base_font["size"]) + 1, weight="bold"),
        }
        style.configure("Big.TButton", font=self.fonts["bold"])
        self.panel_bg = style.lookup("TFrame", "background") or self.cget("background")

        self.jobs = queue.Queue()
        self.busy = False
        self.result = None
        self.flat = None  # flattened outline and channel points of self.result, for redraws
        self.redraw_pending = None

        defaults = {
            "shape": "Circle", "outline_file": "", "petals": "6", "corner_r": "4", "size": "100", "rim": "3",
            "center": CENTER_DEFAULT["theta"],
            "pattern": "theta", "algo": next(iter(ALGOS)), "bias": next(iter(BIASES)),
            "seed": str(random.randrange(10000)), "wall": "1.0", "gap": "1.0", "base": "2", "height": "2",
            "save_3mf": "1", "save_stl": "0", "save_step": "0", "save_dxf": "0", "save_svg": "1",
            "out_dir": str(documents_dir() / APP_NAME),
        }
        self.v = {key: tk.StringVar(value=value) for key, value in defaults.items()}
        self.load_settings()

        self.build_menu()
        self.build_controls()
        self.build_preview()
        # fonts and widgets differ in size between systems; grow the window to fit the controls
        self.update_idletasks()
        w = min(max(w, self.winfo_reqwidth()), self.winfo_screenwidth() - 40)
        h = min(max(h, self.winfo_reqheight()), self.winfo_screenheight() - int(80 * dpi))
        self.geometry(f"{w}x{h}+20+10")
        self.minsize(min(self.winfo_reqwidth(), w), min(self.winfo_reqheight(), h))
        self.v["shape"].trace_add("write", self.shape_changed)
        self.v["pattern"].trace_add("write", self.pattern_changed)
        self.update_states()
        self.protocol("WM_DELETE_WINDOW", self.close)
        if MAC:
            self.createcommand("tk::mac::Quit", self.close)  # Cmd+Q and the app menu's Quit
        self.bind(f"<{SHORTCUT[0]}-g>", lambda _e: self.generate())
        self.bind(f"<{SHORTCUT[0]}-s>", lambda _e: self.save())

    def set_icon(self):
        """Window icon from the files the build bundles; running from source simply has none."""
        try:
            if WINDOWS:
                self.iconbitmap(default=str(bundled("assets", "app.ico")))
            else:
                self.icon_image = tk.PhotoImage(file=str(bundled("assets", "app.png")))
                self.iconphoto(True, self.icon_image)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ layout

    def build_menu(self):
        bar = tk.Menu(self)
        file = tk.Menu(bar, tearoff=False)
        file.add_command(label="Generate preview", accelerator=f"{SHORTCUT[1]}+G", command=self.generate)
        file.add_command(label="Save", accelerator=f"{SHORTCUT[1]}+S", command=self.save)
        file.add_command(label="Save starter set (10 designs)", command=self.starter_set)
        file.add_separator()
        file.add_command(label="Open output folder", command=self.open_folder)
        file.add_command(label="Open gallery", command=self.open_gallery)
        if not MAC:  # macOS puts Quit in the app menu
            file.add_separator()
            file.add_command(label="Exit", command=self.close)
        bar.add_cascade(label="File", menu=file)

        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="What the settings do", command=lambda: self.info_box("Settings", SETTINGS_HELP))
        help_menu.add_separator()
        help_menu.add_command(label="Licence (GPL-3.0)", command=self.show_licence)
        help_menu.add_command(label="Third-party licences", command=self.show_third_party)
        help_menu.add_command(label=f"About {APP_NAME}", command=self.about)
        bar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=bar)

    def build_controls(self):
        side = ttk.Frame(self, padding=(12, 12, 6, 12))
        side.grid(row=0, column=0, sticky="ns")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        def section(title):
            frame = ttk.LabelFrame(side, text=title, padding=(10, 6))
            frame.pack(fill="x", pady=(0, 10))
            frame.columnconfigure(1, weight=1)
            return frame

        def row(parent, r, label, widget):
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="ew", pady=3)
            return widget

        def spin(parent, key, lo, hi, step):
            return ttk.Spinbox(parent, textvariable=self.v[key], from_=lo, to=hi, increment=step, width=8)

        f = section("Coaster")
        row(f, 0, "Shape", ttk.Combobox(f, textvariable=self.v["shape"], values=list(SHAPES),
                                        state="readonly", width=28))
        pick = ttk.Frame(f)
        self.outline_entry = ttk.Entry(pick, textvariable=self.v["outline_file"])
        self.outline_entry.pack(side="left", fill="x", expand=True)
        self.outline_button = ttk.Button(pick, text="Browse…", width=9, command=self.pick_outline)
        self.outline_button.pack(side="left", padx=(4, 0))
        row(f, 1, "Outline file", pick)
        self.petals = row(f, 2, "Petals", spin(f, "petals", 3, 12, 1))
        self.corner = row(f, 3, "Corner radius (mm)", spin(f, "corner_r", 0, 30, 0.5))
        row(f, 4, "Size (mm)", spin(f, "size", 40, 200, 5))
        row(f, 5, "Solid border (mm)", spin(f, "rim", 1, 20, 0.5))
        row(f, 6, "Centre diameter (mm)", spin(f, "center", 2, 80, 1))

        f = section("Pattern")
        ttk.Radiobutton(f, text="Random maze", value="theta", variable=self.v["pattern"]).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(f, text="Classical labyrinth (one path to the centre)", value="classical",
                        variable=self.v["pattern"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.maze_widgets = [
            row(f, 2, "Corridors", ttk.Combobox(f, textvariable=self.v["algo"], values=list(ALGOS), state="readonly")),
            row(f, 3, "Direction", ttk.Combobox(f, textvariable=self.v["bias"], values=list(BIASES), state="readonly")),
        ]
        seed_row = ttk.Frame(f)
        seed = spin(seed_row, "seed", 0, 9999, 1)
        seed.pack(side="left")
        new_maze = ttk.Button(seed_row, text="New maze", command=self.new_maze)
        new_maze.pack(side="left", padx=(6, 0))
        row(f, 4, "Seed", seed_row)
        self.maze_widgets += [seed, new_maze]

        f = section("Walls and height")
        row(f, 0, "Wall thickness (mm)", spin(f, "wall", 0.4, 5, 0.1))
        row(f, 1, "Gap width (mm)", spin(f, "gap", 0.4, 5, 0.1))
        row(f, 2, "Base thickness (mm)", spin(f, "base", 0.4, 10, 0.2))
        row(f, 3, "Wall height (mm)", spin(f, "height", 0.4, 20, 0.2))

        f = section("Save to")
        f.columnconfigure(0, weight=1)
        ttk.Entry(f, textvariable=self.v["out_dir"]).grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(f, text="Browse…", width=9, command=self.pick_out_dir).grid(row=0, column=2, padx=(4, 0))
        kinds = ttk.Frame(f)
        kinds.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        for i, (fmt, label) in enumerate((("3mf", "3MF (3D print)"), ("stl", "STL (3D mesh)"),
                                          ("step", "STEP (CAD)"), ("dxf", "DXF (2D drawing)"),
                                          ("svg", "SVG (picture)"))):
            ttk.Checkbutton(kinds, text=label, variable=self.v[f"save_{fmt}"], onvalue="1", offvalue="0").grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 10), pady=1)

        actions = ttk.Frame(side)
        actions.pack(fill="x")
        self.generate_button = ttk.Button(actions, text="Generate preview", style="Big.TButton", command=self.generate)
        self.generate_button.pack(side="left", expand=True, fill="x", ipady=6)
        self.save_button = ttk.Button(actions, text="Save", style="Big.TButton", command=self.save, state="disabled")
        self.save_button.pack(side="left", expand=True, fill="x", ipady=6, padx=(6, 0))
        links = ttk.Frame(side)
        links.pack(fill="x", pady=(6, 0))
        ttk.Button(links, text="Open folder", command=self.open_folder).pack(side="left", expand=True, fill="x")
        ttk.Button(links, text="Open gallery", command=self.open_gallery).pack(
            side="left", expand=True, fill="x", padx=(6, 0))

    def build_preview(self):
        right = ttk.Frame(self, padding=(6, 12, 12, 12))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(right, background="#f4f1ec", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.schedule_redraw)

        self.info = tk.Text(right, height=5, wrap="word", relief="flat", borderwidth=0, highlightthickness=0,
                            background=self.panel_bg, foreground="#2b2420", font=self.fonts["body"],
                            cursor="arrow")
        self.info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.info.tag_configure("title", font=self.fonts["bold"])
        self.info.tag_configure("pass", foreground="#1f7a3a")
        self.info.tag_configure("fail", foreground="#b3261e")
        self.info.tag_configure("warning", foreground="#9a5b00")
        self.info.tag_configure("note", foreground="#6b5e53")
        self.info.configure(state="disabled")

        bar = ttk.Frame(right)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value="Pick your settings and click Generate preview.")
        ttk.Label(bar, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1)
        self.progress.grid_remove()

    def shape_changed(self, *_):
        shape = SHAPES[self.v["shape"].get()]
        if shape in CORNER_DEFAULT:
            self.v["corner_r"].set(f"{CORNER_DEFAULT[shape]:g}")
        if shape == "custom" and not self.v["outline_file"].get():
            self.pick_outline()
        self.update_states()

    def pattern_changed(self, *_):
        # swap to the other pattern's default centre, unless the user picked their own size
        pattern = self.v["pattern"].get()
        if self.v["center"].get().strip() in CENTER_DEFAULT.values():
            self.v["center"].set(CENTER_DEFAULT[pattern])
        self.update_states()

    def update_states(self):
        shape = SHAPES[self.v["shape"].get()]

        def enable(widgets, on):
            for w in widgets:
                w.configure(state=("readonly" if isinstance(w, ttk.Combobox) else "normal") if on else "disabled")

        enable([self.outline_entry, self.outline_button], shape == "custom")
        enable([self.petals], shape == "flower")
        enable([self.corner], shape in CORNER_DEFAULT)
        enable(self.maze_widgets, self.v["pattern"].get() == "theta")

    # ------------------------------------------------------------ generating

    def number(self, key, label, lo, hi):
        try:
            x = float(self.v[key].get().strip().replace(",", "."))
        except ValueError:
            raise cg.CoasterError(f"{label} must be a number.") from None
        if not lo <= x <= hi:
            raise cg.CoasterError(f"{label} must be between {lo:g} and {hi:g}.")
        return x

    def heights(self):
        return self.number("base", "Base thickness", 0.2, 20), self.number("height", "Wall height", 0.2, 50)

    def formats(self):
        chosen = [f for f in cg.FORMATS if self.v[f"save_{f}"].get() == "1"]
        if not chosen:
            raise cg.CoasterError("Tick at least one file type to save: 3MF, STL, STEP, DXF or SVG.")
        return chosen

    def design(self):
        shape = SHAPES[self.v["shape"].get()]
        outline_file = None
        if shape == "custom":
            outline_file = self.v["outline_file"].get().strip()
            if not outline_file or not Path(outline_file).is_file():
                raise cg.CoasterError("Choose an outline DXF file first (next to Outline file, click Browse).")
        base, height = self.heights()
        num = self.number
        return cg.Design(
            shape="circle" if shape == "custom" else shape,
            outline_file=outline_file,
            pattern=self.v["pattern"].get(),
            size=num("size", "Size", 20, 300),
            rim=num("rim", "Solid border", 0.4, 50),
            center_d=num("center", "Centre diameter", 1, 250),
            wall=num("wall", "Wall thickness", 0.4, 10),
            gap=num("gap", "Gap width", 0.4, 10),
            corner_r=num("corner_r", "Corner radius", 0, 150) if shape in CORNER_DEFAULT else None,
            petals=int(num("petals", "Petals", 3, 24)),
            seed=int(num("seed", "Seed", 0, 10 ** 9)),
            algo=ALGOS[self.v["algo"].get()],
            bias=BIASES[self.v["bias"].get()],
            base=base,
            height=height,
        )

    def out_dir(self):
        text = self.v["out_dir"].get().strip()
        if not text:
            raise cg.CoasterError("Choose a folder to save the coasters in (Save to → Browse).")
        return Path(text)

    def generate(self):
        """Build a preview in memory; nothing is written until Save."""
        try:
            d = self.design()
        except cg.CoasterError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.start("Generating preview… this takes a few seconds.", lambda: [cg.build(d)], self.previewed)

    def new_maze(self):
        self.v["seed"].set(str(random.randrange(10000)))
        self.generate()

    def save(self):
        """Write the previewed coaster in the ticked file types, using the current heights."""
        r = self.result
        if self.busy or r is None:
            return
        try:
            out, formats, (base, height) = self.out_dir(), self.formats(), self.heights()
        except cg.CoasterError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        if (base, height) != (r.design.base, r.design.height):  # heights don't show in the preview
            r.design = replace(r.design, base=base, height=height)
            r.name = r.design.default_name()
        existing = [f"{r.name}.{cg.EXTENSIONS.get(f, f)}" for f in formats
                    if (out / f"{r.name}.{cg.EXTENSIONS.get(f, f)}").exists()]
        if existing and not messagebox.askyesno(
                APP_NAME, "Already in this folder:\n" + "\n".join(existing) + "\n\nReplace with this preview?"):
            return

        def work():
            cg.save(r, out, formats)
            if "svg" in formats:
                cg.write_gallery(out)
            return [r]

        message = "Saving… building the 3D model takes a few seconds." if "3mf" in formats else "Saving…"
        self.start(message, work, self.saved)

    def starter_set(self):
        try:
            out, formats, (base, height) = self.out_dir(), self.formats(), self.heights()
        except cg.CoasterError as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        def work():
            results = [cg.save(cg.build(replace(d, base=base, height=height)), out, formats) for d in cg.EXAMPLES]
            if "svg" in formats:
                cg.write_gallery(out)
            return results

        self.start("Making and saving 10 starter designs… about a minute.", work, self.starter_saved)

    def start(self, message, work, done):
        """Run work() -> [Result] on a background thread, then done(results) back in the window."""
        if self.busy:
            return
        self.save_settings()
        self.set_busy(True, message)
        self.on_done = done

        def worker():
            try:
                self.jobs.put(("ok", work()))
            except cg.CoasterError as e:
                self.jobs.put(("error", str(e)))
            except Exception:
                self.jobs.put(("error", "Something went wrong:\n\n" + traceback.format_exc(limit=4)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self.poll)

    def poll(self):
        try:
            kind, payload = self.jobs.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.set_busy(False)
        if kind == "error":
            self.status.set("Stopped with an error.")
            messagebox.showerror(APP_NAME, payload)
            return
        self.on_done(payload)
        self.update_buttons()

    def previewed(self, results):
        r = results[0]
        self.show(r)
        self.status.set("Preview ready. Nothing is saved yet: click Save if you like it.")
        for level, text in r.notes:
            if level == "warning":
                messagebox.showwarning(APP_NAME, text)

    def saved(self, results):
        r = results[0]
        self.show_info(r)
        self.status.set(f"Saved {', '.join(p.name for p in r.files)} in {r.files[0].parent}")

    def starter_saved(self, results):
        self.show(results[-1])
        failed = sum(not r.ok for r in results)
        note = f" {failed} failed a check." if failed else ""
        self.status.set(f"Saved {len(results)} designs in {results[0].files[0].parent}.{note} "
                        "Click Open gallery to compare them.")

    def set_busy(self, busy, message=""):
        self.busy = busy
        self.configure(cursor="watch" if busy else "")
        self.update_buttons()
        if busy:
            self.status.set(message)
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def update_buttons(self):
        idle = "disabled" if self.busy else "normal"
        self.generate_button.configure(state=idle)
        self.save_button.configure(state=idle if self.result is not None else "disabled")

    # ------------------------------------------------------------ result display

    def show(self, r):
        self.result = r
        self.flat = (cg.flatten_loop(r.outline.loop, PREVIEW_STEP),
                     [cg.flatten_loop(loop, PREVIEW_STEP) for loop in r.loops])
        self.draw_preview()
        self.show_info(r)

    def show_info(self, r):
        stats = ", ".join(f"{STAT_LABELS.get(k, k)} {v}" for k, v in r.stats.items())
        saved = "Saved: " + ", ".join(p.name for p in r.files) if r.files else "Not saved yet"
        t = self.info
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", r.name + "\n", "title")
        t.insert("end", f"{sum(map(len, r.loops))} sketch curves, {stats}. {saved}.\n")
        for label, ok in r.checks:
            t.insert("end", ("✓ " if ok else "✗ ") + label + "    ", "pass" if ok else "fail")
        for level, text in r.notes:
            t.insert("end", ("\n⚠ " if level == "warning" else "\nⓘ ") + text, level)
        t.configure(state="disabled")
        self.fit_info()

    def fit_info(self):
        """Make the result panel exactly as tall as its wrapped text."""
        self.info.update_idletasks()
        lines = self.info.count("1.0", "end", "displaylines")
        lines = max(3, (lines[0] if isinstance(lines, tuple) else lines) or 0)
        if int(self.info.cget("height")) != lines:
            self.info.configure(height=lines)

    def schedule_redraw(self, _event=None):
        if self.redraw_pending:
            self.after_cancel(self.redraw_pending)
        self.redraw_pending = self.after(60, self.draw_preview)

    def draw_preview(self):
        self.redraw_pending = None
        if self.result:
            self.fit_info()  # the window may have been resized, re-wrapping the text
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if not self.flat:
            c.create_text(w / 2, h / 2, text="Your coaster appears here.\nPick settings and click Generate preview.",
                          fill="#8a7f74", font=self.fonts["big"], justify="center")
            return
        outline, channels = self.flat
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        s = min((w - 40) / (max(xs) - min(xs)), (h - 40) / (max(ys) - min(ys)))

        def screen(points):
            return [v for x, y in points for v in (w / 2 + (x - cx) * s, h / 2 - (y - cy) * s)]

        c.create_polygon(screen(outline), fill=WOOD, outline=WOOD_EDGE, width=2)
        for loop in channels:
            c.create_polygon(screen(loop), fill=CHANNEL, outline="")

    # ------------------------------------------------------------ files and folders

    def pick_outline(self):
        path = filedialog.askopenfilename(title="Choose a closed outline drawn in mm",
                                          filetypes=[("DXF files", "*.dxf")])
        if path:
            self.v["outline_file"].set(path)

    def pick_out_dir(self):
        path = filedialog.askdirectory(title="Save coasters in", initialdir=self.v["out_dir"].get() or None)
        if path:
            self.v["out_dir"].set(path)

    def open_folder(self):
        try:
            out = self.out_dir()
        except cg.CoasterError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        out.mkdir(parents=True, exist_ok=True)
        self.open_or_explain(out)

    def open_gallery(self):
        page = Path(self.v["out_dir"].get().strip()) / "index.html"
        if page.is_file():
            self.open_or_explain(page)
        else:
            messagebox.showinfo(APP_NAME, "There's no gallery in this folder yet. Save a coaster first.")

    def open_or_explain(self, path):
        try:
            open_path(path)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Couldn't open {path}:\n\n{e}")

    # ------------------------------------------------------------ licence and about

    def show_licence(self):
        self.text_window("Licence: GNU General Public License v3.0", "LICENSE")

    def show_third_party(self):
        self.text_window("Third-party licences", "THIRD_PARTY_LICENSES.txt",
                         missing="This list is made when the app is built. Running from source, the app "
                                 "uses the Python packages installed on your computer, under their own licences.")

    def text_window(self, title, filename, missing=None):
        path = bundled(filename)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            messagebox.showinfo(APP_NAME, missing or f"{filename} is missing. See {SOURCE_URL}")
            return
        box = tk.Toplevel(self)
        box.title(title)
        box.transient(self)
        box.geometry(f"{min(760, self.winfo_screenwidth() - 80)}x{min(640, self.winfo_screenheight() - 120)}")
        frame = ttk.Frame(box, padding=8)
        frame.pack(fill="both", expand=True)
        view = tk.Text(frame, wrap="word", font=tkfont.nametofont("TkFixedFont"), padx=8, pady=8)
        bar = ttk.Scrollbar(frame, command=view.yview)
        view.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        view.pack(side="left", fill="both", expand=True)
        view.insert("1.0", text)
        view.configure(state="disabled")
        ttk.Button(box, text="Close", command=box.destroy).pack(pady=(0, 8))
        box.bind("<Escape>", lambda _e: box.destroy())

    def about(self):
        messagebox.showinfo(f"About {APP_NAME}",
                            f"{APP_NAME} {APP_VERSION}\n{COPYRIGHT}\n\n"
                            "Circular-maze coasters with customisable wall and gap widths, saved as 3MF "
                            "for 3D printing.\n\n"
                            "This program is free software under the GNU General Public License, version 3 "
                            "or later: you can share and change it under its terms. It comes with ABSOLUTELY "
                            "NO WARRANTY. See Help → Licence for the full text.\n\n"
                            f"Source code: {SOURCE_URL}\n\n"
                            f"Settings are kept in:\n{SETTINGS_FILE.parent}")

    def info_box(self, title, text):
        box = tk.Toplevel(self)
        box.title(title)
        box.transient(self)
        box.resizable(False, False)
        ttk.Label(box, text=text, justify="left", wraplength=560, padding=16).pack()
        ttk.Button(box, text="OK", command=box.destroy).pack(pady=(0, 12))
        box.bind("<Return>", lambda _e: box.destroy())
        box.bind("<Escape>", lambda _e: box.destroy())
        box.grab_set()

    # ------------------------------------------------------------ settings

    def load_settings(self):
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, value in saved.items():
            if key in self.v and isinstance(value, str):
                self.v[key].set(value)
        for key, options in (("shape", SHAPES), ("algo", ALGOS), ("bias", BIASES)):
            if self.v[key].get() not in options:
                self.v[key].set(next(iter(options)))
        if self.v["pattern"].get() not in ("theta", "classical"):
            self.v["pattern"].set("theta")
        if "center" not in saved:  # settings saved before the centre box existed
            self.v["center"].set(CENTER_DEFAULT[self.v["pattern"].get()])

    def save_settings(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps({k: v.get() for k, v in self.v.items()}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def close(self):
        self.save_settings()
        self.destroy()


def main():
    # hidden check used by tools/build.py: builds and saves one coaster without opening a window
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        result = cg.save(cg.build(cg.Design(shape="hexagon", seed=1)), Path(sys.argv[2]), cg.FORMATS)
        sys.exit(0 if result.ok else 1)
    if WINDOWS:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled displays
        except (AttributeError, OSError):
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
