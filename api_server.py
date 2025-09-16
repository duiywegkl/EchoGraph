import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Set
from loguru import logger
import os
import uuid
import time
import asyncio
from threading import Lock
import argparse
import asyncio
from datetime import datetime
from pathlib import Path

# 导入配置
from src.utils.config import config
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# --- Configure file logging for API server ---
os.makedirs("logs", exist_ok=True)
logger.add(
    "logs/api_server_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level=os.getenv("LOG_LEVEL", config.logging.level).upper(),
    rotation="5 MB",
    retention="7 days"
)
# Extra detailed LLM log sink (captures [LLM]/[GRAG] messages at DEBUG)
logger.add(
    "logs/llm_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
    filter=lambda record: any(tag in record["message"] for tag in ("[LLM]", "[GRAG]", "[LLM KG Gen]")),
    rotation="10 MB",
    retention="7 days"
)



# --- WebSocket 连接管理器 ---
class ConnectionManager:
    def __init__(self):
        # Map session_id -> WebSocket (current active socket for that session)
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        # If there is an existing socket for the same session, close it before replacing
        old_ws = self.active_connections.get(session_id)
        if old_ws is not None and old_ws is not websocket:
            try:
                await old_ws.close(code=1012, reason="Replaced by new connection")
            except Exception:
                pass
        self.active_connections[session_id] = websocket
        logger.info(f"🔌 [WS] Plugin connected for session {session_id}. Total connections: {len(self.active_connections)}")

    def disconnect(self, session_id: str, websocket: Optional[WebSocket] = None):
        """Remove session mapping only if it is the same websocket (when provided).
        This avoids deleting a newer connection when an older socket closes later."""
        if session_id in self.active_connections:
            if websocket is None or self.active_connections.get(session_id) is websocket:
                del self.active_connections[session_id]
                logger.info(f"🔌 [WS] Plugin disconnected for session {session_id}. Total connections: {len(self.active_connections)}")

    async def send_message(self, session_id: str, message: Dict[str, Any]):
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            try:
                await websocket.send_json(message)
                logger.info(f"📤 [WS] Sent message to session {session_id}: {message.get('type')}")
            except Exception as e:
                logger.error(f"❌ [WS] Failed to send message to session {session_id}: {e}")
                self.disconnect(session_id, websocket)

manager = ConnectionManager()

# --- 项目核心逻辑导入 ---
from src.memory import GRAGMemory
from src.core.perception import PerceptionModule
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.game_engine import GameEngine
from src.core.validation import ValidationLayer
from src.core.grag_update_agent import GRAGUpdateAgent
from src.core.llm_client import LLMClient
from src.core.delayed_update import DelayedUpdateManager
from src.core.conflict_resolver import ConflictResolver
from src.storage import TavernStorageManager

# --- 滑动窗口系统全局状态 ---
sliding_window_managers: Dict[str, DelayedUpdateManager] = {}
conflict_resolvers: Dict[str, ConflictResolver] = {}

# --- 异步初始化状态管理 ---
initialization_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task_info

# --- 插件角色数据存储 ---
plugin_character_data: Dict[str, Dict[str, Any]] = {}  # character_id -> character_data

# --- 协调式重新初始化跟踪 ---
pending_coordinated_reinits: Set[str] = set()  # session_ids waiting for character data

class InitTaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

# --- Tavern mode global gate ---
# When False, all tavern/plugin interactions (HTTP + WS) are rejected to ensure local-test isolation
TAVERN_MODE_ACTIVE: bool = False


# --- FastAPI 应用初始化 ---
app = FastAPI(
    title="EchoGraph API",
    description="A backend service for SillyTavern to provide dynamic knowledge graph and RAG capabilities.",
    version="1.0.0"
)

# 添加 CORS 中间件支持跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境中应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
)

# --- 全局组件初始化 ---
# 使用新的酒馆存储管理器
storage_manager = TavernStorageManager()
sessions: Dict[str, GameEngine] = {}
# 会话创建锁，防止并发创建相同会话
session_creation_locks: Dict[str, Lock] = {}

def get_or_create_sliding_window_manager(session_id: str, session_config: Dict[str, Any] = None) -> DelayedUpdateManager:
    """获取或创建滑动窗口管理器"""
    if session_id not in sliding_window_managers:
        # 从会话配置获取滑动窗口设置，如果没有则从环境变量获取
        sliding_config = (session_config or {}).get('sliding_window', {})
        window_size = sliding_config.get('window_size', int(os.getenv('SLIDING_WINDOW_SIZE', '4')))
        processing_delay = sliding_config.get('processing_delay', int(os.getenv('PROCESSING_DELAY', '1')))
        enable_enhanced_agent = sliding_config.get('enable_enhanced_agent', os.getenv('ENABLE_ENHANCED_AGENT', 'true').lower() in ('true', '1', 't'))

        # 获取对应的游戏引擎
        engine = sessions.get(session_id)
        if not engine:
            raise ValueError(f"No game engine found for session {session_id}")

        # 首先创建SlidingWindowManager实例
        from src.core.sliding_window import SlidingWindowManager
        sliding_window = SlidingWindowManager(
            window_size=window_size,
            processing_delay=processing_delay
        )

        # 然后创建DelayedUpdateManager，传入SlidingWindowManager实例
        sliding_window_manager = DelayedUpdateManager(
            sliding_window=sliding_window,
            memory=engine.memory,
            grag_agent=engine.grag_agent if enable_enhanced_agent else None
        )

        sliding_window_managers[session_id] = sliding_window_manager
        logger.info(f"Created sliding window manager for session {session_id}: window_size={window_size}, delay={processing_delay}")

    return sliding_window_managers[session_id]

def get_or_create_conflict_resolver(session_id: str) -> ConflictResolver:
    """获取或创建冲突解决器"""
    if session_id not in conflict_resolvers:
        # 获取滑动窗口管理器
        sliding_manager = sliding_window_managers.get(session_id)
        if not sliding_manager:
            raise ValueError(f"No sliding window manager found for session {session_id}")

        # ConflictResolver需要的是SlidingWindowManager和DelayedUpdateManager实例
        # sliding_manager本身就是DelayedUpdateManager实例，它包含了滑动窗口
        conflict_resolver = ConflictResolver(sliding_manager.sliding_window, sliding_manager)
        conflict_resolvers[session_id] = conflict_resolver
        logger.info(f"Created conflict resolver for session {session_id}")

    return conflict_resolvers[session_id]

def get_or_create_session_engine(session_id: str, is_test: bool = False, enable_agent: bool = True) -> GameEngine:
    """根据会话ID获取或创建一个新的GameEngine实例，支持测试模式和Agent开关"""
    # 如果会话已存在，直接返回
    if session_id in sessions:
        return sessions[session_id]

    # 获取或创建会话特定的锁
    if session_id not in session_creation_locks:
        session_creation_locks[session_id] = Lock()

    # 使用锁确保只有一个线程创建会话
    with session_creation_locks[session_id]:
        # 双重检查，因为在等待锁期间可能已经被另一个线程创建
        if session_id in sessions:
            return sessions[session_id]

        logger.info(f"🔧 [ThreadPool] Creating new session engine for session_id={session_id}")

        # 从存储管理器获取对应的文件路径
        logger.debug("📁 [ThreadPool] Getting graph file path...")
        graph_path = storage_manager.get_graph_file_path(session_id, is_test)
        logger.debug(f"📁 [ThreadPool] Graph path: {graph_path}")

        # 初始化核心组件
        logger.debug("🧠 [ThreadPool] Initializing core components...")
        # 生成entities.json路径
        entities_json_path = str(Path(graph_path).parent / "entities.json")
        memory = GRAGMemory(
            graph_save_path=graph_path,
            entities_json_path=entities_json_path,
            auto_load_entities=True  # 酒馆模式需要加载现有数据
        )
        logger.debug("✅ [ThreadPool] GRAGMemory initialized.")

        perception = PerceptionModule()
        logger.debug("✅ [ThreadPool] PerceptionModule initialized.")

        rpg_processor = RPGTextProcessor()
        logger.debug("✅ [ThreadPool] RPGTextProcessor initialized.")

        validation_layer = ValidationLayer()
        logger.debug("✅ [ThreadPool] ValidationLayer initialized.")

        # 可选初始化GRAG Agent
        grag_agent = None
        if enable_agent:
            logger.info("🤖 [ThreadPool] Initializing GRAG Agent...")
            try:
                from src.utils.config import config

                # 检查LLM配置是否完整
                if not config.llm.api_key:
                    logger.warning("⚠️ [ThreadPool] LLM API Key not configured, disabling GRAG Agent.")
                elif not config.llm.base_url:
                    logger.warning("⚠️ [ThreadPool] LLM Base URL not configured, disabling GRAG Agent.")
                else:
                    logger.debug("🌐 [ThreadPool] Initializing LLMClient...")
                    start_time = time.time()
                    llm_client = LLMClient()
                    llm_init_time = time.time() - start_time
                    logger.info(f"✅ [ThreadPool] LLMClient initialized in {llm_init_time:.2f}s")

                    logger.debug("🤖 [ThreadPool] Creating GRAGUpdateAgent instance...")
                    start_time = time.time()
                    grag_agent = GRAGUpdateAgent(llm_client)
                    agent_init_time = time.time() - start_time
                    logger.info(f"✅ [ThreadPool] GRAGUpdateAgent created in {agent_init_time:.2f}s")
            except Exception as e:
                logger.warning(f"⚠️ [ThreadPool] GRAG Agent initialization failed, will use local processor: {e}")
                import traceback
                logger.debug(f"Detailed error: {traceback.format_exc()}")
        else:
            logger.info("🚫 [ThreadPool] Agent function is disabled, using local processor.")

        logger.info("🎮 [ThreadPool] Creating GameEngine instance...")
        start_time = time.time()
        engine = GameEngine(memory, perception, rpg_processor, validation_layer, grag_agent)
        engine_init_time = time.time() - start_time
        sessions[session_id] = engine
        logger.info(f"✅ [ThreadPool] GameEngine instance created in {engine_init_time:.2f}s. Session creation complete.")

        return engine

# --- Pydantic 数据模型定义 ---
class InitializeRequest(BaseModel):
    session_id: Optional[str] = None
    character_card: Dict[str, Any]
    world_info: str
    session_config: Optional[Dict[str, Any]] = {}
    is_test: bool = False  # 新增测试模式标志
    enable_agent: bool = True  # 新增Agent开关

class InitializeResponse(BaseModel):
    session_id: str
    message: str
    graph_stats: Dict[str, Any] = {}  # 改为 Any 类型，支持字符串和数字

class EnhancePromptRequest(BaseModel):
    session_id: str
    user_input: str
    recent_history: Optional[List[Dict[str, str]]] = None
    max_context_length: Optional[int] = 4000

