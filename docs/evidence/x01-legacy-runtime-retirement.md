# X-01 旧运行时模型退役

状态：**已完成（2026-09-29）**。

## 变更

- Lobby 生产 session/routing 不再注入或读取 `catalog_agents`；profile session 的
  `SessionAgentSnapshot` 和 `SessionCapabilitySnapshot` 是 persona、工具授权和运行限制的
  唯一运行时输入。旧 catalog repository 仅保留给一次性迁移和历史测试。
- 旧 `/catalog` CRUD handler 不再由生产 Lobby 注册；profile/revision、Skill revision
  和 capability catalog API 是新的配置入口。
- chatsvc 的编译工具清单重命名为 `runtimeToolManifestJSON`，明确它只是实现 inventory；
  session snapshot 与每轮 `allowed_tools` 继续负责授权。
- 新增 snapshot projection 单测，确保 system prompt 和 turn budget 从冻结 revision 投影，
  不回读旧 catalog。

## 验证

```text
go test ./...
go test ./internal/lobby/usecase ./internal/lobby/transport/http ./cmd/chatsvc ./cmd/lobby
git diff --check
```

以上命令均通过。生产入口审计确认 `CatalogUC: nil`、`AgentRepo: nil`，且
`SkillSnapshotResolver` 不再使用 legacy catalog resolver。

