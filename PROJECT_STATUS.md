# Project Status

## Current State

- Canonical repo: `E:\coding projects\codex-remote-ui`
- Daily launch: `Setup.cmd` once, then `Codrex.cmd`
- Launcher shell: `Codrex.cmd` opens only the Windows launcher shell; the laptop browser app opens only when `Open App` is clicked
- Windows lifecycle path: `Setup.cmd` and the launcher both go through `tools/windows/codrex-runtime.ps1`
- Preferred controller port: `48787`, with automatic fallback to the next free port if that range is occupied
- Main app URL: `http://127.0.0.1:<active-port>/`
- Fallback controls: `http://127.0.0.1:<active-port>/legacy`
- Runtime status endpoint: `http://127.0.0.1:<active-port>/app/runtime`
- Mobile app behavior kept:
  - install prompt support
  - manifest icons and standalone launch mode
  - lightweight service worker registration
- Core product features currently present:
  - mobile-first Codex sessions UI with smoother streaming
  - session-scoped file attachments plus `Copy Path` and `Send via Telegram`
  - per-session notes workspace with `Save`, `Append Latest Response`, `Copy Latest Response`, `Copy Notes`, and `Clear Notes`
  - tmux thread monitor
  - browser-based remote desktop controls with fullscreen mode, trackpad/direct pointer modes, and quick-key actions
  - power controls and wake-readiness diagnostics
- launcher/runtime health reporting via `/app/runtime`
- runtime-local state now lives under `%LocalAppData%\Codrex\remote-ui\state`; tracked `controller.config.json` is defaults-only

## Latest Milestones

- `faeed21`: stabilized launcher/runtime state, authoritative session record, setup auto-launch, and launcher health handling
- `85e0d64`: fixed launcher startup session handoff so background start writes the runtime session correctly
- current working tree: headless Windows lifecycle script, launcher thin-shell conversion, manual-only browser open, manual QR flow, advanced-action collapse, repo-config drift removal, and runtime contract tests

## Security Status

- The previous `npm audit` findings were tied to the PWA build plugin chain, not the Python backend or the runtime React dependencies.
- The PWA plugin path has been replaced with a small manual manifest plus service worker flow so installability can stay without the heavier audited dependency chain.
- Current `npm audit` result: `0 vulnerabilities`.
- Frontend validation currently passes, with a known environment caveat:
  - `npm run lint`
  - `npm run test`
  - `npm run build`
  - `npm run test:e2e`
- On WSL against the mounted `E:` drive, Vite/Playwright artifact writes can fail with `EPERM` when copying build or report assets into repo-local output folders. The app itself still builds and the browser suite passes from the Windows toolchain, which matches the intended daily use on this machine.

## Current TODO

- Manual Windows verification:
  - confirm `Codrex.cmd` does not auto-open the laptop browser app
  - confirm the launcher transitions cleanly from `starting` to `running` in a live `Codrex.cmd` session
  - confirm `Stop` truly clears the controller and session file in real launcher usage
  - confirm launch/stop does not dirty tracked `controller.config.json`
- Polish the browser-based remote control further:
  - add better drag/selection handling
  - add richer quick-key/modifier combinations for tablet use
  - assess whether higher refresh capture presets are needed
- Manually verify mobile install/add-to-home-screen behavior from the active controller port.
- Deploy and test the wake relay only if remote wake is still needed later.
