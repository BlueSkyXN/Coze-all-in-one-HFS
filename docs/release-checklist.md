# Release Checklist

本清单用于把 Coze All In One HFS 从本地改动推进到 GitHub 与 Hugging Face Space。执行前确认本地没有要保留但未提交的无关改动。

## 1. Static Gate

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
git diff --check
```

`static-check.sh` 会覆盖 HFS contract、Bash syntax、`ops_service.py` 编译、`hfs/tests` 单测、`.dockerignore` 私有文件排除和变更文件尾随空白检查。

## 2. Release Pin Review

检查 `hfs-dev.toml` 的 `[[release_pins]]` 与 `Dockerfile` 一致：

- `COZE_SERVER_TAG`、`COZE_WEB_TAG`、`COZE_GIT_REF` 指向同一 Coze Studio release；正式 release 前优先使用 `tag@sha256:...`。
- `ELASTICSEARCH_IMAGE`、`ETCD_IMAGE`、`MILVUS_IMAGE` 对外 release 前优先改成 digest-pinned image ref。
- Deno、Atlas installer、MinIO server、MinIO client 仍是下载型 artifact；正式 release 前应补 `DENO_SHA256_*`、`ATLAS_INSTALL_SHA256`、`MINIO_SHA256_*`、`MC_SHA256_*` 或改为可信 artifact source。

如果只是在开发环境快速验证，可以保留当前可读 tag/version，但发布说明里不要把它描述成 checksum-verified release。

## 3. Env Ledger

`.env.local` 是唯一的本机私有记录，不提交、不上传、不写入公开 docs。发布前只核对 key 分类：

- HF Variables：非敏感运行策略，如 `DISABLE_USER_REGISTRATION`、`ENABLE_LOCAL_MINIO`、`COZE_PUBLIC_URL`。
- HF Secrets：模型、Embedding、S3、ES、Vector、OCR、rerank、第三方 API 的 token/key/password。
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
- smoke 覆盖到 `/nginx-health`、`/_ops/healthz` 和 `/sign`

如果 runtime SHA 尚未切到目标 commit，继续查 HF build/runtime logs，不要把 repo push 视为部署完成。