class EnhancePromptResponse(BaseModel):
    enhanced_context: str
    entities_found: List[str] = []
    context_stats: Dict[str, Any] = {}

class UpdateMemoryRequest(BaseModel):
    session_id: str
    llm_response: str
    user_input: str
    timestamp: Optional[str] = None
    chat_id: Optional[int] = None

class UpdateMemoryResponse(BaseModel):
    message: str
    nodes_updated: int
    edges_added: int
    processing_stats: Dict[str, Any] = {}

# New endpoint models
class SessionStatsResponse(BaseModel):
    session_id: str
    graph_nodes: int
    graph_edges: int
    hot_memory_size: int
    last_update: Optional[str] = None

class ResetSessionRequest(BaseModel):
    session_id: str
    keep_character_data: bool = True

# 滑动窗口系统相关数据模型
class ProcessConversationRequest(BaseModel):
    session_id: str
    user_input: str
    llm_response: str
    timestamp: Optional[str] = None
    chat_id: Optional[int] = None
    tavern_message_id: Optional[str] = None

class ProcessConversationResponse(BaseModel):
    message: str
    turn_sequence: int
    turn_processed: bool
    target_processed: bool
    window_size: int
    nodes_updated: int = 0
    edges_added: int = 0
    conflicts_resolved: int = 0
    processing_stats: Dict[str, Any] = {}

class SyncConversationRequest(BaseModel):
    session_id: str
    tavern_history: List[Dict[str, Any]]

class SyncConversationResponse(BaseModel):
    message: str
    conflicts_detected: int
    conflicts_resolved: int
    window_synced: bool

# --- 异步初始化相关数据模型 ---
class AsyncInitializeRequest(BaseModel):
    session_id: Optional[str] = None
    character_card: Dict[str, Any]
    world_info: str
    session_config: Optional[Dict[str, Any]] = {}
    is_test: bool = False
    enable_agent: bool = False  # 异步模式默认禁用Agent避免超时

# --- 角色数据提交相关数据模型 ---
class SubmitCharacterDataRequest(BaseModel):
    character_id: str
    character_name: str
    character_data: Dict[str, Any]
    timestamp: Optional[float] = None

class SubmitCharacterDataResponse(BaseModel):
    success: bool
    message: str
    character_id: str

class AsyncInitializeResponse(BaseModel):
    task_id: str
    message: str
    estimated_time: str

class InitTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float  # 0.0 - 1.0
    message: str
    session_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str

# --- API 端点实现 ---

@app.post("/initialize", response_model=InitializeResponse)
async def initialize_session(req: InitializeRequest):
    """
    初始化一个新的对话会话，解析角色卡和世界书来创建知识图谱。
    支持酒馆角色卡分类存储和测试模式。
    """
    try:
        logger.info(f"🚀 开始初始化会话，请求数据: session_id={req.session_id}, is_test={req.is_test}, enable_agent={req.enable_agent}")
        session_id = req.session_id or str(uuid.uuid4())
        logger.info(f"📝 使用会话ID: {session_id}")

        # 检查会话是否已经存在并已初始化
        if session_id in sessions:
            logger.info(f"♻️ 会话 {session_id} 已存在，跳过重复初始化")
            # 返回现有会话的统计信息
            engine = sessions[session_id]
            nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
            edges_count = len(engine.memory.knowledge_graph.graph.edges())

            return InitializeResponse(
                success=True,
                session_id=session_id,
                nodes_added=nodes_count,
                edges_added=edges_count,
                message=f"使用现有会话，当前包含 {nodes_count} 个节点和 {edges_count} 条边",
                processing_time=0.0
            )

        # 详细记录角色卡数据
        logger.info("📊 角色卡详细数据分析:")
        if req.character_card:
            logger.info(f"  角色卡键数量: {len(req.character_card.keys())}")
            logger.info(f"  角色卡键列表: {list(req.character_card.keys())}")

            # 记录关键字段
            name = req.character_card.get('name', 'Unknown')
            description = req.character_card.get('description', '')
            personality = req.character_card.get('personality', '')
            scenario = req.character_card.get('scenario', '')
            first_mes = req.character_card.get('first_mes', '')
            mes_example = req.character_card.get('mes_example', '')

            logger.info(f"  角色名称: {name}")
            logger.info(f"  角色描述长度: {len(description)} 字符")
            logger.info(f"  性格描述长度: {len(personality)} 字符")
            logger.info(f"  场景描述长度: {len(scenario)} 字符")
            logger.info(f"  首次消息长度: {len(first_mes)} 字符")
            logger.info(f"  消息示例长度: {len(mes_example)} 字符")

            if description:
                logger.info(f"  角色描述前200字符: {description[:200]}...")
            if personality:
                logger.info(f"  性格描述前200字符: {personality[:200]}...")
            if scenario:
                logger.info(f"  场景描述前200字符: {scenario[:200]}...")
        else:
            logger.warning("  ⚠️ 角色卡数据为空！")

        # 详细记录世界书数据
        logger.info("📚 世界书详细数据分析:")
        if req.world_info:
            logger.info(f"  世界书总长度: {len(req.world_info)} 字符")
            logger.info(f"  世界书前500字符: {req.world_info[:500]}...")

            # 尝试检测世界书格式
            if req.world_info.startswith('[') and req.world_info.endswith(']'):
                logger.info("  检测到JSON格式世界书")
                try:
                    import json
                    world_data = json.loads(req.world_info)
                    if isinstance(world_data, list):
                        logger.info(f"  世界书条目数量: {len(world_data)}")
                        for i, entry in enumerate(world_data[:5]):  # 只显示前5个条目
                            if isinstance(entry, dict):
                                keys = entry.get('keys', [])
                                content = entry.get('content', '')
                                logger.info(f"    条目{i+1}: 关键词={keys}, 内容长度={len(content)}")
                                logger.info(f"    条目{i+1}内容预览: {content[:100]}...")
                except Exception as e:
                    logger.warning(f"  解析JSON世界书失败: {e}")
            else:
                logger.info("  检测到文本格式世界书")
                lines = req.world_info.split('\n')
                logger.info(f"  世界书行数: {len(lines)}")
                non_empty_lines = [line for line in lines if line.strip()]
                logger.info(f"  非空行数: {len(non_empty_lines)}")
        else:
            logger.info("  世界书数据为空")

        # 如果不是测试模式，注册酒馆角色卡
        if not req.is_test:
            logger.info("📊 开始注册酒馆角色卡...")
            local_dir_name = storage_manager.register_tavern_character(req.character_card, session_id)
            logger.info(f"✅ 已注册酒馆角色: {local_dir_name}")
        else:
            logger.info("🧪 在测试模式下初始化")

        # 创建游戏引擎
        logger.info("⚙️ 创建/获取会话引擎...")
        engine = await run_in_threadpool(get_or_create_session_engine, session_id, req.is_test, req.enable_agent)
        logger.info("✅ 会话引擎创建成功")

        # 检查知识图谱是否已有数据，如果有则直接跳过整个初始化
        existing_nodes = len(engine.memory.knowledge_graph.graph.nodes())
        if existing_nodes > 0:
            logger.info(f"♻️ 知识图谱已有 {existing_nodes} 个节点，跳过整个初始化过程")
            existing_edges = len(engine.memory.knowledge_graph.graph.edges())

            return InitializeResponse(
                success=True,
                session_id=session_id,
                nodes_added=existing_nodes,
                edges_added=existing_edges,
                message=f"使用现有知识图谱，包含 {existing_nodes} 个节点和 {existing_edges} 条边",
                processing_time=0.0
            )

        # 调用GameEngine方法来处理数据 - 使用LLM智能解析
        logger.info("🧠 开始使用LLM智能初始化知识图谱...")
        logger.info(f"🎯 调用 engine.initialize_from_tavern_data() 方法")
        logger.info(f"  - 角色卡数据: {bool(req.character_card)} (有数据)")
        logger.info(f"  - 世界书数据: {bool(req.world_info)} (有数据)")

        start_time = time.time()
        try:
            init_result = await run_in_threadpool(engine.initialize_from_tavern_data, req.character_card, req.world_info)
        except Exception as init_error:
            logger.error(f"❌ 初始化过程发生错误: {init_error}")
            import traceback
            logger.error(f"详细错误堆栈: {traceback.format_exc()}")
            # 返回基本的失败结果，但不阻塞整个API
            init_result = {
                "nodes_added": 0,
                "edges_added": 0,
                "method": "failed",
                "error": str(init_error)
            }

        graph_init_time = time.time() - start_time
        logger.info(f"✅ 知识图谱初始化完成: {init_result} (耗时: {graph_init_time:.2f}秒)")

        # 分析初始化结果
        if isinstance(init_result, dict):
            for key, value in init_result.items():
                logger.info(f"  初始化结果 {key}: {value}")
        else:
            logger.info(f"  初始化结果类型: {type(init_result)}")
            logger.info(f"  初始化结果内容: {init_result}")

        # 如果启用了滑动窗口系统，创建相应的管理器
        if req.session_config and req.session_config.get('sliding_window'):
            logger.info("🔄 初始化滑动窗口系统...")
            try:
                get_or_create_sliding_window_manager(session_id, req.session_config)
                get_or_create_conflict_resolver(session_id)
                logger.info(f"✅ 滑动窗口系统初始化成功: {session_id}")
            except Exception as e:
                logger.warning(f"⚠️ 滑动窗口系统初始化失败: {e}")

        logger.info(f"🎉 会话 {session_id} 初始化完全成功")
        return InitializeResponse(
            session_id=session_id,
            message="Session initialized successfully and knowledge graph created.",
            graph_stats=init_result
        )
    except Exception as e:
        logger.error(f"❌ 会话初始化失败: {e}")
        import traceback
        logger.error(f"详细错误堆栈: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize session: {e}")

