# Discord Service

Discord bot integration for OWT. It connects the platform to a Discord server for notifications, commands,
and other community-facing interactions.

- **Entry point:** `main.py` (long-running Discord bot process)
- **Compose profile:** `workers` (started with `docker compose --profile workers up -d`)

## Responsibilities

- Run the Discord bot (built on [discord.py](https://discordpy.readthedocs.io/)).
- Deliver tournament/registration notifications to Discord.
- Act as an authenticated service client of `auth-service` (it holds a service client id/secret and is
  granted scopes such as `parser:logs`).

## Running

```bash
# Local
python main.py

# Docker (workers profile)
docker compose --profile workers up -d discord
```

## Configuration & environment

See `backend/env/discord.env`, which inherits `backend/env/common.env`. Required settings include the
Discord bot token, the service client credentials (`SERVICE_CLIENT_ID` / `SERVICE_CLIENT_SECRET`), and an
optional outbound proxy (`PROXY_HOST` / `PROXY_PORT`).
