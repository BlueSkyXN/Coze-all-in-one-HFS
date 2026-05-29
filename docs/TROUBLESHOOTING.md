# Troubleshooting

## HF Space 显示 `NO_APP_FILE`

说明 Space repo 里没有有效 `Dockerfile`，或者 README metadata 没有正确声明 `sdk: docker`。检查：

```bash
hf spaces info BlueSkyXN/Coze-all-in-one-HFS
git ls-remote https://huggingface.co/spaces/BlueSkyXN/Coze-all-in-one-HFS refs/heads/main
```

## Build 在 Coze 镜像 tag 失败

先确认 tag 存在，再改 build surface：

```bash
git ls-remote --tags https://github.com/coze-dev/coze-studio.git 'refs/tags/v0.5.1'
```

Dockerfile 默认：

```text
COZE_SERVER_TAG=0.5.1
COZE_WEB_TAG=0.5.1
COZE_GIT_REF=v0.5.1
```

三者必须保持同一上游版本线。

## DB schema import fails

当前本地数据库层是 MariaDB。官方 Coze Compose 使用 MySQL 8.4.x。如果 schema 使用 MariaDB 不兼容语法，下一步选项是：

1. 外接 MySQL-compatible 服务。
2. 改造 runtime 使用 MySQL 官方二进制或 MySQL-compatible 镜像组装层。
3. 临时 pin 到已验证可导入的 Coze tag。

不要直接删 schema 或跳过 DB migration 后声称调通。

## `/_ops/healthz` 返回 503

读取 JSON 中的 `checks`：

```bash
curl -fsS https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/healthz
```

常见含义：

- `mariadb=false`：DB 初始化失败或 datadir 权限异常。
- `redis=false`：Redis 未启动，检查 Supervisor logs。
- `nats=false`：NATS JetStream 未启动，检查 `/data/coze/nats` 权限。
- `minio=false`：本地 MinIO fallback 未启动；如果 `ENABLE_LOCAL_MINIO=0`，不应检查该项。
- `coze_server=false`：Coze Server 未监听 `8888`，继续看 ES、VectorStore、DB 或 model 初始化错误。

## 登录或注册被拦

公开 Space 默认关闭注册：

```bash
DISABLE_USER_REGISTRATION=true
```

受控测试可以设置：

```bash
ALLOW_REGISTRATION_EMAIL=you@example.com
```

不要在公开文档、PR 文案或截图里写真实邮箱、账号或密码。

## 模型不可用

最小文本 Agent 需要模型配置：

```text
MODEL_PROTOCOL_0
MODEL_OPENCOZE_ID_0
MODEL_NAME_0
MODEL_ID_0
MODEL_BASE_URL_0
MODEL_API_KEY_0
BUILTIN_CM_TYPE
BUILTIN_CM_OPENAI_BASE_URL
BUILTIN_CM_OPENAI_API_KEY
BUILTIN_CM_OPENAI_MODEL
```

API key 必须放 HF Secrets。Base URL 如果包含私有网关、租户或 token，也按 Secret 管理。

## 文件上传 URL 模型不可读

本地 MinIO fallback 只为 P0/P1 演示保留。真实上传、多模态或模型可读 URL 建议配置 S3/TOS/ImageX：

```text
FILE_UPLOAD_COMPONENT_TYPE=storage
STORAGE_TYPE=s3
S3_ACCESS_KEY
S3_SECRET_KEY
S3_ENDPOINT
S3_BUCKET_ENDPOINT
S3_REGION
STORAGE_BUCKET
```

## Knowledge/RAG 初始化失败

Coze 知识库通常依赖 ES/OpenSearch、Embedding 和 Vector Store。若启动阶段强制初始化这些依赖，应外接 HTTPS endpoint，并配置对应 HF Variables/Secrets：

```text
ES_ADDR
ES_VERSION
ES_USERNAME
ES_PASSWORD
VECTOR_STORE_TYPE
VIKING_DB_HOST
VIKING_DB_REGION
VIKING_DB_AK
VIKING_DB_SK
VIKING_DB_SCHEME
OPENAI_EMBEDDING_BASE_URL
OPENAI_EMBEDDING_MODEL
OPENAI_EMBEDDING_API_KEY
```
