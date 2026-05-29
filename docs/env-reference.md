# ENV Reference

`.env.local` 是本机私有 ENV 台账，不是 runtime 自动加载文件，也不是要上传到 GitHub 或 Hugging Face 的 env-file。公开仓库只维护本文件这类 reference：写 key、分类、默认值、建议位置和说明，不写真实值。

当前远端回读时间：2026-05-29。

| 平台 | 当前状态 |
| --- | --- |
| GitHub Variables | 未配置 |
| GitHub Secrets | 未配置 |
| Hugging Face Variables | 已同步基础运行策略；外部 Provider 按需补充 |
| Hugging Face Secrets | 当前未配置；模型/存储/检索等密钥按需设置 |

## 推荐 HF Variables

| Key | 默认值 | 建议 | 说明 |
| --- | --- | --- | --- |
| `DISABLE_USER_REGISTRATION` | `true` | `true` | 公开 Space 默认关闭注册。 |
| `ALLOW_REGISTRATION_EMAIL` | 空 | 按需填写 | 只允许指定邮箱注册；含个人邮箱时可放本地台账，不写公开 PR 文案。 |
| `ENABLE_LOCAL_MINIO` | `1` | P0/P1 可保留 `1` | 本地 MinIO fallback；设为 `0` 时必须提供外部 object storage，并确保内置 Milvus 可访问 `MINIO_ADDRESS`。 |
| `COZE_PUBLIC_URL` | 从 `SPACE_HOST` 推导 | `https://blueskyxn-coze-all-in-one-hfs.hf.space` | 公开 URL；自定义域名时显式覆盖。 |
| `LOG_LEVEL` | `info` | `info` | Coze Server 日志级别。 |
| `ES_ADDR` | `http://127.0.0.1:9200` | 默认不上传 | 内置 Elasticsearch；只有改用外部 ES/OpenSearch 时才覆盖。 |
| `VECTOR_STORE_TYPE` | `milvus` | 默认不上传 | 内置 Milvus；只有改用 VikingDB/OceanBase/外部 Milvus 时才覆盖。 |

## 推荐 HF Secrets

| Key | 用途 | 说明 |
| --- | --- | --- |
| `MODEL_API_KEY_0` | 默认模型 API key | OpenAI-compatible 模型配置。 |
| `BUILTIN_CM_OPENAI_API_KEY` | 内置 conversation model key | 通常与默认模型 key 同源。 |
| `OPENAI_EMBEDDING_API_KEY` | Embedding key | 启用知识库/RAG 时配置。 |
| `S3_ACCESS_KEY` | S3/TOS/ImageX access key | 文件上传和多模态建议外接对象存储。 |
| `S3_SECRET_KEY` | S3/TOS/ImageX secret key | 必须放 Secret。 |
| `ES_PASSWORD` | ES/OpenSearch password | 私有检索服务凭据。 |
| `VIKING_DB_AK` / `VIKING_DB_SK` | VikingDB 凭据 | 使用 VikingDB vector store 时配置。 |
| `TOS_ACCESS_KEY` / `TOS_SECRET_KEY` | 火山 TOS 凭据 | 使用 TOS 时配置。 |

## 可放 HF Variables 的非敏感 Provider 配置

| Key | 示例 | 说明 |
| --- | --- | --- |
| `MODEL_PROTOCOL_0` | `openai` | 模型协议。 |
| `MODEL_OPENCOZE_ID_0` | `100001` | Coze 内部模型 ID。 |
| `MODEL_NAME_0` | `example-model` | 页面显示名。 |
| `MODEL_ID_0` | `example-model` | Provider 模型 ID。 |
| `MODEL_BASE_URL_0` | `https://provider.example/v1` | 如果 URL 含租户或私有网关信息，改放 Secret。 |
| `BUILTIN_CM_TYPE` | `openai` | 内置模型类型。 |
| `BUILTIN_CM_OPENAI_BASE_URL` | `https://provider.example/v1` | 如果 URL 含私有信息，改放 Secret。 |
| `BUILTIN_CM_OPENAI_MODEL` | `example-model` | 内置模型 ID。 |
| `FILE_UPLOAD_COMPONENT_TYPE` | `storage` | 外接对象存储时使用。 |
| `STORAGE_TYPE` | `s3` | 也可按上游支持填 `tos` 等。 |
| `S3_ENDPOINT` | `https://s3.example.com` | 私有 endpoint 视敏感程度放 Secret。 |
| `S3_BUCKET_ENDPOINT` | `https://bucket.example.com` | 公开 bucket endpoint 可放 Variable。 |
| `S3_REGION` | `us-east-1` | S3 region。 |
| `STORAGE_BUCKET` | `opencoze` | bucket 名若敏感则放 Secret。 |
| `ES_ADDR` | `https://es.example.com` | 默认内置本地 ES；外部 endpoint 视敏感程度放 Secret。 |
| `ES_VERSION` | `v8` | ES 版本。 |
| `VECTOR_STORE_TYPE` | `vikingdb` | 默认内置 `milvus`；外部向量库才覆盖。 |
| `VIKING_DB_HOST` | `api-vikingdb.example.com` | 私有 endpoint 视敏感程度放 Secret。 |
| `VIKING_DB_REGION` | `cn-beijing` | region。 |
| `VIKING_DB_SCHEME` | `https` | scheme。 |

## 平台注入项

不要手动设置这些 key：

```text
SPACE_ID
SPACE_HOST
HF_HOME
```

`SPACE_HOST` 由 Hugging Face runtime 注入，`render-env.sh` 会在未设置 `COZE_PUBLIC_URL` 时自动推导 `https://${SPACE_HOST}`。

## 本地 `.env.local` 台账格式

推荐保留四层：

```text
# [HF_SPACE]
# [HF_VARIABLES]
# [HF_SECRETS]
# [LOCAL_OPS]
```

上传原则：

- 只上传需要生效的非空值。
- 空占位不上传，避免把云端覆盖成空字符串。
- HF Secrets 只能回读 key，不能回读明文；一致性通过本地台账、key 清单和 live smoke 闭环确认。
- GH Variables/Secrets 当前没有运行时需求，保持为空。
