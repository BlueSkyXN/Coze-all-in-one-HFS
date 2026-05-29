# 文档索引

本目录只记录可公开传播的 HFS 运行合同，不记录真实 token、私有 endpoint、账号密码或 `.env.local` 明文。

| 文档 | 内容 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 单端口、多进程、路径分流、内部服务与外部依赖边界 |
| [env-reference.md](env-reference.md) | HF/GH Variables/Secrets 分类、本地 env 台账规则 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 构建、启动、登录、模型、存储和知识库排障入口 |

高频验证入口：

```bash
./scripts/static-check.sh
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```
