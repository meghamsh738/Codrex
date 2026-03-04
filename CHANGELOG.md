# Changelog

All notable changes to this project are documented in this file.

The format follows Keep a Changelog and the project uses Semantic Versioning.

## [1.4.0] - 2026-03-04

### Added
- New mobile-first React/PWA interface under `ui/` with sessions, threads, remote, pairing, settings, and debug tabs.
- New Windows app-style launch utilities:
  - `start-mobile.ps1` / `stop-mobile.ps1`
  - `mobile-launcher.ps1` and `Start Mobile App.cmd`
  - `mobile-tray.ps1` and tray command wrappers.
- Session image upload delivery modes:
  - `insert_path`
  - `desktop_clipboard`
  - `session_path`.
- Network diagnostics and pairing route helpers for LAN/Tailscale workflows.
- Expanded automated test coverage for session profile logic, remote behavior, and UI shell flows.

### Changed
- Default UX updated for Android/tablet control:
  - improved spacing and touch behavior,
  - improved dark theme consistency,
  - better full-width layout usage.
- Codex-family model handling now enforces supported reasoning levels (`low|medium|high`) and auto-repairs stale session profiles before send.
- Remote tab performance tuned:
  - reduced background polling load when other tabs are inactive,
  - added low-data `Ultra` stream profile (downscale + grayscale),
  - improved remote text/paste reliability by using desktop clipboard route.
- Remote screenshot capture now uses desktop capture endpoint with active stream profile settings.

### Fixed
- Prevented image-path prompt sends from failing on codex-family sessions with stale `xhigh` reasoning.
- Restored reliable remote paste/text injection in desktop control workflows.
- Corrected Remote screenshot capture flow to use desktop frame capture instead of generic shot endpoint.

## [1.3.0] - 2026-02-18

### Added
- Release metadata files: `VERSION` and `CHANGELOG.md`.
- One-command Windows bootstrap script: `setup.ps1`.
- README quick install section for desktop and mobile onboarding.
- Project badges and formal versioning policy section.

### Changed
- Release docs expanded with first-run and operational workflows.
- App version metadata aligned for the 1.3.0 release.

## [1.2.0] - 2026-02-18

### Added
- Initial Codrex code import from local controller project.
- Full controller stack: FastAPI app, launcher scripts, autostart/watchdog scripts.
- Unit test suite (`tests/test_run_wsl_bash.py`).
- Screenshot assets and baseline setup/tutorial documentation.
