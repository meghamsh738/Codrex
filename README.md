# Codrex

![Version](https://img.shields.io/badge/version-1.4.1-0b7285)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Platform](https://img.shields.io/badge/platform-Windows%20%2B%20WSL-2D7D9A)
![FastAPI](https://img.shields.io/badge/api-FastAPI-009688)

Codrex is a Windows + WSL remote control app for Codex CLI sessions, tmux shells, and desktop control from laptop, mobile, and tablet.

It includes:
- mobile-first web UI (`/mobile` React/PWA)
- pairing flow with short-lived QR codes
- Codex session control, shell session monitor, and remote desktop controls
- optional Telegram delivery pipeline for generated files

## Screenshots

### Laptop WebUI (React)

![Codrex Laptop WebUI](screenshots/webui-laptop.png)

### Mobile WebUI (React/PWA)

![Codrex Mobile WebUI](screenshots/webui-mobile.png)

### Pairing Tab (WebUI)

![Codrex Pairing WebUI](screenshots/webui-pair.png)

### Legacy UI Archive

![Legacy Desktop UI](screenshots/legacy/codrex-desktop.png)
![Legacy Mobile UI](screenshots/legacy/codrex-mobile.png)
![Legacy Pairing UI](screenshots/legacy/codrex-pairing.png)

## A-to-Z Setup (Fresh Clone)

### 1) Prerequisites

On Windows host:
- Windows 10/11
- WSL2 with Ubuntu distro installed
- Python 3.11+ (Windows)
- Node.js 20+ (Windows)
- npm 9+ (Windows)
- Git

Optional but recommended:
- Tailscale for private remote access
- Telegram app + BotFather (if you want file delivery via Telegram)

### 2) Clone

```powershell
git clone git@github.com:meghamsh738/Codrex.git C:\codex-remote-ui
Set-Location C:\codex-remote-ui
```

### 3) Prepare WSL workdir

```powershell
wsl -d Ubuntu -- bash -lc "mkdir -p /home/megha/codrex-work/output"
```

If your Linux username is not `megha`, replace the path in config accordingly.

### 4) First bootstrap

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -OpenFirewall
```

What this does:
- creates/updates `.venv`
- installs Python deps
- starts controller
- can open firewall rule for the configured port

### 5) Start full mobile stack

```powershell
Set-Location C:\codex-remote-ui
.\start-mobile.ps1
```

Or use launcher UI:
- `Start Mobile App.cmd`

Expected URLs:
- Controller: `http://<your-lan-ip>:8787`
- Mobile UI (React): `http://<your-lan-ip>:4312`

### 6) Auth and pairing

On laptop browser:
1. Open `http://127.0.0.1:4312`
2. Go to **Pair** tab
3. Keep **Tailscale** route (default and recommended)
4. Generate QR
5. Scan on phone/tablet

Important:
- `controller.config.json` ships with empty token; `start-controller.ps1` auto-generates a strong token on first run.
- Generated token is stored in untracked `controller.config.local.json` (not in the tracked main config).
- Pair QR uses short-lived one-time code exchange and does not place the long token in URL.
- LAN/current pairing routes are intentionally restricted for localhost browser sessions only.
- `/docs`, `/redoc`, and `/openapi.json` are auth-protected whenever auth is enabled.

### 7) Telegram delivery (optional)

Create bot with BotFather, then save token locally:

```powershell
Set-Location C:\codex-remote-ui
Set-Content -Path ".\Telegram bot\key.txt" -Value "<BOT_TOKEN>"
```

Send one message to your bot from your Telegram account, then restart stack:

```powershell
.\stop-mobile.ps1
.\start-mobile.ps1
```

Verify from browser:
- `GET /telegram/status` should show `configured: true`

### 8) Use Codex + shell monitors

- **Sessions tab**: Codex sessions (create, prompt, screen stream, interrupt, Ctrl+C, close)
- **Threads tab**: tmux shell monitor (Ubuntu/PowerShell/CMD panes)
- **Remote tab**: desktop controls and screenshot capture
- **Pair tab**: QR auth/pairing

### 9) File send to Telegram from Codex

In a Codex session prompt, you can ask naturally:
- `Send that graph to Telegram.`

Or deterministic command:

```bash
tgsend "/home/megha/codrex-work/output/result.png" --title "Result" --expires 24
```

Alias also supported:

```bash
codrex-send "/home/megha/codrex-work/output/result.png" --title "Result" --expires 24
```

When Telegram is configured, `codrex-send` defaults to Telegram send if `telegramDefaultSend` is enabled.

## Daily Operations

Start:

```powershell
Set-Location C:\codex-remote-ui
.\start-mobile.ps1
```

Stop:

```powershell
Set-Location C:\codex-remote-ui
.\stop-mobile.ps1
```

Desktop launcher:
- Start: `Start Mobile App.cmd`

## Security Checklist (Recommended)

1. Keep auth enabled (`controller.config.local.json` should contain a non-empty `token` after first start).
2. Prefer Tailscale/private LAN; do not expose controller/UI ports directly to public internet.
3. Use Pair QR from an authenticated laptop session only.
4. Keep `Telegram bot/key.txt` local only (it is gitignored).
5. Rotate token if machine is shared or token was exposed.
6. Keep firewall rules scoped to trusted network profiles.
7. Keep `CODEX_COOKIE_SECURE=auto` (default). Use `always` behind HTTPS reverse proxies; avoid `never` except local HTTP testing.

## Known Security Risks

- If ports `8787`/`4312` are exposed to the public internet, attack surface increases significantly.
- If someone gets local filesystem access, they can read local runtime secrets and logs.
- Pair links are short-lived but still sensitive while valid; share only in trusted context.
- Telegram delivery sends files to the configured chat ID; treat bot token as a secret.
- If `CODEX_COOKIE_SECURE=never` is used on untrusted networks, auth-cookie interception risk increases.

## Feature Notes

- Reasoning options are model-aware (Codex-family models only support `low|medium|high`).
- Remote stream profiles include `Extreme` for very low bandwidth.
- `?tab=<name>` deep-link is supported for direct opening of tabs (`sessions`, `threads`, `remote`, `pair`, `settings`, `debug`).
- Desktop control mode is server-enforced globally; when disabled, input endpoints are blocked while live stream remains available in view-only mode.

## Development

Backend tests:

```bash
cd /mnt/c/codex-remote-ui
python3 -m unittest tests.test_run_wsl_bash
```

Frontend checks:

```bash
cd /mnt/c/codex-remote-ui/ui
npm run lint
npm run test
```

## Versioning

- Current release metadata: `VERSION` and `CHANGELOG.md`
- Changelog format: Keep a Changelog
