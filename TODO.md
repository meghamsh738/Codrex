# Codrex TODO

## Active Milestone

- [x] Stabilize launcher/runtime state and setup flow
- [x] Add per-session notes with latest-response capture
- [x] Add browser-based fullscreen remote controls
- [x] Refresh tracked project status for rollback and handoff
- [ ] Manually validate launcher stop/start behavior on Windows after the latest changes
- [ ] Manually validate the notes flow from the real controller-backed app, not only mocked tests
- [ ] Manually validate tablet fullscreen remote control against a live desktop session

## Next Slices

- [ ] Decide whether the remote-control surface needs higher-frequency capture or codec improvements beyond the current browser-stream model
- [ ] Add persistent note export/import if session notes become long-lived planning artifacts
- [ ] Add an advanced launcher panel for force cleanup, log viewing, and runtime/session-file inspection
- [ ] Revisit wake-relay deployment only if hardware-supported remote wake is still a real need

## Environment Notes

- Windows is the primary development/runtime environment for this repo.
- WSL can run backend tests and frontend unit tests reliably.
- WSL builds and Playwright runs against the mounted `E:` drive can hit `EPERM` while writing dist/report artifacts; when that happens, validate `npm run build` and `npm run test:e2e` from the Windows toolchain instead of changing product behavior to fit the mount quirk.
