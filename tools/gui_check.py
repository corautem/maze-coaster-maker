# Maze Coaster Maker: circular-maze coasters for 3D printing.
# Copyright (C) 2026 corautem
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the app's window works: opens it from source, makes a preview, saves it in every
format, opens the licence window, and takes screenshots along the way. The GitHub build
runs this on Windows, macOS and Linux.

    python tools/gui_check.py <output folder>

Exits with 0 when everything worked; the screenshots land in the output folder.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import coaster_app as ca  # noqa: E402
import coaster_gen as cg  # noqa: E402

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
ca.SETTINGS_FILE = out / "settings.json"  # leave the real settings alone
problems = []
ca.messagebox.showerror = lambda title, text, **kw: problems.append(f"error box: {text}")
ca.messagebox.showwarning = lambda title, text, **kw: problems.append(f"warning box: {text}")
ca.messagebox.askyesno = lambda title, text, **kw: True

app = ca.App()
app.v["out_dir"].set(str(out / "coasters"))
app.v["shape"].set("Hexagon")
app.v["seed"].set("4")
for fmt in cg.FORMATS:
    app.v[f"save_{fmt}"].set("1")


def screenshot(name):
    app.update()
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(out / f"{name}.png")
    except Exception as e:  # some CI screens can't be captured; the checks below still count
        print(f"screenshot {name} skipped: {e}")


def when_idle(then):
    def check():
        if app.busy:
            app.after(200, check)
        else:
            app.after(500, then)
    return check


def after_preview():
    if app.result is None or not app.result.ok:
        problems.append("preview didn't build, or a check failed")
    screenshot("1-preview")
    app.save()
    app.after(300, when_idle(after_save))


def after_save():
    made = sorted(p.suffix for p in (out / "coasters").glob(f"{app.result.name}.*"))
    if made != sorted([".3mf", ".dxf", ".step", ".stl", ".svg"]):
        problems.append(f"saved {made}")
    app.show_licence()
    app.after(800, after_licence)


def after_licence():
    screenshot("2-licence")
    finish()


def finish():
    print(f"{app.result.name if app.result else 'no preview'}: "
          f"{', '.join(p.name for p in app.result.files) if app.result else ''}")
    print("\n".join(problems) or "window check passed")
    app.destroy()


app.after(120_000, lambda: (problems.append("timed out"), finish()))
app.after(800, lambda: (app.generate(), app.after(300, when_idle(after_preview))))
app.mainloop()
sys.exit(1 if problems else 0)
