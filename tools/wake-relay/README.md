# Wake Relay

Small stdlib-only Wake-on-LAN relay for the Codrex remote power flow.

## What it does

- `GET /health` returns relay status and the configured wake target.
- `POST /wake` sends a Wake-on-LAN magic packet to the configured laptop MAC.
- Both endpoints accept relay-token auth via `x-relay-token` or `Authorization: Bearer ...`.
- Optional Telegram long polling lets a dedicated wake bot handle `/wake` and `/status` for one allowed chat id.

## Configuration

Set these environment variables before starting the relay:

- `WAKE_RELAY_TARGET_MAC`: required laptop MAC address.
- `WAKE_RELAY_TOKEN`: shared token for the HTTP endpoints.
- `WAKE_RELAY_HOST`: default `0.0.0.0`
- `WAKE_RELAY_PORT`: default `8765`
- `WAKE_RELAY_BROADCAST_IP`: default `255.255.255.255`
- `WAKE_RELAY_WAKE_PORT`: default `9`
- `WAKE_RELAY_ALLOWED_CHAT_ID`: Telegram chat id allowed to use the wake bot.
- `WAKE_RELAY_TELEGRAM_BOT_TOKEN`: Telegram bot token for the dedicated wake bot.
- `WAKE_RELAY_TELEGRAM_API_BASE`: default `https://api.telegram.org`
- `WAKE_RELAY_WAKE_COMMAND`: default `/wake`

Telegram polling stays disabled unless both `WAKE_RELAY_ALLOWED_CHAT_ID` and `WAKE_RELAY_TELEGRAM_BOT_TOKEN` are set.

## Run

```bash
export WAKE_RELAY_TARGET_MAC="AA:BB:CC:DD:EE:FF"
export WAKE_RELAY_TOKEN="change-me"
python3 tools/wake-relay/wake_relay.py
```

## Quick checks

```bash
curl -H 'x-relay-token: change-me' http://127.0.0.1:8765/health
curl -X POST -H 'x-relay-token: change-me' http://127.0.0.1:8765/wake
```

## Notes

- Keep this relay on a device that stays online when the laptop is powered off.
- The wake bot should be separate from the laptop-hosted Telegram file delivery bot.
- Wake-on-LAN still depends on BIOS/UEFI and Windows adapter power settings being configured correctly.
- On many laptops, Wi-Fi wake is unsupported or unreliable. Prefer Ethernet when validating remote wake.
- The Codrex Remote tab shows `ready`, `partial`, or `unsupported` wake diagnostics; treat `partial` and `unsupported` as warnings, not guarantees.
