# H2OMeta Desktop Migration Implement

## Execution Rules

- 以 `docs/migration/plan.md` 为当前执行事实源。
- 小步修改，优先拆分超大文件。
- 新功能先接入现有 API/runtime 边界，不绕开底座重写。
- 每完成一段可验证改动后立即跑静态验证和构建。

## UI Direction

- 以 Notion 为主参考对象。
- 优先收敛布局噪音、信息密度和操作分区，不做品牌资产复制。
- 设置页优先提升“可操作性”，再保留 JSON 编辑器作为高级入口。
