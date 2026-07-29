---
title: Coze All In One HFS
emoji: ⚡
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
suggested_hardware: cpu-upgrade
pinned: false
license: gpl-3.0
---

# Coze All In One HFS

这是一个 Hugging Face Docker Space 包装仓，用来把 Coze Studio 以单个 Docker Space 的形态运行起来。仓库根目录就是 Space root，符合本机 HFS Pattern A：上游产品源码不在本仓库内，本仓库维护 Dockerfile、runtime glue、运维入口、文档、smoke 和本地 env 台账。

## 当前形态

仓库采用 HFS v2 hybrid 交付边界：

- reviewable Pattern A wrapper：根目录的 `Dockerfile`、`hfs/`、docs、static gates 和 runtime bootstrap
- Coze server/web：由 `COZE_RUNTIME_MANIFEST_URI` 的单一 manifest 选择，启动时下载、SHA-256 校验、共同 staging 后以可恢复方式安装的不可变 artifact 对
- `coze-dev/coze-studio` 的同一不可变 commit MySQL schema / Atlas schema（`v0.5.1` 仅作 release label）
- Elasticsearch、etcd、Milvus：仍为 digest-pinned image-input deviation，待逐组件可运行证明后再决定是否抽取
- 内置 Nginx、Supervisor、MariaDB、Redis、NATS JetStream、MinIO fallback、etcd、Milvus、Elasticsearch

运行 manifest 必须记录完整 source commit、commit-named `BUILD_SOURCE-<commit>.json` checksum、server/web artifact 名称、SHA-256 与 size。manifest 或 artifact 出错会 fail-closed；不会回退到旧 `/app`、`latest`、缓存、目录扫描或备用 URI。

外部只暴露 Hugging Face 的单一端口 `7860`。Nginx 在容器内汇聚：

```text
browser
  -> https://blueskyxn-coze-all-in-one-hfs.hf.space
  -> nginx:7860
       /                 -> Coze Web 静态文件
       /api, /v1, /v2    -> Coze Server:8888
       /admin,/api/admin  -> 404 until upstream admin auth is fail-closed
       /local_storage    -> optional MinIO fallback:9000
       /_ops/healthz     -> read-only HFS ops health
       /_ops/            -> token-protected read-only ops dashboard/API
       /_admin/          -> default-off admin dashboard/API
```

## 运行边界

内置本地服务：

- MariaDB/MySQL-compatible：`127.0.0.1:3306`
- Redis：`127.0.0.1:6379`
- NATS JetStream：`127.0.0.1:4222`
- MinIO fallback：`127.0.0.1:9000`
- etcd：`127.0.0.1:2379`
- Elasticsearch：`127.0.0.1:9200`
- Milvus：`127.0.0.1:19530`
- Coze Server：`127.0.0.1:8888`
- Nginx public listener：`0.0.0.0:7860`

建议仍外接的服务：

- 模型 API
- Embedding API
- S3/TOS/ImageX 文件存储
- 外部 Elasticsearch/OpenSearch-compatible endpoint
- VikingDB/OceanBase/Milvus 等外部向量服务
- OCR、rerank、plugin 相关第三方服务

## Health 与 Smoke

主要检查点：

```text
/nginx-health     shallow Nginx health
/_ops/healthz     HFS runtime health, read-only JSON
/_ops/readyz      同 healthz
/_ops/status      同 healthz
/_ops/            只读运维 dashboard，需 OPS_TOKEN
/_admin/          受控管理入口，默认 ADMIN_ENABLED=false
/sign             Coze Web 登录入口
```

本机或 CI 可跑：

```bash
./scripts/static-check.sh
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
./scripts/admin-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

如果本机没有 Docker，不要把本地 build/run 作为验证结论；以 HF build logs、HF runtime logs 和 live endpoint 回读为准。

## Ops 与 Admin

`/_ops/healthz`、`/_ops/readyz`、`/_ops/status` 保持公开只读健康探针，用于 Docker healthcheck、HF smoke 和外部 uptime 判断。

更完整的 `/_ops/` dashboard/API 需要至少 24 字符的强随机 `OPS_TOKEN`。CLI 和自动化优先使用 header：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/health
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/system
curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/logs?service=coze-server&lines=100"
```

浏览器直接打开 `/_ops/`，在页面中输入 `OPS_TOKEN`；token 只保留在当前页面内存中。服务会拒绝 `?token=`，不要把 secret 放入 URL、浏览器历史或 Nginx access log。

`/_admin/` 是独立管理面，默认关闭：

