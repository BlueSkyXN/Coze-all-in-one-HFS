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
       /api, /v1, /v2, /admin  -> coze-server:8888
       /local_storage          -> optional minio:9000
       /_ops/healthz           -> ops-service:8081

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
  - nginx:7860
```

## Build Inputs

默认开发输入：

| Surface | Default | Purpose |
| --- | --- | --- |
| `COZE_SERVER_TAG` | `0.5.1` | `cozedev/coze-studio-server` image tag |
| `COZE_WEB_TAG` | `0.5.1` | `cozedev/coze-studio-web` image tag |
| `COZE_GIT_REF` | `v0.5.1` | schema and Atlas source ref |
| `ELASTICSEARCH_IMAGE` | `bitnamilegacy/elasticsearch:8.18.0` | runtime base image and local ES |
| `ETCD_IMAGE` | `bitnamilegacy/etcd:3.5` | local etcd for Milvus |
| `MILVUS_IMAGE` | `milvusdb/milvus:v2.5.10` | local vector store |
| `DENO_VERSION` | `2.4.5` | Deno binary used by Coze runtime |
| `ATLAS_INSTALL_URL` | `https://atlasgo.sh` | Optional Atlas installer URL |

发布态应把镜像 digest、Coze git commit、下载 artifact checksum 明确 pin 住。Dockerfile 已支持 `DENO_SHA256_*`、`ATLAS_INSTALL_SHA256`、`MINIO_SHA256_*` 和 `MC_SHA256_*` build args；本仓库当前默认值适合开发部署，不应被描述成生产级不可变 release。

Coze v0.5.1 的 bootstrap 文件包含 MySQL 8.0 专属 collation `utf8mb4_0900_ai_ci`。本仓库在 build 阶段把 `schema.sql` 和 Atlas HCL 规范化为 `utf8mb4_unicode_ci`，以保持 MariaDB 运行层可启动。

## Persistence

默认持久化边界是 `/data/coze`：

```text
/data/coze/mysql
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

按 Coze 正常能力建议外接：

- 模型 API
- Embedding API
- S3/TOS/ImageX
- external ES/OpenSearch override
- external VikingDB/OceanBase/Milvus override
- OCR/rerank/plugin provider

## Ops Surface

`/_ops/healthz`、`/_ops/readyz`、`/_ops/status` 只做只读健康检查。返回字段包括 `mariadb`、`redis`、`nats`、`minio`、`etcd`、`elasticsearch`、`milvus`、`coze_server`、`data_dir`。

禁止在 `/_ops` 增加写操作、shell、SQL、restart、delete、secret rotation 或配置修改。
