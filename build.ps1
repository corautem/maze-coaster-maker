# Builds dist\MazeCoasterMaker.exe: one standalone file that runs without installing or Python.
#
# Needs: pip install -r requirements.txt
# Run:   powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"  # keep __pycache__ folders out of the project
$root = $PSScriptRoot
$work = "$root\build"  # temporary; removed at the end
$version = [regex]::Match((Get-Content "$root\coaster_app.py" -Raw), 'APP_VERSION = "([^"]+)"').Groups[1].Value
Write-Host "Building Maze Coaster Maker $version" -ForegroundColor Cyan

python "$root\tools\make_icon.py" "$work\app.ico"
if ($LASTEXITCODE) { throw "icon build failed" }

python -m PyInstaller --noconfirm --clean --windowed --onefile --name MazeCoasterMaker `
    --icon "$work\app.ico" `
    --add-data "$work\app.ico;assets" `
    --add-data "$root\fusion\CoasterBuilder\CoasterBuilder.py;fusion\CoasterBuilder" `
    --add-data "$root\fusion\CoasterBuilder\CoasterBuilder.manifest;fusion\CoasterBuilder" `
    --exclude-module PySide6 --exclude-module shiboken6 --exclude-module PyQt5 `
    --exclude-module PyQt6 --exclude-module matplotlib --exclude-module PIL `
    --distpath "$work\dist" --workpath "$work\pyinstaller" --specpath "$work" "$root\coaster_app.py"
# (the excludes: ezdxf has optional viewers that would drag in ~90 MB of Qt; the app uses tkinter)
if ($LASTEXITCODE) { throw "PyInstaller failed" }
$built = "$work\dist\MazeCoasterMaker.exe"

# quick check that the packaged app can build and save a coaster (3MF, DXF, SVG) without Python
$check = Join-Path $env:TEMP "MazeCoasterMaker-selftest"
$proc = Start-Process $built -ArgumentList "--selftest", "`"$check`"" -Wait -PassThru
if ($proc.ExitCode) { throw "self-test failed (exit code $($proc.ExitCode))" }
Remove-Item $check -Recurse -Force

# built in build\ first so a running copy of the app only blocks this last, instant step
New-Item -ItemType Directory -Force "$root\dist" | Out-Null
try {
    Copy-Item $built "$root\dist\MazeCoasterMaker.exe" -Force
} catch {
    throw "Maze Coaster Maker is open, so dist\MazeCoasterMaker.exe can't be replaced. " +
          "Close the app and run this again, or copy $built yourself."
}
Remove-Item $work -Recurse -Force

$exe = Get-Item "$root\dist\MazeCoasterMaker.exe"
Write-Host ("Done: {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB)) -ForegroundColor Green
