# EchoGraph 滑动窗口对话管理设计

## 问题分析

1. **对话不稳定性**：用户可能随时修改、删除、重新生成对话
2. **冲突处理复杂**：历史记录可能被改得面目全非
3. **节点创建不完整**：新角色缺乏基础属性
4. **更新时机混乱**：不确定何时进行GRAG更新

## 解决方案：滑动窗口 + 延迟更新

### 1. 滑动窗口机制

```
对话历史：[轮次1] [轮次2] [轮次3] [轮次4] [轮次5] [轮次6(新)] ...
有效窗口：                    [轮次3] [轮次4] [轮次5]
更新目标：                            [轮次4]  <- 用户发轮次6时更新轮次4
```

**窗口规则**：
- 窗口大小：3-5轮对话（可配置）
- 只有窗口内的对话修改才会影响GRAG
- 超出窗口的历史修改被忽略

### 2. 延迟更新策略

**触发时机**：用户发出新消息时，分析**倒数第2轮**对话
- 用户发轮次N → 分析轮次(N-2)
- 确保被分析的对话相对稳定
- 避免分析正在进行的对话

### 3. 版本冲突解决

每轮对话包含：
```json
{
  "turn_id": "uuid",
  "sequence": 123,
  "timestamp": "2025-01-01T12:00:00",
  "user_input": "...",
  "llm_response": "...",
  "grag_processed": false,
  "grag_timestamp": null
}
```

**冲突解决规则**：
- 同一轮次多个版本 → 最新时间戳获胜
- GRAG更新基于最终版本
- 已处理的轮次如果被修改 → 重新标记待处理

### 4. 智能节点创建

**新角色检测**：Agent分析时发现新实体
**属性推断策略**：
```json
{
  "node_id": "ellie_forest_elf",
  "type": "character",
  "base_attributes": {
    "name": "Ellie",
    "race": "Forest Elf",
    "location": "mysterious_forest",
    "disposition": "helpful_but_cautious",
    "knowledge_level": "local_expert"
  },
  "world_context_attributes": {
    "faction": "neutral",
    "threat_level": "low",
    "interaction_history": []
  }
}
```

### 5. 实现架构

#### 5.1 对话管理器
```python
class SlidingWindowManager:
    def __init__(self, window_size=4):
        self.window_size = window_size
        self.conversations = deque(maxlen=window_size)
    
    def add_turn(self, user_input, llm_response):
        # 添加新轮次，触发倒数第2轮的GRAG分析
        
    def get_processing_target(self):
        # 返回需要处理的轮次（倒数第2个）
        
    def handle_modification(self, turn_id, new_content):
        # 处理历史对话修改
```

#### 5.2 增强Agent系统
```python
class EnhancedGRAGAgent:
    def analyze_with_world_context(self, conversation, world_info):
        # 分析对话 + 基于世界观推断新实体属性
        
    def create_complete_nodes(self, entities):
        # 确保创建完整的节点和关系
        
    def resolve_conflicts(self, old_data, new_data):
        # 解决属性冲突，最新优先
```

#### 5.3 状态同步机制
```python
class ConflictResolver:
    def sync_conversation_state(self, tavern_history):
        # 同步酒馆对话状态到滑动窗口
        
    def validate_processing_eligibility(self, turn):
        # 验证轮次是否在有效窗口内
        
    def mark_outdated_turns(self, modified_turn_id):
        # 标记受影响的轮次需要重新处理
```

## 实现优先级

1. **Phase 1**：滑动窗口对话管理
2. **Phase 2**：延迟更新机制
3. **Phase 3**：增强节点创建
4. **Phase 4**：冲突解决和状态同步

## 配置参数

```yaml
sliding_window:
  size: 4  # 窗口大小
  processing_delay: 1  # 延迟轮次数
  max_retries: 3  # 冲突解决重试次数
  
node_creation:
  auto_infer_attributes: true
  use_world_context: true
  min_attributes: 3  # 新节点最少属性数
  
conflict_resolution:
  strategy: "latest_wins"  # 最新优先
  preserve_user_edits: true  # 保留用户手动编辑
```

## 预期效果

1. **稳定性**：只有窗口内的修改影响GRAG，系统更稳定
2. **准确性**：延迟更新确保分析相对稳定的对话
3. **完整性**：新角色自动获得合理的基础属性
4. **可控性**：用户可以通过UI直接修改GRAG，覆盖自动分析

这个方案如何？我们从哪个部分开始实现？