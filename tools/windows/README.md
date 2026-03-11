# Windows Tools

This folder contains the Windows-specific scripts behind the Codrex launcher stack.

Normal use:
- daily launch: `..\..\Codrex.cmd`
- first-time bootstrap: `..\..\Setup.cmd`
- launcher behavior: `Codrex.cmd` prefers the .NET 8 WebView2 desktop launcher and falls back to the legacy PowerShell launcher if the desktop launcher has not been built yet
- browser behavior: the laptop browser app opens only when you click `Open App`
- pairing behavior: QR generation is manual via `Show Pair QR`

Advanced tools kept here:
- `mobile-launcher.ps1`: legacy launcher UI kept as a compatibility fallback
- `build-launcher.ps1`: publishes the .NET 8 WebView2 desktop launcher
- `codrex-runtime.ps1`: authoritative JSON lifecycle entrypoint used by setup and the launcher
- `start-mobile.ps1` / `stop-mobile.ps1`: direct stack control
- `start-mobile.ps1 -DevUi`: optional developer-only Vite runtime on `54312` or the next free port
- `mobile-tray.ps1`: tray mode
- `controller-launcher.ps1`: controller-only utility UI
- `install-autostart.ps1` / `uninstall-autostart.ps1`: scheduled-task setup

Port behavior:
- Codrex prefers controller port `48787` for the main app.
- If that port is busy, startup moves to the next free port and writes the effective runtime config to `%LocalAppData%\Codrex\remote-ui\state\controller.config.local.json`.
- `controller.config.json` remains the tracked defaults file and is no longer rewritten during normal launcher/runtime use.

Legacy `.cmd` wrappers are kept under `legacy-launchers/` for compatibility only.
