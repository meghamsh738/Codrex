# Security Patch Follow-up Plan (2026-03-04)

Scope from user report after latest security pass.

## Issue 1: Telegram send fails with `Login required`
- [x] Diagnose auth path used by `tools/codrex-send.py`
- [x] Load token from `controller.config.local.json` (fallback from tracked config)
- [x] Ensure base URL discovery still works in WSL/Windows mixed environment
- [x] Add/adjust tests for helper config resolution logic
- [x] Verify end-to-end by sending a real test file to Telegram

## Issue 2: Remote live stream behavior/regression
- [x] Restore "view-only stream when control is off" behavior
- [x] Keep input actions blocked when control is off
- [x] Improve Ultra/Extreme readability (profile tuning + defaults)
- [x] Verify Remote tab behavior manually + unit tests where feasible

## Issue 3: Ambiguous short-form control labels
- [x] Replace cryptic short labels with compact full-text labels
- [x] Keep compact footprint (small font/pill buttons)
- [x] Verify readability on mobile width

## Finalization
- [x] Run backend + frontend tests
- [x] Update changelog notes
- [x] Send Telegram "done" message from app pipeline

## Notes
- Root cause for issue #1 was `codrex-send` still reading tracked `controller.config.json` (empty token) after token migration to `controller.config.local.json`.
- Remote view now keeps desktop stream visible even when control is disabled; input endpoints remain blocked by backend mode checks.
