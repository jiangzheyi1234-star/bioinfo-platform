# Detection Workspace V2 Implement Rules

1. 先改结构壳，再改流程映射，再做样式细化。
2. 每完成一组改动先做 JS 语法检查；检查失败禁止进入下一组。
3. M3 后保留 `switchTab('history'|'integrated')` 兼容语义，但禁止再依赖 legacy 独立 DOM。
4. 新增交互默认可回退（隐藏入口/切换 class），避免一次性硬切。
5. 发现主链路断裂（提交后无法定位 run、结果无法打开）必须立即修复，不允许带病推进。
