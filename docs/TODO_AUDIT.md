# EchoGraph TODO 审计清单

本文档用于汇总当前已知的 TODO，重点标注“空实现/未落地逻辑”。

## 空实现 / 占位实现

1. `src/tavern/tavern_connector.py`
   - `TODO(tavern-monitor): 实现 WebSocket 或轮询监控机制，并在连接/会话状态变化时回调 callback。`

## 已完成（最近修复）

1. `src/core/validation.py`
   - 已替换占位实现，新增结构校验、关系语义校验、危险删除拦截与置信度门槛。
   - 已支持基础策略参数（`min_confidence`、`allow_wildcard_deletions`）与校验统计（`validation_report`）。

## 现有功能性 TODO

1. `run_ui.py`
   - `TODO: 实现对话历史同步`
   - `TODO: 从配置获取`（API base URL）
   - `TODO: 未来可以实现真正的对话-图谱关联机制`
