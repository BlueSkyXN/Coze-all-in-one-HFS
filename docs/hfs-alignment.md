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

容器内由 Supervisor 管理 MariaDB、Redis、NATS、MinIO fallback、etcd、Elasticsearch、Milvus、Coze Server、ops service 和 Nginx。外部只通过 Nginx `7860` 进入：

```text
/nginx-health          shallow Nginx health
/_ops/healthz          read-only HFS runtime health JSON
/_ops/readyz           same health payload
/_ops/status           same health payload
/sign                  Coze Web login entry
/api, /v1, /v2, /admin Coze Server proxy
/local_storage/        optional MinIO fallback proxy
```

`/_ops/*` 只保留 read-only diagnostics。不要在 `/_ops` 下加入 shell、SQL、restart、delete、secret rotation、配置写入或任意命令执行能力；如果未来需要管理面，应另设明确隔离的管理入口并先确认风险。

## Release Pins

`hfs-dev.toml` 使用 schema v2 的 `[[release_pins]]` 记录所有 release 需要审计的输入：

- Coze image tags：`COZE_SERVER_TAG`、`COZE_WEB_TAG`
- Coze upstream config ref：`COZE_GIT_REF`
- Runtime dependency images：`ELASTICSEARCH_IMAGE`、`ETCD_IMAGE`、`MILVUS_IMAGE`
- Downloaded artifacts：Deno、Atlas installer、MinIO server、MinIO client

当前开发默认值保持可读 tag/version。对外 release 前，应确认 Coze server/web/tag/git ref 三者一致，并优先把 Coze 镜像 tag 写成 `tag@sha256:...`，把依赖镜像和下载型 artifact 收敛到 digest/checksum 可验证的形式。Dockerfile 不直接执行 `curl | sh`，下载型 artifact 会在 checksum build arg 存在时先校验再安装。

## Local-Only Materials

`local/` 只作参考材料或本地临时记录，不进入部署包、公开文档真相源或提交边界。`.env.local` 是本机私有 env ledger，只能记录本地同步状态和私有值；公开文档只写 key、分类、默认值、占位符和操作规则。

## Validation

默认本地验证：

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
```

线上 Space 验证：

```bash
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

如果本机没有 Docker，不要把本地 build/run 写成已验证；以静态检查、HF build logs、HF runtime logs 和 live endpoint 回读分层说明。
