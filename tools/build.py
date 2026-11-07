# Maze Coaster Maker: circular-maze coasters for 3D printing.
# Copyright (C) 2026 corautem
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the standalone app for the system it runs on, into dist/:

    Windows  MazeCoasterMaker-<version>-windows-<arch>.exe  one file, nothing to install
    macOS    MazeCoasterMaker-<version>-macos-<arch>.zip    holds Maze Coaster Maker.app
    Linux    MazeCoasterMaker-<version>-linux-<arch>.tar.gz holds one program file

PyInstaller can only build for the system it runs on, so each system builds its own;
.github/workflows/build.yml does all three on GitHub's machines.

    pip install -r requirements.txt
    python tools/build.py [--launch-check screenshots]
"""
import argparse
import importlib.metadata as metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "build"   # temporary; removed at the end
DIST = ROOT / "dist"
NAME = "MazeCoasterMaker"
APP_TITLE = "Maze Coaster Maker"  # the macOS app's name in Finder and the Dock
SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
ARCH = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                 platform.machine().lower())
# ezdxf has optional viewers that would pull in about 90 MB of Qt; the app draws with tkinter
EXCLUDES = ["PySide6", "shiboken6", "PyQt5", "PyQt6", "matplotlib", "PIL"]


def app_version():
    text = (ROOT / "coaster_app.py").read_text(encoding="utf-8")
    return re.search(r'^APP_VERSION = "([^"]+)"', text, re.M).group(1)


def run(*args):
    print("+", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


# ---------------------------------------------------------------- third-party licences

def requirement_name(req):
    return re.split(r"[ ;<>=!~\[(]", req.strip(), maxsplit=1)[0]


def bundled_distributions():
    """The Python packages the app is built from: shapely and ezdxf, everything they need,
    and PyInstaller, whose start-up code is part of every build."""
    found, todo = {}, ["shapely", "ezdxf"]
    while todo:
        name = todo.pop(0)
        key = name.lower().replace("_", "-")
        if key in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        found[key] = dist
        for req in dist.requires or []:
            if "extra ==" not in req and "sys_platform" not in req:
                todo.append(requirement_name(req))
    found["pyinstaller"] = metadata.distribution("pyinstaller")
    return list(found.values())


def licence_name(md):
    """A package's licence in a few words, from whichever metadata field it fills in."""
    if md.get("License-Expression"):
        return md["License-Expression"]
    first_line = (md.get("License") or "").strip().splitlines()[:1]
    if first_line and len(first_line[0]) <= 60:
        return first_line[0]
    for classifier in md.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "see below"


