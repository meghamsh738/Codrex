# Android UX Refactor Plan

Date: 2026-03-03
Repo: `E:\coding projects\codex-remote-ui`

## Progress Snapshot
- Phase 1: Done
- Phase 2: Done
- Phase 3: Done
- Phase 4: Done
- Phase 5: Done
- Phase 6: Partial (local laptop quick-auth added; full no-login launcher bundling still pending)

## Goals
- Keep all existing core functionality (Codex sessions, tmux control, remote desktop, pairing/auth).
- Simplify information architecture for phone/tablet usage.
- Improve visual quality so it feels app-like on Android.
- Make model + reasoning controls explicit and effective at runtime.
- Reduce login friction while preserving secure pairing behavior.

## Requested Product Decisions
1. `Sessions` = Codex sessions only.
2. `Threads` = tmux sessions + shell execution workflows (including previous tools-like actions).
3. `Remote` = remote desktop and screenshot capture only.
4. Remove `Tools` tab from top/bottom nav.
5. Pairing UI should show one clear QR action (avoid duplicate/confusing QR sections).
6. Settings should include theme switcher (dark mode required).
7. Settings should include network diagnostics panel.
8. Model and reasoning should be dropdowns, defaulting to strongest available options.
9. Work mode controls must actually change execution behavior, not only prompt wording.
10. Login flow should support “launch on laptop then pair mobile by QR” without exposing raw token to mobile entry.

## Implementation Phases

### Phase 1: Information Architecture Refactor
- Update tab types/order/state to remove `tools`.
- Move tmux/powershell/shell utilities under `Threads` tab.
- Keep `Sessions` focused on Codex session lifecycle + prompts.
- Move screenshot capture controls from `Tools` into `Remote`.
- Update navigation icons/test IDs and keyboard cycling logic.
- Update UI tests for new tab structure.

Validation:
- `npm run test -- app-shell`
- Manual: verify all features previously in `Tools` are reachable in `Threads` or `Remote`.

### Phase 2: Pairing UX Cleanup
- Consolidate Pair tab to one QR-first flow.
- Keep generated pairing code and expiry details, but avoid extra “default/open app” duplicate QR.
- Keep route controls (LAN/Tailscale) and safety messaging.
- Keep copy/open link actions.

Validation:
- `npm run test -- app-shell`
- Manual: generate pairing QR and open `/auth/pair/consume` flow.

### Phase 3: Theme + Visual Polish
- Introduce theme state (`system`/`light`/`dark`) with local persistence.
- Add dark mode token set in `styles.css`.
- Apply improved spacing, hierarchy, and card polish for mobile.
- Preserve existing accessibility affordances and focus visibility.

Validation:
- `npm run test -- app-shell`
- Manual: switch themes in Settings and reload.

### Phase 4: Network Diagnostics
- Add diagnostics panel in Settings:
  - backend health/auth status
  - LAN/Tailscale reachability hints
  - current origin, selected pairing route, and quick warnings
- Reuse `/net/info` and `/auth/status` data; avoid new server dependencies unless needed.

Validation:
- `npm run test -- app-shell`
- Manual: verify warnings adapt when Tailscale IP is missing.

### Phase 5: Real Model/Reasoning Controls
- Add explicit dropdowns:
  - model selector
  - reasoning effort selector (`minimal/low/medium/high/xhigh`)
- Default strategy: pick highest tier from a configurable preferred model list.
- Backend changes:
  - extend `/codex/session` create payload to accept model + reasoning effort
  - apply to codex startup command (`codex -c model=... -c model_reasoning_effort=...`)
  - store metadata for each created session and expose via `/codex/sessions`
- UI changes:
  - save selected model/effort in local storage
  - show active model/effort in session badges

Validation:
- backend unit test update for session creation command generation
- `npm run test`
- `python3 -m pytest tests/test_run_wsl_bash.py` (and targeted new backend tests)

### Phase 6: Laptop-First Auth UX
- Preserve secure token model; do not disable auth globally.
- Improve friction by adding optional local “remember this browser” behavior based on existing auth cookie lifetime controls.
- Keep QR pairing as the mobile onboarding mechanism from authenticated laptop session.
- Ensure app launch path points user directly to Pair flow and no manual token sharing is needed for mobile.

Validation:
- Manual:
  - laptop logs in once
  - pairing QR grants mobile auth
  - mobile can access UI without typing token

## Regression Checklist (final)
- Sessions: create/send/interrupt/close, image send.
- Threads: tmux list/screen/send/ctrl-c + shell actions.
- Remote: desktop stream controls + screenshot capture.
- Pair: QR generation, expiry countdown, consume flow.
- Settings: theme, diagnostics, auth info, Android settings.
- Debug: app events/run list still visible.

## Test Commands
- `cd ui && npm install` (if node modules missing)
- `cd ui && npm run lint`
- `cd ui && npm run test`
- `cd ui && npm run build`
- `cd .. && python3 -m pytest tests/test_run_wsl_bash.py`
- If `pytest` is not installed: `cd .. && python3 -m unittest tests/test_run_wsl_bash.py`

## Notes
- Existing uncommitted repo changes are preserved.
- Work proceeds in small increments with verification after each phase.
