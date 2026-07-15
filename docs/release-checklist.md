# Release Checklist

本清单用于把 Coze All In One HFS 从本地改动推进到 GitHub 与 Hugging Face Space。执行前确认本地没有要保留但未提交的无关改动。

## 1. Static Gate

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
git diff --check
```

`static-check.sh` 会覆盖 HFS contract、Bash syntax、runtime helper 编译、`hfs/tests` 单测、sandbox env 渲染、`.dockerignore` 私有文件排除和变更文件尾随空白检查。
如果改动涉及 `/_admin`，并且目标 runtime 已启动，额外运行：

```bash
./scripts/admin-smoke.sh <base-url>
```

默认会验证 `ADMIN_ENABLED=false` 时 `/_admin/` 和 `/_admin/api/status` 返回 404；显式开启 admin 时必须提供 `ADMIN_TOKEN`。

## 2. Release Pin Review

检查 `hfs-dev.toml` 的 `[[release_pins]]` 与 `Dockerfile` 一致：

- `COZE_SERVER_TAG`、`COZE_WEB_TAG`、`COZE_GIT_REF` 指向同一 Coze Studio release；Coze server/web 默认值必须保持 `tag@sha256:...`。
- `ELASTICSEARCH_IMAGE`、`ETCD_IMAGE`、`MILVUS_IMAGE` 对外 release 前优先改成 digest-pinned image ref。
- Deno、Atlas installer、MinIO server、MinIO client 仍是下载型 artifact；正式 release 前应补 `DENO_SHA256_*`、`ATLAS_INSTALL_SHA256`、`MINIO_SHA256_*`、`MC_SHA256_*` 或改为可信 artifact source。

即使 Coze 镜像已经 digest-pinned，只要依赖镜像、Deno、Atlas 或 MinIO/MC 仍未提供完整 digest/checksum，发布说明就不能描述成全链路 checksum-verified release。

同时执行 upstream readback：确认最新正式 release、Docker Hub server/web tag digest、`v<current>...main` commit 差异。没有匹配 server/web image pair 时，不允许只把 `COZE_GIT_REF` 切到 upstream `main`。

## 3. Env Ledger

`.env.local` 是唯一的本机私有记录，不提交、不上传、不写入公开 docs。发布前只核对 key 分类：

- HF Variables：非敏感运行策略，如 `DISABLE_USER_REGISTRATION`、`ENABLE_LOCAL_MINIO`、`COZE_PUBLIC_URL`。
- HF Secrets：`OPS_TOKEN`、按需开启时的 `ADMIN_TOKEN` / `ADMIN_CSRF_KEY`、模型、Embedding、S3、ES、Vector、OCR、rerank、第三方 API 的 token/key/password。
- 平台注入项：`SPACE_HOST`、`SPACE_ID` 等不要手动配置。

`ENABLE_LOCAL_MINIO=0` 只适合已经提供外部 object storage 的场景。只要继续使用内置 Milvus，就必须保证 `MINIO_ADDRESS` 指向一个 Milvus 可访问的对象存储 endpoint，并提前准备好 `MINIO_BUCKET_NAME` 对应 bucket。

## 4. Remote Sync

确认 GitHub 和 Hugging Face remote 分层：

```bash
git remote -v
git status --short --branch --untracked-files=all
git rev-parse HEAD origin/main
```

需要部署到 HF 时，再显式推送 Space remote：

```bash
git push hf main
```

GitHub push、HF repo commit、HF runtime takeover 是三层验证，不要只看其中一层就下结论。

## 5. Live Runtime Gate

HF build 完成后先看 Space runtime 状态，再跑 live smoke：

```bash
hf spaces info BlueSkyXN/Coze-all-in-one-HFS
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

收口时至少记录：

- HF runtime `stage`
- HF runtime `raw.sha`
- GitHub `origin/main` SHA
- HF Space repo SHA
- smoke 覆盖到 `/nginx-health`、`/_ops/healthz`、`?token=` 拒绝、upstream `/admin` guard、`/_admin/` 默认关闭状态和 `/sign`

如果提供 `OPS_TOKEN`，`hf-space-smoke.sh` 会额外检查 `/_ops/health`、`/_ops/system`、`/_ops/metrics` 和 `/_ops/errors`；smoke 还会验证 `?token=` 被拒绝，避免 secret 进入 URL/access log。如果目标实例显式开启 admin，设置 `SMOKE_ADMIN_ENABLED=true ADMIN_TOKEN=<admin-token>`，脚本会检查 `/_admin/api/status`、`/_admin/api/actions` 与 `/_admin/api/audit`；默认不会执行 admin action，除非额外设置 `SMOKE_ADMIN_ACTIONS=true`。

Coze `v0.5.1` 部署还应确认 `/admin` 与 `/api/admin/*` 返回 404，并在业务验证中确认 code runner 使用 sandbox。下一次版本升级前，先验证持久化 DB 的 Atlas migration，不要只确认新 binary 已启动。

如果 runtime SHA 尚未切到目标 commit，继续查 HF build/runtime logs，不要把 repo push 视为部署完成。