def licence_texts(dist):
    texts = []
    for f in dist.files or []:
        if re.search(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", f.name, re.I) and ".dist-info" in str(f):
            try:
                text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")
                texts.append((str(f).split(".dist-info/", 1)[-1], text))
            except OSError:
                pass
    return texts


def tcl_tk_licences():
    """Tcl/Tk's license.terms from the Tcl/Tk that tkinter (and so the app) uses.

    Some Python builds don't ship them (Debian keeps them elsewhere); then the copies in
    tools/licences, taken from Tcl/Tk 8.6's source, are used.
    """
    found = []
    try:
        import tkinter
        tcl_lib = Path(tkinter.Tcl().eval("info library"))
        for folder in [tcl_lib, *sorted(tcl_lib.parent.glob("tk8*")), *sorted(tcl_lib.parent.glob("tk9*"))]:
            terms = folder / "license.terms"
            if terms.is_file():
                found.append((f"{folder.name}/license.terms", terms.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        pass
    if not found:
        found = [(f"{p.stem.split('-')[0].capitalize()} 8.6 license.terms", p.read_text(encoding="utf-8"))
                 for p in sorted((ROOT / "tools" / "licences").glob("*-license.terms"))]
    return found


def python_licence():
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
                      Path(sys.base_prefix) / "share" / "doc" / "python3" / "copyright"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def write_third_party(path):
    rule = "=" * 78
    parts = [f"Maze Coaster Maker {app_version()} is built from the following third-party software, "
             "each under its own licence. The full texts follow.", ""]
    missing = []

    py = python_licence()
    parts += [rule, f"Python {platform.python_version()} (PSF License)", rule,
              py or "Python Software Foundation License: https://docs.python.org/3/license.html"]
    if not py:
        missing.append("Python")

    tcl = tcl_tk_licences()
    parts += [rule, "Tcl/Tk (BSD-style licence), the toolkit that draws the window", rule]
    parts += [f"--- {name} ---\n{text}" for name, text in tcl] or ["Tcl/Tk licence: https://www.tcl.tk/software/tcltk/license.html"]
    if not tcl:
        missing.append("Tcl/Tk")

    for dist in bundled_distributions():
        md = dist.metadata
        parts += [rule, f"{md['Name']} {dist.version} ({licence_name(md)})", rule]
        if md["Name"].lower() == "shapely":
            geos = shapely_geos_version()
            parts.append(f"shapely includes GEOS {geos} (LGPL-2.1). GEOS source code: "
                         f"https://download.osgeo.org/geos/geos-{geos}.tar.bz2 , also attached to every "
                         "Maze Coaster Maker release on GitHub.\n")
        if md["Name"].lower() == "pyinstaller":
            parts.append("Only PyInstaller's bootloader is part of the app. Its licence allows that "
                         "(see the bootloader exception in the text below).\n")
        texts = licence_texts(dist)
        parts += [f"--- {name} ---\n{text}" for name, text in texts] or ["(no licence file found in the package)"]
        if not texts:
            missing.append(md["Name"])

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"third-party licences: {path.stat().st_size // 1024} KB" +
          (f"; missing texts for {', '.join(missing)}" if missing else ""))


def shapely_geos_version():
    import shapely
    return shapely.geos_version_string


# ---------------------------------------------------------------- build

def built_program():
    if SYSTEM == "windows":
        return WORK / "dist" / f"{NAME}.exe"
    if SYSTEM == "macos":
        return WORK / "dist" / f"{APP_TITLE}.app" / "Contents" / "MacOS" / APP_TITLE
    return WORK / "dist" / NAME


def selftest(program):
    """The packaged app builds and saves a coaster in every format without opening a window."""
    with tempfile.TemporaryDirectory() as out:
        run(program, "--selftest", out)
        made = sorted(p.suffix for p in Path(out).iterdir())
        if made != sorted([".3mf", ".dxf", ".step", ".stl", ".svg"]):
            raise SystemExit(f"self-test wrote {made}")
    print("self-test passed: 3MF, STL, STEP, DXF and SVG written")


def launch_check(program, shots):
    """Starts the packaged app with its window, checks it is still running after 15 s, and
    saves a screenshot to the shots folder. Catches start-up crashes the self-test can't see."""
    shots.mkdir(parents=True, exist_ok=True)
    settings = tempfile.mkdtemp()  # keep the check's settings out of the real ones on Windows and Linux
    proc = subprocess.Popen([str(program)], env={**os.environ, "APPDATA": settings, "XDG_CONFIG_HOME": settings})
    time.sleep(15)
    running = proc.poll() is None
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(shots / f"packaged-{SYSTEM}-{ARCH}.png")
    except Exception as e:  # some build machines' screens can't be captured
        print(f"screenshot skipped: {e}")
    if SYSTEM == "windows":  # the one-file .exe runs the app in a child process
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(settings, ignore_errors=True)
    if not running:
        raise SystemExit(f"the packaged app closed by itself within 15 s (exit code {proc.returncode})")
    print("launch check passed: the window stayed open")


def package(version):
    DIST.mkdir(exist_ok=True)
    stem = f"{NAME}-{version}-{SYSTEM}-{ARCH}"
    if SYSTEM == "windows":
        target = DIST / f"{stem}.exe"
        try:
            shutil.copy2(built_program(), target)
        except PermissionError:
            raise SystemExit(f"{target.name} is open, so it can't be replaced. Close it and build again.")
    elif SYSTEM == "macos":
        target = DIST / f"{stem}.zip"
        target.unlink(missing_ok=True)
        # ditto keeps the app's internal links and permissions, which a plain zip would break
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", WORK / "dist" / f"{APP_TITLE}.app", target)
    else:
        target = DIST / f"{stem}.tar.gz"
        with tarfile.open(target, "w:gz") as tar:
            tar.add(built_program(), arcname=f"{stem}/{NAME}")
            tar.add(ROOT / "LICENSE", arcname=f"{stem}/LICENSE")
            tar.add(WORK / "THIRD_PARTY_LICENSES.txt", arcname=f"{stem}/THIRD_PARTY_LICENSES.txt")
    (DIST / f"build-info-{SYSTEM}-{ARCH}.json").write_text(json.dumps(
        {"version": version, "system": SYSTEM, "arch": ARCH, "python": platform.python_version(),
         "geos": shapely_geos_version()}, indent=2))
    return target


def main():
    parser = argparse.ArgumentParser(description="Build the standalone app for this system into dist/.")
    parser.add_argument("--launch-check", metavar="FOLDER", type=Path,
                        help="also start the packaged app's window and save a screenshot to FOLDER")
    options = parser.parse_args()
    version = app_version()
    print(f"Building Maze Coaster Maker {version} for {SYSTEM} ({ARCH})", flush=True)
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir()
    run(sys.executable, ROOT / "tools" / "make_icon.py", WORK)
    write_third_party(WORK / "THIRD_PARTY_LICENSES.txt")

    sep = os.pathsep
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--distpath", WORK / "dist", "--workpath", WORK / "pyinstaller", "--specpath", WORK,
            "--add-data", f"{ROOT / 'LICENSE'}{sep}.",
            "--add-data", f"{WORK / 'THIRD_PARTY_LICENSES.txt'}{sep}.",
            "--add-data", f"{WORK / 'app.png'}{sep}assets",
            "--add-data", f"{WORK / 'app.ico'}{sep}assets"]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    if SYSTEM == "macos":
        # a .app folder: PyInstaller no longer supports single-file macOS apps
        args += ["--onedir", "--name", APP_TITLE, "--icon", WORK / "app.png",
                 "--osx-bundle-identifier", "io.github.corautem.mazecoastermaker"]
    elif SYSTEM == "windows":
        args += ["--onefile", "--name", NAME, "--icon", WORK / "app.ico"]
    else:  # Linux programs carry no icon of their own; the window sets it at start-up
        args += ["--onefile", "--name", NAME]
    run(*args, ROOT / "coaster_app.py")
    selftest(built_program())
    if options.launch_check:
        launch_check(built_program(), options.launch_check)
    target = package(version)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"Done: {target} ({target.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
