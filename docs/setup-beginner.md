# Codrex Setup Guide For Beginners

This guide is for a first-time Windows user who wants to run Codrex locally, open the web UI, pair a phone or tablet, and optionally send files through Telegram.

## 1. What Codrex needs

Install these on Windows first:
- Windows 10 or Windows 11
- WSL2
- an Ubuntu WSL distro
- Python 3.11 or newer on Windows
- Node.js 20 or newer on Windows
- Git
- WebView2 runtime for the Windows launcher

Optional but recommended:
- Tailscale for safer remote access
- Telegram on your phone and BotFather if you want Telegram delivery

## 2. Clone the repository

Open PowerShell and run:

```powershell
git clone https://github.com/meghamsh738/Codrex.git
Set-Location .\Codrex
```

If you prefer a different folder, clone it there. The guide assumes your current folder is the repository root.

## 3. Decide your WSL work directory

Codrex keeps session files and uploads inside a WSL work directory.

The current default config in this repository uses:

```text
/home/megha/codrex-work
```

If your Ubuntu username is not `megha`, change `controller.config.json` before first launch:

```json
{
  "port": 48787,
  "distro": "Ubuntu",
  "workdir": "/home/<your-linux-user>/codrex-work",
  "fileRoot": "/home/<your-linux-user>/codrex-work",
  "token": "",
  "telegramDefaultSend": true
}
```

Then create the folders inside WSL:

```powershell
wsl -d Ubuntu -- bash -lc "mkdir -p /home/<your-linux-user>/codrex-work/output"
```

If you keep the default `/home/megha/codrex-work`, create that folder instead:

```powershell
wsl -d Ubuntu -- bash -lc "mkdir -p /home/megha/codrex-work/output"
```

## 4. Run first-time setup

From the repository root:

```powershell
.\Setup.cmd
```

What `Setup.cmd` does:
- creates the Windows virtual environment in `.venv`
- installs Python dependencies
- installs UI dependencies
- builds the React UI
- builds the Windows launcher if the .NET 8 SDK is installed
- starts the backend stack

If you want the Windows firewall rule opened during setup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -OpenFirewall
```

## 5. Start Codrex after setup

For normal daily use:

```powershell
.\Codrex.cmd
```

What to expect:
- the Windows launcher opens
- the backend starts on `http://127.0.0.1:48787` unless that port is busy
- if `48787` is already in use, Codrex moves to the next free port automatically

If the launcher is not available yet, the backend still starts and you can open the browser manually.

## 6. Open the local web UI

Use one of these:
- click `Open App` in the launcher
- or open the local URL in a browser manually

Typical local address:

```text
http://127.0.0.1:48787
```

Tabs you should see:
- `Sessions`
- `Threads`
- `Remote`
- `Pair`
- `Settings`
- `Debug`

## 7. Pair a phone or tablet

Recommended path:
- keep the controller reachable only on a trusted network, private LAN, or Tailscale
- open the UI on your laptop first
- go to the `Pair` tab
- leave the route on `Tailscale` if you use Tailscale
- click `Generate QR`
- scan the QR code from your phone or tablet

Important details:
- the long-lived controller token is stored locally, not in the public QR URL
- the pairing code is short-lived
- LAN and current-origin pairing routes are intentionally more restricted than the local laptop flow

## 8. Configure Telegram delivery

Telegram is optional. Use it only if you want Codrex to send files or text to your Telegram account or chat.

### 8.1 Create a bot

In Telegram:
1. Open `@BotFather`
2. Send `/newbot`
3. Choose a bot name
4. Choose a bot username
5. Copy the bot token BotFather gives you

### 8.2 Save the bot token locally

Create the local secrets folder and save the token:

```powershell
New-Item -ItemType Directory -Force -Path "$env:LocalAppData\Codrex\remote-ui\secrets\telegram" | Out-Null
Set-Content -Path "$env:LocalAppData\Codrex\remote-ui\secrets\telegram\key.txt" -Value "<BOT_TOKEN>"
```

Local files used by Codrex:
- token: `%LocalAppData%\Codrex\remote-ui\secrets\telegram\key.txt`
- chat id: `%LocalAppData%\Codrex\remote-ui\secrets\telegram\chat_id.txt`

Do not store the bot token in the repository.

