# Windows Tools

This folder contains the Windows-specific scripts behind the Codrex launcher.

Normal use:
- daily launch: `..\..\Codrex.cmd`
- first-time bootstrap: `..\..\Setup.cmd`

Advanced tools kept here:
- `mobile-launcher.ps1`: launcher UI used by `Codrex.cmd`
- `start-mobile.ps1` / `stop-mobile.ps1`: direct stack control
- `start-mobile.ps1 -DevUi`: optional developer-only Vite runtime on `54312` or the next free port
- `mobile-tray.ps1`: tray mode
- `controller-launcher.ps1`: controller-only utility UI
- `install-autostart.ps1` / `uninstall-autostart.ps1`: scheduled-task setup

Port behavior:
- Codrex prefers controller port `48787` for the main app.
- If that port is busy, startup moves to the next free port and writes the actual port to `controller.config.json`.

Legacy `.cmd` wrappers are kept under `legacy-launchers/` for compatibility only.
