# Deployment Recovery Demo API

Small FastAPI service used to demonstrate AI-agent deployment recovery.

- **v1** — healthy deployment (`GET /health` → HTTP 200)
- **v2** — intentionally unhealthy deployment (`GET /health` → HTTP 500)

The live deployment version is stored in `deployment_state.txt` at the
project root. Change that file while Uvicorn keeps running — no process
restart is required. Other API endpoints continue to work in both versions.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.10+ (uv will fetch one if needed)
- Docker (optional, for container runs)

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

## 2. Run locally

```bash
./uvw run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`deployment_state.txt` starts as `v1` (healthy).

## 3. Simulate a bad deployment (v2) — no restart

While the server is still running:

```bash
echo v2 > deployment_state.txt
curl -i http://127.0.0.1:8000/health
```

Expected HTTP 500:

```json
{"status":"unhealthy","version":"v2","reason":"simulated deployment failure"}
```

## 4. Roll back to a healthy deployment (v1) — no restart

```bash
echo v1 > deployment_state.txt
curl -i http://127.0.0.1:8000/health
```

Expected HTTP 200:

```json
{"status":"healthy","version":"v1"}
```

## 5. Test `/health` and other endpoints

```bash
curl -i http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/version
curl http://127.0.0.1:8000/api/users
curl http://127.0.0.1:8000/api/orders
```

## 6. Build the Docker image

```bash
docker build -t recovery-demo-api .
```

## 7. Run the Docker container

```bash
docker run --rm -p 8000:8000 recovery-demo-api
```

Custom port:

```bash
docker run --rm -p 9000:9000 -e PORT=9000 recovery-demo-api
```

To simulate deploy/rollback inside a container, mount or rewrite
`deployment_state.txt` the same way as locally.

## 8. Why v2 fails `/health`

Writing `v2` into `deployment_state.txt` makes `/health` return HTTP 500
with a simulated deployment failure. Business endpoints (`/api/users`,
`/api/orders`, etc.) still respond normally. That split lets an agent
detect an unhealthy deploy and trigger recovery (for example by writing
`v1` back) while the rest of the API remains observable — all without
restarting Uvicorn.

## API overview

| Method | Path              | Description                          |
|--------|-------------------|--------------------------------------|
| GET    | `/health`         | Health check (fails only in v2)      |
| GET    | `/version`        | Current version from state file      |
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
