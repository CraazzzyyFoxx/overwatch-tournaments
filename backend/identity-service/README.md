# Authentication Service

Microservice for user authentication and authorization.

## Features

- 🔐 User registration with validation
- 🔑 Authentication by email and password
- 🎫 JWT tokens (access + refresh)
- 🔄 Token refresh
- 👤 Read and update the user profile
- 🚪 Logout from one or all sessions
- ✅ Token validation for other microservices
- 🎮 **Discord OAuth** — sign in via Discord
- 🔗 **Discord linking** — attach a Discord account to an existing user
- 👥 **Player linking** — attach in-game player profiles to an auth user

## Technologies

- **FastAPI** — web framework
- **SQLAlchemy 2.0+** — ORM with async support
- **PostgreSQL** — database (shared with the main application)
- **JWT** (python-jose) — authentication tokens
- **Bcrypt** (passlib) — password hashing
- **Pydantic** — data validation
- **Loguru** — logging
- **HTTPX** — HTTP client for the Discord API

## Project structure

```
auth-service/
├── main.py              # Entry point
├── pyproject.toml       # Dependencies
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker composition
├── .env.example         # Example environment variables
└── src/
    ├── core/            # Core configuration
    │   ├── config.py    # Application settings
    │   ├── db.py        # Database
    │   └── logging.py   # Logging
    ├── models.py        # Re-exports models from shared
    ├── schemas/         # Pydantic schemas
    │   └── auth.py
    ├── services/        # Business logic
    │   └── auth_service.py
    └── routes/          # API endpoints
        ├── auth.py      # Authentication
        └── health.py    # Health checks
```

## Setup and run

### Local run

1. Sync dependencies from the backend workspace and activate the virtualenv:

```bash
cd backend
uv sync
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
```

2. Copy `.env.example` to `.env` and configure the variables:

```bash
cp .env.example .env
```

3. Run the service:

```bash
python main.py
```

The service will be available at `http://localhost:8001`.

### Docker run

1. Create an `.env` file with the required variables.

2. Start the service (typically as part of the root `docker compose` stack):

```bash
docker compose up -d auth-service
```

3. Check the health endpoint:

```bash
curl http://localhost:8001/health
```

## API endpoints

### Core endpoints

- `GET /` — service info
- `GET /health` — health check
- `GET /docs` — Swagger documentation
- `GET /redoc` — ReDoc documentation

### Authentication

- `POST /register` — register a new user
- `POST /login` — log in (obtain tokens)
- `POST /refresh` — refresh the access token
- `POST /logout` — log out (revoke the token)
- `POST /logout-all` — log out from all devices
- `POST /set-password` 🔒 — set/change password
- `GET /me` — get the current user
- `PATCH /me` — update the profile
- `POST /validate` — validate a token (for other services)

### OAuth (Discord)

- `GET /oauth/discord/url` — get the Discord authorization URL
- `GET /oauth/discord/callback` — handle the Discord callback (GET version)
- `POST /oauth/discord/callback` — handle the Discord callback (POST version)
- `POST /oauth/discord/link` 🔒 — link Discord to the account
- `DELETE /oauth/discord/unlink` 🔒 — unlink Discord
- `GET /oauth/connections` 🔒 — all OAuth connections for the account

### Player linking

- `POST /player/link` 🔒 — link an in-game player
- `DELETE /player/unlink/{player_id}` 🔒 — unlink a player
- `GET /player/linked` 🔒 — list linked players
- `PATCH /player/linked/{player_id}/primary` 🔒 — set the primary player

🔒 — requires authorization.

## Usage examples

### Register

```bash
curl -X POST "http://localhost:8001/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "testuser",
    "password": "Password123",
    "first_name": "John",
    "last_name": "Doe"
  }'
```

### Log in

```bash
curl -X POST "http://localhost:8001/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "Password123"
  }'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "a1b2c3...",
  "token_type": "bearer"
}
```

### Use a token

```bash
curl -X GET "http://localhost:8001/me" \
  -H "Authorization: Bearer eyJ..."
```

### Refresh a token

```bash
curl -X POST "http://localhost:8001/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "a1b2c3..."
  }'
```

## Integration with other services

Other microservices can validate tokens through the `/validate` endpoint:

```python
import httpx

async def validate_token(token: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://auth-service:8001/validate",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            return response.json()  # TokenPayload
        return None
```

## Configuration

Key environment variables (see `.env.example`):

```bash
# Application
ENVIRONMENT=development
DEBUG=True
HOST=0.0.0.0
PORT=8001

# Database (shared with the main app)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=tournaments

# JWT
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
```

## Database

The service uses the **shared database** together with the main application:

- Tables are created via Alembic migrations in the main application.
- The auth service connects to the existing `auth_users` and `refresh_tokens` tables.
- No separate migrations are required for the auth service.

## Development

### Logging

Logs are emitted through Loguru with colored formatting:

```
2024-01-15 12:00:00.000 | INFO     | Starting Authentication Service...
2024-01-15 12:00:01.000 | SUCCESS  | Database connection established
2024-01-15 12:00:02.000 | INFO     | Registering new user: user@example.com
```

### Security

- ✅ Passwords are hashed with bcrypt
- ✅ JWT tokens are signed with a secret key
- ✅ Refresh tokens are stored in the database
- ✅ Token revocation is supported
- ✅ Password-strength validation
- ✅ CORS middleware

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   Client    │────▶│ Auth Service │────▶│  PostgreSQL  │
│ (Frontend)  │     │  (Port 8001) │     │  (Shared DB) │
└─────────────┘     └──────────────┘     └──────────────┘
                            │                     ▲
                            │                     │
                            ▼                     │
                    ┌──────────────┐              │
                    │  Main App    │──────────────┘
                    │ (Port 8000)  │
                    └──────────────┘
```

## Monitoring

A health-check endpoint is available for monitoring:

```bash
curl http://localhost:8001/health
```

Response:

```json
{
  "status": "healthy",
  "service": "auth-service"
}
```

## License

This service is part of the OWT project, licensed under the GNU AGPL v3.0 with additional attribution
terms. See the repository-root [LICENSE](../../LICENSE).
