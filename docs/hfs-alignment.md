# HFS Alignment

本文件只记录可公开传播的 HFS 运行合同；不记录 `.env` / `.env.local` 明文、token、私有 endpoint 或本机路径。

## Contract

- Pattern A: HFS Port Repository
- HFS v2.1 registry: `hfs-dev.toml` (`standard = "2.1"`)
- Project class: `preview`; canonical target role: `primary`
- Delivery lane: `artifact` registry with a hybrid implementation
- Space root: repo root
- Public port: `7860`
- Canonical health endpoint: `/_ops/healthz`

仓库根目录同时是 GitHub 维护根和 Hugging Face Space root。reviewable wrapper 包含 `Dockerfile`、`hfs/`、docs 和 local gates；Space build context 不包含产品源码、`.env*`、`local/`、cache、generated data 或 credentials。

`hfs-dev.toml` 只登记 HFS v2 的项目关系、车道和 Setting 键名。上游 ref、镜像 digest、checksum、bootstrap 和 runtime invariants 的事实源仍是 `Dockerfile`、`hfs/bin/bootstrap_runtime.py` 与构建 workflow；不要把它们复制到 manifest 形成第二份 pin 表。

Preview 日常变更可以直接更新 canonical Space，再做 readback 和 smoke。任何 Secret 都必须先写入被忽略的本机明文 `.env`；远端值只是部署副本，无法反向读回。`hfs-dev.candidate.toml` 仅用于高风险可选验证，不是常规前置，其独立账本为 `local/hfs-targets/candidate.env`。

## Hybrid Runtime Boundary

Coze server 与 web 是不可变 runtime artifacts。启动时 `bootstrap_runtime.py`：

1. 只读取一次 `COZE_RUNTIME_MANIFEST_URI` 指向的 Hugging Face HTTPS `manifest.json`；URL 不允许 query、fragment 或嵌入凭据。仅允许 `huggingface.co` 同域中间跳转和 `*.xethub.hf.co` 下载跳转；Bearer 只在同域保留，进入 Xet 域前移除。
2. 只接受 `schema_version=1`、完整 40 位 Git commit、按该 commit 命名的 `BUILD_SOURCE-<commit>.json` checksum，以及恰好一份 server 和 web artifact。
3. 从 manifest 同目录下载按 commit 命名的 `BUILD_SOURCE-<commit>.json`、server 和 web；分别校验 SHA-256、size、完整 component provenance、tar path/link/device/privileged-mode safety、解包上限与必需入口文件。两个 payload 先共同完成 staging 与动态库验证，再安装；任一替换失败会恢复两个先前目录。
4. 仅将成功校验的 payload 原子安装至 `/app/runtime` 与 `/opt/coze-web`。server staging 与目标均位于 HF 的 `/app` filesystem，避免跨设备 rename；下载文件仍只在 `/tmp`，不会写入 `/data/coze`。
5. 任一 manifest、网络、checksum、size、archive、动态库或安装错误都会非零退出；不会扫描目录、使用 `latest`、旧 `/app`、本地缓存或备用 URI。

`COZE_RUNTIME_DOWNLOAD_TOKEN` 是可选 Space Secret，仅以 Authorization header 发送，不进入 URL、日志或 provenance。私有 `hfs-dist` 的实际直连 URL / access model 必须在发布前由 owner 验证；不能以非空 token 或网页可见性代替 readback。

`/_ops/version`（受 `OPS_TOKEN` 保护）仅返回 bootstrap 写入的 source commit、manifest checksum、artifact name/checksum/size。不会返回 manifest URL、下载 token 或其他 Secret。

## Immutable Artifact Publication

`.github/workflows/build-pinned-coze.yml` 只支持手动触发：

- `build`：以显式 40 位 `upstream_ref` 构建并验证成对 server/web bundle；不写远端。
- `publish-edge`：必须 `confirmed=true`，先上传 commit-named artifact 和 `BUILD_SOURCE-<commit>.json`、逐项 readback，再最后写 `edge/manifest.json` 并 readback。
- `release`：必须 `confirmed=true` 与 `release_tag`，将已验证运行时集合存为 GitHub Release 历史归档并 readback。
- `promote-release`：必须 `confirmed=true`，从 GitHub Release 重新下载并验证后，按 artifact-first / readback / manifest-last 写入 `release/`。

槽位约定为 `hfs-dist/coze-all-in-one-hfs/{edge,release}`。artifact 文件名包含完整 source commit；`manifest.json` 是唯一选择器。观察期和明确 owner gate 之后才可删除不再引用的槽位对象。artifact promotion 仍是独立发布控制，不构成 Preview 修改 canonical Space 的常规前置。

## Retained Infrastructure Deviations

Elasticsearch、etcd 和 Milvus 仍通过 digest-pinned image input 提供，因为其 rootfs、动态库、启动和持久化耦合尚未完成逐组件 extraction/cold-start proof。这是记录在 `hfs-dev.toml` 的限期 hybrid deviation，而不是 artifact 车道已完成的声明。解除前必须由 owner 批准并完成动态库、license、health、cold-start、持久化和隔离恢复验证。

MariaDB、Redis、NATS、MinIO、etcd、Milvus、Elasticsearch 的服务、路径、端口、auth、Nginx routing、`/_ops/*` 只读边界和 default-off `/_admin/*` 语义不因 artifact bootstrap 改变。`/data/coze` 继续是持久化根；`/run/coze`、Nginx temporary files、ES 和 Milvus local runtime state 继续留在容器本地。

## Validation

```bash
./scripts/validate-hfs-contract.sh
./scripts/check-syntax.sh
python3 -m unittest discover -s hfs/tests -p 'test_*.py'
./scripts/static-check.sh
python3 /Users/sky/Github/SKY-Prompt/hfs-dev/scripts/check_hfs_alignment.py .
git diff --check
```

Docker build/run、artifact build/publish/promote、Space Settings sync、remote smoke、login/business flow、backup 和隔离 restore 都是单独的 owner/runtime gates；本地静态检查不能替代它们。
