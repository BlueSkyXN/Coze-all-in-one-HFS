# HFS Alignment

本文件记录当前仓库与 HFS 开发范式的对齐合同，只写公开可传播的信息，不记录 `.env.local` 明文、真实 token、私有 endpoint 或本机路径。

## Contract

- Pattern A: HFS Port Repository
- Runtime mode: image-assembly
- Space root: repo root
- Public port: `7860`
- Canonical health endpoint: `/_ops/healthz`

仓库根目录同时是 GitHub 维护根和 Hugging Face Space root。不要把部署入口迁移到 `cloud/hfs/` 或其他二级目录；HF 构建应直接读取根目录的 `README.md`、`Dockerfile` 和 `.dockerignore`。

## Source Of Truth

本仓库不复制 Coze Studio 源码。上游事实源分为三层：

- Coze runtime 镜像：`cozedev/coze-studio-server` 与 `cozedev/coze-studio-web`。
- Coze bootstrap 文件：`coze-dev/coze-studio` 中与 `COZE_GIT_REF` 对齐的 schema/config。
- HFS wrapper：本仓库的 `Dockerfile`、`hfs/`、`scripts/`、`docs/` 和 `hfs-dev.toml`。

文档以当前 wrapper 代码为准：端口和路径先看 `Dockerfile`、`hfs/conf/nginx.conf`、`hfs/conf/supervisord.conf`、`hfs/bin/*` 和 `hfs/bin/ops_service.py`，再回写 README/docs。

## Runtime Shape

容器内由 Supervisor 管理 MariaDB、Redis、NATS、MinIO fallback、etcd、Elasticsearch、Milvus、Coze Server、ops service、admin service 和 Nginx。外部只通过 Nginx `7860` 进入：

```text
/nginx-health          shallow Nginx health
/_ops/healthz          read-only HFS runtime health JSON
/_ops/readyz           same health payload
/_ops/status           same health payload
/_ops/                 token-protected read-only ops dashboard/API
/_admin/               default-off admin dashboard/API
/sign                  Coze Web login entry
/api, /v1, /v2         Coze Server proxy
/admin, /api/admin/*    blocked until upstream admin auth is fail-closed
/local_storage/        optional MinIO fallback proxy
```

`/_ops/*` 只保留 read-only diagnostics。`/_admin/*` 是独立管理入口，默认关闭，使用独立 `ADMIN_TOKEN`、白名单 action、`confirm=true`、cookie CSRF 和 audit log。不要在 `/_ops` 下加入 shell、SQL、restart、delete、secret rotation、配置写入或任意命令执行能力；不要在 `/_admin` 下加入任意 shell command 或不受白名单约束的写能力。

## Release Pins

`hfs-dev.toml` 使用 schema v2 的 `[[release_pins]]` 记录所有 release 需要审计的输入：

- Coze image tags：`COZE_SERVER_TAG`、`COZE_WEB_TAG`
- Coze upstream config ref：`COZE_GIT_REF`
- Runtime dependency images：`ELASTICSEARCH_IMAGE`、`ETCD_IMAGE`、`MILVUS_IMAGE`
- Downloaded artifacts：Deno、Atlas CLI、MinIO server、MinIO client

当前 Coze server/web 默认值使用 `v0.5.1` 的 `tag@sha256:...` manifest digest，`COZE_GIT_REF=v0.5.1` 与其保持同一 release。Elasticsearch、etcd、Milvus 也使用 manifest digest；Deno、Atlas CLI、MinIO 和 MC 使用固定版本及 amd64/arm64 SHA-256。Dockerfile 不执行 `curl | sh`，下载型 artifact 在安装前必须通过 checksum。

## Upstream Tracking Snapshot

2026-07-15 live readback：

- 最新正式 release 仍是 `v0.5.1`；Docker Hub 的 `latest` 与 `0.5.1` 对 server/web 分别指向相同 manifest digest。
- upstream `main@22275b1c2661d35344a7493cffe401e8cc61cf8e` 比 `v0.5.1` 多 8 个未发布 commit，但没有对应的新 server/web image pair，不能把 `COZE_GIT_REF` 单独切到 `main` 后声称完成适配。
- wrapper 已等价吸收可由配置层完成的 `8de249d`：生成环境显式设置 `CODE_RUNNER_TYPE=sandbox`。
- wrapper 暂时阻断 `/admin` 和 `/api/admin/*`，缓解 `5aaf6d5` 修复前的 upstream admin fail-open。SQL injection、OAuth nonce/phishing 和 workflow resume 修复属于 upstream binary 变化，必须等待匹配 release 或改用经过审计的自建 server/web 镜像。
- MySQL 初始化记录 pinned HCL 的 SHA-256。旧 `.coze_bootstrap_done` 数据目录或 schema 指纹变化时会启动临时 MariaDB 并执行 `atlas schema apply`；Atlas 失败会阻止启动且不会推进 marker，避免把换 binary 误报为完成持久化数据库 migration。

## Local-Only Materials

`local/` 只作参考材料或本地临时记录，不进入部署包、公开文档真相源或提交边界。`.env.local` 是本机私有 env ledger，只能记录本地同步状态和私有值；公开文档只写 key、分类、默认值、占位符和操作规则。

## Validation

默认本地验证：

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
```

如果本地 runtime 已启动，可额外跑 `./scripts/admin-smoke.sh http://localhost:7860` 验证 admin 默认关闭或受控开启状态。

线上 Space 验证：

```bash
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

如果本机没有 Docker，不要把本地 build/run 写成已验证；以静态检查、HF build logs、HF runtime logs 和 live endpoint 回读分层说明。
