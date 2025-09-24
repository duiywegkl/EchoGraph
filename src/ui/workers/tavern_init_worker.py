"""
酒馆初始化工作线程
从原始run_ui.bak移植的TavernInitWorker实现 - 完整功能版本
"""
import json
import time
import asyncio
import websockets
import os
from typing import Dict, Any, Optional
from PySide6.QtCore import QThread, Signal
from loguru import logger
import requests


class TavernInitWorker(QThread):
    """酒馆模式初始化工作线程

    负责连接到API服务器并建立WebSocket连接
    从原始run_ui.bak完整移植，保持原有逻辑
    """

    # 信号定义
    connection_status_changed = Signal(bool, str)  # 连接状态, 状态消息
    session_id_received = Signal(str)  # 收到会话ID
    initialization_completed = Signal(dict)  # 初始化完成
    websocket_message_received = Signal(dict)  # WebSocket消息
    error_occurred = Signal(str)  # 错误发生

    def __init__(self, api_base_url: str):
        super().__init__()
        self.api_base_url = api_base_url
        self.websocket_url = ""
        self.session_id = ""
        self.should_stop = False
        self.websocket = None

    def run(self):
        """主线程执行方法 - 完整的酒馆初始化流程"""
        try:
            logger.info("🧵 开始后台酒馆初始化线程...")

            # 步骤1: 连接测试
            self.connection_status_changed.emit(True, "🔍 测试SillyTavern连接...")

            if not self._check_api_connection():
                self.error_occurred.emit("无法连接到API服务器")
                return

            # 步骤2: 等待插件提供角色信息
            self.connection_status_changed.emit(True, "🎭 等待插件提供角色信息...")

            character_data = self._wait_for_character_from_plugin()
            if not character_data:
                self.error_occurred.emit("插件未能获取到角色信息，请确保：\n1. 已在SillyTavern中选择了角色\n2. EchoGraph插件正常运行\n3. 刷新页面后重试\n\n⚠️ 如果持续无法获取角色信息，将自动切换回本地测试模式")
                return

            # 步骤3: 检查现有会话
            self.connection_status_changed.emit(True, f"🔍 检查现有会话...")

            existing_session = self._check_existing_session(character_data.get('name'))
            if existing_session:
                # 使用现有会话（与当前角色匹配）
                session_id = existing_session["session_id"]
                nodes_count = existing_session.get("graph_nodes", 0)

                self.connection_status_changed.emit(True, f"✅ 发现现有会话")
                logger.info(f"会话ID: {session_id[:8]}... 节点数: {nodes_count}")

                # 通知插件连接状态
                self._notify_plugin_connection(session_id)

                result = {
                    "character": character_data['name'],
                    "session_id": session_id,
                    "nodes_created": nodes_count,
                    "reused_existing": True
                }

                self.session_id = session_id
                self.session_id_received.emit(self.session_id)

                # 建立WebSocket连接
                self._establish_websocket_connection()
                self.initialization_completed.emit(result)
                return

            # 步骤4: 启动异步初始化
            self.connection_status_changed.emit(True, "🚀 启动异步初始化...")

            task_id = self._start_async_initialization_with_character_data(character_data)
            if not task_id:
                return  # 错误已在方法中处理

            # 步骤5: 实时轮询任务进度
            self._poll_initialization_progress(task_id, character_data)

        except Exception as e:
            logger.error(f"❌ 酒馆初始化线程异常: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            self.error_occurred.emit(f"初始化过程发生异常: {str(e)}")

    def _check_api_connection(self) -> bool:
        """检查API服务器连接"""
        try:
            response = requests.get(f"{self.api_base_url}/system/liveness", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[TavernWorker] API连接检查失败: {e}")
            return False

    def _get_current_tavern_session(self) -> Optional[Dict[str, Any]]:
        """获取当前酒馆会话"""
        try:
            response = requests.get(f"{self.api_base_url}/tavern/current_session", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("has_session"):
                    return data
                else:
                    logger.warning("[TavernWorker] 当前没有活跃的酒馆会话")
                    return None
            else:
                logger.error(f"[TavernWorker] 获取会话失败: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"[TavernWorker] 获取酒馆会话失败: {e}")
            return None

    async def _run_websocket(self):
        """运行WebSocket连接"""
        try:
            async with websockets.connect(self.websocket_url) as websocket:
                self.websocket = websocket
                self.connection_status_changed.emit(True, "✅ WebSocket连接已建立")
                self.initialization_completed.emit({"session_id": self.session_id})

                # 发送当前会话查询
                await self._send_websocket_message({
                    "action": "tavern.current_session",
                    "request_id": f"session_query_{int(time.time())}"
                })

                # 监听消息
                while not self.should_stop:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        self.websocket_message_received.emit(data)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logger.error(f"[TavernWorker] WebSocket消息处理错误: {e}")
                        break

        except Exception as e:
            logger.error(f"[TavernWorker] WebSocket连接失败: {e}")
            self.error_occurred.emit(f"WebSocket连接失败: {str(e)}")

    async def _send_websocket_message(self, message: dict):
        """发送WebSocket消息"""
        try:
            if self.websocket:
                await self.websocket.send(json.dumps(message))
                logger.debug(f"[TavernWorker] 发送WebSocket消息: {message.get('action')}")
        except Exception as e:
            logger.error(f"[TavernWorker] 发送WebSocket消息失败: {e}")

    def _wait_for_character_from_plugin(self, timeout=10):
        """等待插件提供角色信息"""
        import os

        logger.info("⏳ 等待插件提供角色信息...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # 检查后台是否已收到插件提交的角色数据
                available_chars_url = f"{self.api_base_url}/tavern/available_characters"

                api_timeout = int(os.getenv("API_TIMEOUT", "15"))
                response = requests.get(available_chars_url, timeout=api_timeout)

                if response.status_code == 200:
                    characters_data = response.json()
                    characters = characters_data.get('characters', [])

                    logger.info(f"🔍 检查插件提交的角色数据: 找到 {len(characters)} 个角色")

                    if characters:
                        # 选择最新提交的角色（按时间排序，第一个是最新的）
                        latest_character = characters[0]
                        character_id = latest_character['character_id']
                        character_name = latest_character['character_name']

                        logger.info(f"✅ 找到最新角色: {character_name} (ID: {character_id})")

                        # 获取完整的角色数据
                        char_data_url = f"{self.api_base_url}/tavern/get_character/{character_id}"
                        char_response = requests.get(char_data_url, timeout=api_timeout)

                        if char_response.status_code == 200:
                            character_info = char_response.json()
                            character_data = character_info.get('character_data', {})

                            logger.info(f"✅ 成功获取角色完整数据: {character_name}")
                            logger.info(f"  - 描述长度: {len(character_data.get('description', ''))}")
                            logger.info(f"  - 个性长度: {len(character_data.get('personality', ''))}")
                            logger.info(f"  - 场景长度: {len(character_data.get('scenario', ''))}")

                            # 返回格式化的角色数据
                            return {
                                'name': character_data.get('name', character_name),
                                'description': character_data.get('description', ''),
                                'personality': character_data.get('personality', ''),
                                'scenario': character_data.get('scenario', ''),
                                'first_mes': character_data.get('first_mes', ''),
                                'example_dialogue': character_data.get('mes_example', ''),
                                'world_info': [],  # 世界书信息暂时为空，后续可扩展
                                'character_id': character_id,
                                'source': 'plugin_submission'
                            }
                        else:
                            logger.warning(f"⚠️ 无法获取角色详细数据: HTTP {char_response.status_code}")
                    else:
                        logger.debug("🔄 插件尚未提交角色数据，继续等待...")
                else:
                    logger.debug(f"🔄 检查角色数据失败: HTTP {response.status_code}，继续等待...")

            except Exception as e:
                logger.debug(f"检查插件角色信息时异常: {e}")

            time.sleep(1)

        logger.warning("⏰ 等待插件角色信息超时")
        return None

    def _check_existing_session(self, character_name: str = None):
        """检查是否有现有的酒馆会话
        优先按角色名推导的会话ID精确查询，避免误用上一次的会话。
        """
        try:
            import hashlib
            import os

            # 如果提供了角色名，则根据一致规则生成会话ID并精确查询
            if character_name and character_name.strip():
                character_hash = hashlib.md5(character_name.encode('utf-8')).hexdigest()[:8]
                session_id = f"tavern_{character_name}_{character_hash}"
                try:
                    health_timeout = int(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))
                    stats_resp = requests.get(f"{self.api_base_url}/sessions/{session_id}/stats", timeout=health_timeout)
                    if stats_resp.status_code == 200:
                        stats = stats_resp.json() if hasattr(stats_resp, 'json') else {}
                        return {
                            "has_session": True,
                            "session_id": session_id,
                            "graph_nodes": stats.get("graph_nodes", 0),
                            "graph_edges": stats.get("graph_edges", 0)
                        }
                except Exception:
                    pass  # 精确查询失败则回退到全局最新会话

            # 回退：查询最新的酒馆会话（可能与当前角色不一致，谨慎使用）
            health_timeout = int(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))
            response = requests.get(f"{self.api_base_url}/tavern/current_session", timeout=health_timeout)
            if response.status_code == 200:
                session_data = response.json()
                if session_data.get("has_session"):
                    return session_data

            return None
        except Exception as e:
            logger.warning(f"检查现有会话失败: {e}")
            return None

    def _start_async_initialization_with_character_data(self, character_data) -> str:
        """基于插件提交的角色数据启动异步初始化任务，返回task_id"""
        logger.info("🚀 ========== 基于插件角色数据启动异步初始化任务 ==========")
        try:
            import hashlib

            # 从插件角色数据生成一致的会话ID
            character_name = character_data['name']
            character_hash = hashlib.md5(character_name.encode('utf-8')).hexdigest()[:8]
            session_id = f"tavern_{character_name}_{character_hash}"

            logger.info(f"📝 会话信息:")
            logger.info(f"  - 角色名称: {character_name}")
            logger.info(f"  - 角色哈希: {character_hash}")
            logger.info(f"  - 会话ID: {session_id}")
            logger.info(f"  - 数据来源: {character_data.get('source', 'unknown')}")

            # 构建角色卡数据
            character_card = {
                "name": character_data['name'],
                "description": character_data.get('description', ''),
                "personality": character_data.get('personality', ''),
                "scenario": character_data.get('scenario', ''),
                "first_mes": character_data.get('first_mes', ''),
                "mes_example": character_data.get('example_dialogue', ''),
                "tags": ["tavern_mode", "plugin_submitted"]
            }

            # 构建世界书数据（暂时为空，后续可扩展）
            world_info_text = ""

            # 构建API请求负载
            payload = {
                "session_id": session_id,
                "character_card": character_card,
                "world_info": world_info_text,
                "is_test": False,
                "enable_agent": False,  # 暂时禁用Agent避免LLM超时阻塞
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
            logger.info(f"[LINK] API URL: {self.api_base_url}/initialize_async")
            logger.info(f"📦 请求数据大小:")
            logger.info(f"  - 角色卡字段数: {len(character_card)}")
            logger.info(f"  - 世界书长度: {len(world_info_text)}")
            logger.info(f"  - 配置项数: {len(payload)}")

            # 第一步：启动异步初始化任务
            response = requests.post(
                f"{self.api_base_url}/initialize_async",
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
                self.error_occurred.emit(f"启动异步初始化失败: HTTP {response.status_code} - {error_text}")
                return None

            # 获取任务ID
            async_result = response.json()
            task_id = async_result.get("task_id")

            logger.info(f"[OK] 异步任务已启动，任务ID: {task_id}")
            logger.info(f"⏱️ 预计耗时: {async_result.get('estimated_time', '未知')}")

            # 保存会话ID供后续使用
            self.session_id = session_id
            self.session_id_received.emit(self.session_id)

            return task_id

        except Exception as e:
            logger.error(f"❌ 启动异步初始化异常: {e}")
            import traceback
            logger.error(f"❌ 完整堆栈: {traceback.format_exc()}")
            self.error_occurred.emit(f"启动异步初始化异常: {str(e)}")
            return None

    def _poll_initialization_progress(self, task_id: str, character_data: dict):
        """轮询任务状态直到完成"""
        max_wait_time = 120  # 最大等待2分钟
        poll_interval = 2  # 每2秒轮询一次
        start_time = time.time()

        status_url = f"{self.api_base_url}/initialize_status/{task_id}"
        logger.info(f"[SEARCH] 开始轮询任务状态: {status_url}")

        while time.time() - start_time < max_wait_time:
            if self.should_stop:
                logger.info("收到停止信号，中断轮询")
                return

            try:
                status_response = requests.get(status_url, timeout=10)

                if status_response.status_code == 200:
                    status_data = status_response.json()
                    task_status = status_data.get("status")
                    progress = status_data.get("progress", 0)
                    message = status_data.get("message", "")

                    logger.info(f"[POLL] 任务状态: {task_status}, 进度: {progress:.1%}, 消息: {message}")

                    # 更新进度显示
                    self.connection_status_changed.emit(True, f"初始化进度: {progress:.1%} - {message}")

                    if task_status == "completed":
                        # 任务完成
                        result = status_data.get("result", {})
                        nodes_created = result.get("nodes_added", 0)
                        edges_created = result.get("edges_added", 0)

                        logger.info(f"[OK] ========== 异步初始化任务完成 ==========")
                        logger.info(f"✅ 创建节点: {nodes_created}")
                        logger.info(f"✅ 创建关系: {edges_created}")

                        # 通知插件连接状态
                        self._notify_plugin_connection(self.session_id)

                        # 建立WebSocket连接
                        self._establish_websocket_connection()

                        # 发送完成信号
                        completion_result = {
                            "character": character_data['name'],
                            "session_id": self.session_id,
                            "nodes_created": nodes_created,
                            "edges_created": edges_created,
                            "reused_existing": False
                        }
                        self.initialization_completed.emit(completion_result)
                        return

                    elif task_status == "failed":
                        # 任务失败
                        error_msg = status_data.get("error", "未知错误")
                        logger.error(f"❌ 异步初始化任务失败: {error_msg}")
                        self.error_occurred.emit(f"初始化失败: {error_msg}")
                        return

                    elif task_status in ["pending", "running"]:
                        # 任务进行中，继续轮询
                        pass
                    else:
                        logger.warning(f"⚠️ 未知任务状态: {task_status}")

                else:
                    logger.warning(f"⚠️ 轮询状态失败: HTTP {status_response.status_code}")

            except Exception as e:
                logger.warning(f"轮询任务状态时异常: {e}")

            time.sleep(poll_interval)

        # 超时
        logger.error("❌ 初始化任务轮询超时")
        self.error_occurred.emit("初始化超时，请检查网络连接和服务器状态")

    def _notify_plugin_connection(self, session_id: str):
        """通知插件连接状态"""
        try:
            # 尝试多个可能的插件通知端点
            notify_endpoints = [
                "/api/plugins/echograph/notify_connection",
                "/api/plugins/echograph/connection_status",
                "/plugins/echograph/notify"
            ]

            notification_data = {
                "status": "connected",
                "session_id": session_id,
                "timestamp": time.time()
            }

            for endpoint in notify_endpoints:
                try:
                    logger.debug(f"尝试通知端点: {self.api_base_url}{endpoint}")
                    response = requests.post(
                        f"{self.api_base_url}{endpoint}",
                        json=notification_data,
                        timeout=5
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

    def _establish_websocket_connection(self):
        """建立WebSocket连接"""
        try:
            self.websocket_url = f"ws://127.0.0.1:9543/ws/tavern/{self.session_id}"
            self.connection_status_changed.emit(True, "正在建立WebSocket连接...")

            # 运行WebSocket连接
            asyncio.run(self._run_websocket())

        except Exception as e:
            logger.error(f"建立WebSocket连接失败: {e}")
            self.error_occurred.emit(f"WebSocket连接失败: {str(e)}")

    def stop(self):
        """停止工作线程"""
        self.should_stop = True
        if self.websocket:
            asyncio.create_task(self.websocket.close())
        self.quit()
        self.wait()