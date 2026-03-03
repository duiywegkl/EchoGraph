#!/usr/bin/env python3
"""
SillyTavern 连接管理器
负责EchoGraph主动连接和管理与SillyTavern的双向通信
"""

import requests
import asyncio
import json
import threading
from typing import Dict, Any, Optional, List, Callable
from loguru import logger
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TavernConfig:
    """酒馆连接配置"""
    host: str = "localhost"
    port: int = 8000
    api_key: Optional[str] = None
    timeout: int = 30  # 增加默认超时时间到30秒


@dataclass
class CharacterInfo:
    """角色信息"""
    name: str
    description: str
    personality: str
    scenario: str
    first_mes: str
    example_dialogue: str
    world_info: List[Dict[str, Any]]


class SillyTavernConnector:
    """SillyTavern连接器 - 主动管理与酒馆的连接"""
    
    def __init__(self, config: TavernConfig):
        self.config = config
        self.base_url = f"http://{config.host}:{config.port}"
        self.is_connected = False
        self.current_character: Optional[CharacterInfo] = None
        self.session = requests.Session()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop_event = threading.Event()
        self._last_monitor_state: Optional[Dict[str, Any]] = None
        
        if config.api_key:
            self.session.headers.update({'Authorization': f'Bearer {config.api_key}'})
    
    def test_connection(self) -> Dict[str, Any]:
        """测试与SillyTavern的连接"""
        try:
            logger.info(f"[SEARCH] 开始测试SillyTavern连接: {self.base_url}")
            # 尝试多个可能的健康检查端点
            endpoints_to_try = [
                "/api/ping",
                "/health", 
                "/api/version",
                "/"
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    logger.debug(f"尝试连接端点: {self.base_url}{endpoint}")
                    response = self.session.get(
                        f"{self.base_url}{endpoint}",
                        timeout=self.config.timeout
                    )
                    
                    logger.debug(f"端点 {endpoint} 响应状态: {response.status_code}")
                    
                    if response.status_code == 200:
                        self.is_connected = True
                        logger.info(f"[OK] 成功连接SillyTavern: {self.base_url}{endpoint}")
                        return {
                            "status": "connected",
                            "endpoint": endpoint,
                            "url": self.base_url
                        }
                except Exception as e:
                    logger.debug(f"端点 {endpoint} 连接失败: {e}")
                    continue
            
            # 所有端点都失败
            self.is_connected = False
            logger.warning(f"[WARN] 所有端点都无法连接到 {self.base_url}")
            return {
                "status": "failed",
                "error": f"尝试了多个端点但都无法连接到 {self.base_url}"
            }
                
        except requests.exceptions.ConnectionError as e:
            self.is_connected = False
            logger.error(f"❌ 连接错误: {e}")
            return {
                "status": "failed", 
                "error": f"无法连接到 {self.base_url}，请确保SillyTavern正在运行"
            }
        except Exception as e:
            self.is_connected = False
            logger.error(f"❌ 测试连接异常: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def get_current_character(self) -> Optional[CharacterInfo]:
        """获取当前选中的角色信息"""
        logger.info("🎭 ========== 开始获取当前角色信息 ==========")
        try:
            # 尝试多个可能的角色API端点
            character_endpoints = [
                "/api/characters/current",
                "/getcharacter",
                "/api/character",
                "/character"
            ]
            
            for i, endpoint in enumerate(character_endpoints, 1):
                try:
                    full_url = f"{self.base_url}{endpoint}"
                    logger.info(f"[SEARCH] 尝试端点 {i}/{len(character_endpoints)}: {full_url}")
                    
                    response = self.session.get(
                        full_url,
                        timeout=self.config.timeout
                    )
                    
                    logger.info(f"📨 端点 {endpoint} 响应:")
                    logger.info(f"  - HTTP状态: {response.status_code}")
                    logger.info(f"  - 响应头: {dict(response.headers)}")
                    logger.info(f"  - 响应大小: {len(response.content)} 字节")
                    
                    if response.status_code == 200:
                        try:
                            char_data = response.json()
                            logger.info(f"[LOG] 端点 {endpoint} 返回的JSON数据:")
                            logger.info(f"  - 数据类型: {type(char_data)}")
                            
                            if isinstance(char_data, dict):
                                logger.info(f"  - JSON键: {list(char_data.keys())}")
                                name = char_data.get('name', '')
                                logger.info(f"  - 角色名称: '{name}'")
                                logger.info(f"  - 有效角色名: {bool(name and name.strip())}")
                                
                                # 检查是否有有效的角色数据
                                if name and name.strip():
                                    logger.info(f"[OK] 发现有效角色: {name}")
                                    
                                    # 获取世界书信息
                                    logger.info("🌍 获取世界书信息...")
                                    world_info = self.get_world_info()
                                    
                                    character = CharacterInfo(
                                        name=char_data.get('name', ''),
                                        description=char_data.get('description', ''),
                                        personality=char_data.get('personality', ''),
                                        scenario=char_data.get('scenario', ''),
                                        first_mes=char_data.get('first_mes', ''),
                                        example_dialogue=char_data.get('mes_example', ''),
                                        world_info=world_info
                                    )
                                    
                                    self.current_character = character
                                    logger.info(f"[OK] 角色信息获取成功:")
                                    logger.info(f"  - 角色名: {character.name}")
                                    logger.info(f"  - 描述长度: {len(character.description)} 字符")
                                    logger.info(f"  - 个性长度: {len(character.personality)} 字符")
                                    logger.info(f"  - 场景长度: {len(character.scenario)} 字符")
                                    logger.info(f"  - 首条消息长度: {len(character.first_mes)} 字符")
                                    logger.info(f"  - 示例对话长度: {len(character.example_dialogue)} 字符")
                                    logger.info(f"  - 世界书条目数: {len(character.world_info)}")
                                    
                                    return character
                                else:
                                    logger.warning(f"[WARN] 端点 {endpoint} 返回空角色名或无效数据")
                                    if isinstance(char_data, dict):
                                        logger.warning(f"  - 完整数据: {char_data}")
                            else:
                                logger.warning(f"[WARN] 端点 {endpoint} 返回非字典数据: {char_data}")
                                
                        except json.JSONDecodeError as e:
                            logger.warning(f"[WARN] 端点 {endpoint} JSON解析失败: {e}")
                            logger.warning(f"  - 原始响应: {response.text[:200]}...")
                    else:
                        logger.warning(f"[WARN] 端点 {endpoint} HTTP错误: {response.status_code}")
                        if response.text:
                            logger.warning(f"  - 错误详情: {response.text[:200]}...")
                            
                except requests.exceptions.Timeout as e:
                    logger.warning(f"[WARN] 端点 {endpoint} 超时: {e}")
                except requests.exceptions.ConnectionError as e:
                    logger.warning(f"[WARN] 端点 {endpoint} 连接错误: {e}")
                except Exception as e:
                    logger.warning(f"[WARN] 端点 {endpoint} 其他异常: {e}")
                    import traceback
                    logger.warning(f"  - 详细错误: {traceback.format_exc()}")
            
            # 所有端点都失败，不再返回模拟数据
            logger.error("❌ ========== 角色信息获取失败 ==========")
            logger.error("❌ 所有API端点都无法获取角色信息")
            logger.error("❌ 请确保：")
            logger.error("   1. SillyTavern正在运行")
            logger.error("   2. 已在SillyTavern中选择了角色")
            logger.error("   3. 角色卡数据完整且有效")
            logger.error("   4. API端点可访问")
            
            return None
                
        except Exception as e:
            logger.error("❌ ========== 获取角色信息发生异常 ==========")
            logger.error(f"❌ 异常详情: {e}")
            import traceback
            logger.error(f"❌ 完整堆栈: {traceback.format_exc()}")
            return None
    
    def get_world_info(self) -> List[Dict[str, Any]]:
        """获取世界书信息"""
        try:
            # 尝试多个可能的世界书API端点
            world_info_endpoints = [
                "/api/worldinfo",
                "/getWorldInfo", 
                "/api/world",
                "/worldinfo"
            ]
            
            for endpoint in world_info_endpoints:
                try:
                    response = self.session.get(
                        f"{self.base_url}{endpoint}",
                        timeout=self.config.timeout
                    )
                    
                    if response.status_code == 200:
                        world_data = response.json()
                        if isinstance(world_data, list):
                            logger.info(f"🌍 获取世界书: {len(world_data)} 条条目")
                            return world_data
                except:
                    continue
            
            logger.warning("[WARN] 无法从SillyTavern获取世界书信息")
            return []
                
        except Exception as e:
            logger.error(f"获取世界书异常: {e}")
            return []
    
    def get_chat_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取当前对话历史"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/chats/current?limit={limit}",
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                chat_data = response.json()
                logger.info(f"💬 获取对话历史: {len(chat_data)} 条消息")
                return chat_data
            else:
                return []
                
        except Exception as e:
            logger.error(f"获取对话历史异常: {e}")
            return []
    
    def send_enhanced_context(self, context: str) -> bool:
        """向SillyTavern发送增强上下文（如果支持）"""
        try:
            # 这里可能需要根据SillyTavern的具体API调整
            response = self.session.post(
                f"{self.base_url}/api/context/enhance",
                json={"enhanced_context": context},
                timeout=self.config.timeout
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.warning(f"发送增强上下文失败: {e}")
            return False
    
    def start_monitoring(self, callback: Callable[[Dict[str, Any]], None], interval: float = 3.0):
        """开始监控酒馆连接/会话状态变化（轮询模式）"""
        if not callable(callback):
            raise ValueError("callback must be callable")

        self.stop_monitoring()
        self._monitor_stop_event.clear()
        self._last_monitor_state = None

        poll_interval = max(1.0, float(interval))

        def _monitor_loop():
            logger.info(f"📡 启动SillyTavern状态监控，轮询间隔={poll_interval:.1f}s")
            while not self._monitor_stop_event.wait(poll_interval):
                try:
                    current_state = self._collect_monitor_state()
                    previous_state = self._last_monitor_state
                    state_changed = previous_state is None or self._has_monitor_state_changed(previous_state, current_state)
                    self._last_monitor_state = current_state

                    if state_changed:
                        event = {
                            "event": "state_changed",
                            "previous": previous_state,
                            "current": current_state,
                            "timestamp": datetime.now().isoformat(),
                        }
                        try:
                            callback(event)
                        except Exception as cb_error:
                            logger.warning(f"监控回调执行失败: {cb_error}")
                except Exception as monitor_error:
                    logger.warning(f"状态监控轮询失败: {monitor_error}")

            logger.info("🛑 SillyTavern状态监控已停止")

        self._monitor_thread = threading.Thread(
            target=_monitor_loop,
            name="SillyTavernMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop_monitoring(self):
        """停止状态监控线程"""
        self._monitor_stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        self._monitor_thread = None

    def _collect_monitor_state(self) -> Dict[str, Any]:
        connected = self._check_health()
        character_name = self._query_current_character_name()
        session_id, message_count = self._query_current_session_info()
        self.is_connected = connected
        return {
            "connected": connected,
            "character_name": character_name,
            "session_id": session_id,
            "message_count": message_count,
        }

    def _check_health(self) -> bool:
        for endpoint in ["/api/ping", "/health", "/api/version", "/"]:
            try:
                response = self.session.get(
                    f"{self.base_url}{endpoint}",
                    timeout=min(self.config.timeout, 5),
                )
                if response.status_code == 200:
                    return True
            except Exception:
                continue
        return False

    def _query_current_character_name(self) -> Optional[str]:
        endpoints = ["/api/characters/current", "/getcharacter", "/api/character", "/character"]
        for endpoint in endpoints:
            try:
                response = self.session.get(
                    f"{self.base_url}{endpoint}",
                    timeout=min(self.config.timeout, 5),
                )
                if response.status_code != 200:
                    continue
                data = response.json()
                if isinstance(data, dict):
                    name = data.get("name") or data.get("char_name") or data.get("character_name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
            except Exception:
                continue
        return None

    def _query_current_session_info(self) -> tuple[Optional[str], int]:
        endpoints = ["/api/chats/current", "/api/chat/current", "/api/chats"]
        for endpoint in endpoints:
            try:
                response = self.session.get(
                    f"{self.base_url}{endpoint}",
                    timeout=min(self.config.timeout, 5),
                )
                if response.status_code != 200:
                    continue
                data = response.json()

                if isinstance(data, dict):
                    session_id = data.get("id") or data.get("chat_id") or data.get("session_id")
                    messages = data.get("messages", [])
                    if isinstance(messages, list):
                        return str(session_id) if session_id else None, len(messages)
                    return str(session_id) if session_id else None, 0

                if isinstance(data, list):
                    # 某些端点直接返回消息数组
                    return None, len(data)
            except Exception:
                continue
        return None, 0

    @staticmethod
    def _has_monitor_state_changed(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        keys = ("connected", "character_name", "session_id", "message_count")
        return any(previous.get(k) != current.get(k) for k in keys)
    
    def notify_plugin_connection(self, session_id: str = None) -> bool:
        """通知SillyTavern插件EchoGraph已连接并提供会话ID"""
        try:
            logger.info("📢 尝试通知SillyTavern插件EchoGraph已连接...")
            # 尝试向插件发送连接通知，包含会话ID
            notify_endpoints = [
                "/api/plugins/EchoGraph/connect",
                "/api/extensions/EchoGraph/connect", 
                "/EchoGraph/connect"
            ]
            
            notification_data = {
                "status": "connected",
                "version": "1.0.0",
                "message": "EchoGraph已进入酒馆模式",
                "session_id": session_id,  # 关键：传递会话ID
                "api_base_url": "http://127.0.0.1:9543"
            }
            
            for endpoint in notify_endpoints:
                try:
                    logger.debug(f"尝试通知端点: {self.base_url}{endpoint}")
                    response = self.session.post(
                        f"{self.base_url}{endpoint}",
                        json=notification_data,
                        timeout=self.config.timeout
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"[OK] 成功通知插件连接并传递会话ID: {session_id}")
                        return True
                    else:
                        logger.debug(f"端点 {endpoint} 响应状态: {response.status_code}")
                except Exception as e:
                    logger.debug(f"端点 {endpoint} 通知失败: {e}")
                    continue
            
            logger.info("ℹ️ 无法找到插件通知端点（这是正常的，插件会通过其他方式发现连接）")
            return False
            
        except Exception as e:
            logger.warning(f"通知插件连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        self.stop_monitoring()
        self.is_connected = False
        self.current_character = None
        self.session.close()
        logger.info("🔌 已断开SillyTavern连接")


class TavernModeManager:
    """酒馆模式管理器 - 整合所有酒馆相关功能"""
    
    def __init__(self, EchoGraph_engine):
        self.engine = EchoGraph_engine
        self.connector: Optional[SillyTavernConnector] = None
        self.is_tavern_mode = False
        self.saved_session_data = None
        self._last_monitor_event: Optional[Dict[str, Any]] = None
        self._backup_graph_path = Path("data/backup_before_tavern.graphml")
        
    def enter_tavern_mode(
        self,
        tavern_config: TavernConfig,
        on_world_info_missing: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """进入酒馆模式"""
        try:
            logger.info("[READY] 正在切换到酒馆模式...")
            
            # 1. 保存当前会话和知识图谱
            self.save_current_session()
            
            # 2. 清空知识图谱
            self.engine.memory.knowledge_graph.clear()
            
            # 3. 连接酒馆
            self.connector = SillyTavernConnector(tavern_config)
            connection_result = self.connector.test_connection()
            
            if connection_result["status"] != "connected":
                self.restore_previous_session()
                return {
                    "success": False,
                    "error": "无法连接SillyTavern",
                    "details": connection_result
                }
            
            # 4. 获取角色信息
            character = self.connector.get_current_character()
            if not character:
                self.restore_previous_session()
                return {
                    "success": False,
                    "error": "无法获取角色信息，请确保在SillyTavern中选择了角色"
                }

            if not self._has_world_info(character.world_info):
                logger.warning("⚠️ 未获取到世界书文本。")
                should_continue = False
                if on_world_info_missing:
                    try:
                        should_continue = bool(on_world_info_missing())
                    except Exception as callback_error:
                        logger.warning(f"⚠️ 世界书确认回调执行失败: {callback_error}")
                        should_continue = False
                if not should_continue:
                    self.restore_previous_session()
                    return {
                        "success": False,
                        "error": "未获取到世界书文本，用户取消继续。"
                    }
                logger.info("ℹ️ 用户选择继续：世界书将按空文本处理。")
            
            # 5. 用LLM初始化知识图谱
            init_result = self.initialize_knowledge_graph_from_character(character)
            
            if init_result["success"]:
                session_id = init_result.get("session_id")
                
                # 6. 通知插件连接状态，并传递会话ID
                self.connector.notify_plugin_connection(session_id)
                self.connector.start_monitoring(self._handle_monitor_event)
                
                self.is_tavern_mode = True
                logger.info("[OK] 酒馆模式切换成功")
                return {
                    "success": True,
                    "character": character.name,
                    "session_id": session_id,  # 返回会话ID给UI
                    "nodes_created": init_result["nodes_created"],
                    "connection": connection_result
                }
            else:
                self.restore_previous_session()
                return init_result
                
        except Exception as e:
            logger.error(f"进入酒馆模式失败: {e}")
            self.restore_previous_session()
            return {
                "success": False,
                "error": f"切换失败: {e}"
            }

    def _handle_monitor_event(self, event: Dict[str, Any]):
        """处理连接器监控事件，记录连接/会话变化"""
        self._last_monitor_event = event
        current = event.get("current", {})
        previous = event.get("previous", {}) or {}
        logger.info(
            "📡 [TavernMonitor] 状态变化: "
            f"connected {previous.get('connected')} -> {current.get('connected')}, "
            f"character {previous.get('character_name')} -> {current.get('character_name')}, "
            f"session {previous.get('session_id')} -> {current.get('session_id')}, "
            f"messages {previous.get('message_count')} -> {current.get('message_count')}"
        )
    
    def save_current_session(self):
        """保存当前会话数据"""
        try:
            self.saved_session_data = {
                "timestamp": datetime.now().isoformat(),
                "graph_nodes": len(self.engine.memory.knowledge_graph.graph.nodes),
                "graph_edges": len(self.engine.memory.knowledge_graph.graph.edges),
                # 可以添加更多需要保存的数据
            }
            
            # 实际保存知识图谱到文件
            self._backup_graph_path.parent.mkdir(parents=True, exist_ok=True)
            self.engine.memory.knowledge_graph.save_graph(str(self._backup_graph_path))
            logger.info(f"💾 已保存当前会话: {self.saved_session_data['graph_nodes']} 节点, {self.saved_session_data['graph_edges']} 边")
            
        except Exception as e:
            logger.error(f"保存会话失败: {e}")

    def restore_previous_session(self) -> bool:
        """失败时自动恢复切换前的图谱。"""
        try:
            if not self._backup_graph_path.exists():
                logger.warning("⚠️ 未找到可恢复的备份图谱文件。")
                return False
            self.engine.memory.knowledge_graph.load_graph(str(self._backup_graph_path))
            self.engine.memory.sync_entities_to_json()
            logger.info("♻️ 已自动恢复切换前图谱。")
            return True
        except Exception as e:
            logger.error(f"恢复会话失败: {e}")
            return False

    @staticmethod
    def _has_world_info(world_info: List[Dict[str, Any]]) -> bool:
        """判断世界书是否包含可用文本。"""
        for entry in world_info or []:
            if isinstance(entry, dict) and str(entry.get("content", "")).strip():
                return True
        return False
    
    def initialize_knowledge_graph_from_character(self, character: CharacterInfo) -> Dict[str, Any]:
        """根据角色信息通过EchoGraph API初始化知识图谱"""
        logger.info("[AI] ========== 开始智能初始化知识图谱 ==========")
        try:
            logger.info(f"🎭 目标角色信息:")
            logger.info(f"  - 角色名称: {character.name}")
            logger.info(f"  - 描述长度: {len(character.description)} 字符")
            logger.info(f"  - 个性长度: {len(character.personality)} 字符") 
            logger.info(f"  - 场景长度: {len(character.scenario)} 字符")
            logger.info(f"  - 首条消息长度: {len(character.first_mes)} 字符")
            logger.info(f"  - 示例对话长度: {len(character.example_dialogue)} 字符")
            logger.info(f"  - 世界书条目数量: {len(character.world_info)}")
            
            # 首先检查是否已有该角色的活跃会话
            import requests
            api_base_url = "http://127.0.0.1:9543"
            
            # 1. 检查当前活跃的酒馆会话
            logger.info("[SEARCH] ========== 检查现有酒馆会话 ==========")
            try:
                logger.info(f"[SEARCH] 查询URL: {api_base_url}/tavern/current_session")
                current_session_response = requests.get(
                    f"{api_base_url}/tavern/current_session",
                    timeout=10
                )
                
                logger.info(f"📨 会话查询响应: {current_session_response.status_code}")
                
                if current_session_response.status_code == 200:
                    session_data = current_session_response.json()
                    logger.info(f"[CHART] 会话查询结果: {session_data}")
                    
                    if session_data.get("has_session"):
                        existing_session_id = session_data.get("session_id")
                        logger.info(f"[OK] 发现现有酒馆会话: {existing_session_id}")
                        
                        # 使用现有会话，返回其统计信息
                        stats_url = f"{api_base_url}/sessions/{existing_session_id}/stats"
                        logger.info(f"[CHART] 获取现有会话统计: {stats_url}")
                        
                        stats_response = requests.get(stats_url, timeout=10)
                        logger.info(f"📨 统计查询响应: {stats_response.status_code}")
                        
                        if stats_response.status_code == 200:
                            stats = stats_response.json()
                            logger.info(f"[CHART] 现有会话统计: {stats}")
                            logger.info("[SUCCESS] ========== 使用现有会话完成 ==========")
                            return {
                                "success": True,
                                "nodes_created": stats.get("graph_nodes", 0),
                                "session_id": existing_session_id,
                                "reused_existing": True
                            }
                        else:
                            logger.warning(f"[WARN] 获取现有会话统计失败: {stats_response.status_code}")
                    else:
                        logger.info("ℹ️ 没有找到现有的酒馆会话")
                else:
                    logger.warning(f"[WARN] 会话查询失败: {current_session_response.status_code}")
                    
            except Exception as e:
                logger.warning(f"[WARN] 检查现有会话失败，将创建新会话: {e}")
            
            # 2. 创建新的固定会话ID（基于角色名，不使用时间戳）
            logger.info("🆕 ========== 创建新会话 ==========")
            import hashlib
            character_hash = hashlib.md5(character.name.encode('utf-8')).hexdigest()[:8]
            session_id = f"tavern_{character.name}_{character_hash}"
            
            logger.info(f"🔑 会话ID生成:")
            logger.info(f"  - 角色名称: {character.name}")
            logger.info(f"  - 角色哈希: {character_hash}")
            logger.info(f"  - 会话ID: {session_id}")
            
            # 构建角色卡数据
            logger.info("📝 ========== 构建角色卡数据 ==========")
            character_card = {
                "name": character.name,
                "description": character.description,
                "personality": character.personality,
                "scenario": character.scenario,
                "first_mes": character.first_mes,
                "mes_example": character.example_dialogue,
                "tags": ["tavern_mode"]
            }
            
            logger.info(f"🎭 角色卡数据构建完成:")
            for key, value in character_card.items():
                if key != "tags":
                    logger.info(f"  - {key}: {len(str(value))} 字符")
                else:
                    logger.info(f"  - {key}: {value}")
            
            # 构建世界信息文本
            logger.info("🌍 ========== 构建世界书数据 ==========")
            world_info_text = ""
            for i, entry in enumerate(character.world_info):
                if isinstance(entry, dict):
                    keys = entry.get('keys', [])
                    content = entry.get('content', '')
                    if keys and content:
                        entry_text = f"[{', '.join(keys)}]: {content}"
                        world_info_text += entry_text + "\n\n"
                        logger.info(f"  - 条目{i+1}: [{', '.join(keys)}] ({len(content)} 字符)")
            
            if not world_info_text:
                logger.info("ℹ️ 没有世界书条目，按空文本继续初始化")
            
            logger.info(f"🌍 世界书构建完成: {len(world_info_text)} 字符")
            
            # 调用EchoGraph API进行异步初始化
            api_url = f"{api_base_url}/initialize_async"
            
            payload = {
                "session_id": session_id,  # 使用固定的会话ID
                "character_card": character_card,
                "world_info": world_info_text,
                "is_test": False,  # 酒馆模式不是测试模式
                "enable_agent": True,  # 图谱维护优先使用LLM Agent
                "session_config": {
                    "sliding_window": {
                        "window_size": 4,
                        "processing_delay": 1,
                        "enable_enhanced_agent": True,
                        "enable_conflict_resolution": True
                    },
                    "memory_enhancement": {
                        "hot_memory_turns": 5,
                        "enable_world_book_integration": True,
                        "enable_character_card_enhancement": True
                    }
                }
            }
            
            logger.info("[START] ========== 调用异步API初始化 ==========")
            logger.info(f"[LINK] API URL: {api_url}")
            logger.info(f"📦 请求数据大小:")
            logger.info(f"  - 角色卡字段数: {len(character_card)}")
            logger.info(f"  - 世界书长度: {len(world_info_text)}")
            logger.info(f"  - 配置项数: {len(payload)}")
            
            # 第一步：启动异步初始化任务
            response = requests.post(
                api_url,
                json=payload,
                timeout=10,  # 异步启动只需要短超时
                headers={'Content-Type': 'application/json'}
            )
            
            logger.info(f"📨 异步任务启动响应: {response.status_code}")
            
            if response.status_code != 200:
                error_text = response.text
                logger.error("❌ ========== 异步任务启动失败 ==========")
                logger.error(f"📨 响应状态: {response.status_code}")
                logger.error(f"[LOG] 错误详情: {error_text}")
                return {
                    "success": False,
                    "error": f"启动异步初始化失败: HTTP {response.status_code} - {error_text}"
                }
            
            # 获取任务ID
            async_result = response.json()
            task_id = async_result.get("task_id")
            
            logger.info(f"[OK] 异步任务已启动，任务ID: {task_id}")
            logger.info(f"⏱️ 预计耗时: {async_result.get('estimated_time', '未知')}")
            
            # 第二步：轮询任务状态直到完成
            import time
            max_wait_time = 120  # 最大等待2分钟
            poll_interval = 2  # 每2秒轮询一次
            start_time = time.time()
            
            status_url = f"{api_base_url}/initialize_status/{task_id}"
            logger.info(f"[SEARCH] 开始轮询任务状态: {status_url}")
            
            while time.time() - start_time < max_wait_time:
                try:
                    status_response = requests.get(status_url, timeout=10)
                    
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        task_status = status_data.get("status")
                        progress = status_data.get("progress", 0.0)
                        message = status_data.get("message", "")
                        
                        logger.info(f"[CHART] 任务进度: {progress*100:.1f}% - {message}")
                        
                        if task_status == "completed":
                            # 任务完成
                            result = status_data.get("result", {})
                            nodes_created = result.get("graph_stats", {}).get("nodes_updated", 0)
                            
                            logger.info("[SUCCESS] ========== 异步初始化成功 ==========")
                            logger.info(f"[CHART] 初始化结果:")
                            logger.info(f"  - 节点数量: {nodes_created}")
                            logger.info(f"  - 会话ID: {result.get('session_id')}")
                            logger.info(f"  - 总耗时: {time.time() - start_time:.1f}秒")
                            
                            return {
                                "success": True,
                                "nodes_created": nodes_created,
                                "session_id": result.get("session_id"),
                                "api_response": result,
                                "async_task_id": task_id
                            }
                        
                        elif task_status == "failed":
                            # 任务失败
                            error_message = status_data.get("error", "未知错误")
                            logger.error("❌ ========== 异步初始化失败 ==========")
                            logger.error(f"[LOG] 错误详情: {error_message}")
                            return {
                                "success": False,
                                "error": f"异步初始化失败: {error_message}",
                                "async_task_id": task_id
                            }
                        
                        # 任务还在运行中，继续等待
                        time.sleep(poll_interval)
                    
                    else:
                        logger.warning(f"[WARN] 状态查询失败: {status_response.status_code}")
                        time.sleep(poll_interval)
                        
                except Exception as poll_error:
                    logger.warning(f"[WARN] 轮询状态异常: {poll_error}")
                    time.sleep(poll_interval)
            
            # 超时处理
            logger.error("❌ ========== 异步初始化超时 ==========")
            logger.error(f"[LOG] 超时时间: {max_wait_time}秒")
            return {
                "success": False,
                "error": f"异步初始化超时（超过{max_wait_time}秒），任务可能仍在后台运行",
                "async_task_id": task_id
            }
            
        except requests.exceptions.ConnectionError as e:
            logger.error("❌ ========== API连接失败 ==========")
            logger.error(f"[LOG] 连接错误: {e}")
            return {
                "success": False,
                "error": "无法连接到EchoGraph API服务器，请确保服务器正在运行"
            }
        except requests.exceptions.Timeout as e:
            logger.error("❌ ========== API调用超时 ==========")
            logger.error(f"[LOG] 超时错误: {e}")
            return {
                "success": False,
                "error": "API调用超时，初始化过程可能需要更长时间"
            }
        except Exception as e:
            logger.error("❌ ========== 初始化异常 ==========")
            logger.error(f"[LOG] 异常详情: {e}")
            import traceback
            logger.error(f"[LOG] 完整堆栈: {traceback.format_exc()}")
            return {
                "success": False,
                "error": f"初始化异常: {e}"
            }
    
    def exit_tavern_mode(self) -> Dict[str, Any]:
        """退出酒馆模式"""
        try:
            if self.connector:
                self.connector.disconnect()
                self.connector = None
            
            # 可选：恢复之前的会话
            # self.restore_previous_session()
            
            self.is_tavern_mode = False
            logger.info("🏠 已退出酒馆模式")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"退出酒馆模式失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """获取酒馆模式状态"""
        return {
            "is_tavern_mode": self.is_tavern_mode,
            "is_connected": self.connector.is_connected if self.connector else False,
            "current_character": self.connector.current_character.name if self.connector and self.connector.current_character else None,
            "tavern_url": self.connector.base_url if self.connector else None
        }
