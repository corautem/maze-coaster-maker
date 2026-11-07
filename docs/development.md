# Development

How to run the app from its source code, build it, and release a version.

## Running from source

With Python 3.10 or newer:

```
pip install -r requirements.txt
python coaster_app.py
```

On Linux, Python's Tk support may be a separate package, such as `python3-tk` on Debian and Ubuntu. For the command-line version, see [Command line](command-line.md).

## Project files

| File | What it is |
|---|---|
| `coaster_app.py` | The app's window |
| `coaster_gen.py` | The maze generator and the file writers, also usable from the command line |
| `tools/build.py` | Builds the app for the system it runs on |
| `tools/gui_check.py` | Opens the window, makes and saves a coaster, and takes screenshots |
| `tools/make_icon.py` | Draws the app icon during a build |
| `tools/licences/` | Tcl/Tk's licence texts, for builds whose Python doesn't include them |
| `.github/workflows/build.yml` | Builds, checks and releases the app on GitHub |
| `CHANGELOG.md` | What changed in each version, and what waits for the next one |
| `THIRD-PARTY-NOTICES.md` | The licences of the software inside the built app |
| `docs/` | These pages and their pictures |

## Building the app

PyInstaller builds only for the system it runs on. To build for your own computer:

```
pip install -r requirements.txt
python tools/build.py
```

The result goes to `dist/`. The build:

1. draws the icon and collects the licence texts of everything inside the app;
2. builds the app with PyInstaller;
3. has the built app make and save a coaster in every file type, without opening a window;
4. packs it for the system: an `.exe` on Windows, a `.zip` holding the `.app` on macOS, a `.tar.gz` on Linux.

`python tools/build.py --launch-check screenshots` also starts the built app's window, checks it stays open for 15 seconds, and saves a screenshot.

## Builds on GitHub

[`.github/workflows/build.yml`](../.github/workflows/build.yml) builds five versions on GitHub's machines: Windows, macOS for Apple silicon and for Intel, and Linux for x64 and ARM. Each one is checked three ways: the window from source with `tools/gui_check.py`, the built app's self-test, and the launch check. The screenshots are kept with each run. Run it by hand from the **Actions** tab to build without releasing.

## Releasing a version

1. Move the entries under **Unreleased** in `CHANGELOG.md` to the new version, and raise `APP_VERSION` in `coaster_app.py` to match.
2. Refresh the licence texts with `python tools/build.py --notices`, after `pip install -r requirements.txt --upgrade` so the versions match the build.
3. Commit, then push a tag with the version, such as `v2.0.1`.

The workflow then builds and checks all five versions and publishes the release, with that version's changelog entries as its notes and GEOS's source code attached, as its LGPL licence asks.
