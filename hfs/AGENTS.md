# hfs/ runtime guardrails

This directory is the Hugging Face Docker Space runtime glue layer. Read this card before modifying entrypoints, service scripts, Nginx, Supervisor, ops health, or runtime tests.

Key files: `bin/entrypoint.sh`, `bin/healthcheck.sh`, `bin/ops_service.py`, `conf/nginx.conf`, `conf/supervisord.conf`, `tests/test_ops_service.py`.

## Scope

- `bin/`: entrypoint, service startup scripts, healthcheck, env rendering, bootstrap helpers, and the Python ops service.
- `conf/`: Nginx, Supervisor, Redis, and NATS runtime config.
- `tests/`: local tests for runtime helpers. These tests must not require real external services.

## Why this is high-risk

- Changes here affect container startup, exposed routes, persistent data paths, service supervision, and live health reporting.
- `/_ops/*` is remotely reachable through Nginx, so accidental write/action behavior is a security issue.
- Coze, MariaDB, Redis, NATS, MinIO, etcd, Milvus, and Elasticsearch share one container and `/data/coze` persistence assumptions.

## Required before changes

- Identify every affected runtime surface: entrypoint, Supervisor service, Nginx route, healthcheck, ops JSON, env rendering, or persistent data path.
- For `ops_service.py`, inspect `tests/test_ops_service.py` and update tests with behavior changes.
- For port, route, health endpoint, `Dockerfile` build input, or copied-file changes, plan synchronized updates to `hfs-dev.toml`, `scripts/validate-hfs-contract.sh`, `scripts/hf-space-smoke.sh`, and public docs.
- For startup order or service name changes, check `conf/supervisord.conf`, corresponding `bin/run-*.sh`, `bin/healthcheck.sh`, and README/docs service lists.

## Local invariants

- Public traffic goes through Nginx on port `7860`; do not add a second public listener.
- `/_ops/healthz`, `/_ops/readyz`, and `/_ops/status` remain read-only JSON diagnostics.
- `/_ops/*` must not expose shell, SQL, restart, delete, secret rotation, config writes, or arbitrary command execution.
- `/_admin/*` remains default-off, uses a separate token, and runs as the dedicated `cozeadmin` OS user. Do not give the shared Coze runtime `user` access to the Supervisor control socket.
- Coze `v0.5.1` upstream `/admin` and `/api/admin/*` stay blocked until a matching server/web release contains the fail-closed admin authorization fix.
- `/data/coze` is the persistent root. Runtime data for MySQL/MariaDB, Redis, NATS, MinIO, etcd, Milvus, and Elasticsearch must not be written back into the image layer.
- Nginx must retain `/nginx-health`, `/_ops/*` proxying, Coze Web static routing, Coze Server API proxying, and `/local_storage/` fallback boundaries.
- `ENABLE_LOCAL_MINIO=0` only disables bundled MinIO startup; embedded Milvus still needs `MINIO_ADDRESS` pointing at reachable object storage.

## Do not

- Do not write `.env.local`, real tokens, private endpoints, account names, passwords, or local machine paths into this directory.
- Do not add third-party Python dependencies for `ops_service.py`; keep it standard-library only.
- Do not turn health or ops endpoints into control-plane APIs.
- Do not change runtime ports or paths without updating the root contract and smoke checks.

## Validation

| Command | Purpose | Sandbox notes |
|---|---|---|
| `./scripts/check-syntax.sh` | Shell syntax for `hfs/` and `scripts/`. | No network or Docker. |
| `python3 -m unittest discover -s hfs/tests -p 'test_*.py'` | Runtime helper tests. | No network or Docker. Use `python3`. |
| `./scripts/static-check.sh` | Full repository static gate for HFS changes. | No network or Docker. Requires Git metadata and `python3`; optional `shellcheck` may be skipped. |
| `./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space` | Live Hugging Face smoke check. | Requires network and a running Space. |