# --- 异步初始化端点 ---
async def perform_async_initialization(task_id: str, req: AsyncInitializeRequest):
    """在后台执行异步初始化"""
    logger.info(f"🔄 [Async Task {task_id}] Starting background initialization for session: {req.session_id or 'new'}")
    try:
        # 更新任务状态
        initialization_tasks[task_id]["status"] = InitTaskStatus.RUNNING
        initialization_tasks[task_id]["progress"] = 0.1
        initialization_tasks[task_id]["message"] = "开始初始化会话..."
        initialization_tasks[task_id]["updated_at"] = datetime.now().isoformat()

        session_id = req.session_id or str(uuid.uuid4())
        logger.info(f"🔄 [Async Task {task_id}] Using Session ID: {session_id}")

        # 如果不是测试模式，注册酒馆角色卡
        if not req.is_test:
            logger.info(f"📊 [Async Task {task_id}] Registering Tavern character...")
            storage_manager.register_tavern_character(req.character_card, session_id)
            logger.info(f"✅ [Async Task {task_id}] Character registered.")

        # 步骤1: 创建引擎 (20%)
        initialization_tasks[task_id]["progress"] = 0.2
        initialization_tasks[task_id]["message"] = "创建会话引擎..."
        logger.info(f"🔄 [Async Task {task_id}] Step 1: Creating session engine in thread pool...")

        engine = await run_in_threadpool(get_or_create_session_engine, session_id, req.is_test, req.enable_agent)
        logger.info(f"✅ [Async Task {task_id}] Step 1: Session engine created.")

        # 步骤2: 初始化知识图谱 (60%)
        initialization_tasks[task_id]["progress"] = 0.6
        initialization_tasks[task_id]["message"] = "正在分析角色卡和世界书..."
        logger.info(f"🔄 [Async Task {task_id}] Step 2: Initializing knowledge graph in thread pool...")

        init_result = await run_in_threadpool(engine.initialize_from_tavern_data, req.character_card, req.world_info)
        logger.info(f"✅ [Async Task {task_id}] Step 2: Knowledge graph initialized.")

        # 步骤3: 配置滑动窗口 (80%)
        initialization_tasks[task_id]["progress"] = 0.8
        initialization_tasks[task_id]["message"] = "配置滑动窗口系统..."
        logger.info(f"🔄 [Async Task {task_id}] Step 3: Configuring sliding window...")

        if req.session_config and req.session_config.get('sliding_window'):
            try:
                get_or_create_sliding_window_manager(session_id, req.session_config)
                get_or_create_conflict_resolver(session_id)
                logger.info(f"✅ [Async Task {task_id}] Step 3: Sliding window configured.")
            except Exception as e:
                logger.warning(f"⚠️ [Async Task {task_id}] Sliding window system initialization failed: {e}")

        # 完成 (100%)
        initialization_tasks[task_id]["status"] = InitTaskStatus.COMPLETED
        initialization_tasks[task_id]["progress"] = 1.0
        initialization_tasks[task_id]["message"] = "初始化完成"
        initialization_tasks[task_id]["session_id"] = session_id
        initialization_tasks[task_id]["result"] = {
            "session_id": session_id,
            "graph_stats": init_result
        }
        initialization_tasks[task_id]["updated_at"] = datetime.now().isoformat()

        logger.info(f"🎉 [Async Task {task_id}] Async initialization finished successfully.")

        # 通过WebSocket推送完成通知
        await manager.send_message(session_id, {
            "type": "initialization_complete",
            "session_id": session_id,
            "stats": init_result
        })

    except Exception as e:
        logger.error(f"❌ [Async Task {task_id}] Async initialization failed: {e}")
        import traceback
        logger.error(f"❌ [Async Task {task_id}] Full traceback: {traceback.format_exc()}")
        initialization_tasks[task_id]["status"] = InitTaskStatus.FAILED
        initialization_tasks[task_id]["error"] = str(e)
        initialization_tasks[task_id]["updated_at"] = datetime.now().isoformat()

