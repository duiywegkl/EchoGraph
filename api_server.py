import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from loguru import logger
import os
import uuid

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

# --- FastAPI 应用初始化 ---
app = FastAPI(
    title="ChronoForge API",
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

def get_or_create_sliding_window_manager(session_id: str, session_config: Dict[str, Any] = None) -> DelayedUpdateManager:
    """获取或创建滑动窗口管理器"""
    if session_id not in sliding_window_managers:
        # 从会话配置获取滑动窗口设置
        sliding_config = (session_config or {}).get('sliding_window', {})
        window_size = sliding_config.get('window_size', 4)
        processing_delay = sliding_config.get('processing_delay', 1)
        enable_enhanced_agent = sliding_config.get('enable_enhanced_agent', True)
        
        # 获取对应的游戏引擎
        engine = sessions.get(session_id)
        if not engine:
            raise ValueError(f"No game engine found for session {session_id}")
        
        # 创建滑动窗口管理器
        sliding_window_manager = DelayedUpdateManager(
            window_size=window_size,
            processing_delay=processing_delay,
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
        
        conflict_resolver = ConflictResolver(sliding_manager)
        conflict_resolvers[session_id] = conflict_resolver
        logger.info(f"Created conflict resolver for session {session_id}")
    
    return conflict_resolvers[session_id]

def get_or_create_session_engine(session_id: str, is_test: bool = False, enable_agent: bool = True) -> GameEngine:
    """根据会话ID获取或创建一个新的GameEngine实例，支持测试模式和Agent开关"""
    if session_id not in sessions:
        logger.info(f"Creating new session engine for session_id: {session_id}, test_mode: {is_test}, agent_enabled: {enable_agent}")
        
        # 从存储管理器获取对应的文件路径
        graph_path = storage_manager.get_graph_file_path(session_id, is_test)
        
        # 初始化核心组件
        memory = GRAGMemory(graph_save_path=graph_path)
        perception = PerceptionModule()
        rpg_processor = RPGTextProcessor()
        validation_layer = ValidationLayer()
        
        # 可选初始化GRAG Agent
        grag_agent = None
        if enable_agent:
            try:
                from src.utils.config import config
                
                # 检查LLM配置是否完整
                if not config.llm.api_key:
                    logger.warning("LLM API Key未配置，禁用GRAG Agent功能")
                elif not config.llm.base_url:
                    logger.warning("LLM Base URL未配置，禁用GRAG Agent功能")
                else:
                    llm_client = LLMClient()
                    grag_agent = GRAGUpdateAgent(llm_client)
                    logger.info("GRAG智能Agent初始化成功")
            except Exception as e:
                logger.warning(f"GRAG Agent初始化失败，将使用本地处理器: {e}")
        
        engine = GameEngine(memory, perception, rpg_processor, validation_layer, grag_agent)
        sessions[session_id] = engine
    
    return sessions[session_id]

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

# --- API 端点实现 ---

@app.post("/initialize", response_model=InitializeResponse)
async def initialize_session(req: InitializeRequest):
    """
    初始化一个新的对话会话，解析角色卡和世界书来创建知识图谱。
    支持酒馆角色卡分类存储和测试模式。
    """
    try:
        session_id = req.session_id or str(uuid.uuid4())
        
        # 如果不是测试模式，注册酒馆角色卡
        if not req.is_test:
            local_dir_name = storage_manager.register_tavern_character(req.character_card, session_id)
            logger.info(f"Registered tavern character: {local_dir_name}")
        else:
            logger.info("Initializing in test mode")
        
        # 创建游戏引擎
        engine = get_or_create_session_engine(session_id, req.is_test, req.enable_agent)

        # 调用GameEngine方法来处理数据
        init_result = engine.initialize_from_tavern_data(req.character_card, req.world_info)

        # 如果启用了滑动窗口系统，创建相应的管理器
        if req.session_config and req.session_config.get('sliding_window'):
            try:
                get_or_create_sliding_window_manager(session_id, req.session_config)
                get_or_create_conflict_resolver(session_id)
                logger.info(f"Sliding window system initialized for session {session_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize sliding window system: {e}")

        return InitializeResponse(
            session_id=session_id, 
            message="Session initialized successfully and knowledge graph created.",
            graph_stats=init_result
        )
    except Exception as e:
        logger.error(f"Error during session initialization: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize session: {e}")

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
                   f"Turn: {result['turn_sequence']}, Target processed: {result['target_processed']}")
        
        return ProcessConversationResponse(
            message="Conversation processed successfully with sliding window",
            turn_sequence=result['turn_sequence'],
            turn_processed=result['turn_processed'],
            target_processed=result['target_processed'],
            window_size=result['current_window_size'],
            nodes_updated=result.get('nodes_updated', 0),
            edges_added=result.get('edges_added', 0),
            processing_stats={
                "timestamp": req.timestamp,
                "chat_id": req.chat_id,
                "tavern_message_id": req.tavern_message_id,
                "llm_response_length": len(req.llm_response),
                "user_input_length": len(req.user_input)
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
        
        # 同步对话状态
        sync_result = conflict_resolver.sync_conversation_state(req.tavern_history)
        
        logger.info(f"Conversation sync for session {req.session_id[:8]}... | "
                   f"Conflicts detected: {sync_result['conflicts_detected']}, "
                   f"Resolved: {sync_result['conflicts_resolved']}")
        
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
            stats_dict = stats.dict()
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

@app.get("/health")
async def health_check():
    """健康检查端点"""
    # 检查Agent支持情况
    agent_sessions = sum(1 for engine in sessions.values() if engine.grag_agent is not None)
    local_processor_sessions = len(sessions) - agent_sessions
    
    return {
        "status": "healthy",
        "version": "1.0.0",
        "active_sessions": len(sessions),
        "agent_enabled_sessions": agent_sessions,
        "local_processor_sessions": local_processor_sessions,
        "storage_path": str(storage_manager.base_path),
        "total_characters": len(storage_manager.character_mapping)
    }

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
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=chronoforge-graph-{session_id[:8]}.json"
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

# --- 服务器启动 ---
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChronoForge API Server")
    
    # 从环境变量获取默认端口
    from src.utils.config import config
    default_port = int(os.getenv("API_SERVER_PORT", "9543"))
    
    parser.add_argument("--port", type=int, default=default_port, help="Port to run the API server on")
    args = parser.parse_args()

    logger.info(f"Starting ChronoForge API server on port {args.port}...")
    uvicorn.run(app, host="127.0.0.1", port=args.port)