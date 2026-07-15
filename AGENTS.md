# Coze-all-in-one-HFS agent instructions

## Purpose

This repository is a Hugging Face Docker Space wrapper for Coze Studio. It follows HFS Pattern A: the repository root is both the GitHub maintenance root and the Hugging Face Space root.

The upstream product source of truth is `coze-dev/coze-studio` and the `cozedev/coze-studio-*` images. This repository only maintains the HFS single-container runtime glue, release-pin contract, documentation, smoke checks, and environment-variable ledger.

## Codex startup behavior

- Codex usually starts from the repository root, so this file is the primary repo-local startup instruction.
- Local `AGENTS.md` files under subdirectories are navigation cards, not full replacements for this root router.
- Before editing a path that has a local `AGENTS.md`, read that file first with `cat <path>/AGENTS.md`.
- If multiple nested `AGENTS.md` files ever exist on the path to a target file, read them from shallow to deep before making changes.
- If Codex starts from a subdirectory, closer `AGENTS.md` files may be loaded automatically; still use this root file as the repository map and command index.

## Directory map

| Path | Responsibility | Local AGENTS.md | Read when |
|---|---|---:|---|
| `Dockerfile` | Builds the all-in-one HFS image from Coze, Elasticsearch, etcd, Milvus, Deno, Atlas, and MinIO inputs. | No | Before changing image sources, ARG defaults, exposed ports, installed packages, copied runtime files, healthcheck, or entrypoint. |
| `hfs-dev.toml` | HFS contract manifest for Pattern A, repo-root Space layout, release pins, required files, port, and canonical health endpoint. | No | Before changing release pins, required files, runtime mode, public port, or health endpoint. |
| `README.md` | Hugging Face Space metadata and operator-facing repository overview. | No | Before changing Space metadata, SDK/app port claims, or public setup guidance. |
| `hfs/` | High-risk runtime glue: entrypoint, service scripts, Nginx, Supervisor, MariaDB/Redis/NATS/MinIO glue, ops health, and local runtime tests. | Yes | Always before modifying anything under `hfs/`, and also before changing `Dockerfile` lines that copy or execute `hfs/` content. |
| `scripts/` | Repository validation, HFS contract checks, local Docker helpers, and live Hugging Face smoke checks. | No | Before changing command behavior, exit codes, smoke expectations, or CI-facing checks. |
| `.github/workflows/` | GitHub Actions entrypoint for repository static checks. | No | Before changing CI triggers, permissions, runner, or the `scripts/static-check.sh` invocation. |
| `docs/` | Architecture, troubleshooting, release checklist, HFS alignment notes, and environment reference. | No | Before changing public operational guidance, env categorization, release workflow, or troubleshooting claims. |
| `examples/` | Public examples such as Hugging Face Variables templates. | No | Before adding or changing example env keys, defaults, or placeholder values. |
| `.codex/` | Local Codex helper material for this workspace. | No | Only when the user asks for Codex-local helper updates; do not treat it as deployed Space content. |
| `local/` | Local-only reference material and experiments. It is not part of the deployment package, commit boundary, or cloud fact source. | No | Do not use as evidence for deployed behavior unless the user explicitly asks for local reference analysis. |
| `.env.local` | Private local environment ledger. It must remain gitignored and must not be copied into public docs, commits, PR text, logs, or screenshots. | No | Read only when the user explicitly asks for private local env work. |

## On-demand cat protocol

Before editing files under a directory that has a local `AGENTS.md`, read that file first:

```bash
cat hfs/AGENTS.md
```

Use the local card for directory-specific invariants and this root file for repository-wide boundaries, command selection, and deployment context.

## Commands

| Command | Purpose | Scope | Sandbox notes |
|---|---|---|---|
| `./scripts/check-syntax.sh` | Runs `bash -n` over shell scripts in `hfs/` and `scripts/`. | Shell syntax only | No network or Docker. Requires `bash` and file access. |
| `python3 -m unittest discover -s hfs/tests -p 'test_*.py'` | Runs the Python tests for HFS runtime helpers, especially `ops_service.py`. | `hfs/tests/` | No network or Docker. Use `python3`, not `python`. |
| `./scripts/validate-hfs-contract.sh` | Validates HFS Pattern A contract details, required files, manifest fields, release-pin surfaces, README metadata, and `.dockerignore` expectations. | Repo contract | No network or Docker. Requires `python3`; reads repository files. |
| `./scripts/static-check.sh` | Default local gate: required-file checks, contract validation, shell syntax, Python compile, unit tests, optional `shellcheck`, whitespace checks, and git ignore checks. | Whole repo | No network or Docker. Requires `python3` and Git metadata. Optional `shellcheck` is skipped when unavailable. |
| `./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space` | Live smoke for `/nginx-health`, `/_ops/healthz`, and `/sign` on the Hugging Face Space. | Remote Space | Requires network and a running Hugging Face Space. Use only for remote verification. |
| `./scripts/local-build.sh` | Builds the Docker image with current ARG defaults and optional checksum build args. | Local Docker image | Requires Docker and network access to upstream images/artifacts unless already cached. Do not claim this passed if Docker is unavailable. |
| `./scripts/local-run.sh` | Runs the local Docker image on port `7860` with `/data/coze` mounted from `.data`. | Local Docker runtime | Requires Docker, a built image, and local port `7860`. |

The GitHub Actions workflow `.github/workflows/static-check.yml` runs:

```bash
scripts/static-check.sh
```

## Global rules

