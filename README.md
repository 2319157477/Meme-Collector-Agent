# Meme Collector Agent Service

A single-host Python service for collecting recent Chinese internet memes, staging them for review, and writing approved entries to a Dify knowledge base.

## What it does

- FastAPI + server-rendered WebUI.
- SQLite persistence for settings, tasks, runs, and meme candidates.
- APScheduler scheduled collection plus manual "run now".
- OpenAI Agents SDK for meme extraction and structuring.
- AnySearch MCP for web search and page extraction/fetching.
- Human review queue: collection creates `pending` candidates only.
- Dify writes happen only when selected in the WebUI.
- Docker deployment for one Linux ECS host.

## Configuration

Copy `.env.example` to `.env` and fill the values you want to provide at startup:

```bash
cp .env.example .env
```

Important values:

- `OPENAI_API_KEY`: required for real agent runs.
- `OPENAI_MODEL`: model used by the Agents SDK.
- `OPENAI_BASE_URL`: optional OpenAI-compatible large-model endpoint base URL, for example a private gateway or proxy ending in `/v1`.
  Custom OpenAI-compatible base URLs are sent through Chat Completions because many gateways do not support `/v1/responses`.
- `OPENAI_PROXY`: optional HTTP proxy for OpenAI API calls. The app does not inherit ambient `HTTP_PROXY`/`HTTPS_PROXY` for OpenAI; set this explicitly if the ECS host needs a proxy.
- `ANYSEARCH_API_KEY`: optional for AnySearch search/extract tools; anonymous access is lower quota.
- `ANYSEARCH_MCP_URL`: AnySearch MCP endpoint; defaults to `https://api.anysearch.com/mcp`.
- `ANYSEARCH_PROXY`: optional HTTP proxy for connecting to AnySearch MCP from restricted hosts, for example `http://127.0.0.1:7890`.
- `DIFY_BASE_URL`: defaults to `https://api.dify.ai/v1`.
- `DIFY_DATASET_ID`: Dify knowledge base dataset id.
- `DIFY_API_KEY`: Dify dataset API key.
- `DIFY_PROXY`: optional HTTP proxy.
- `DIFY_SKIP_CHECK_FOR_DRY_RUN`: testing-only flag. When `true`, collection dry-runs skip Dify credential preflight and existing-document listing; approved Dify writes still require real credentials.
- `DATABASE_PATH`: SQLite path. In Docker it defaults to `/data/meme_collector.sqlite3`.
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`: single-admin WebUI login. Development defaults to `admin` / `admin` only when unset. Set real values for deployed hosts.
- `JWT_SECRET`: signing secret for the WebUI JWT cookie and CSRF token. Required outside development; use a long random value.
- `JWT_TTL_MINUTES`: optional login lifetime; defaults to 480 minutes.
- `JWT_COOKIE_NAME` / `CSRF_COOKIE_NAME`: optional cookie names for the auth JWT and CSRF token.

The WebUI is protected by a single-admin login. `/health` stays public for deployment checks. The `/settings` page can save/update connection settings after login. OpenAI/AnySearch/Dify secrets are masked after saving; admin credentials and JWT secret are environment-only and are not editable from the WebUI. The dry-run Dify skip flag is persistent until disabled and should stay off outside testing.

## Local startup

```bash
python -m pip install -e .
python -m uvicorn meme_collector_app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>.

## Docker startup

```bash
cp .env.example .env
# edit .env
docker compose up --build -d
```

SQLite data is stored in the `meme_collector_data` volume.

If Docker Hub is unavailable on the ECS host, set `BASE_IMAGE` in `.env` to a reachable Python mirror image before building, for example:

```env
BASE_IMAGE=docker.m.daocloud.io/python:3.12-slim
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

### Linux ECS notes

- Run the container behind the ECS security group/firewall port you choose for the WebUI.
- Keep `.env` readable only by the deployment user because it may contain API keys.
- Mount or keep the Docker volume on persistent disk; the SQLite DB is the source of truth for settings, tasks, runs, and pending candidates.
- For a simple single-host deployment, restart policy `unless-stopped` is enough. Do not add multi-node scheduling unless the app is later redesigned away from SQLite.
- If collection fails with `Failed to connect to MCP server 'anysearch'`, verify the ECS host can reach `ANYSEARCH_MCP_URL` and set `ANYSEARCH_PROXY` when outbound access requires a proxy.
- If collection fails with `Connection error.` during the model call, verify the container can reach `api.openai.com` or configure `OPENAI_PROXY` to a proxy URL reachable from inside the container.

### GitHub Actions ECS deployment

Pushes to `main` trigger `.github/workflows/deploy-ecs.yml`. The workflow SSHes into the ECS host, runs `git pull --ff-only`, rebuilds/restarts Docker Compose, and checks `/health`.

Configure these GitHub repository secrets before enabling deployment:

- `ECS_HOST`: ECS public IP or DNS name.
- `ECS_USER`: SSH user on the ECS host.
- `ECS_SSH_PRIVATE_KEY`: private key that can SSH to the ECS host.
- `ECS_PORT`: optional SSH port; defaults to `22`.

Optional GitHub repository variables:

- `ECS_DEPLOY_DIR`: remote checkout path; defaults to `~/meme-collector-agent`.
- `ECS_HEALTH_URL`: remote health URL; defaults to `http://127.0.0.1:8000/health`.
- `ECS_REPO_URL`: repo URL used by ECS `git pull`; defaults to `https://github.com/2319157477/Meme-Collector-Agent.git`.
- `ECS_BRANCH`: deploy branch; defaults to `main`.

If the GitHub repository is private, make sure the ECS host can `git clone`/`git pull` the configured `ECS_REPO_URL` (for example with a deploy key).

### Docker smoke verification

After editing `.env`, run the smoke script on the ECS host or any machine with Docker:

```bash
./scripts/docker-smoke.sh
```

On Windows PowerShell:

```powershell
.\scripts\docker-smoke.ps1
```

The script builds the image, starts the compose service, checks `/health`, verifies the SQLite file exists in the mounted volume, restarts the service, and checks `/health` again.

### Backup and restore

Back up the SQLite volume regularly:

```bash
docker compose stop meme-collector
docker run --rm -v meme_collector_data:/data -v "$PWD/backups:/backup" busybox \
  cp /data/meme_collector.sqlite3 /backup/meme_collector.sqlite3
docker compose start meme-collector
```

Restore by stopping the service, copying the saved SQLite file back into the volume, then starting the service again.

## Operational flow

1. Configure OpenAI, AnySearch, and Dify in `/settings`.
2. Log in to the WebUI, then create a scheduled task in `/tasks` with the schedule panel or click "立即运行" for a manual run.
3. Existing custom cron values remain supported, but normal task creation uses the schedule panel instead of hand-written cron. Collection runs search/fetch/extract and saves candidates as `pending`.
4. Review candidates and source links in `/pending`.
5. Approve selected candidates.
6. Select approved candidates and click "写入选中已批准项到 Dify".
7. The app lists existing Dify documents, skips duplicates, and uploads approved records.

## Safety guarantees

- Collection never writes directly to Dify.
- Automated tests use mocks/fakes and do not perform real external writes.
- Dify writes require selected candidate IDs from the WebUI approval page.
- `DIFY_SKIP_CHECK_FOR_DRY_RUN` only skips collection preflight/listing for tests; it does not bypass Dify write credentials or fake write success.
- API keys are masked in the WebUI and should not be committed.
- The auth JWT cookie is HTTP-only and mutating WebUI forms include CSRF protection.
- `/health` is intentionally public; WebUI pages and form actions require login.

## Development verification

```bash
python -m compileall meme_collector_app
python -m unittest discover -s tests -v
```

Optional when installed:

```bash
ruff check .
```
