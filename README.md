# Maze Coaster Maker

A small Windows app that makes 3D-printable coasters with a circular maze of **1 mm walls and 1 mm gaps**, and saves them as a **3MF** file you open straight in your slicer. No Fusion 360 needed for printing.

## Use the app

Double-click `dist\MazeCoasterMaker.exe`. It's one standalone file: nothing to install, no Python needed. It takes about 7 seconds to open while it unpacks.

1. Pick a **shape**, **size**, **border** and **centre diameter**.
2. Pick a **pattern**: *Random maze* (new maze for every seed) or *Classical labyrinth* (one path to the centre).
3. Set **wall thickness**, **gap width**, **base thickness** (the solid floor) and **wall height** (above the floor). The coaster is base + wall height thick: 2 + 2 = 4 mm by default.
4. Click **Generate preview**. The checks under the preview should all be ✓.
5. Tick the files you want and click **Save**:
   - **3MF**: the finished 3D model. Open it in PrusaSlicer, Bambu Studio, Orca, Cura or any other slicer and print.
   - **DXF**: the flat drawing, only needed if you want to edit the coaster in Fusion 360.
   - **SVG**: a picture of the design. **Open gallery** shows all saved SVGs side by side.

Files go to `Documents\Maze Coaster Maker` unless you choose another folder. **Help → What the settings do** explains every setting.

The app remembers your settings in `%APPDATA%\Maze Coaster Maker`. To remove it completely, delete the `.exe` and that folder.

## Printing tips

- 0.4 mm nozzle and 0.2 mm layers. 1 mm walls print as two perimeters.
- For walls in a second colour, add a filament change in your slicer at the base height (2 mm by default).
- Cork or felt pads can go under the solid base.

## Fusion 360 (optional)

To edit a coaster in Fusion, save it with **DXF** ticked, then use the app's **Fusion 360** menu:

1. **Add CoasterBuilder script to Fusion** (once).
2. In Fusion, press **Shift+S**, run **CoasterBuilder** and pick the DXF files.

The script builds the same 3D coaster as the 3MF.

## Project files

| File | What it is |
|---|---|
| `dist\MazeCoasterMaker.exe` | The app |
| `coaster_app.py` | The app's window |
| `coaster_gen.py` | The maze and file generator (also usable from the command line) |
| `fusion\CoasterBuilder\` | The Fusion 360 script (bundled into the app) |
| `tools\make_icon.py` | Draws the app icon during a build |
| `build.ps1` | Rebuilds the `.exe` |
| `requirements.txt` | Python packages for running from source and building |

## Rebuilding the app

Only needed after changing the code. Close the app first, then:

```
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

The build takes about 2 minutes. It checks the new `.exe` can make and save a coaster, then replaces `dist\MazeCoasterMaker.exe` and deletes its temporary `build` folder. The version shown in **Help → About** comes from `APP_VERSION` in `coaster_app.py`.

The app isn't code-signed, so on another computer Windows may show "Windows protected your PC" the first time. Click **More info → Run anyway**.

## Command line

`coaster_gen.py` does the same from a terminal and saves 3MF, DXF and SVG for each design:

```
python coaster_gen.py --shape hexagon --seed 42 --base 2 --wall-height 2
python coaster_gen.py --pattern classical --center 20
python coaster_gen.py --examples        # 10 starter designs in output\
python coaster_gen.py --help            # every option
```