```text
ADMIN_ENABLED=false
ADMIN_TOKEN=
```

确需短期开启时，应使用 Private/Protected Space、至少 24 字符且不复用 `OPS_TOKEN` 的 `ADMIN_TOKEN`，并用 `X-Admin-Token` 或登录 cookie 访问。admin service 使用独立 `cozeadmin` OS user，Supervisor control socket 不向 Coze Server 运行用户开放。当前白名单 action 只有 restart supervisor service 和 run health checks；每个 action 都要求 `confirm=true`，cookie session 还要求 `X-Admin-CSRF`，并写入 `ADMIN_AUDIT_LOG`。`/_ops` 仍只读，不承载写操作、shell、SQL 或任意命令执行。

官方 `v0.5.1` 的内置 `/admin`、`/api/admin/*` 在未保存 admin email 时会 fail-open；本 wrapper 暂时返回 404。待上游发布包含 `5aaf6d5` 或等价修复的匹配 server/web 镜像后再复核是否解除。

## ENV 管理

公开说明见 [docs/env-reference.md](docs/env-reference.md)。本机部署值记录在 gitignored `.env`（从无密 `.env.example` 开始）；遗留 `.env.local` 同样保持忽略，不会进入 GitHub、Hugging Face 或 Docker build context。同步顺序固定为本地改值 → diff → 经批准 push → readback，不在网页直接留下未回收的配置。

首次切换到 artifact runtime 前，Space Variable 必须设置无凭据的直接 HTTPS `COZE_RUNTIME_MANIFEST_URI`；private `hfs-dist` 如需认证，另以 Space Secret 提供 `COZE_RUNTIME_DOWNLOAD_TOKEN`。两者均需由发布 workflow 的 artifact/readback/manifest-last 证据支撑，不能填入 URL query 或从旧镜像回退。

最小公开运行推荐显式配置：

```bash
DISABLE_USER_REGISTRATION=true
ENABLE_LOCAL_MINIO=1
COZE_PUBLIC_URL=https://blueskyxn-coze-all-in-one-hfs.hf.space
CODE_RUNNER_TYPE=sandbox
PERSISTENCE_REQUIRED=true
OPS_TOKEN=<fixed-random-token>
```

这组设置就是 clean no-paid profile。未提供外部 provider、S3 或 VikingDB 配置时，
`render-env.sh` 会继续使用本地 MinIO、Elasticsearch 和 Milvus，模型/provider tuple 不会形成可用配置；
因此页面、健康检查和本地基础服务可以启动，但模型相关业务能力不会在没有显式 provider 配置时可用。

文本 Agent 测试需要另行建立完整的 provider-enabled 配置，不能在 clean profile 中同步空值或占位值。
配置前先按 [docs/env-reference.md](docs/env-reference.md) 核对完整字段；token、key、password 和私有 endpoint 必须放 HF Secrets。

## 持久化

默认数据目录是 `/data/coze`。HF Space 未挂载 persistent storage 时，数据库、Redis、NATS、MinIO 数据都可能在 rebuild、restart 或迁移后丢失。长期演示或真实使用应把 private HF bucket 以 read-write volume 挂载到 `/data/coze`，并设置 `PERSISTENCE_REQUIRED=true`；canonical health 会在 mount 丢失时返回 503。仍应定期备份 `/data/coze/mysql`。

## 已知限制

- 官方 Coze Studio 主要面向 Docker Compose / Helm 部署，本仓库是 HFS 单容器包装，不是官方部署方式。
- 当前数据库层使用 MariaDB 作为 MySQL-compatible 本地服务；如果上游 schema 使用 MySQL 8.4 专属特性，可能需要切到外部 MySQL 或后续改造 MySQL runtime。
- Knowledge/RAG 相关能力已内置 ES + Milvus 的启动路径；真实知识库效果仍需要配置 Embedding、rerank、OCR 或外部托管向量服务。
- 本地 MinIO fallback 不适合生产文件公开访问；真实上传、多模态和模型可读 URL 建议接 S3/TOS/ImageX。
- 公开 Space 默认关闭注册：`DISABLE_USER_REGISTRATION=true`。

## 文档

- [docs/README.md](docs/README.md)：文档索引
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：架构和路径边界
- [docs/env-reference.md](docs/env-reference.md)：ENV 分类和同步规则
- [docs/hfs-alignment.md](docs/hfs-alignment.md)：HFS Pattern A、runtime mode、Space root 和 release pin 合同
- [docs/release-checklist.md](docs/release-checklist.md)：发布前检查、远端同步和 live runtime 收口清单
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)：排障入口
