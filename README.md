# EchoGraph

![EchoGraph](assets/icons/OIG1.png)

## 简介

EchoGraph是一个基于知识图谱的智能角色扮演助手，集成了先进的对话系统和关系图谱管理功能，支持与SillyTavern无缝集成。

### 核心特性

- **🧠 智能对话系统**: 基于大语言模型的高质量对话生成
- **🕸️ 知识图谱管理**: 动态构建和管理角色关系与记忆
- **🔗 SillyTavern集成**: 完美集成酒馆角色卡和对话系统
- **📊 可视化界面**: 直观的图形化界面和实时状态监控
- **🔧 模块化架构**: 高度可扩展和可维护的代码结构
- **🛡️ 安全可靠**: 完善的安全机制和错误处理

## 项目架构

### 新模块化架构 (v1.1.0)

```
EchoGraph/
├── src/                          # 核心源代码
│   ├── api/                      # API服务层
│   │   ├── main.py              # API主入口
│   │   ├── routes/              # 路由处理
│   │   ├── services/            # 业务逻辑服务
│   │   ├── middleware/          # 中间件
│   │   ├── models/              # 数据模型
│   │   └── websocket/           # WebSocket处理
│   ├── core/                     # 核心组件
│   │   ├── game_engine.py       # 游戏引擎
│   │   ├── llm_client.py        # LLM客户端
│   │   └── delayed_update.py    # 延迟更新
│   ├── ui/                       # 用户界面
│   │   ├── components/          # UI组件
│   │   ├── windows/             # 窗口模块
│   │   └── managers/            # UI管理器
│   ├── utils/                    # 工具模块
│   │   ├── security.py          # 安全工具
│   │   ├── exceptions.py        # 异常处理
│   │   └── enhanced_config.py   # 配置管理
│   ├── memory/                   # 记忆系统
│   ├── graph/                    # 知识图谱
│   └── storage/                  # 存储管理
├── config/                       # 配置文件
├── logs/                         # 日志文件
├── api_server.py                # API启动器
├── run_ui.py                    # UI启动器
├── version.toml                 # 版本管理配置
├── release.py                   # 版本发布工具
└── REFACTORING_PLAN.md         # 重构计划
```

## 安装和使用

### 环境要求

- Python 3.8+
- PySide6
- FastAPI
- 其他依赖见 `requirements.txt`

### 快速开始

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 配置环境

复制 `.env.example` 到 `.env` 并配置你的API密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件：
```env
API_KEY=your_api_key_here
API_BASE_URL=https://api.openai.com/v1
MODEL_NAME=deepseek-v3.1
```

#### 3. 启动方式

**启动API服务器：**
```bash
python api_server.py
```

**启动UI界面：**
```bash
python run_ui.py
```

### SillyTavern集成

1. 在SillyTavern中安装EchoGraph插件
2. 配置连接地址为 `http://localhost:8000`
3. 启用增强记忆模式

## 配置说明

### 环境配置文件

- `config/development.yaml`: 开发环境配置
- `config/production.yaml`: 生产环境配置

### 主要配置项

```yaml
system:
  environment: "development"  # 环境类型
  debug: true                # 调试模式

llm:
  provider: "openai"         # API提供商
  model: "deepseek-v3.1"     # 模型名称
  max_tokens: 16000          # 最大Token数
  temperature: 0.8           # 生成温度

memory:
  max_hot_memory: 10         # 最大热记忆数
  max_context_length: 4000   # 最大上下文长度

security:
  enable_rate_limiting: true # 启用限流
  max_requests_per_minute: 60 # 每分钟最大请求数
```

## 功能说明

### 记忆系统

- **热记忆**: 最近的重要对话内容
- **温记忆**: 中等重要性的历史对话
- **冷记忆**: 长期存储的背景信息

### 知识图谱

- **动态构建**: 自动识别和构建角色关系
- **实时更新**: 根据对话内容更新图谱结构
- **可视化展示**: 直观展示关系网络

### 安全特性

- **API密钥安全**: 安全存储和传输API密钥
- **输入验证**: 全面的输入数据验证
- **错误处理**: 完善的异常处理机制
- **访问控制**: 细粒度的权限控制

## 开发指南

### 代码结构

项目采用模块化架构，每个模块职责清晰：

- **API层**: 处理HTTP请求和WebSocket连接
- **服务层**: 实现业务逻辑
- **数据层**: 管理数据存储和访问
- **UI层**: 提供用户交互界面

### 扩展开发

1. **添加新的API端点**: 在 `src/api/routes/` 下创建新的路由文件
2. **扩展UI组件**: 在 `src/ui/components/` 下创建新的组件
3. **添加新服务**: 在 `src/api/services/` 下实现业务逻辑

### 测试

```bash
# 运行单元测试
python -m pytest tests/

# 运行集成测试
python -m pytest tests/integration/
```

## 版本历史

### v1.1.0 (2024-09-22)
- **重大重构**: 完全模块化的架构
- **安全增强**: 新的安全机制和API密钥处理
- **UI优化**: 全新的组件化UI界面
- **性能提升**: 优化的异步处理和资源管理

### v1.x
- 修改项目名字从ChronoForge -> EchoGraph
- 更新UI，修正模式切换BUG
- 优化日志等级和配置项
- 优化知识图谱节点之间的力度

## 问题反馈

如果遇到问题或有建议，请在GitHub Issues中提交。

## 许可证

本项目采用MIT许可证。详见 [LICENSE](LICENSE) 文件。

## 贡献指南

欢迎贡献代码！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解贡献流程。

