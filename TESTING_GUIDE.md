# ChronoForge SillyTavern 插件测试指南

## 🚀 快速开始

### 1. 部署插件
```bash
# 运行自动部署脚本
python deploy_to_sillytavern.py
```

### 2. 启动后端服务
```bash
# 启动ChronoForge UI（推荐，包含管理界面）
python run_ui.py

# 或者直接启动API服务器
python api_server.py --port 8000
```

### 3. 配置SillyTavern
1. 启动SillyTavern
2. 进入设置 → 插件管理
3. 启用 "ChronoForge RAG Enhancer" 插件
4. 检查插件设置（API地址默认: `http://127.0.0.1:8000`）

## 🧪 测试流程

### 第一次测试（初始化）
1. 在SillyTavern中创建或选择一个角色
2. 开始新对话
3. 观察控制台日志，应该看到初始化信息：
   ```
   [ChronoForge] Initializing session for character: [角色名]
   [ChronoForge] Knowledge graph created with X nodes, Y edges
   ```

### 对话测试（上下文增强）
1. 发送包含实体信息的消息，例如：
   - "我装备了+5烈焰长剑攻击哥布林王"
   - "去酒馆找老板娘打听消息"
   - "我的法力值只剩30点了"

2. 观察以下内容：
   - **控制台日志**：实体识别和关系提取
   - **UI管理界面**：在关系图页面看到新增的节点和边
   - **AI回复质量**：应该更符合上下文

### 记忆更新测试
1. AI回复后，观察日志中的记忆更新：
   ```
   [ChronoForge] Memory updated: X nodes, Y edges added
   ```

2. 在ChronoForge UI的"管理"页面：
   - 查看会话列表
   - 测试RPG文本解析功能
   - 检查系统状态

## 🔍 调试功能

### 插件调试面板
- 在SillyTavern中按 `Ctrl+Shift+D` 打开ChronoForge调试面板
- 查看实时处理状态和错误信息

### ChronoForge管理界面
- **会话管理**：查看当前活跃会话
- **角色管理**：管理SillyTavern角色数据
- **测试工具**：实时测试RPG文本解析

### 日志监控
- **ChronoForge UI**：查看完整的后端日志
- **浏览器控制台**：查看插件前端日志
- **SillyTavern控制台**：查看整体系统日志

## ⚠️ 常见问题

### 连接失败
- 确保ChronoForge API服务器已启动（默认端口8000）
- 检查防火墙设置
- 验证插件配置中的API地址

### 初始化失败
- 检查角色卡格式是否正确
- 确保有足够的磁盘空间创建数据文件
- 查看错误日志获取具体原因

### 记忆更新异常
- 检查知识图谱文件权限
- 验证RPG文本处理器是否正常工作
- 确保存储目录结构正确

## 🎯 预期效果

成功集成后，你应该看到：

1. **智能上下文增强**：AI能记住和引用之前的装备、属性、位置等信息
2. **动态知识图谱**：实时更新的人物关系、物品属性、地点信息
3. **RPG元素识别**：自动识别装备、技能、数值属性等游戏要素
4. **会话持久化**：每个角色的记忆独立保存和管理

## 🛠️ 高级配置

### API端口修改
在`.env`文件中设置：
```
API_SERVER_PORT=8001
```

### 插件设置调整
在SillyTavern插件设置中可以配置：
- API基础URL
- 调试模式开关
- 最大上下文长度
- 自动初始化开关