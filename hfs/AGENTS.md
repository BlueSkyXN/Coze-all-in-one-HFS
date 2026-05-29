# hfs/ Runtime Guardrails

本目录是 Hugging Face Docker Space 的 runtime glue 层。改这里会直接影响容器启动、端口暴露、数据目录、健康检查和线上可诊断性。

## 适用边界

- `bin/`：entrypoint、服务启动脚本、healthcheck、ops service。
- `conf/`：Nginx、Supervisor、Redis、NATS 等运行配置。
- `tests/`：只覆盖本目录内脚本或 Python runtime helper，不依赖真实外部服务。

## 不变量

- 对外只暴露 Nginx `7860`，不要新增第二个 public listener。
- `/_ops/healthz`、`/_ops/readyz`、`/_ops/status` 必须保持 read-only JSON 诊断面。
- `/_ops/*` 不允许加入 shell、SQL、restart、delete、secret rotation、配置写入或任意命令执行。
- `/data/coze` 是持久化根；MySQL、Redis、NATS、MinIO、etcd、Milvus、Elasticsearch 的运行数据不要写回镜像层。
- Nginx 必须保留 `/nginx-health`、`/_ops/*` proxy、Coze Web 静态入口、Coze Server API proxy 和 `/local_storage/` fallback 的路径边界。
- `ENABLE_LOCAL_MINIO=0` 只表示不启动本地 MinIO；内置 Milvus 仍需要 `MINIO_ADDRESS` 指向可访问的外部对象存储。

## 修改规则

- 改 `ops_service.py` 时同步更新 `hfs/tests/test_ops_service.py`，并保持无第三方 Python 依赖。
- 改端口、路由、health endpoint 或 `Dockerfile` build input 时，同步更新 `hfs-dev.toml`、`scripts/validate-hfs-contract.sh`、`scripts/hf-space-smoke.sh` 和公开 docs。
- 改启动顺序或服务名时，同步检查 `supervisord.conf`、对应 `run-*.sh`、`healthcheck.sh` 和 README/docs 的服务列表。
- 不把 `.env.local`、真实 token、私有 endpoint、账号密码或本机路径写入本目录。

## 验证

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
python3 -m unittest discover -s hfs/tests -p 'test_*.py'
```

需要验证线上 Space 时再跑：

```bash
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```