### 8.3 Let Codrex discover your chat id automatically

Codrex can discover the Telegram chat id from recent bot updates.

Do this:
1. Open your new bot in Telegram
2. Send it a message such as `/start`
3. Restart Codrex:

```powershell
.\tools\windows\stop-mobile.ps1
.\Codrex.cmd
```

4. Open the UI and check `GET /telegram/status` in the browser or through the app

What should happen:
- the bot token is read from `key.txt`
- Codrex calls Telegram `getUpdates`
- the latest chat id is discovered
- the discovered chat id is saved to `%LocalAppData%\Codrex\remote-ui\secrets\telegram\chat_id.txt`

Once both token and chat id are available, `/telegram/status` should report:
- `configured: true`

### 8.4 Manual chat id fallback

If auto-discovery does not work, you can put the chat id in the local file yourself:

```powershell
Set-Content -Path "$env:LocalAppData\Codrex\remote-ui\secrets\telegram\chat_id.txt" -Value "<CHAT_ID>"
```

Keep that file local. Do not commit it.

## 9. Where Codrex stores local state

These paths are local to your machine and should stay out of Git:

```text
%LocalAppData%\Codrex\remote-ui\state\
%LocalAppData%\Codrex\remote-ui\logs\
%LocalAppData%\Codrex\remote-ui\secrets\
```

Examples:
- controller config override: `%LocalAppData%\Codrex\remote-ui\state\controller.config.local.json`
- mobile session state: `%LocalAppData%\Codrex\remote-ui\state\mobile.session.json`
- Telegram token: `%LocalAppData%\Codrex\remote-ui\secrets\telegram\key.txt`
- Telegram chat id: `%LocalAppData%\Codrex\remote-ui\secrets\telegram\chat_id.txt`

## 10. Session files and uploads

Codex session uploads are isolated by session inside the WSL work directory.

Example path:

```text
/home/<your-linux-user>/codrex-work/.remote_uploads/<session>/
```

If you kept the repository default config, the path will use `/home/megha/codrex-work/...`.

From a Codex session you can still use the helper command:

```bash
tgsend "/home/<your-linux-user>/codrex-work/output/result.png" --title "Result" --expires 24
```

Alias also supported:

```bash
codrex-send "/home/<your-linux-user>/codrex-work/output/result.png" --title "Result" --expires 24
```

## 11. Stop Codrex

Use:

```powershell
.\tools\windows\stop-mobile.ps1
```

## 12. Safe networking recommendations

Recommended:
- use localhost on the laptop
- use Tailscale or a trusted private LAN for remote devices
- keep controller auth enabled
- use the QR pairing flow instead of manually sharing tokens

Avoid:
- exposing the controller port directly to the public internet
- committing local config overrides, tokens, chat ids, or runtime logs
- publishing screenshots taken from a real private desktop session

## 13. Public screenshot workflow

The repository screenshots are intentionally generated from mocked data so the public repo does not leak:
- real hostnames
- real IP addresses
- real Codex prompts
- real session names
- real desktop captures
- secrets

To regenerate those public screenshots:

```powershell
Set-Location .\ui
npm install
npm run screenshots:public
```

That command refreshes:
- `screenshots/launcher-overview.png`
- `screenshots/webui-tab-sessions.png`
- `screenshots/webui-tab-threads.png`
- `screenshots/webui-tab-remote.png`
- `screenshots/webui-tab-pair.png`
- `screenshots/webui-tab-settings.png`
- `screenshots/webui-tab-debug.png`

## 14. Troubleshooting

If `Setup.cmd` fails:
- confirm Python 3.11+ is installed on Windows
- confirm Node.js and `npm` are installed on Windows
- confirm WSL and your Ubuntu distro are installed

If the launcher opens but the UI does not:
- open `http://127.0.0.1:48787` manually
- if that port is busy, look at the launcher or logs for the port Codrex selected

If Telegram shows as not configured:
- confirm `%LocalAppData%\Codrex\remote-ui\secrets\telegram\key.txt` exists
- send a message such as `/start` to the bot
- restart Codrex
- check `/telegram/status` again

If pairing does not work on mobile:
- generate the QR code from the laptop first
- prefer Tailscale if you have it
- keep the laptop and mobile device on the same trusted network if you use LAN pairing
