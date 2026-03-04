# Changelog

All notable changes to this project are documented in this file.

The format follows Keep a Changelog and the project uses Semantic Versioning.

## [Unreleased]

### Added
- Deterministic shared-file outbox APIs:
  - `GET /shares`
  - `POST /shares`
  - `DELETE /shares/{share_id}`
  - `GET /share/file/{share_id}`
- Telegram delivery support for shared files:
  - `GET /telegram/status`
  - `POST /shares/{share_id}/telegram`
  - `codrex-send ... --telegram [--caption ...]` command option.
  - automatic token loading from `Telegram bot/key.txt`
  - automatic chat-id resolution via Telegram updates (or `Telegram bot/chat_id.txt`).
- New WSL helper script:
  - `tools/codrex-send.py`
  - auto-linked to `~/.local/bin/codrex-send` on controller startup.
- Codex session command interception for share commands:
  - `codrex-send <path> [--title ...] [--expires <hours>] [--telegram] [--caption ...]`
  - aliases: `/codrex-send`, `/send-file`, `/share-file`, `tgsend`, `/tgsend`
  - optional override flag: `--no-telegram`
- New **Shared Files Inbox** panel in Sessions tab with:
  - direct share creation,
  - command copy helper,
  - open/copy-link/remove actions,
  - one-click **Send Telegram** action.
- Config-driven Telegram default-send toggle via `controller.config.json`:
  - `"telegramDefaultSend": true|false`
  - exported to backend as `CODEX_TELEGRAM_DEFAULT_SEND`.

### Changed
- Vite dev/preview proxy now includes `/shares`, `/share`, and `/telegram` routes.
- Expanded backend/unit and UI/API test coverage for outbox + Telegram flows.
- Codex session launch now prepends `~/.local/bin` to PATH so helper commands are available from Codex.
- Sessions UI now hides Shared Files Inbox when Telegram is configured, keeping file-share UX focused on direct command flow.
- Action-heavy controls across Sessions/Threads/Remote/Pair/Debug now use compact pill-style buttons to reduce large text-box UI density.
- Added lightweight tab deep-link support via `?tab=<name>` for direct navigation and documentation screenshots.
- Refreshed screenshot assets in `screenshots/` and updated README with complete A-to-Z setup + security hardening guidance.
- Pairing route defaults are now Tailscale-first in WebUI, and LAN/current route hints are restricted to localhost browser context.
- Screenshot assets were split into:
  - new WebUI screenshots in `screenshots/`
  - legacy UI archive screenshots in `screenshots/legacy/`

### Security
- Sanitized tracked `controller.config.json` token value to empty default so a real auth token is generated locally on first run, not committed in git.
- `/auth/bootstrap/local` now requires a loopback client address, reducing risk from Host/Origin header spoofing.
- `start-controller.ps1` now stores runtime auth token in untracked `controller.config.local.json` and masks token in console output.
- `/telegram/status` no longer exposes local secret-file paths.

## [1.4.1] - 2026-03-04

### Added
- New `Extreme` remote stream profile in the mobile UI for very weak connections:
  - ~1.5 FPS target
  - max stream downscale (`scale=6`)
  - grayscale rendering (`bw=1`)

### Changed
- Remote stream profile selector now includes:
  - `Responsive`
  - `Balanced`
  - `Saver`
  - `Ultra`
  - `Extreme`
- Release metadata updated to `1.4.1`.

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
