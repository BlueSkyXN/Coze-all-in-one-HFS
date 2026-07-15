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
- `minio=false`：本地 MinIO fallback 未启动；如果 `ENABLE_LOCAL_MINIO=0`，ops 不检查本地 MinIO，但内置 Milvus 仍需要可访问的外部 `MINIO_ADDRESS`。
- `etcd=false`：Milvus 依赖的 etcd 未启动。
- `elasticsearch=false`：ES 未启动或 `analysis-smartcn` / index template 初始化失败。
- `milvus=false`：Milvus standalone 未启动，先看 etcd/MinIO 依赖；如果日志出现 `libaio.so.1`、`libgomp.so.1` 或 `libopenblas.so.0`，说明 final image 缺 Milvus runtime 动态库。
- `coze_server=false`：Coze Server 未监听 `8888`，继续看 ES、VectorStore、DB 或 model 初始化错误；如果日志出现 `/app/opencoze: cannot execute: required file not found`，说明 Alpine/musl ABI 的 Coze server 二进制缺动态加载器。

如果已配置 `OPS_TOKEN`，继续查看只读诊断面：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/processes
curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/logs?service=coze-server&lines=200"
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-coze-all-in-one-hfs.hf.space/_ops/errors
```

`/_ops/logs` 只能读取 `/data/coze/logs` 下的白名单日志；不能用它读取任意路径、secret 文件或 `.env.local`。

## `/_ops/` 返回 401 或 503

- 401：未提供有效 `OPS_TOKEN`。CLI 使用 `X-Ops-Token` 或 `Authorization: Bearer`。
- 503：`OPS_TOKEN` 未设置或少于 24 字符。

浏览器直接打开：

```text
/_ops/
```

在页面中输入 `OPS_TOKEN`。服务明确拒绝 `?token=`；不要把 secret 放进 URL、浏览器历史或 Nginx access log。刷新页面后需要重新输入，这是有意的非持久化认证边界。

## `/_admin/` 返回 404

这是默认安全状态：`ADMIN_ENABLED=false`。确需短期开启时设置：

```text
ADMIN_ENABLED=true
ADMIN_TOKEN=<at-least-24-random-characters>
```

`ADMIN_TOKEN` 不能复用 `OPS_TOKEN`。admin service 使用独立 `cozeadmin` OS user，默认 audit 路径是 `/data/coze/admin/audit.jsonl`。

开启后用 smoke 验证：

```bash
ADMIN_EXPECTED_ENABLED=true \
ADMIN_TOKEN=$ADMIN_TOKEN \
./scripts/admin-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

公开 Space 不建议长期开启 admin。`/_admin` 只支持白名单 action、`confirm=true`、cookie CSRF 和 audit，不提供 Web terminal、任意 shell command、SQL 执行或 secret rotation。

## `/admin` 或 `/api/admin/*` 返回 404

这是 Coze `v0.5.1` 的临时安全 guard，不是 Nginx 路由遗漏。该版本的 upstream admin middleware 在 admin email 为空时会 fail-open；wrapper 在匹配的 upstream 修复版 server/web 镜像发布前阻断内置 admin UI/API。运行策略通过 HF Variables/Secrets 和 `/app/.env` 管理，不要绕过该 guard。

## 登录或注册被拦

公开 Space 默认关闭注册：

```bash
DISABLE_USER_REGISTRATION=true
```

`ALLOW_REGISTRATION_EMAIL` 在 Coze `v0.5.1` fresh fallback config 中存在 upstream 读取缺陷，不能只凭 env 值声称 allowlist 已生效。受控测试可以设置：

```bash
ALLOW_REGISTRATION_EMAIL=you@example.com
```

设置后仍需执行真实注册 smoke；不要在公开文档、PR 文案或截图里写真实邮箱、账号或密码。

## Code runner 不在 sandbox

生成的 `/app/.env` 应包含：

```text
CODE_RUNNER_TYPE=sandbox
CODE_RUNNER_ALLOW_NET=cdn.jsdelivr.net
```

Coze `v0.5.1` 对空值会回退到 local runner。本 wrapper 已显式覆盖为 sandbox；如果手动设置 `CODE_RUNNER_TYPE=local`，属于明确降低隔离级别的操作。静态 env 检查不能替代真实 workflow code-node smoke，尤其要确认 `user` 的 `HOME=/home/user` 下 Deno/Pyodide 首次加载成功。

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

Coze 启动阶段会初始化 ES 和 Vector Store。本包装仓默认内置 ES + Milvus；若改用外部托管服务，配置对应 HF Variables/Secrets：

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
