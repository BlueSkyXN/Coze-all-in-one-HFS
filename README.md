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

镜像构建采用 Coze Studio 官方镜像组装模式：

- `cozedev/coze-studio-server:0.5.1`
- `cozedev/coze-studio-web:0.5.1`
- `coze-dev/coze-studio` 的 `v0.5.1` MySQL schema / Atlas schema
- Elasticsearch 运行层，内置 Nginx、Supervisor、MariaDB、Redis、NATS JetStream、MinIO fallback、etcd、Milvus、Elasticsearch

外部只暴露 Hugging Face 的单一端口 `7860`。Nginx 在容器内汇聚：

```text
browser
  -> https://blueskyxn-coze-all-in-one-hfs.hf.space
  -> nginx:7860
       /                 -> Coze Web 静态文件
       /api, /v1, /v2    -> Coze Server:8888
       /local_storage    -> optional MinIO fallback:9000
       /_ops/healthz     -> read-only HFS ops health
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
/sign             Coze Web 登录入口
```

本机或 CI 可跑：

```bash
./scripts/static-check.sh
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

如果本机没有 Docker，不要把本地 build/run 作为验证结论；以 HF build logs、HF runtime logs 和 live endpoint 回读为准。

## ENV 管理

公开说明见 [docs/env-reference.md](docs/env-reference.md)。本机私有记录放在 `.env.local`，该文件被 `.gitignore` 和 `.dockerignore` 忽略，不会进入 GitHub、Hugging Face 或 Docker build context。

最小公开运行推荐显式配置：

```bash
DISABLE_USER_REGISTRATION=true
ENABLE_LOCAL_MINIO=1
COZE_PUBLIC_URL=https://blueskyxn-coze-all-in-one-hfs.hf.space
```

文本 Agent 测试通常还需要模型配置。含 token/key/password 的值必须放 HF Secrets：

```bash
MODEL_PROTOCOL_0=openai
MODEL_OPENCOZE_ID_0=100001
MODEL_NAME_0=your-model-display-name
MODEL_ID_0=your-model-id
MODEL_BASE_URL_0=https://your-openai-compatible-endpoint/v1
MODEL_API_KEY_0=sk-...

BUILTIN_CM_TYPE=openai
BUILTIN_CM_OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
BUILTIN_CM_OPENAI_API_KEY=sk-...
BUILTIN_CM_OPENAI_MODEL=your-model-id
```

## 持久化

默认数据目录是 `/data/coze`。HF Space 未挂载 persistent storage 时，数据库、Redis、NATS、MinIO 数据都可能在 rebuild、restart 或迁移后丢失。长期演示或真实使用前，应在 Hugging Face Space 设置中挂载 persistent storage，并定期备份 `/data/coze/mysql`。

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
