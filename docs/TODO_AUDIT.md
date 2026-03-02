# EchoGraph TODO 审计清单

本文档用于汇总当前已知的 TODO，重点标注“空实现/未落地逻辑”。

## 空实现 / 占位实现

（当前无）

## 已完成（最近修复）

1. `src/core/validation.py`
   - 已替换占位实现，新增结构校验、关系语义校验、危险删除拦截与置信度门槛。
   - 已支持基础策略参数（`min_confidence`、`allow_wildcard_deletions`）与校验统计（`validation_report`）。

2. `src/tavern/tavern_connector.py`
   - 已实现轮询式状态监控（连接/角色/会话/消息数量），并在状态变化时触发 callback。

3. `run_ui.py`
   - 已实现“删除消息 -> 同步删除对话历史”。
   - 已实现本地模式按对话隔离图谱快照（切换时保存当前对话、加载目标对话）。
   - 已将酒馆会话轮询升级为持续监控（会话丢失/重连可自动更新状态与图谱附着）。

## 现有功能性 TODO

1. `run_ui.py`
   - `TODO: 从配置获取`（API base URL）
