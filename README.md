# Deployment Recovery Demo API

Small FastAPI service used to demonstrate AI-agent deployment recovery.

- **v1** — healthy deployment (`GET /health` → HTTP 200)
- **v2** — intentionally unhealthy deployment (`GET /health` → HTTP 500)

Version is controlled by the `APP_VERSION` environment variable (default
`v1`). A new deployment starts a new process with a different
`APP_VERSION`. Other API endpoints continue to work in both versions.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.10+ (uv will fetch one if needed)
- Docker (optional)

## 1. Install dependencies

This project uses **uv** (not pip). Use the `./uvw` wrapper so the
virtualenv lives under `~/.cache/uv/envs/...` instead of inside this folder.

```bash
cd /home/brm/Project/automated-server-recovery
chmod +x uvw
./uvw sync
```

If you still have leftover local envs from earlier setup:

```bash
rm -rf venv .venv
```

## 2. Run locally (default = v1)

```bash
./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 3. Run v1 (healthy)

```bash
APP_VERSION=v1 ./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 4. Run v2 (simulated failure)

```bash
APP_VERSION=v2 ./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 5. Test `/health`

Healthy (v1):

```bash
curl -i http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"healthy","version":"v1"}
```

Unhealthy (v2):

```bash
curl -i http://127.0.0.1:8000/health
```

Expected HTTP 500:

```json
{"status":"unhealthy","version":"v2","reason":"simulated deployment failure"}
```

Other useful checks:

```bash
curl http://127.0.0.1:8000/version
curl http://127.0.0.1:8000/api/users
curl http://127.0.0.1:8000/api/orders
```

## 6. Build the Docker image

```bash
docker build -t recovery-demo-api .
```

## 7. Run the Docker container

v1 (healthy):

```bash
docker run --rm -p 8000:8000 -e APP_VERSION=v1 recovery-demo-api
```

v2 (simulated failure):

```bash
docker run --rm -p 8000:8000 -e APP_VERSION=v2 recovery-demo-api
```

Custom port:

```bash
docker run --rm -p 9000:9000 -e PORT=9000 -e APP_VERSION=v1 recovery-demo-api
```

## 8. Why v2 fails `/health`

`APP_VERSION=v2` makes `/health` return HTTP 500 with a simulated
deployment failure. Business endpoints (`/api/users`, `/api/orders`, etc.)
still respond normally. That split lets an agent detect an unhealthy
deploy and trigger recovery by starting a new process with
`APP_VERSION=v1`.

## API overview

| Method | Path              | Description                          |
|--------|-------------------|--------------------------------------|
| GET    | `/health`         | Health check (fails only in v2)      |
| GET    | `/version`        | Current `APP_VERSION`                |
| GET    | `/api/users`      | List users                           |
| GET    | `/api/users/{id}` | Get one user                         |
| GET    | `/api/orders`     | List orders                          |
| GET    | `/api/orders/{id}`| Get one order                        |
| POST   | `/api/orders`     | Create an order                      |

Create order example:

```bash
curl -X POST http://127.0.0.1:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "product": "Mouse", "amount": 29.99}'
```