@app.post("/initialize_async", response_model=AsyncInitializeResponse)
async def initialize_session_async(req: AsyncInitializeRequest, background_tasks: BackgroundTasks):
    """
    异步初始化会话，避免长时间阻塞请求
    返回任务ID，客户端可以通过轮询来获取进度
    """
    try:
        task_id = str(uuid.uuid4())

        # 创建任务记录
        initialization_tasks[task_id] = {
            "task_id": task_id,
            "status": InitTaskStatus.PENDING,
            "progress": 0.0,
            "message": "任务已创建，等待执行...",
            "session_id": None,
            "result": None,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # 添加后台任务
        background_tasks.add_task(perform_async_initialization, task_id, req)

        logger.info(f"🚀 创建异步初始化任务: {task_id}")

        return AsyncInitializeResponse(
            task_id=task_id,
            message="异步初始化任务已创建",
            estimated_time="30-60秒（取决于角色复杂度）"
        )

    except Exception as e:
        logger.error(f"❌ 创建异步初始化任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create async initialization task: {e}")

@app.get("/initialize_status/{task_id}", response_model=InitTaskStatusResponse)
async def get_initialization_status(task_id: str):
    """获取异步初始化任务的状态"""
    try:
        if task_id not in initialization_tasks:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        task_info = initialization_tasks[task_id]

        return InitTaskStatusResponse(
            task_id=task_id,
            status=task_info["status"],
            progress=task_info["progress"],
            message=task_info["message"],
            session_id=task_info.get("session_id"),
            result=task_info.get("result"),
            error=task_info.get("error"),
            created_at=task_info["created_at"],
            updated_at=task_info["updated_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {e}")

@app.post("/enhance_prompt", response_model=EnhancePromptResponse)
async def enhance_prompt(req: EnhancePromptRequest):
    """
    根据用户输入，从知识图谱中检索上下文以增强Prompt。
    支持最大上下文长度限制和详细的实体分析。
    """
    try:
        if req.session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {req.session_id} not found. Please initialize first.")

        engine = sessions[req.session_id]

        # 1. 感知用户输入中的实体
        perception_result = engine.perception.analyze(req.user_input, engine.memory.knowledge_graph)
        entities = perception_result.get("entities", [])
        intent = perception_result.get("intent", "unknown")

        # 2. 从知识图谱中检索相关上下文
        recent_turns = min(req.max_context_length // 200, 5) if req.max_context_length else 3
        context = engine.memory.retrieve_context_for_prompt(entities, recent_turns=recent_turns)

        # 3. 如果上下文过长，进行智能截断
        if len(context) > req.max_context_length:
            context = context[:req.max_context_length - 100] + "\n[...context truncated...]"

        logger.info(f"Enhanced prompt for session {req.session_id[:8]}... | Entities: {entities} | Intent: {intent}")

        return EnhancePromptResponse(
            enhanced_context=context,
            entities_found=entities,
            context_stats={
                "entities_count": len(entities),
                "context_length": len(context),
                "intent": intent,
                "graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "graph_edges": len(engine.memory.knowledge_graph.graph.edges())
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during prompt enhancement: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enhance prompt: {e}")

@app.post("/update_memory", response_model=UpdateMemoryResponse)
async def update_memory(req: UpdateMemoryRequest):
    """
    分析LLM的回复，提取新信息更新知识图谱，并记录对话历史。
    支持时间戳和聊天ID跟踪。
    """
    try:
        if req.session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {req.session_id} not found.")

        engine = sessions[req.session_id]

        # 1. 调用新的GameEngine方法从LLM回复中提取并应用状态更新
        update_results = engine.extract_updates_from_response(req.llm_response, req.user_input)

        # 2. 将当前的用户输入和LLM回复存入对话历史
        engine.memory.add_conversation(req.user_input, req.llm_response)

        # 3. 保存所有记忆更新
        engine.memory.save_all_memory()

        logger.info(f"Memory updated for session {req.session_id[:8]}... | Nodes: {update_results.get('nodes_updated', 0)}, Edges: {update_results.get('edges_added', 0)}")

        return UpdateMemoryResponse(
            message="Memory updated successfully.",
            nodes_updated=update_results.get("nodes_updated", 0),
            edges_added=update_results.get("edges_added", 0),
            processing_stats={
                "timestamp": req.timestamp,
                "chat_id": req.chat_id,
                "llm_response_length": len(req.llm_response),
                "user_input_length": len(req.user_input),
                "total_graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "total_graph_edges": len(engine.memory.knowledge_graph.graph.edges())
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during memory update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update memory: {e}")

# --- 滑动窗口系统端点 ---

@app.post("/process_conversation", response_model=ProcessConversationResponse)
async def process_conversation(req: ProcessConversationRequest):
    """
    使用滑动窗口系统处理新的对话轮次
    支持延迟处理和冲突解决
    """
    try:
        if req.session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {req.session_id} not found.")

        # Inbound turn preview
        try:
            logger.info(f"[SW] Inbound turn | session={req.session_id[:8]}... | user_input_len={len(req.user_input)} | llm_response_len={len(req.llm_response)}")
            if req.user_input:
                logger.info(f"[SW] user_input preview (first 200):\n---\n{req.user_input[:200]}\n---")
            if req.llm_response:
                logger.info(f"[SW] llm_response preview (first 200):\n---\n{req.llm_response[:200]}\n---")
        except Exception:
            pass

        # 获取或创建滑动窗口管理器（如果还未创建）
        try:
            sliding_manager = get_or_create_sliding_window_manager(req.session_id)
        except ValueError:
            # 如果没有初始化滑动窗口系统，回退到原始处理方式
            logger.warning(f"Sliding window system not initialized for session {req.session_id}, using fallback")
            engine = sessions[req.session_id]
            update_results = engine.extract_updates_from_response(req.llm_response, req.user_input)
            engine.memory.add_conversation(req.user_input, req.llm_response)
            engine.memory.save_all_memory()

            return ProcessConversationResponse(
                message="Processed using fallback method",
                turn_sequence=1,
                turn_processed=True,
                target_processed=True,
                window_size=1,
                nodes_updated=update_results.get("nodes_updated", 0),
                edges_added=update_results.get("edges_added", 0)
            )

        # 使用滑动窗口系统处理对话
        result = sliding_manager.process_new_conversation(req.user_input, req.llm_response)

        logger.info(f"Sliding window processed conversation for session {req.session_id[:8]}... | "
                   f"Turn: {result['new_turn_sequence']}, Target processed: {result['target_processed']}")

        # 推送图谱更新通知
        if result.get('target_processed'):
            engine = sessions[req.session_id]
            await manager.send_message(req.session_id, {
                "type": "graph_updated",
                "session_id": req.session_id,
                "nodes_updated": result.get('grag_updates', {}).get('nodes_updated', 0),
                "edges_added": result.get('grag_updates', {}).get('edges_added', 0),
                "total_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "total_edges": len(engine.memory.knowledge_graph.graph.edges())
            })

        return ProcessConversationResponse(
            message="Conversation processed successfully with sliding window",
            turn_sequence=result['new_turn_sequence'],
            turn_processed=True,  # 新轮次总是被处理的
            target_processed=result['target_processed'],
            window_size=result['window_info']['current_turns'],  # 使用正确的键名
            nodes_updated=result.get('grag_updates', {}).get('nodes_updated', 0),
            edges_added=result.get('grag_updates', {}).get('edges_added', 0),
            processing_stats={
                "timestamp": req.timestamp,
                "chat_id": req.chat_id,
                "tavern_message_id": req.tavern_message_id,
                "llm_response_length": len(req.llm_response),
                "user_input_length": len(req.user_input),
                "new_turn_id": result['new_turn_id'],
                "window_info": result['window_info']
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during sliding window conversation processing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process conversation: {e}")

@app.post("/sync_conversation", response_model=SyncConversationResponse)
async def sync_conversation(req: SyncConversationRequest):
    """
    同步SillyTavern对话历史，解决冲突
    """
    try:
        if req.session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {req.session_id} not found.")

        # 获取冲突解决器
        try:
            conflict_resolver = get_or_create_conflict_resolver(req.session_id)
        except ValueError as e:
            logger.warning(f"Conflict resolver not available: {e}")
            return SyncConversationResponse(
                message="Conflict resolution not available - sliding window system not initialized",
                conflicts_detected=0,
                conflicts_resolved=0,
                window_synced=False
            )

        # 同步对话状态（添加详细日志）
        try:
            hist_len = len(req.tavern_history)
            logger.info(f"[SYNC] Starting conversation sync | session={req.session_id[:8]}... | history_len={hist_len}")
            if hist_len > 0:
                first = req.tavern_history[0]
                last = req.tavern_history[-1]
                logger.info(f"[SYNC] First turn preview: user='{(first.get('user','') or '')[:80]}' | assistant='{(first.get('assistant','') or '')[:80]}'")
                if hist_len > 1:
                    logger.info(f"[SYNC] Last turn preview: user='{(last.get('user','') or '')[:80]}' | assistant='{(last.get('assistant','') or '')[:80]}'")
        except Exception:
            pass

        sync_result = conflict_resolver.sync_conversation_state(req.tavern_history)

        logger.info(
            "[SYNC] Conversation sync result | "
            f"session={req.session_id[:8]}... | "
            f"synced_turns={sync_result.get('synced_turns')} | "
            f"conflicts_detected={sync_result.get('conflicts_detected')} | "
            f"conflicts_resolved={sync_result.get('conflicts_resolved')} | "
            f"out_of_window={sync_result.get('out_of_window')} | "
            f"new_turns={sync_result.get('new_turns')} | "
            f"updated_turns={sync_result.get('updated_turns')} | "
            f"deleted_turns={sync_result.get('deleted_turns')}"
        )

        return SyncConversationResponse(
            message="Conversation state synchronized successfully",
            conflicts_detected=sync_result['conflicts_detected'],
            conflicts_resolved=sync_result['conflicts_resolved'],
            window_synced=sync_result.get('window_synced', True)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during conversation sync: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync conversation: {e}")

# --- 原有管理端点 ---

@app.post("/sessions/{session_id}/clear")
async def clear_session_graph(session_id: str):
    """清空指定会话的知识图谱"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        engine = sessions[session_id]
        engine.memory.clear_all()
        logger.info(f"会话 {session_id} 的知识图谱已清空")

        return {"success": True, "message": f"Session {session_id} knowledge graph cleared successfully"}
    except Exception as e:
        logger.error(f"清空会话 {session_id} 图谱失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear graph: {str(e)}")

@app.get("/sessions/{session_id}/stats", response_model=SessionStatsResponse)
async def get_session_stats(session_id: str):
    """获取会话统计信息，包括滑动窗口状态"""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

        engine = sessions[session_id]

        # 基础统计信息
        stats = SessionStatsResponse(
            session_id=session_id,
            graph_nodes=len(engine.memory.knowledge_graph.graph.nodes()),
            graph_edges=len(engine.memory.knowledge_graph.graph.edges()),
            hot_memory_size=len(engine.memory.basic_memory.conversation_history),
            last_update=None  # 可以添加时间戳跟踪
        )

        # 如果有滑动窗口系统，添加额外信息
        if session_id in sliding_window_managers:
            sliding_manager = sliding_window_managers[session_id]
            # 扩展返回的数据，虽然模型定义中没有这些字段，但可以在响应中包含
            stats_dict = stats.model_dump()  # 使用model_dump替代deprecated的dict()
            stats_dict.update({
                "sliding_window_size": len(sliding_manager.sliding_window.conversations),
                "processed_turns": sliding_manager._processed_count if hasattr(sliding_manager, '_processed_count') else 0,
                "window_capacity": sliding_manager.sliding_window.window_size,
                "processing_delay": sliding_manager.sliding_window.processing_delay
            })
            return stats_dict

        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session stats: {e}")

@app.post("/sessions/{session_id}/reset")
async def reset_session(session_id: str, req: ResetSessionRequest):
    """重置会话数据"""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

        if req.keep_character_data:
            # 只清除对话历史，保留知识图谱
            engine = sessions[session_id]
            engine.memory.basic_memory.conversation_history.clear()
            logger.info(f"Cleared conversation history for session {session_id}")
        else:
            # 完全重置会话
            del sessions[session_id]
            logger.info(f"Completely reset session {session_id}")

        return {"message": "Session reset successfully", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset session: {e}")

@app.post("/sessions/{session_id}/reinitialize")
async def reinitialize_session(session_id: str):
    """重新初始化酒馆会话的角色知识图谱"""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

        engine = sessions[session_id]

        # 在清空之前先获取角色名称
        character_name = "Unknown Character"

        # 检查是否有酒馆连接器数据
        if hasattr(engine, '_tavern_character_name'):
            character_name = engine._tavern_character_name
            logger.info(f"📋 从引擎属性获取角色名: {character_name}")
        elif hasattr(engine, 'memory') and hasattr(engine.memory, 'get_state'):
            stored_character = engine.memory.get_state('tavern_character_name')
            if stored_character:
                character_name = stored_character
                logger.info(f"📋 从内存状态获取角色名: {character_name}")

        # 如果还是找不到，尝试从session_id中提取
        if character_name == "Unknown Character":
            try:
                # session_id格式: tavern_角色名_随机字符
                if session_id.startswith('tavern_'):
                    parts = session_id.split('_')
                    logger.info(f"📋 解析session_id: {session_id}, 分割结果: {parts}")
                    if len(parts) >= 3:
                        # 提取角色名部分（去掉tavern_前缀和后面的随机字符）
                        character_name = '_'.join(parts[1:-1])
                        logger.info(f"📋 拼接角色名: {character_name}")
                        # URL解码
                        import urllib.parse
                        character_name = urllib.parse.unquote(character_name)
                        logger.info(f"📋 URL解码后角色名: {character_name}")
            except Exception as e:
                logger.warning(f"从session_id提取角色名失败: {e}")

        logger.info(f"🎯 最终确定的角色名称: {character_name}")

        # 检查知识图谱当前状态
        current_nodes = len(engine.memory.knowledge_graph.graph.nodes())
        current_edges = len(engine.memory.knowledge_graph.graph.edges())
        logger.info(f"📊 清空前知识图谱状态: 节点={current_nodes}, 边={current_edges}")

        if current_nodes > 0:
            logger.info("📋 当前图谱中的节点:")
            for i, (node_id, attrs) in enumerate(engine.memory.knowledge_graph.graph.nodes(data=True)):
                if i < 10:  # 只显示前10个节点
                    node_type = attrs.get('type', 'unknown')
                    description = attrs.get('description', '')[:50]
                    logger.info(f"  节点{i+1}: {node_id} (类型: {node_type}) - {description}...")
                elif i == 10:
                    logger.info(f"  ... 还有 {current_nodes - 10} 个节点")
                    break

        logger.info("🧹 开始清空知识图谱...")
        # 清空现有知识图谱
        engine.memory.clear_all()
        logger.info(f"✅ 知识图谱已清空")

        nodes_created = 0
        edges_created = 0

        # 从角色名称重新创建基本的角色节点
        if character_name and character_name != "Unknown Character":
            logger.info(f"🎭 开始为角色 '{character_name}' 创建基础节点...")

            # 创建角色节点
            logger.info(f"📝 创建主角色节点: {character_name}")
            engine.memory.add_or_update_node(
                character_name,
                "character",
                description=f"SillyTavern中的角色 {character_name}",
                role="主角",
                source="SillyTavern"
            )
            nodes_created += 1
            logger.info(f"✅ 主角色节点创建成功，总节点数: {nodes_created}")

            # 创建一些基础的关系节点
            logger.info("🏠 创建对话世界节点...")
            engine.memory.add_or_update_node(
                "对话世界",
                "location",
                description=f"{character_name}所在的对话环境",
                type="虚拟空间"
            )
            nodes_created += 1
            logger.info(f"✅ 对话世界节点创建成功，总节点数: {nodes_created}")

            # 创建角色与世界的关系
            logger.info(f"🔗 创建 {character_name} 与 对话世界 的关系...")
            engine.memory.add_edge(character_name, "对话世界", "位于")
            edges_created += 1
            logger.info(f"✅ 关系创建成功，总边数: {edges_created}")

            # 保存角色名称到状态中
            logger.info(f"💾 保存角色名称到状态: {character_name}")
            engine.memory.update_state('tavern_character_name', character_name)
            logger.info("✅ 角色名称状态保存成功")

        else:
            logger.warning(f"⚠️ 角色名称无效: '{character_name}'，跳过节点创建")

        # 验证创建结果
        final_nodes = len(engine.memory.knowledge_graph.graph.nodes())
        final_edges = len(engine.memory.knowledge_graph.graph.edges())
        logger.info(f"📊 重新初始化完成统计:")
        logger.info(f"  - 期望创建节点: {nodes_created}, 实际节点数: {final_nodes}")
        logger.info(f"  - 期望创建边: {edges_created}, 实际边数: {final_edges}")

        if final_nodes != nodes_created:
            logger.warning(f"⚠️ 节点数量不匹配！期望={nodes_created}, 实际={final_nodes}")
        if final_edges != edges_created:
            logger.warning(f"⚠️ 边数量不匹配！期望={edges_created}, 实际={final_edges}")

        # 显示最终的图谱内容
        if final_nodes > 0:
            logger.info("📋 最终图谱内容:")
            for i, (node_id, attrs) in enumerate(engine.memory.knowledge_graph.graph.nodes(data=True)):
                node_type = attrs.get('type', 'unknown')
                description = attrs.get('description', '')[:100]
                logger.info(f"  节点{i+1}: {node_id} (类型: {node_type}) - {description}...")

        logger.info(f"🎉 重新初始化会话 {session_id} 完成:")
        logger.info(f"  - 角色: {character_name}")
        logger.info(f"  - 节点: {nodes_created}")
        logger.info(f"  - 边: {edges_created}")

        return {
            "message": "Session reinitialized successfully",
            "session_id": session_id,
            "character_name": character_name,
            "nodes_created": nodes_created,
            "edges_created": edges_created
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reinitializing session: {e}")
        import traceback
        logger.error(f"Detailed error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to reinitialize session: {e}")

@app.get("/sessions")
async def list_sessions():
    """列出所有活跃会话"""
    try:
        session_list = []
        for sid, engine in sessions.items():
            session_list.append({
                "session_id": sid,
                "graph_nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "graph_edges": len(engine.memory.knowledge_graph.graph.edges()),
                "conversation_turns": len(engine.memory.basic_memory.conversation_history)
            })

        return {"sessions": session_list, "total_sessions": len(sessions)}
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}")

# --- 插件角色数据提交端点 ---
@app.post("/tavern/submit_character", response_model=SubmitCharacterDataResponse)
async def submit_character_data(req: SubmitCharacterDataRequest):
    """
    插件提交角色数据端点
    允许SillyTavern插件直接提交检测到的角色数据到后台
    """
    if not TAVERN_MODE_ACTIVE:
        raise HTTPException(status_code=403, detail="Tavern mode disabled")
    try:
        logger.info(f"🎭 [角色提交] 收到插件角色数据提交请求")
        logger.info(f"  - 角色ID: {req.character_id}")
        logger.info(f"  - 角色名称: {req.character_name}")
        logger.info(f"  - 提交时间: {req.timestamp or time.time()}")

        # 详细记录角色数据
        if req.character_data:
            logger.info(f"  - 角色数据字段数: {len(req.character_data.keys())}")
            logger.info(f"  - 角色数据字段: {list(req.character_data.keys())}")

            # 记录关键字段
            for key in ['name', 'description', 'personality', 'scenario', 'first_mes']:
                if key in req.character_data:
                    value = req.character_data[key]
                    if isinstance(value, str):
                        logger.info(f"    {key}: {len(value)} 字符 - {value[:100]}{'...' if len(value) > 100 else ''}")
                    else:
                        logger.info(f"    {key}: {type(value)} - {value}")

        # 存储角色数据
        plugin_character_data[req.character_id] = {
            "character_id": req.character_id,
            "character_name": req.character_name,
            "character_data": req.character_data,
            "timestamp": req.timestamp or time.time(),
            "submitted_at": time.time()
        }

        logger.info(f"✅ [角色提交] 角色数据已成功存储: {req.character_name} (ID: {req.character_id})")
        logger.info(f"📊 [角色提交] 当前存储的角色数据总数: {len(plugin_character_data)}")

        # 检查是否有待处理的协调式重新初始化请求
        logger.info(f"🔍 [Coord Re-init] Checking for pending reinit requests...")
        logger.info(f"🔍 [Coord Re-init] Pending requests: {list(pending_coordinated_reinits)}")
        logger.info(f"🔍 [Coord Re-init] Character ID from submission: {req.character_id}")
        logger.info(f"🔍 [Coord Re-init] Character name from submission: {req.character_name}")

        matching_sessions = []
        for session_id in list(pending_coordinated_reinits):
            # 检查这个会话是否对应当前提交的角色
            try:
                logger.info(f"🔍 [Coord Re-init] Checking session {session_id} for character match...")
                session_info = storage_manager.get_session_info(session_id)
                logger.info(f"🔍 [Coord Re-init] Session info: {session_info}")

                if session_info:
                    character_mapping_key = session_info.get("character_mapping_key")
                    logger.info(f"🔍 [Coord Re-init] Character mapping key: {character_mapping_key}")

                    # 修复：尝试多种匹配方式
                    # 1. 直接按角色ID匹配
                    # 2. 按角色名称匹配
                    # 3. 按会话ID中的角色名匹配
                    match_found = False

                    if character_mapping_key == req.character_id:
                        logger.info(f"✅ [Coord Re-init] Character ID match found! {character_mapping_key} == {req.character_id}")
                        match_found = True
                    elif character_mapping_key == req.character_name:
                        logger.info(f"✅ [Coord Re-init] Character name match found! {character_mapping_key} == {req.character_name}")
                        match_found = True
                    elif session_id.startswith(f"tavern_{req.character_name}_"):
                        logger.info(f"✅ [Coord Re-init] Session ID contains character name! {session_id} contains {req.character_name}")
                        match_found = True

                    if match_found:
                        matching_sessions.append(session_id)
                    else:
                        logger.info(f"❌ [Coord Re-init] No match: mapping_key='{character_mapping_key}' vs character_id='{req.character_id}' vs character_name='{req.character_name}'")
                else:
                    logger.warning(f"⚠️ [Coord Re-init] No session info found for {session_id}")
            except Exception as e:
                logger.warning(f"⚠️ [Coord Re-init] Failed to check session {session_id}: {e}")
                pending_coordinated_reinits.discard(session_id)

        logger.info(f"🔍 [Coord Re-init] Matching sessions found: {matching_sessions}")

        # 为匹配的会话触发自动重新初始化
        for session_id in matching_sessions:
            logger.info(f"🚀 [Coord Re-init] Triggering auto-reinitialization for session {session_id}")
            try:
                # 从待处理集合中移除
                pending_coordinated_reinits.discard(session_id)

                # 创建后台任务来执行重新初始化
                import asyncio
                async def _trigger_auto_reinit():
                    try:
                        logger.info(f"🚀 [Auto-Reinit] Starting auto-reinitialization for session {session_id}")

                        # 直接执行重新初始化逻辑，不依赖后台任务系统
                        engine = sessions[session_id]

                        # 获取角色数据
                        character_data_found = None
                        for stored_char_id, char_data in plugin_character_data.items():
                            stored_char_name = char_data.get("character_name", "")
                            if stored_char_name == req.character_name:
                                character_data_found = char_data
                                logger.info(f"✅ [Auto-Reinit] Found character data: {stored_char_name} (ID: {stored_char_id})")
                                break

                        if not character_data_found:
                            raise Exception(f"No character data found for {req.character_name}")

                        character_card = character_data_found.get("character_data", {})
                        world_info = character_card.get("world_info", "")

                        # 清空知识图谱
                        logger.info(f"🧹 [Auto-Reinit] Clearing existing knowledge graph for session {session_id}")
                        engine.memory.clear_all()

                        # 重新进行LLM初始化
                        logger.info(f"🧠 [Auto-Reinit] Re-running LLM initialization with character: {req.character_name}")
                        await run_in_threadpool(engine.initialize_from_tavern_data, character_card, world_info)

                        logger.info(f"🎉 [Auto-Reinit] Auto-reinitialization completed successfully for session {session_id}")

                        # 通过WebSocket推送完成通知
                        await manager.send_message(session_id, {
                            "type": "auto_reinitialization_complete",
                            "message": f"角色 {req.character_name} 的知识图谱重新初始化完成",
                            "session_id": session_id,
                            "character_name": req.character_name
                        })

                    except Exception as reinit_error:
                        logger.error(f"❌ [Auto-Reinit] Auto-reinitialization failed for {session_id}: {reinit_error}")
                        import traceback
                        logger.error(f"❌ [Auto-Reinit] Full error traceback: {traceback.format_exc()}")
                        # 发送失败通知
                        try:
                            await manager.send_message(session_id, {
                                "type": "auto_reinitialization_failed",
                                "message": f"角色 {req.character_name} 的自动重新初始化失败: {str(reinit_error)}",
                                "session_id": session_id,
                                "error": str(reinit_error)
                            })
                        except Exception:
                            pass

                # 异步启动重新初始化任务
                asyncio.create_task(_trigger_auto_reinit())

            except Exception as trigger_error:
                logger.error(f"❌ [Coord Re-init] Failed to trigger auto-reinitialization for {session_id}: {trigger_error}")
                pending_coordinated_reinits.discard(session_id)

        if matching_sessions:
            logger.info(f"🎯 [Coord Re-init] Triggered auto-reinitialization for {len(matching_sessions)} session(s)")

        # 注释掉自动初始化逻辑，避免与WebSocket初始化冲突
        # 当处于酒馆模式时，WebSocket会话已经处理初始化
        # try:
        #     if TAVERN_MODE_ACTIVE and req.character_name:
        #         import hashlib
        #         character_hash = hashlib.md5(req.character_name.encode('utf-8')).hexdigest()[:8]
        #         auto_session_id = f"tavern_{req.character_name}_{character_hash}"
        #         if auto_session_id not in sessions:
        #             async def _bg_auto_init():
        #                 try:
        #                     init_req = InitializeRequest(
        #                         session_id=auto_session_id,
        #                         character_card=req.character_data,
        #                         world_info=req.character_data.get("world_info", ""),
        #                         is_test=False,
        #                         enable_agent=True,
        #                     )
        #                     await initialize_session(init_req)
        #                     logger.info(f"🚀 [AutoInit] 会话已根据插件提交自动初始化: {auto_session_id}")
        #                 except Exception as ie:
        #                     logger.warning(f"⚠️ [AutoInit] 自动初始化失败: {ie}")
        #             asyncio.create_task(_bg_auto_init())
        # except Exception as auto_err:
        #     logger.warning(f"⚠️ [AutoInit] 自动初始化触发异常: {auto_err}")

        return SubmitCharacterDataResponse(
            success=True,
            message=f"角色数据提交成功: {req.character_name}",
            character_id=req.character_id
        )

    except Exception as e:
        logger.error(f"❌ [角色提交] 角色数据提交失败: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")

        return SubmitCharacterDataResponse(
            success=False,
            message=f"角色数据提交失败: {str(e)}",
            character_id=req.character_id
        )

@app.get("/tavern/get_character/{character_id}")
async def get_character_data(character_id: str):
    """
    获取插件提交的角色数据
    供后台初始化流程使用
    """
    try:
        logger.info(f"🔍 [角色获取] 查询角色数据: {character_id}")

        if character_id in plugin_character_data:
            character_info = plugin_character_data[character_id]
            logger.info(f"✅ [角色获取] 找到角色数据: {character_info['character_name']}")
            return character_info
        else:
            logger.warning(f"⚠️ [角色获取] 未找到角色数据: {character_id}")
            logger.info(f"📊 [角色获取] 当前可用角色: {list(plugin_character_data.keys())}")
            raise HTTPException(status_code=404, detail=f"Character data not found: {character_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [角色获取] 获取角色数据异常: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/tavern/available_characters")
async def get_available_characters():
    """
    获取所有可用的角色数据
    """
    if not TAVERN_MODE_ACTIVE:
        raise HTTPException(status_code=403, detail="Tavern mode disabled")
    try:
        logger.info(f"📋 [角色列表] 查询可用角色列表，当前数量: {len(plugin_character_data)}")

        characters = []
        for character_id, character_info in plugin_character_data.items():
            characters.append({
                "character_id": character_id,
                "character_name": character_info["character_name"],
                "submitted_at": character_info["submitted_at"],
                "timestamp": character_info.get("timestamp")
            })

        # 按提交时间排序，最新的在前
        characters.sort(key=lambda x: x["submitted_at"], reverse=True)

        logger.info(f"✅ [角色列表] 返回 {len(characters)} 个角色")
        return {"characters": characters, "count": len(characters)}

    except Exception as e:
        logger.error(f"❌ [角色列表] 获取角色列表异常: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/health")
async def health_check():
    """健康检查端点"""
    if not TAVERN_MODE_ACTIVE:
        # 在本地测试模式下，完全隔离：直接拒绝健康检查
        raise HTTPException(status_code=403, detail="Tavern mode disabled")
    logger.info("🏥 [Health Check] Received request. Processing...")

    # 检查Agent支持情况
    agent_sessions = sum(1 for engine in sessions.values() if engine.grag_agent is not None)
    local_processor_sessions = len(sessions) - agent_sessions

    # 检查WebSocket连接状态
    ws_connections = len(manager.active_connections)

    # 检查LLM配置状态
    llm_configured = False
    try:
        from src.utils.config import config
        llm_configured = bool(config.llm.api_key and config.llm.base_url)
    except Exception:
        pass

    health_data = {
        "status": "healthy",
        "version": "1.0.0",
        "active_sessions": len(sessions),
        "agent_enabled_sessions": agent_sessions,
        "local_processor_sessions": local_processor_sessions,
        "websocket_connections": ws_connections,
        "llm_configured": llm_configured,
        "storage_path": str(storage_manager.base_path),
        "total_characters": len(storage_manager.character_mapping)
    }

    # 详细健康检查日志
    logger.info("🏥 [Health Check] System status details:")
    logger.info(f"  - Total sessions: {len(sessions)}")
    logger.info(f"  - Agent-enabled sessions: {agent_sessions}")
    logger.info(f"  - Local processor sessions: {local_processor_sessions}")
    logger.info(f"  - WebSocket connections: {ws_connections}")
    logger.info(f"  - LLM configured: {llm_configured}")
    logger.info(f"  - Storage path: {storage_manager.base_path}")
    logger.info(f"  - Total characters: {len(storage_manager.character_mapping)}")

    # 如果有活跃会话，记录会话详情
    if sessions:
        logger.info("🏥 [Health Check] Active sessions details:")
        for session_id, engine in list(sessions.items())[:5]:  # 只显示前5个
            try:
                nodes = len(engine.memory.knowledge_graph.graph.nodes())
                edges = len(engine.memory.knowledge_graph.graph.edges())
                has_agent = engine.grag_agent is not None
                logger.info(f"  - {session_id[:12]}...: {nodes} nodes, {edges} edges, agent={has_agent}")
            except Exception as e:
                logger.info(f"  - {session_id[:12]}...: error getting stats - {e}")
        if len(sessions) > 5:
            logger.info(f"  - ... and {len(sessions) - 5} more sessions")

    logger.info(f"✅ [Health Check] Responding with status=healthy")
    return health_data


# --- Liveness endpoint (always 200, not gated) ---
@app.get("/system/liveness")
async def liveness():
    return {"ok": True, "version": "1.0.0"}

# --- System mode control endpoints ---
@app.get("/system/tavern_mode")
async def get_tavern_mode_state():
    return {"active": TAVERN_MODE_ACTIVE}

@app.post("/system/tavern_mode")
async def set_tavern_mode_state(payload: Dict[str, Any]):
    global TAVERN_MODE_ACTIVE
    try:
        raw_val = payload.get("active")
        def to_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return False
        active = to_bool(raw_val)
        TAVERN_MODE_ACTIVE = active
        logger.debug(f"🛠️ [Mode] Set TAVERN_MODE_ACTIVE = {TAVERN_MODE_ACTIVE} (raw={raw_val!r})")
        return {"success": True, "active": TAVERN_MODE_ACTIVE}
    except Exception as e:
        logger.error(f"[Mode] Failed to set tavern mode: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# --- 酒馆角色和会话管理端点 ---

@app.post("/tavern/new_session")
async def create_new_session(character_name: str):
    """为已存在的角色创建新会话"""
    try:
        # 查找角色映射键
        character_mapping_key = None
        for key, _ in storage_manager.character_mapping.items():
            if character_name.lower() in key.lower():
                character_mapping_key = key
                break

        if not character_mapping_key:
            raise HTTPException(status_code=404, detail=f"Character '{character_name}' not found")



        new_session_id = storage_manager.create_new_session(character_mapping_key)
        return {
            "session_id": new_session_id,
            "character_name": character_name,
            "message": "New session created successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating new session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create new session: {e}")

# --- 酒馆消息处理端点 ---
class TavernMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = "tavern_session"
    mode: Optional[str] = "tavern_integration"
    timestamp: Optional[float] = None

class TavernMessageResponse(BaseModel):
    enhanced_context: Optional[str] = None
    nodes_updated: int = 0
    edges_added: int = 0
    status: str = "success"
    error: Optional[str] = None

@app.post("/tavern/process_message", response_model=TavernMessageResponse)
async def process_tavern_message(request: TavernMessageRequest):
    """处理来自酒馆插件的消息并进行GRAG增强"""
    if not TAVERN_MODE_ACTIVE:
        raise HTTPException(status_code=403, detail="Tavern mode disabled")
    try:
        logger.info(f"🍺 [API] 收到酒馆消息处理请求: {request.message[:100]}...")

        # 生成一致的会话ID（与UI和插件逻辑一致）
        def generate_consistent_session_id(character_name: str) -> str:
            """生成与UI和插件一致的会话ID"""
            import hashlib
            character_hash = hashlib.md5(character_name.encode('utf-8')).hexdigest()[:8]
            return f"tavern_{character_name}_{character_hash}"

        # 1. 首先尝试从请求中推断角色名称
        character_name = None
        if "角色初始化：" in request.message:
            # 从初始化消息中提取角色名称
            character_name = request.message.replace("角色初始化：", "").strip()

        # 2. 检查是否有现有的酒馆会话，优先使用现有会话
        session_id = request.session_id
        existing_tavern_sessions = [
            sid for sid, engine in sessions.items()
            if sid.startswith("tavern_") and engine is not None
        ]

        if existing_tavern_sessions:
            # 使用最新的酒馆会话
            session_id = max(existing_tavern_sessions)
            logger.info(f"🔄 [API] 使用现有酒馆会话: {session_id}")
        elif character_name:
            # 如果有角色名称，生成一致的会话ID
            consistent_session_id = generate_consistent_session_id(character_name)
            if consistent_session_id in sessions:
                session_id = consistent_session_id
                logger.info(f"🎯 [API] 找到匹配的一致性会话: {session_id}")
            else:
                session_id = consistent_session_id
                logger.info(f"🆕 [API] 使用一致性会话ID创建新会话: {session_id}")
        elif session_id not in sessions:
            logger.info(f"🆕 [API] 为酒馆创建新会话: {session_id}")

        # 3. 如果会话不存在，创建新的会话引擎
        if session_id not in sessions:
            # 初始化核心组件 - 使用本地模式目录
            base_data_path = Path(__file__).parent / "data" / "local_mode"
            base_data_path.mkdir(exist_ok=True)  # 确保目录存在
            memory = GRAGMemory(
                graph_save_path=str(base_data_path / "knowledge_graph.graphml"),
                entities_json_path=str(base_data_path / "entities.json"),
                auto_load_entities=True  # 本地模式也需要加载已有数据
            )
            perception = PerceptionModule()
            rpg_processor = RPGTextProcessor()
            validation_layer = ValidationLayer()

            # 创建游戏引擎
            game_engine = GameEngine(memory, perception, rpg_processor, validation_layer)
            sessions[session_id] = game_engine

            # 为酒馆会话创建滑动窗口管理器
            if session_id not in sliding_window_managers:
                from src.core.sliding_window import SlidingWindowManager
                window_size = int(os.getenv('SLIDING_WINDOW_SIZE', '4'))
                processing_delay = int(os.getenv('PROCESSING_DELAY', '1'))
                sliding_window = SlidingWindowManager(window_size=window_size, processing_delay=processing_delay)
                sliding_window_managers[session_id] = DelayedUpdateManager(
                    sliding_window=sliding_window,
                    grag_agent=None  # 将在需要时创建
                )

        engine = sessions[session_id]

        # 使用GRAG系统增强上下文
        logger.info(f"🧠 [API] 开始GRAG增强处理...")

        # 模拟用户输入和AI回复的对话对
        # 在酒馆模式下，我们主要处理用户输入并提供增强上下文
        enhanced_context = ""
        nodes_updated = 0
        edges_added = 0

        try:
            # 从记忆中检索相关上下文
            relevant_context = engine.memory.retrieve_relevant_context(
                request.message,
                max_context_length=4000
            )

            if relevant_context:
                enhanced_context = f"[EchoGraph Enhanced Context]\n{relevant_context}\n\n[User Message]\n{request.message}"
                logger.info(f"📖 [API] 检索到相关上下文，长度: {len(relevant_context)}")

            # 如果没有足够的上下文，尝试从消息中提取实体
            if len(enhanced_context) < 100:
                logger.info(f"🔍 [API] 上下文较短，尝试从消息中提取实体...")

                # 使用感知模块分析消息
                perception_results = engine.perception.analyze_text(request.message)

                if perception_results.get('entities'):
                    entity_info = []
                    for entity in perception_results['entities'][:5]:  # 最多5个实体
                        entity_name = entity.get('name', '')
                        entity_type = entity.get('type', 'concept')
                        if entity_name:
                            # 检查知识图谱中是否有这个实体
                            if engine.memory.knowledge_graph.graph.has_node(entity_name):
                                node_data = engine.memory.knowledge_graph.graph.nodes[entity_name]
                                description = node_data.get('description', '')
                                if description:
                                    entity_info.append(f"• {entity_name} ({entity_type}): {description}")
                            else:
                                entity_info.append(f"• {entity_name} ({entity_type}): 新发现的实体")

                    if entity_info:
                        enhanced_context = f"[EchoGraph Entity Context]\n" + "\n".join(entity_info) + f"\n\n[User Message]\n{request.message}"

            # 异步更新知识图谱（不阻塞响应）
            if request.message and len(request.message.strip()) > 10:
                logger.info(f"🔄 [API] 异步更新知识图谱...")
                try:
                    # 使用滑动窗口处理（如果可用）
                    if session_id in sliding_window_managers:
                        window_manager = sliding_window_managers[session_id]
                        # 添加到滑动窗口，延迟处理
                        result = window_manager.add_conversation_turn(
                            user_input=request.message,
                            llm_response="",  # 酒馆模式下AI回复由酒馆生成
                            timestamp=request.timestamp or time.time()
                        )

                        if result.get('target_processed'):
                            nodes_updated = result.get('nodes_updated', 0)
                            edges_added = result.get('edges_added', 0)
                            logger.info(f"✅ [API] 滑动窗口处理完成: +{nodes_updated}节点, +{edges_added}关系")
                    else:
                        # 直接处理（备用方案）
                        update_result = engine.extract_updates_from_response("", request.message)
                        nodes_updated = update_result.get('nodes_updated', 0)
                        edges_added = update_result.get('edges_added', 0)
                        logger.info(f"✅ [API] 直接处理完成: +{nodes_updated}节点, +{edges_added}关系")

                except Exception as update_error:
                    logger.warning(f"⚠️ [API] 知识图谱更新失败: {update_error}")
                    # 不影响主要功能，继续返回增强上下文

        except Exception as context_error:
            logger.warning(f"⚠️ [API] 上下文增强失败: {context_error}")
            # 即使增强失败，也返回基本响应
            enhanced_context = f"[EchoGraph Basic Context]\n{request.message}"

        response = TavernMessageResponse(
            enhanced_context=enhanced_context if enhanced_context else None,
            nodes_updated=nodes_updated,
            edges_added=edges_added,
            status="success"
        )

        logger.info(f"✅ [API] 酒馆消息处理完成 - 返回上下文长度: {len(enhanced_context) if enhanced_context else 0}")
        return response

    except Exception as e:
        logger.error(f"❌ [API] 酒馆消息处理异常: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")

        return TavernMessageResponse(
            status="error",
            error=str(e)
        )

@app.get("/sessions/{session_id}/export")
async def export_session_graph(session_id: str):
    """导出会话的知识图谱为JSON格式"""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

        engine = sessions[session_id]

        # 将NetworkX图转换为JSON格式
        import networkx as nx
        from networkx.readwrite import json_graph
        from datetime import datetime

        graph_data = json_graph.node_link_data(engine.memory.knowledge_graph.graph)

        # 添加元数据
        export_data = {
            "session_id": session_id,
            "export_timestamp": str(datetime.utcnow()),
            "graph_stats": {
                "nodes": len(engine.memory.knowledge_graph.graph.nodes()),
                "edges": len(engine.memory.knowledge_graph.graph.edges())
            },
            "graph_data": graph_data
        }

        from fastapi.responses import StreamingResponse
        import io
        import json

        # 创建JSON流
        json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
        json_bytes = json_str.encode('utf-8')

        return StreamingResponse(
            io.BytesIO(json_bytes),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=echograph-graph-export.json"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting session graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export graph: {e}")

@app.post("/ui_test/clear_data")
async def clear_test_data():
    """清空UI测试数据"""
    try:
        storage_manager.clear_test_data()

        # 同时清理测试会话
        test_sessions_to_remove = [
            sid for sid, engine in sessions.items()
            if sid.startswith("test_") or "test" in sid.lower()
        ]
        for test_sid in test_sessions_to_remove:
            del sessions[test_sid]

        return {"message": "Test data cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing test data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear test data: {e}")

@app.delete("/tavern/character/{character_name}")
async def delete_character(character_name: str):
    """删除指定角色的所有数据"""
    try:
        # 查找角色映射键
        character_mapping_key = None
        for key, _ in storage_manager.character_mapping.items():
            if character_name.lower() in key.lower():
                character_mapping_key = key
                break

        if not character_mapping_key:
            raise HTTPException(status_code=404, detail=f"Character '{character_name}' not found")

        storage_manager.clear_character_data(character_mapping_key)

        # 清理相关会话
        sessions_to_remove = [
            sid for sid, engine in sessions.items()
            if storage_manager.get_session_info(sid) and
               storage_manager.get_session_info(sid).get("character_mapping_key") == character_mapping_key
        ]
        for sid in sessions_to_remove:
            del sessions[sid]

        return {"message": f"Character '{character_name}' deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting character: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete character: {e}")

@app.get("/tavern/current_session")
async def get_current_tavern_session():
    """获取当前活跃的酒馆会话ID"""
    if not TAVERN_MODE_ACTIVE:
        raise HTTPException(status_code=403, detail="Tavern mode disabled")
    try:
        # 找到最新的酒馆会话
        tavern_sessions = [
            sid for sid, engine in sessions.items()
            if sid.startswith("tavern_") and engine is not None
        ]

        if not tavern_sessions:
            logger.info(f"[get_current_tavern_session] No active tavern sessions found")
            return {
                "has_session": False,
                "message": "No active tavern session found"
            }

        # 返回最新的酒馆会话（按时间戳排序）
        latest_session = max(tavern_sessions)
        engine = sessions[latest_session]

        # 获取图谱节点和边的数量
        nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
        edges_count = len(engine.memory.knowledge_graph.graph.edges())

        logger.info(f"[get_current_tavern_session] Found session: {latest_session}")
        logger.info(f"[get_current_tavern_session] Graph stats: nodes={nodes_count}, edges={edges_count}")

        return {
            "has_session": True,
            "session_id": latest_session,
            "graph_nodes": nodes_count,
            "graph_edges": edges_count,
            "message": "Active tavern session found"
        }
    except Exception as e:
        logger.error(f"Error getting current tavern session: {e}")
        return {
            "has_session": False,
            "error": str(e)
        }

@app.get("/tavern/characters")
async def list_characters():
    """列出所有已注册的角色"""
    try:
        characters = storage_manager.list_characters()
        return {"characters": characters, "total_count": len(characters)}
    except Exception as e:
        logger.error(f"Error listing characters: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list characters: {e}")

@app.get("/tavern/sessions")
async def list_active_sessions():
    """列出所有活跃会话"""
    try:
        sessions_info = []
        for session_id, session_info in storage_manager.active_sessions.items():
            engine_exists = session_id in sessions
            sessions_info.append({
                "session_id": session_id,
                "character_name": session_info.get("character_name", "Unknown"),
                "local_dir": session_info.get("local_dir_name", "unknown"),
                "created_at": session_info.get("created_at"),
                "engine_loaded": engine_exists
            })

        return {"sessions": sessions_info, "total_count": len(sessions_info)}
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}")

@app.post("/tavern/sessions/{session_id}/request_reinitialize")
async def request_coordinated_reinitialize(session_id: str):
    """
    请求插件提交当前角色数据，然后自动执行重新初始化。
    这是一个协调式的初始化流程，确保获取最新的角色数据。
    """
    logger.info(f"🔄 [Coord Re-init] Received coordinated re-initialization request for session {session_id}.")

    if session_id not in sessions:
        logger.error(f"❌ [Coord Re-init] Session {session_id} not found.")
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    # 检查WebSocket连接
    if session_id not in manager.active_connections:
        logger.error(f"❌ [Coord Re-init] No active WebSocket connection for session {session_id}.")
        raise HTTPException(
            status_code=400,
            detail=f"无法重新初始化：会话 {session_id} 没有活动的插件连接。请确保SillyTavern插件已连接。"
        )

    # 发送请求给插件，要求其提交当前角色数据
    try:
        # 标记此会话为待处理协调式重新初始化
        pending_coordinated_reinits.add(session_id)
        logger.info(f"🔄 [Coord Re-init] Marked session {session_id} as pending coordinated reinitialization.")

        await manager.send_message(session_id, {
            "type": "request_character_submission",
            "message": "请提交当前角色的数据以进行重新初始化",
            "session_id": session_id,
            "action_required": "submit_current_character_data"
        })

        logger.info(f"✅ [Coord Re-init] Sent character data request to plugin for session {session_id}.")

        return {
            "success": True,
            "message": "已向插件发送角色数据请求，请等待插件提交数据后自动重新初始化。",
            "session_id": session_id,
            "next_step": "插件将自动提交角色数据并触发重新初始化"
        }

    except Exception as e:
        logger.error(f"❌ [Coord Re-init] Failed to send request to plugin: {e}")
        # 如果失败，从待处理集合中移除
        pending_coordinated_reinits.discard(session_id)
        raise HTTPException(
            status_code=500,
            detail=f"向插件发送请求失败：{e}"
        )


@app.post("/tavern/sessions/{session_id}/reinitialize_from_plugin")
async def reinitialize_session_from_plugin(session_id: str, background_tasks: BackgroundTasks):
    """
    使用插件最后一次提交的数据，重新初始化会话的知识图谱。
    这是一个耗时操作，将作为后台任务运行。
    现在会被协调式重新初始化流程自动调用。
    """
    logger.info(f"🔄 [Re-init] Received request to re-initialize session {session_id} from plugin submission.")

    if session_id not in sessions:
        logger.error(f"❌ [Re-init] Session {session_id} not found.")
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    # 1. 从会话ID反查角色ID
    session_info = storage_manager.get_session_info(session_id)
    if not session_info or not session_info.get("character_mapping_key"):
        logger.error(f"❌ [Re-init] Could not find character mapping for session {session_id}.")
        raise HTTPException(status_code=404, detail="Could not determine character for this session.")

    character_id = session_info["character_mapping_key"]
    logger.info(f"✅ [Re-init] Found character ID for session: {character_id}")

    # 2. 检查是否有插件数据，支持多种查找方式
    character_data_found = None
    character_key_used = None

    # 方式1：直接用character_id查找
    if character_id in plugin_character_data:
        character_data_found = plugin_character_data[character_id]
        character_key_used = character_id
        logger.info(f"✅ [Re-init] Found plugin data using character_id: {character_id}")
    else:
        # 方式2：遍历所有角色数据，按角色名匹配
        for stored_char_id, char_data in plugin_character_data.items():
            stored_char_name = char_data.get("character_name", "")
            if stored_char_name == character_id:  # character_id 实际上是角色名
                character_data_found = char_data
                character_key_used = stored_char_id
                logger.info(f"✅ [Re-init] Found plugin data using character name match: {stored_char_name} (stored as {stored_char_id})")
                break

        # 方式3：从会话ID中提取角色名再匹配
        if not character_data_found and session_id.startswith("tavern_"):
            # 提取会话ID中的角色名：tavern_Seraphina_08a0fb04 -> Seraphina
            parts = session_id.split("_")
            if len(parts) >= 2:
                session_char_name = parts[1]  # 获取角色名部分
                for stored_char_id, char_data in plugin_character_data.items():
                    stored_char_name = char_data.get("character_name", "")
                    if stored_char_name == session_char_name:
                        character_data_found = char_data
                        character_key_used = stored_char_id
                        logger.info(f"✅ [Re-init] Found plugin data using session-derived name: {session_char_name} (stored as {stored_char_id})")
                        break

    if not character_data_found:
        logger.error(f"❌ [Re-init] No plugin data found for character ID: {character_id}")
        logger.error(f"❌ [Re-init] Available character IDs: {list(plugin_character_data.keys())}")
        # 显示更详细的调试信息
        for stored_id, stored_data in plugin_character_data.items():
            logger.error(f"   - ID: {stored_id}, Name: {stored_data.get('character_name', 'Unknown')}")
        raise HTTPException(
            status_code=404,
            detail=f"无法重新初始化：没有找到角色 '{character_id}' 的插件数据。请确保插件已正确提交角色数据。"
        )

    # 3. 使用插件数据进行重新初始化
    last_submission = character_data_found
    character_card = last_submission.get("character_data", {})
    world_info = character_card.get("world_info", "")

    logger.info(f"✅ [Re-init] Found last submitted data for character {character_id} from timestamp {last_submission.get('timestamp')}.")

    # 4. 定义后台重新初始化任务
    async def reinitialize_task():
        logger.info(f"🚀 [Re-init Task] Starting background re-initialization for session {session_id}.")
        engine = sessions[session_id]

        # 清空知识图谱
        logger.info(f"🧹 [Re-init Task] Clearing existing knowledge graph for session {session_id}.")
        engine.memory.clear_all()

        # 重新进行LLM初始化
        logger.info(f"🧠 [Re-init Task] Re-running LLM initialization...")
        await run_in_threadpool(engine.initialize_from_tavern_data, character_card, world_info)
        logger.info(f"🎉 [Re-init Task] Background re-initialization for session {session_id} completed.")

    # 4. 启动后台任务
    background_tasks.add_task(reinitialize_task)

    return {
        "message": "Re-initialization started in the background. The graph will be updated shortly.",
        "session_id": session_id,
        "character_id": character_id
    }

@app.post("/system/full_reset")
async def full_system_reset():
    """
    完全清理系统状态，包括所有会话、存储数据和缓存
    解决重复连接和数据冲突问题
    """
    try:
        logger.info("🧼 [Full Reset] 开始完全清理系统...")

        # 1. 清理所有活跃会话
        session_count = len(sessions)
        sessions.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {session_count} 个活跃会话")

        # 2. 清理滑动窗口管理器
        sliding_window_count = len(sliding_window_managers)
        sliding_window_managers.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {sliding_window_count} 个滑动窗口管理器")

        # 3. 清理冲突解决器
        conflict_resolver_count = len(conflict_resolvers)
        conflict_resolvers.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {conflict_resolver_count} 个冲突解决器")

        # 4. 清理初始化任务
        init_task_count = len(initialization_tasks)
        initialization_tasks.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {init_task_count} 个初始化任务")

        # 5. 清理插件角色数据
        plugin_char_count = len(plugin_character_data)
        plugin_character_data.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {plugin_char_count} 个插件角色数据")

        # 6. 清理WebSocket连接
        ws_connection_count = len(manager.active_connections)
        for session_id in list(manager.active_connections.keys()):
            try:
                await manager.active_connections[session_id].close()
            except:
                pass
        manager.active_connections.clear()
        logger.info(f"🧼 [Full Reset] 清理了 {ws_connection_count} 个WebSocket连接")

        # 7. 重新初始化存储管理器
        logger.info("🧼 [Full Reset] 重新初始化存储管理器...")
        storage_manager.__init__()

        # 8. 清理文件系统缓存（可选）
        try:
            import gc
            gc.collect()
            logger.info("🧼 [Full Reset] 执行垃圾回收")
        except Exception as gc_error:
            logger.warning(f"🧼 [Full Reset] 垃圾回收失败: {gc_error}")

        total_cleared = session_count + sliding_window_count + conflict_resolver_count + init_task_count + plugin_char_count + ws_connection_count

        logger.info(f"🎉 [Full Reset] 系统完全清理完成！总共清理 {total_cleared} 个对象")

        return {
            "success": True,
            "message": "系统已完全清理，可以重新开始使用",
            "cleared_counts": {
                "sessions": session_count,
                "sliding_windows": sliding_window_count,
                "conflict_resolvers": conflict_resolver_count,
                "initialization_tasks": init_task_count,
                "plugin_characters": plugin_char_count,
                "websocket_connections": ws_connection_count,
                "total": total_cleared
            }
        }

    except Exception as e:
        logger.error(f"❌ [Full Reset] 系统清理失败: {e}")
        import traceback
        logger.error(f"❌ [Full Reset] 详细错误: {traceback.format_exc()}")
        return {
            "success": False,
            "message": f"系统清理失败: {str(e)}",
            "error": str(e)
        }

@app.get("/system/quick_reset")
async def quick_reset():
    """
    快速清理 - 只清理内存中的会话和连接，不影响文件系统
    适合解决重复连接问题
    """
    try:
        logger.info("🛠️ [Quick Reset] 开始快速清理...")

        # 清理所有内存中的数据
        session_count = len(sessions)
        sliding_window_count = len(sliding_window_managers)
        conflict_resolver_count = len(conflict_resolvers)
        ws_connection_count = len(manager.active_connections)
        plugin_char_count = len(plugin_character_data)

        sessions.clear()
        sliding_window_managers.clear()
        conflict_resolvers.clear()
        plugin_character_data.clear()

        # 关闭所有WebSocket连接
        for session_id in list(manager.active_connections.keys()):
            try:
                await manager.active_connections[session_id].close()
            except:
                pass
        manager.active_connections.clear()

        total_cleared = session_count + sliding_window_count + conflict_resolver_count + ws_connection_count + plugin_char_count

        logger.info(f"✅ [Quick Reset] 快速清理完成！清理 {total_cleared} 个对象")

        return {
            "success": True,
            "message": f"快速清理完成，清理了 {total_cleared} 个对象",
            "cleared_counts": {
                "sessions": session_count,
                "sliding_windows": sliding_window_count,
                "conflict_resolvers": conflict_resolver_count,
                "websocket_connections": ws_connection_count,
                "plugin_characters": plugin_char_count,
                "total": total_cleared
            }
        }

    except Exception as e:
        logger.error(f"❌ [Quick Reset] 快速清理失败: {e}")
        return {
            "success": False,
            "message": f"快速清理失败: {str(e)}",
            "error": str(e)
        }

# --- WebSocket 请求处理辅助函数 ---
async def _handle_ws_request(session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
    action = message.get("action")
    payload = message.get("payload") or {}
    try:
        logger.info(f"[WS] Routing action='{action}' for session={session_id} | payload_keys={list((payload or {}).keys())}")
    except Exception:
        pass
    try:
        # 初始化会话
        if action == "initialize":
            req = InitializeRequest(**payload)
            # 强制使用WebSocket连接的session_id，确保一致性
            req.session_id = session_id
            resp = await initialize_session(req)
            return {"ok": True, "data": resp.model_dump()}
        # 增强提示
        elif action == "enhance_prompt":
            req = EnhancePromptRequest(**payload)
            resp = await enhance_prompt(req)
            return {"ok": True, "data": resp.model_dump()}
        # 滑动窗口对话处理
        elif action == "process_conversation":
            req = ProcessConversationRequest(**payload)
            resp = await process_conversation(req)
            return {"ok": True, "data": resp.model_dump()}
        # 对话同步（冲突解决）
        elif action == "sync_conversation":
            req = SyncConversationRequest(**payload)
            resp = await sync_conversation(req)
            return {"ok": True, "data": resp.model_dump()}
        # 提交角色数据
        elif action == "tavern.submit_character":
            req = SubmitCharacterDataRequest(**payload)
            resp = await submit_character_data(req)
            return {"ok": True, "data": resp.model_dump()}
        # 请求插件提交角色数据
        elif action == "tavern.request_character_data":
            logger.info(f"[WS] Processing tavern.request_character_data for session_id: {session_id}")
            # 这是一个通知消息，告诉插件需要提交当前角色数据
            # 插件收到后应该调用 tavern.submit_character
            return {"ok": True, "data": {"message": "请插件提交当前角色数据", "action_required": "submit_current_character"}}
        # 查询当前会话
        elif action == "tavern.current_session":
            logger.info(f"[WS] Processing tavern.current_session for session_id: {session_id}")
            logger.info(f"[WS] Current sessions: {list(sessions.keys())}")

            # 查询当前特定会话的状态
            if session_id in sessions and session_id.startswith("tavern_"):
                logger.info(f"[WS] Found existing session: {session_id}")
                engine = sessions[session_id]
                nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
                edges_count = len(engine.memory.knowledge_graph.graph.edges())

                logger.info(f"[WS] Session graph stats: nodes={nodes_count}, edges={edges_count}")

                data = {
                    "has_session": True,
                    "session_id": session_id,
                    "graph_nodes": nodes_count,
                    "graph_edges": edges_count,
                    "message": "Active tavern session found"
                }
            else:
                logger.info(f"[WS] No session found for: {session_id}, waiting for frontend to send initialization data...")
                data = {
                    "has_session": False,
                    "message": f"No active tavern session found for {session_id}. Please send initialization data."
                }

            logger.info(f"[WS] Returning session data: {data}")
            return {"ok": True, "data": data}
        # 会话统计
        elif action == "sessions.stats":
            sid = payload.get("session_id") or session_id
            resp = await get_session_stats(sid)
            # 检查返回的是字典还是Pydantic模型
            if hasattr(resp, 'model_dump'):
                return {"ok": True, "data": resp.model_dump()}
            elif hasattr(resp, 'dict'):  # 向后兼容
                return {"ok": True, "data": resp.model_dump()}
            else:
                return {"ok": True, "data": resp}
        # 健康检查（可选，通过WS返回当前状态）
        elif action == "health":
            data = await health_check()
            return {"ok": True, "data": data}
        # 完全清理系统
        elif action == "system.full_reset":
            data = await full_system_reset()
            return {"ok": True, "data": data}
        else:
            return {"ok": False, "error": {"code": "unknown_action", "message": f"Unknown action: {action}"}}
    except HTTPException as he:
        return {"ok": False, "error": {"code": he.status_code, "message": he.detail}}
    except Exception as e:
        logger.exception(f"[WS] Error handling action '{action}' for session {session_id}: {e}")
        return {"ok": False, "error": {"code": "internal_error", "message": str(e)}}


@app.websocket("/ws/tavern/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket端点，供SillyTavern插件连接；支持请求-响应与服务端推送"""
    # Gate by tavern mode: refuse any WS when tavern mode is disabled
    if not TAVERN_MODE_ACTIVE:
        await websocket.accept()
        await websocket.close(code=1008, reason="Tavern mode disabled")
        return
    await manager.connect(session_id, websocket)
    try:
        # 发送连接确认消息
        await websocket.send_json({
            "type": "connection_established",
            "message": f"Successfully connected to EchoGraph for session {session_id}.",
            "session_id": session_id
        })

        # 主循环：接收请求并路由处理
        while True:
            msg = await websocket.receive_json()
            # 标准化请求结构：{type:'request', action:'...', request_id:'...', payload:{...}}
            req_id = msg.get("request_id")
            action = msg.get("action")
            try:
                payload_keys = list((msg.get("payload") or {}).keys())
                logger.info(f"📥 [WS] Received request | session={session_id} | action={action} | request_id={req_id} | payload_keys={payload_keys}")
            except Exception:
                pass
            result = await _handle_ws_request(session_id, msg)
            # 直接通过此连接回传响应，避免与广播消息混淆
            await websocket.send_json({
                "type": "response",
                "action": action,
                "request_id": req_id,
                **result
            })
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
    except Exception as e:
        logger.error(f" [WS] Error in WebSocket connection for session {session_id}: {e}")
        manager.disconnect(session_id, websocket)

# --- 服务器启动 ---
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EchoGraph API Server")

    # 从环境变量获取默认端口
    from src.utils.config import config
    default_port = int(os.getenv("API_SERVER_PORT", "9543"))

    parser.add_argument("--port", type=int, default=default_port, help="Port to run the API server on")
    args = parser.parse_args()

    logger.info(f"Starting EchoGraph API server on port {args.port}...")
    uvicorn.run(app, host="127.0.0.1", port=args.port)