# Coze-all-in-one-HFS 协作说明

本仓库是 Hugging Face Docker Space 包装仓，按 HFS Pattern A 维护：仓库根目录同时是 GitHub 维护根和 Hugging Face Space root。`local/` 只作参考材料，不进入部署包、提交边界或云上事实。

## 边界

- 上游 source of truth 是 `coze-dev/coze-studio` 与 `cozedev/coze-studio-*` 镜像；本仓库只维护 HFS 单容器 runtime glue、文档、smoke 和 env 台账。
- `hfs/` 是高风险 runtime 层，包含 entrypoint、Nginx、Supervisor、MariaDB/Redis/NATS/MinIO glue 和 ops health；改动后必须跑静态检查。
- `/_ops/*` 必须保持只读诊断面，不加入 shell、SQL、restart、delete、secret rotation 或配置写入能力。
- `.env.local` 是本机私有台账，必须保持 gitignored；公开文档只能写 key、分类、默认值、占位符和操作规则。

## 常用命令

```bash
./scripts/static-check.sh
./scripts/check-syntax.sh
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```

本机当前没有 Docker 时，不要声称完成本地 build/run；以静态检查、HF build logs、HF runtime logs 和 live endpoint 回读为准。

## 部署验证

- GitHub 代码源：`https://github.com/BlueSkyXN/Coze-all-in-one-HFS`
- Hugging Face Space：`https://huggingface.co/spaces/BlueSkyXN/Coze-all-in-one-HFS`
- Live host：`https://blueskyxn-coze-all-in-one-hfs.hf.space`
- Canonical health：`/_ops/healthz`
- Shallow Nginx health：`/nginx-health`

## ENV 管理

- HF Variables：非敏感运行策略，如 `DISABLE_USER_REGISTRATION`、`ENABLE_LOCAL_MINIO`、`COZE_PUBLIC_URL`。
- HF Secrets：模型、Embedding、S3、ES、Vector、OCR、rerank、第三方 API 的 token/key/password。
- GH Variables/Secrets：当前仓库没有 CI/CD runtime 需求时保持为空。
- 平台注入项如 `SPACE_HOST`、`SPACE_ID` 不要手动配置。
