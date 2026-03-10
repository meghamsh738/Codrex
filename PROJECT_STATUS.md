# Project Status

## Current State

- Canonical repo: `E:\coding projects\codex-remote-ui`
- Daily launch: `Setup.cmd` once, then `Codrex.cmd`
- Main app URL: `http://127.0.0.1:8787`
- Fallback controls: `http://127.0.0.1:8787/legacy`
- Mobile app behavior kept:
  - install prompt support
  - manifest icons and standalone launch mode
  - lightweight service worker registration
- Core product features currently present:
  - mobile-first Codex sessions UI with smoother streaming
  - session-scoped file attachments plus `Copy Path` and `Send via Telegram`
  - tmux thread monitor
  - remote desktop controls
  - power controls and wake-readiness diagnostics

## Security Status

- The previous `npm audit` findings were tied to the PWA build plugin chain, not the Python backend or the runtime React dependencies.
- The PWA plugin path has been replaced with a small manual manifest plus service worker flow so installability can stay without the heavier audited dependency chain.
- Current `npm audit` result: `0 vulnerabilities`.
- Frontend validation has passed from the Windows toolchain used for daily development:
  - `npm run lint`
  - `npm run test`
  - `npm run build`
  - `npm run test:e2e`

## Current TODO

- Manually verify mobile install/add-to-home-screen behavior from `8787`.
- Deploy and test the wake relay only if remote wake is still needed later.
