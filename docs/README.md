# 文档索引

本目录只记录可公开传播的 HFS 运行合同，不记录真实 token、私有 endpoint、账号密码或 `.env.local` 明文。

| 文档 | 内容 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 单端口、多进程、路径分流、内部服务与外部依赖边界 |
| [env-reference.md](env-reference.md) | HF/GH Variables/Secrets 分类、本地 env 台账规则 |
| [hfs-alignment.md](hfs-alignment.md) | HFS Pattern A、runtime mode、Space root、release pin 与验证合同 |
| [release-checklist.md](release-checklist.md) | 发布前静态检查、env ledger、remote sync 与 live runtime 收口清单 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 构建、启动、登录、模型、存储和知识库排障入口 |

高频验证入口：

```bash
./scripts/static-check.sh
./scripts/hf-space-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
./scripts/admin-smoke.sh https://blueskyxn-coze-all-in-one-hfs.hf.space
```
