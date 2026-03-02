# EchoGraph TODO 审计清单

本文档用于汇总当前已知的 TODO，重点标注“空实现/未落地逻辑”。

## 空实现 / 占位实现

1. `src/core/validation.py`
   - `TODO(validation): 用真实的冲突/规则校验替换当前占位实现。`
   - `TODO(validation): 增加可配置的校验策略与指标统计。`
   - `TODO(validation): 在写入图谱前校验实体字段、关系完整性与危险更新。`

2. `src/tavern/tavern_connector.py`
   - `TODO(tavern-monitor): 实现 WebSocket 或轮询监控机制，并在连接/会话状态变化时回调 callback。`

## 现有功能性 TODO

1. `run_ui.py`
   - `TODO: 实现对话历史同步`
   - `TODO: 从配置获取`（API base URL）
   - `TODO: 未来可以实现真正的对话-图谱关联机制`
