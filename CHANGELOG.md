# Changelog

## Unreleased

Changes in the source code that aren't in a released version yet. They go out with the next release.

- Nothing yet.

## 2.0.0

- Runs on Windows, macOS (Apple silicon and Intel) and Linux (x64 and ARM, such as a 64-bit Raspberry Pi). GitHub builds and checks all five versions for every release.
- New file types to save: **STEP**, an exact solid that opens as an editable body in CAD programs such as FreeCAD, Fusion and Onshape, and **STL**, the same model as the 3MF for programs that don't read 3MF.
- Removed the Fusion 360 script and the Fusion 360 menu. To edit a coaster in a CAD program, save it as STEP or DXF.
- Now free software under the GNU General Public License, version 3 or later. **Help → Licence** and **Help → Third-party licences** show the licence texts.
- Help → About describes the wall and gap widths as customisable. It said "1 mm walls and gaps", but 1 mm is only the default.
- The window grows to fit its controls on systems with larger fonts. On screens too short for all the settings, the settings scroll and the Generate preview, Save, Open folder and Open gallery buttons stay in view.
- `tools/build.py` replaces `build.ps1` and builds the app on any of the three systems.
- Notes under the preview start with ℹ, which the standard Linux fonts include; the earlier symbol showed as an empty box there.
- A new README with pictures and an animation, documentation pages for settings, files, the command line and development, issue forms for bugs, ideas and questions, and the third-party licence texts in `THIRD-PARTY-NOTICES.md`.

## 1.3.0

First release on GitHub.

- Random circular mazes and a classical labyrinth, in circle, hexagon, octagon, rounded-square, flower or custom DXF outlines.
- Adjustable size, border, centre diameter, wall and gap widths, base thickness and wall height.
- Generate a preview first, then save as 3MF (ready for a slicer), DXF (Fusion 360) and/or SVG.
