## Downloads

| Computer | File |
|---|---|
| Windows | `MazeCoasterMaker-VERSION-windows-x64.exe` |
| Mac with Apple silicon (M1 or newer) | `MazeCoasterMaker-VERSION-macos-arm64.zip` |
| Mac with an Intel processor | `MazeCoasterMaker-VERSION-macos-x64.zip` |
| Linux | `MazeCoasterMaker-VERSION-linux-x64.tar.gz` |
| Linux on ARM, such as a 64-bit Raspberry Pi | `MazeCoasterMaker-VERSION-linux-arm64.tar.gz` |

Nothing to install, and you don't need Python.

- **Windows:** double-click the `.exe`. The first time, Windows may show "Windows protected your PC", because the app isn't code-signed. Click **More info**, then **Run anyway**.
- **Mac:** unzip it and drag **Maze Coaster Maker** into Applications. The first time, macOS blocks it because it isn't signed by Apple: open it, close the message, then go to **System Settings → Privacy & Security** and click **Open Anyway**.
- **Linux:** unpack it and run `MazeCoasterMaker`. It needs glibc 2.35 or newer, as in Ubuntu 22.04, Debian 12, Fedora 36 and later.

`geos-*.tar.bz2` is the source code of GEOS, a geometry library inside the app; GEOS's licence (LGPL) asks for its source to be offered with the app. Maze Coaster Maker's own source code is in the "Source code" archives below.
