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

## 2. Hybrid Artifact Review

先检查 `hfs-dev.toml` 是最小 HFS v2.1 preview registry：`standard="2.1"`、`project_class="preview"`、`target_role="primary"`、Pattern A `port`、artifact registry lane、Setting key names 和已登记 hybrid deviation。不要把 Docker ARG、artifact checksum 或 runtime invariant 复制回 registry。

每次 server/web artifact 发布必须满足：

- workflow 输入为完整 40 位 `upstream_ref`；构建 checkout、commit-named `BUILD_SOURCE-<commit>.json`、manifest `source_ref` 和 artifact 文件名必须一致。
- commit-named `BUILD_SOURCE-<commit>.json`、server、web 都有 SHA-256；manifest 还记录 server/web `size_bytes`。
- 用 `scripts/verify-runtime-artifacts.py` 在发布前验证 manifest、checksum、tar safety 和入口文件。
- 只允许 artifact-first → object readback → manifest-last；Space runtime 不扫描 slot、旧 `/app`、cache 或备用 URI。
- `release` 把已验证集合写入 GitHub Release 历史；`promote-release` 必须从该 Release 重下载、复验后再写 `release/`。

`COZE_SOURCE_COMMIT` 是 server/web artifact、schema 与 Atlas HCL 的唯一来源；`COZE_RELEASE_TAG` 只作 release label。Elasticsearch、etcd、Milvus 仍必须保持 Dockerfile digest；没有组件 extraction、动态库、cold-start 和持久化证据时，不能删去 deviation 或声称已 artifact 化。

## 3. Env Ledger

`.env` 是 HFS 唯一的本机明文事实源，不提交、不上传、不写入公开 docs。Secret 必须先在该文件中落盘，再写入 Space；`.env.local` 只保留本地运行兼容。发布前只核对 key 分类：

- HF Variables：非敏感运行策略，如 `DISABLE_USER_REGISTRATION`、`ENABLE_LOCAL_MINIO`、`COZE_PUBLIC_URL`。
- HF Secrets：`OPS_TOKEN`、按需开启时的 `ADMIN_TOKEN` / `ADMIN_CSRF_KEY`、模型、Embedding、S3、ES、Vector、OCR、rerank、第三方 API 的 token/key/password。
- 平台注入项：`SPACE_HOST`、`SPACE_ID` 等不要手动配置。

`ENABLE_LOCAL_MINIO=0` 只适合已经提供外部 object storage 的场景。只要继续使用内置 Milvus，就必须保证 `MINIO_ADDRESS` 指向一个 Milvus 可访问的对象存储 endpoint，并提前准备好 `MINIO_BUCKET_NAME` 对应 bucket。

如果 `/data/coze` 已挂载 read-write HF bucket volume，同时设置 `PERSISTENCE_REQUIRED=true`。此后 canonical health 会把 mount 丢失视为 503，避免在 overlay filesystem 上静默启动并误报持久化正常。线上 smoke 使用 `SMOKE_PERSISTENCE_REQUIRED=true` 回读该门禁。

## 4. Controlled Remote Publication

artifact publication 仍只允许 GitHub Actions 的手动 workflow；选择 `publish-edge`、`release` 或 `promote-release` 时必须填写 `confirmed=true`。本项目属于 Preview，wrapper 或 Settings 可直接更新 canonical Space，但 Secret 必须本地明文先行，并且写后必须 readback；candidate 只是高风险可选验证。仍禁止 credential-bearing Git URL、whole-repo force-push 和 `hf upload --delete`。

发布后至少 read back：

- artifact、commit-named `BUILD_SOURCE-<commit>.json` 与最后写入的 manifest 字节一致；
- GitHub Release tag、target commit 与 assets；
- Space wrapper revision、runtime provenance 和 Setting key presence；
- Space runtime stage / SHA、`/nginx-health`、`/_ops/healthz`、`/_ops/version`、`/sign` 与适用的 auth/business smoke。

GitHub commit、artifact publication、Space wrapper update 和运行接管是独立事实；任何单项成功均不代表其余层已完成。

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

Coze `v0.5.1` 部署还应确认 `/admin` 与 `/api/admin/*` 返回 404，并在业务验证中确认 code runner 使用 sandbox。版本升级后必须检查启动日志包含目标 schema SHA-256，并验证旧数据目录执行了 Atlas reconcile；不能只确认新 binary 已启动。

如果 runtime SHA 尚未切到目标 commit，继续查 HF build/runtime logs，不要把 repo push 视为部署完成。
