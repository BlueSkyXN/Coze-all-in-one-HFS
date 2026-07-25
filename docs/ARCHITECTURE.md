# Architecture

## HFS Pattern

本仓库采用 HFS Pattern A：repo root 就是 Hugging Face Space root。它不是 Coze Studio 产品源码仓，而是第三方上游程序的 HFS 部署包装仓。

```text
repo root
  README.md       HF Space card + GitHub 入口
  Dockerfile      Docker Space build 入口
  hfs/            runtime glue
  docs/           公开运行合同
  scripts/        static check 与 smoke
  .env.local      本地私有台账，gitignored
```

## Runtime Shape

Hugging Face Docker Spaces 只暴露一个公开端口。本仓库用 Nginx 在 `7860` 汇聚多个内部服务。

```text
browser
  -> https://${SPACE_HOST}
  -> nginx:7860
       /                       -> /opt/coze-web
       /api, /v1, /v2          -> coze-server:8888
       /admin, /api/admin       -> 404 upstream v0.5.1 guard
       /local_storage          -> optional minio:9000
       /_ops/healthz           -> ops-service:8081
       /_ops/                  -> ops-service:8081
       /_admin/                -> admin-service:8082

local processes:
  - mariadbd:3306
  - redis-server:6379
  - nats-server:4222
  - minio:9000
  - etcd:2379
  - elasticsearch:9200
  - milvus:19530
  - coze-server:8888
  - ops-service:8081
  - admin-service:8082
  - nginx:7860
```

## Build Inputs

默认开发输入：

| Surface | Default | Purpose |
| --- | --- | --- |
| `COZE_SERVER_TAG` | `0.5.1@sha256:bacce3aa...7744` | digest-pinned `cozedev/coze-studio-server` image |
| `COZE_WEB_TAG` | `0.5.1@sha256:a137a16a...2aea` | digest-pinned `cozedev/coze-studio-web` image |
| `COZE_GIT_REF` | `v0.5.1` | schema and Atlas source ref |
| `ELASTICSEARCH_IMAGE` | `bitnamilegacy/elasticsearch:8.18.0@sha256:4a7d1422...5a38` | digest-pinned runtime base image and local ES |
| `ETCD_IMAGE` | `bitnamilegacy/etcd:3.5@sha256:1b9977cf...69d0` | digest-pinned local etcd for Milvus |
| `MILVUS_IMAGE` | `milvusdb/milvus:v2.5.10@sha256:02e1d60d...4379` | digest-pinned local vector store |
| `DENO_VERSION` | `2.4.5` | Deno binary used by Coze runtime |
| `ATLAS_VERSION` | `v1.2.0` + amd64/arm64 SHA-256 | checksum-verified Atlas CLI |
| `MINIO_VERSION` / `MC_VERSION` | fixed releases + amd64/arm64 SHA-256 | checksum-verified MinIO server/client |

Coze server/web 默认镜像已 pin 到 `v0.5.1` 的 manifest digest；Elasticsearch、etcd、Milvus 同样 digest-pinned，Deno、Atlas、MinIO、MC 使用固定版本加双架构 SHA-256，安装前强制校验，不允许空 checksum。

Coze v0.5.1 的 bootstrap 文件包含 MySQL 8.0 专属 collation `utf8mb4_0900_ai_ci`。本仓库在 build 阶段把 `schema.sql` 和 Atlas HCL 规范化为 `utf8mb4_unicode_ci`，以保持 MariaDB 运行层可启动。首次初始化导入 `schema.sql` 后执行 Atlas reconcile；已存在的数据目录按 HCL SHA-256 判断是否需要 reconcile。Atlas 失败会使启动失败，schema marker 只在成功后原子更新。

## Persistence

默认持久化边界是 `/data/coze`：

Unix socket 与 PID 文件不属于持久化边界：HF bucket volume 不支持 unix socket（`Bind on unix socket: Function not implemented`），MariaDB、mysql-init 与 supervisord 的 socket/pid 固定在容器内 `RUN_DIR`（默认 `/run/coze`），重建后可安全丢弃。

```text
/data/coze/mysql
/data/coze/admin
/data/coze/redis
/data/coze/nats
/data/coze/minio
/data/coze/elasticsearch
/data/coze/logs
/data/coze/run
/data/coze/generated-secrets.env
```

`generated-secrets.env` 用于保存未显式配置时生成的本地服务密码和 Coze plugin AES secrets。它在 runtime 写入 `/data/coze`，不会进入镜像或 Git。

## Internal vs External

为 HFS 单容器便利内置：

- MariaDB/MySQL-compatible
- Redis
- NATS JetStream
- MinIO fallback
- etcd
- Elasticsearch
- Milvus
- Nginx
- Supervisor
- read-only ops-service
- default-off admin-service

按 Coze 正常能力建议外接：

- 模型 API
- Embedding API
- S3/TOS/ImageX
- external ES/OpenSearch override
- external VikingDB/OceanBase/Milvus override
- OCR/rerank/plugin provider

## Ops / Admin Surface

`/_ops/healthz`、`/_ops/readyz`、`/_ops/status` 只做公开只读健康检查。返回字段包括 `mariadb`、`redis`、`nats`、`minio`、`etcd`、`elasticsearch`、`milvus`、`coze_server`、`data_dir` 和非敏感运行策略 `code_runner_type`；live smoke 要求其为 `sandbox`。

完整 `/_ops/` dashboard/API 仍是只读面，但需要 `OPS_TOKEN`。它覆盖：

```text
/_ops/health
/_ops/processes
/_ops/system
/_ops/config
/_ops/version
/_ops/logs?service=<service>&lines=<n>
/_ops/errors
/_ops/metrics
```

`/_ops/logs` 只读取 `OPS_LOG_DIR` 下的白名单日志文件，并拒绝绝对路径、`..` 和 symlink escape。默认日志目录是 `/data/coze/logs`，由 Supervisor 把各服务 stdout/stderr 写入对应文件。

`/_admin/` 是独立管理面，只监听 `127.0.0.1:8082` 并通过 Nginx 代理。默认 `ADMIN_ENABLED=false`，因此入口返回 404。服务使用独立 `cozeadmin` OS user；owner-only Supervisor socket 不向 Coze Server、ops service 或其他 `user` 进程开放。开启后使用独立 `ADMIN_TOKEN`，支持登录 cookie、CSRF、confirm 和 audit，当前只允许白名单 action：

```text
restart-service
run-health-checks
```

禁止在 `/_ops` 增加写操作、shell、SQL、restart、delete、secret rotation 或配置修改。`/_admin` 也不接受任意 shell command；后续如果新增写 action，必须继续使用独立 token、专用 OS identity、白名单、`confirm=true`、CSRF 和 audit。

Coze `v0.5.1` 在 `CODE_RUNNER_TYPE` 为空时会选择 local runner。本 wrapper 在生成 `/app/.env` 时显式写入 `CODE_RUNNER_TYPE=sandbox`，并保留 HF Variable 覆盖能力，避免重写官方 image env 后退回直接本地执行。
