# Windows Tools

This folder contains the Windows-specific scripts behind the Codrex launcher.

Normal use:
- daily launch: `..\..\Codrex.cmd`
- first-time bootstrap: `..\..\setup.ps1`

Advanced tools kept here:
- `mobile-launcher.ps1`: launcher UI used by `Codrex.cmd`
- `start-mobile.ps1` / `stop-mobile.ps1`: direct stack control
- `mobile-tray.ps1`: tray mode
- `controller-launcher.ps1`: controller-only utility UI
- `install-autostart.ps1` / `uninstall-autostart.ps1`: scheduled-task setup

Legacy `.cmd` wrappers are kept under `legacy-launchers/` for compatibility only.
