# Wingman Lite

A minimal Global Mission Workbench shell with a working **Wingman** AI assistant, built to
test the DRAGON pipeline end to end (build → scan → sign → Helm → deploy to dev on WDP).

Wingman calls Databricks Model Serving chat endpoints. The user picks the model from a
dropdown in the Wingman panel; the choice is remembered per browser.

```
browser ──► FastAPI (/api/chat, SSE stream) ──► Databricks /serving-endpoints/<model>/invocations
                   └─ /api/models ──────────────► Databricks /api/2.0/serving-endpoints (readiness)
```

The browser never sees Databricks credentials; the backend holds them.

## Run locally

```bash
pip install -r requirements.txt
# Mock mode: canned replies, no model access needed
WINGMAN_MOCK=true uvicorn app.main:app --port 8080
# Real models
export DATABRICKS_HOST=https://adb-xxxxxxxx.azuredatabricks.net
export DATABRICKS_TOKEN=dapi...            # or DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET
uvicorn app.main:app --port 8080
```

Open http://localhost:8080. API docs are at `/api/docs`.

Tests: `pip install pytest pytest-asyncio && pytest`

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `DATABRICKS_HOST` | Workspace URL. If unset, the app runs in mock mode. | — |
| `DATABRICKS_TOKEN` | PAT or service principal token | — |
| `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` | Service principal OAuth (M2M), used when no token is set | — |
| `WINGMAN_MODELS` | Comma-separated endpoint allowlist for the picker | the 9 `system.ai` chat endpoints |
| `WINGMAN_DEFAULT_MODEL` | Preselected model | first in the list |
| `WINGMAN_DISCOVER_MODELS` | Ask the workspace which allowlisted endpoints exist and are READY | `true` |
| `WINGMAN_MOCK` | Force canned replies | `false` |
| `WINGMAN_MAX_TOKENS`, `WINGMAN_TEMPERATURE`, `WINGMAN_TIMEOUT_SECONDS`, `WINGMAN_SYSTEM_PROMPT` | Model call tuning | 1024, 0.3, 120, Workbench prompt |

`databricks-genie` is left out on purpose: it is a Genie space with a different API, not a
chat endpoint.

The identity behind the credentials needs **Can Query** on each serving endpoint. If it
can't list endpoints, the picker falls back to the full allowlist.

## Deploying with DRAGON

`.gitlab-ci.yml` follows Scenario 2 of the Quick Start Guide:

```yaml
CONTAINER_BUILD: "true"
CONTAINER_DEPLOY: "true"
DEPLOY_DEV: "true"
```

Before the first pipeline run:

1. **Base image.** If WDP requires an approved base (e.g. Iron Bank), set `BASE_IMAGE` in
   the Dockerfile.
2. **Credentials.** Create the Secret in the dev namespace (name matches
   `existingSecret` in `chart/values.yaml`):
   ```bash
   kubectl -n <namespace> create secret generic wingman-databricks \
     --from-literal=DATABRICKS_CLIENT_ID=... --from-literal=DATABRICKS_CLIENT_SECRET=...
   ```
   Or, for a pure pipeline smoke test, set `WINGMAN_MOCK: "true"` in `chart/values.yaml`.
3. **Host.** Set `env.DATABRICKS_HOST` and, if you need external access, `ingress` in
   `chart/values.yaml`.
4. **Network.** The pod needs egress to the Databricks workspace host.
5. **Chart.** The guide says DRAGON creates the Helm chart. If it generates its own,
   delete `chart/` and pass the same env vars and Secret through DRAGON's mechanism.
   If it uses the repo's chart, run `helm lint chart` first (not yet linted).

To exercise more of the promotion path, uncomment `DEPLOY_TEST`, `DEPLOY_STAGING` and
`DEPLOY_PRODUCTION`, and push a SemVer tag (`git tag v0.1.0 && git push origin v0.1.0`).

## Layout

```
app/main.py          FastAPI routes, SSE streaming, health checks
app/databricks.py    Databricks auth (token or OAuth M2M), model listing, streaming chat
app/config.py        Environment settings and the default model allowlist
app/static/          UI: Workbench shell + Wingman panel (no build step)
chart/               Minimal Helm chart (non-root, read-only root FS)
tests/               Pytest suite with a mocked Databricks API
```

## Health endpoints

- `/healthz` — liveness/readiness probe (always 200 when the process is up)
- `/readyz` — 503 if no Databricks credentials are configured and mock mode is off
