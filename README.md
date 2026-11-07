# Maze Coaster Maker

A small app for Windows, macOS and Linux that makes 3D-printable coasters with a circular maze, with **customisable wall and gap widths** (1 mm each by default). It saves a **3MF** file you open straight in your slicer, and can also save STL, a STEP solid for CAD programs, a DXF drawing and an SVG picture.

## Download

Get the file for your computer from the [Releases page](https://github.com/corautem/maze-coaster-maker/releases). Nothing to install, and you don't need Python.

| Computer | File | First run |
|---|---|---|
| Windows | `…-windows-x64.exe` | Double-click it. If Windows shows "Windows protected your PC", click **More info → Run anyway** (the app isn't code-signed). |
| Mac, Apple silicon or Intel | `…-macos-arm64.zip` or `…-macos-x64.zip` | Unzip and drag **Maze Coaster Maker** into Applications. The first time, macOS blocks it because it isn't signed by Apple: open it, close the message, then click **Open Anyway** in **System Settings → Privacy & Security**. |
| Linux, x64 or ARM (such as a 64-bit Raspberry Pi) | `…-linux-x64.tar.gz` or `…-linux-arm64.tar.gz` | Unpack it and run `MazeCoasterMaker`. Needs glibc 2.35 or newer: Ubuntu 22.04, Debian 12, Fedora 36 and later. |

## Use the app

1. Pick a **shape**, **size**, **border** and **centre diameter**.
2. Pick a **pattern**: *Random maze* (a new maze for every seed) or *Classical labyrinth* (one path to the centre).
3. Set **wall thickness**, **gap width**, **base thickness** (the solid floor) and **wall height** (above the floor). The coaster is base + wall height thick: 2 + 2 = 4 mm by default.
4. Click **Generate preview**. The checks under the preview should all be ✓.
5. Tick the files you want and click **Save**:
   - **3MF**: the finished 3D model. Open it in PrusaSlicer, Bambu Studio, OrcaSlicer, Cura or another slicer and print.
   - **STL**: the same 3D model, for programs that don't read 3MF.
   - **STEP**: an exact solid for CAD programs such as FreeCAD, Fusion and Onshape, if you want to edit the coaster: add a name or logo, a recess for a cork pad, and so on.
   - **DXF**: the flat 2D drawing, for CAD or laser-cutting programs.
   - **SVG**: a picture of the design. **Open gallery** shows all saved SVGs side by side.

Files go to `Maze Coaster Maker` in your Documents folder unless you choose another one. **Help → What the settings do** explains every setting.

The app remembers your settings in `%APPDATA%\Maze Coaster Maker` on Windows, `~/Library/Application Support/Maze Coaster Maker` on a Mac and `~/.config/maze-coaster-maker` on Linux. To remove the app completely, delete it and that folder.

## Printing tips

- 0.4 mm nozzle and 0.2 mm layers. 1 mm walls print as two perimeters.
- For walls in a second colour, add a filament change in your slicer at the base height (2 mm by default).
- Cork or felt pads can go under the solid base.

## Run from source

With Python 3.10 or newer:

```
pip install -r requirements.txt
python coaster_app.py
```

On Linux, Python's Tk support may be a separate package, for example `sudo apt install python3-tk` on Debian and Ubuntu.

`coaster_gen.py` does the same from a terminal:

```
python coaster_gen.py --shape hexagon --seed 42 --base 2 --wall-height 2
python coaster_gen.py --pattern classical --center 20 --formats 3mf,step
python coaster_gen.py --examples        # 10 starter designs in output/
python coaster_gen.py --help            # every option
```

## Building the app

PyInstaller can only build for the system it runs on, so GitHub builds all five versions (Windows, Mac Apple silicon and Intel, Linux x64 and ARM) with [.github/workflows/build.yml](.github/workflows/build.yml). Each build is checked three ways before it's kept:

- the window opens from source, makes a preview and saves every file type;
- the packaged app builds and saves a coaster without a window;
- the packaged app's window opens and stays open.

Screenshots of each system are kept with the build.

To make a release:

1. Check the **Unreleased** section of [CHANGELOG.md](CHANGELOG.md), raise `APP_VERSION` in `coaster_app.py`, and move those entries under the new version number.
2. Commit, then push a tag with that version: `git tag v2.0.0` and `git push origin v2.0.0`.

GitHub then builds everything and publishes the release, with the changelog entries as its notes. To build without releasing, run the **Build** workflow by hand from the repository's **Actions** tab.

To build on your own computer, for your system only:

```
pip install -r requirements.txt
python tools/build.py
```

The result lands in `dist/`.

## Project files

| File | What it is |
|---|---|
| `coaster_app.py` | The app's window |
| `coaster_gen.py` | The maze and file generator (also usable from the command line) |
| `tools/build.py` | Builds the standalone app for the system it runs on |
| `tools/gui_check.py` | Opens the window, makes and saves a coaster, takes screenshots: the build's window check |
| `tools/make_icon.py` | Draws the app icon during a build |
| `tools/licences/` | Tcl/Tk's licence texts, for builds whose Python doesn't include them |
| `.github/workflows/build.yml` | Builds, checks and releases the app on GitHub |
| `requirements.txt` | Python packages for running from source and building |
| `CHANGELOG.md` | What changed in each version, and what's waiting for the next release |
| `LICENSE` | The GNU General Public License, version 3 |

## Licence

Maze Coaster Maker is free software: you can share and change it under the terms of the [GNU General Public License](LICENSE), version 3 or (at your option) any later version. It comes with no warranty.

The built app also contains other people's open-source software (Python, Tcl/Tk, shapely with GEOS, numpy, ezdxf and others). Their licences are listed in the app under **Help → Third-party licences**, and each release includes GEOS's source code, as GEOS's LGPL licence asks.
