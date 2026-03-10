# Project Status

## Current State

- Canonical repo: `E:\coding projects\codex-remote-ui`
- Daily launch: `Setup.cmd` once, then `Codrex.cmd`
- Launcher shell: `Codrex.cmd` opens the Windows launcher and the main web app after setup/start succeeds
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

## Latest Milestones

- `faeed21`: stabilized launcher/runtime state, authoritative session record, setup auto-launch, and launcher health handling
- current working tree: session notes, runtime/version visibility in the web app, fullscreen remote controls, and project tracking refresh

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
  - confirm `Setup.cmd` leaves a readable success/failure summary instead of closing too fast
  - confirm launcher `Stop` truly clears the controller and session file in real usage
  - confirm the web app clearly feels separate from the launcher shell
- Polish the browser-based remote control further:
  - add better drag/selection handling
  - add richer quick-key/modifier combinations for tablet use
  - assess whether higher refresh capture presets are needed
- Manually verify mobile install/add-to-home-screen behavior from the active controller port.
- Deploy and test the wake relay only if remote wake is still needed later.