- Keep this repository aligned with HFS Pattern A: `space_root_mode = "repo-root"`, `hfs_dir = "."`, public port `7860`, and canonical health endpoint `/_ops/healthz`.
- Treat `hfs-dev.toml` as the HFS contract source. If `Dockerfile`, `hfs/`, `scripts/`, docs, or release pins change in a way that affects the contract, update the manifest and validation script together.
- Keep root-level deployed files self-contained. The Hugging Face Space must be able to build from the repository root without depending on `local/`.
- Use upstream Coze tags/images intentionally. `COZE_SERVER_TAG`, `COZE_WEB_TAG`, and `COZE_GIT_REF` must stay aligned unless the user explicitly requests a split.
- Release-oriented image or artifact inputs in `hfs-dev.toml` must remain represented as structured `[[release_pins]]`.
- Default local scripting should use Bash and Python standard library. Do not add long-term dependencies unless the user approves the reason and alternatives.
- Use `python3` in commands and docs. Do not assume `python` exists on this machine.
- `/_ops/*` endpoints are read-only diagnostics. They may report state but must not expose shell execution, SQL execution, restarts, deletes, secret rotation, config writes, or arbitrary command execution.
- `/nginx-health` is the shallow Nginx probe. `/_ops/healthz` is the canonical health endpoint. Keep both semantics distinct.
- Nginx must keep path boundaries for `/nginx-health`, `/_ops/*`, Coze Web static routing, Coze Server API proxying, and `/local_storage/` fallback.
- `/data/coze` is the persistent runtime root. MySQL/MariaDB, Redis, NATS, MinIO, etcd, Milvus, and Elasticsearch runtime data must not be written back into the image layer.
- `ENABLE_LOCAL_MINIO=0` means the bundled MinIO service is not started; embedded Milvus still needs `MINIO_ADDRESS` pointing at reachable object storage.
- Public docs may list env keys, categories, defaults, placeholders, and operational rules. They must not include real tokens, passwords, private endpoints, private account names, or `.env.local` values.
- HF Variables are for non-sensitive runtime policy such as `DISABLE_USER_REGISTRATION`, `ENABLE_LOCAL_MINIO`, and `COZE_PUBLIC_URL`.
- HF Secrets are for model, embedding, S3/object storage, Elasticsearch, vector, OCR, rerank, third-party API tokens, passwords, and private endpoints.
- GH Variables/Secrets should remain empty unless there is a current CI/CD runtime need.
- Do not manually configure platform-injected values such as `SPACE_HOST` or `SPACE_ID`.

## Do not

- Do not treat `local/` as deployed source of truth, a required build input, or evidence of cloud behavior.
- Do not commit `.env.local`, generated private ledgers, real credentials, private endpoints, local filesystem paths, account data, or customer/personal data.
- Do not add write/action capabilities to `/_ops/*`.
- Do not add a second public listener. The public listener is Nginx on port `7860`.
- Do not bypass `scripts/static-check.sh` for changes to `hfs/`, `Dockerfile`, `hfs-dev.toml`, `scripts/`, or release-facing docs.
- Do not claim local Docker build/run validation unless `./scripts/local-build.sh` or `./scripts/local-run.sh` actually ran successfully in an environment with Docker.
- Do not claim live Space verification unless `./scripts/hf-space-smoke.sh` or equivalent live endpoint checks actually ran against the Hugging Face host.
- Do not make broad formatting rewrites or unrelated README/docs changes while fixing runtime glue.
- Do not edit generated, downloaded, or upstream-derived content in place when the correct source is an upstream tag/image, `Dockerfile` ARG, or bootstrap download.
- Do not use `AGENTS.override.md` unless the user explicitly asks for an override strategy.

## Validation standard

For most repository changes, use the smallest relevant subset of these checks:

1. Shell-only changes in `hfs/` or `scripts/`: `./scripts/check-syntax.sh`.
2. Python runtime helper changes: `python3 -m unittest discover -s hfs/tests -p 'test_*.py'`.
3. HFS contract, `Dockerfile`, docs, or deployment-surface changes: `./scripts/validate-hfs-contract.sh`.
4. Before handing off HFS runtime, contract, or CI changes: `./scripts/static-check.sh`.
5. For remote deployment verification only: `./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space`.
6. For local image validation only when Docker is available: `./scripts/local-build.sh`, then `./scripts/local-run.sh`.

If a command is skipped, final reporting must say whether it was skipped because it was out of scope, required Docker, required network, required a live Space, or was not requested.

## Deployment references

- GitHub code source: `https://github.com/BlueSkyXN/Coze-all-in-one-HFS`
- Hugging Face Space: `https://huggingface.co/spaces/BlueSkyXN/Coze-all-in-one-HFS`
- Live host: `https://blueskyxn-coze-all-in-one-hfs.hf.space`
- Canonical health: `/_ops/healthz`
- Shallow Nginx health: `/nginx-health`

## Notes for future agents

- `hfs/` is the highest-risk directory. Read `hfs/AGENTS.md` before edits there.
- Changes to ports, routes, health endpoints, copied runtime files, release pins, or Docker build inputs usually require synchronized updates across `Dockerfile`, `hfs-dev.toml`, `scripts/validate-hfs-contract.sh`, `scripts/hf-space-smoke.sh`, docs, and sometimes `.github/workflows/static-check.yml`.
- When local Docker is unavailable, use static checks, GitHub Actions logs, Hugging Face build/runtime logs, and live endpoint readback as the evidence chain. Be explicit about what was and was not verified.
