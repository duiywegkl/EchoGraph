"""
ChronoForge 主UI程序
智能角色扮演助手 - 集成对话系统和关系图谱
"""
import sys
import os
import time
import traceback
import subprocess
import json
import requests
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QPushButton, QCheckBox, QTabWidget,
    QMessageBox, QSplitter, QListWidget, QListWidgetItem, QLabel, QTextEdit,
    QGroupBox, QComboBox, QInputDialog, QStyle, QDialog, QFileDialog,
    QRadioButton, QButtonGroup, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QObject, Signal as pyqtSignal, QUrl, Slot, QTimer, QPropertyAnimation, QRect, QThread
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtGui import QIcon, QFont, QColor, QIntValidator, QTextCursor, QPainter, QPen, QBrush
from dotenv import dotenv_values, set_key
from loguru import logger

# 添加酒馆初始化工作线程类
class TavernInitWorker(QThread):
    """酒馆模式初始化工作线程"""

    # 定义信号
    progress_updated = pyqtSignal(str, str)  # (status_message, step_info)
    initialization_completed = pyqtSignal(dict)  # (result_data)
    error_occurred = pyqtSignal(str)  # (error_message)

    def __init__(self, tavern_manager, tavern_config):
        super().__init__()
        self.tavern_manager = tavern_manager
        self.tavern_config = tavern_config

    def run(self):
        """在后台线程中执行酒馆初始化"""
        try:
            logger.info("🧵 开始后台酒馆初始化线程...")

            # 步骤1: 连接测试
            self.progress_updated.emit("🔍 测试SillyTavern连接...", "检查连接可用性")

            # 测试连接
            connector = SillyTavernConnector(self.tavern_config)
            connection_result = connector.test_connection()

            if connection_result["status"] != "connected":
                self.error_occurred.emit(f"无法连接SillyTavern: {connection_result.get('error', '连接失败')}")
                return

            # 步骤2: 不再依赖后台API获取角色，而是等待插件提供角色信息
            self.progress_updated.emit("🎭 等待插件提供角色信息...", "插件会自动检测当前选中的角色")

            # 检查插件是否已经提供角色信息
            character_data = self._wait_for_character_from_plugin()
            if not character_data:
                self.error_occurred.emit("插件未能获取到角色信息，请确保：\n1. 已在SillyTavern中选择了角色\n2. ChronoForge插件正常运行\n3. 刷新页面后重试\n\n⚠️ 如果持续无法获取角色信息，将自动切换回本地测试模式")
                return

            # 步骤3: 检查现有会话
            self.progress_updated.emit("🔍 检查现有会话...", f"查找角色 {character_data['name']} 的现有会话")

            existing_session = self._check_existing_session(character_data.get('name'))
            if existing_session:
                # 使用现有会话（与当前角色匹配）
                session_id = existing_session["session_id"]
                nodes_count = existing_session.get("graph_nodes", 0)

                self.progress_updated.emit("✅ 发现现有会话", f"会话ID: {session_id[:8]}... 节点数: {nodes_count}")

                # 通知插件连接状态
                connector.notify_plugin_connection(session_id)

                result = {
                    "character": character_data['name'],
                    "session_id": session_id,
                    "nodes_created": nodes_count,
                    "connection": connection_result,
                    "reused_existing": True
                }

                self.initialization_completed.emit(result)
                return

            # 步骤4: 启动异步初始化
            self.progress_updated.emit("🚀 启动异步初始化...", "准备创建新的知识图谱会话")

            task_id = self._start_async_initialization_with_character_data(character_data)
            if not task_id:
                return  # 错误已在方法中处理

            # 步骤5: 实时轮询任务进度
            self._poll_initialization_progress(task_id, character_data, connector, connection_result)

        except Exception as e:
            logger.error(f"❌ 酒馆初始化线程异常: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            self.error_occurred.emit(f"初始化过程发生异常: {str(e)}")

    def _wait_for_character_from_plugin(self, timeout=10):
        """等待插件提供角色信息"""
        import time
        import requests

        logger.info("⏳ 等待插件提供角色信息...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # 检查后台是否已收到插件提交的角色数据
                api_base_url = "http://127.0.0.1:9543"
                available_chars_url = f"{api_base_url}/tavern/available_characters"

                response = requests.get(available_chars_url, timeout=3)

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
                        char_data_url = f"{api_base_url}/tavern/get_character/{character_id}"
                        char_response = requests.get(char_data_url, timeout=3)

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
            import requests
            import hashlib
            api_base_url = "http://127.0.0.1:9543"

            # 如果提供了角色名，则根据一致规则生成会话ID并精确查询
            if character_name and character_name.strip():
                character_hash = hashlib.md5(character_name.encode('utf-8')).hexdigest()[:8]
                session_id = f"tavern_{character_name}_{character_hash}"
                try:
                    stats_resp = requests.get(f"{api_base_url}/sessions/{session_id}/stats", timeout=10)
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
            response = requests.get(f"{api_base_url}/tavern/current_session", timeout=10)
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
            import requests
            import hashlib
            import time

            api_base_url = "http://127.0.0.1:9543"

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

            # 构建世界信息（暂时简化，后续可从插件数据扩展）
            world_info_text = f"这是{character_name}的世界设定。"
            world_info_entries = character_data.get('world_info', [])

            if world_info_entries:
                for entry in world_info_entries:
                    if isinstance(entry, dict):
                        keys = entry.get('keys', [])
                        content = entry.get('content', '')
                        if keys and content:
                            world_info_text += f"[{', '.join(keys)}]: {content}\n\n"

            logger.info(f"📦 插件角色数据统计:")
            logger.info(f"  - 角色卡字段数: {len(character_card)}")
            logger.info(f"  - 角色描述长度: {len(character_card['description'])} 字符")
            logger.info(f"  - 角色个性长度: {len(character_card['personality'])} 字符")
            logger.info(f"  - 角色场景长度: {len(character_card['scenario'])} 字符")
            logger.info(f"  - 世界书长度: {len(world_info_text)} 字符")
            logger.info(f"  - 世界书条目数: {len(world_info_entries)}")

            payload = {
                "session_id": session_id,
                "character_card": character_card,
                "world_info": world_info_text,
                "is_test": False,
                "enable_agent": False,  # 禁用Agent避免超时
                "session_config": {
                    "sliding_window": {
                        "window_size": 4,
                        "processing_delay": 1,
                        "enable_enhanced_agent": True,
                        "enable_conflict_resolution": True
                    }
                }
            }

            # 先测试API服务器健康状态
            logger.info("🔍 测试API服务器健康状态...")
            try:
                health_url = f"{api_base_url}/health"
                logger.info(f"📡 健康检查URL: {health_url}")

                health_response = requests.get(health_url, timeout=10)
                logger.info(f"📨 健康检查响应:")
                logger.info(f"  - HTTP状态: {health_response.status_code}")
                logger.info(f"  - 响应时间: {health_response.elapsed.total_seconds():.2f}秒")

                if health_response.status_code == 200:
                    health_data = health_response.json()
                    logger.info(f"✅ API服务器健康:")
                    logger.info(f"  - 版本: {health_data.get('version', 'Unknown')}")
                    logger.info(f"  - 活跃会话: {health_data.get('active_sessions', 0)}")
                    logger.info(f"  - 已注册角色: {health_data.get('total_characters', 0)}")
                else:
                    logger.warning(f"⚠️ API服务器健康检查异常: {health_response.status_code}")

            except Exception as health_error:
                logger.error(f"❌ API服务器健康检查失败: {health_error}")
                self.error_occurred.emit(f"API服务器不可用: {health_error}")
                return None

            # 发送异步初始化请求
            async_url = f"{api_base_url}/initialize_async"
            logger.info(f"🚀 发送异步初始化请求:")
            logger.info(f"  - URL: {async_url}")
            logger.info(f"  - 超时设置: 15秒")
            logger.info(f"  - 请求大小: {len(str(payload))} 字符")

            start_time = time.time()
            response = requests.post(
                async_url,
                json=payload,
                timeout=15,
                headers={'Content-Type': 'application/json'}
            )
            request_time = time.time() - start_time

            logger.info(f"📨 异步初始化响应:")
            logger.info(f"  - HTTP状态: {response.status_code}")
            logger.info(f"  - 请求耗时: {request_time:.2f}秒")
            logger.info(f"  - 响应大小: {len(response.content)} 字节")
            logger.info(f"  - 响应头: {dict(response.headers)}")

            if response.status_code == 200:
                async_result = response.json()
                task_id = async_result.get("task_id")
                estimated_time = async_result.get("estimated_time", "30-60秒")

                logger.info(f"✅ 异步任务启动成功:")
                logger.info(f"  - 任务ID: {task_id}")
                logger.info(f"  - 预计耗时: {estimated_time}")
                logger.info(f"  - 完整响应: {async_result}")

                self.progress_updated.emit(
                    f"✅ 初始化任务已启动",
                    f"任务ID: {task_id[:8]}... 预计耗时: {estimated_time}"
                )

                return task_id
            else:
                error_text = response.text
                logger.error(f"❌ 异步初始化请求失败:")
                logger.error(f"  - HTTP状态: {response.status_code}")
                logger.error(f"  - 错误内容: {error_text}")
                logger.error(f"  - 响应头: {dict(response.headers)}")

                self.error_occurred.emit(f"启动异步初始化失败: HTTP {response.status_code} - {error_text}")
                return None

        except requests.exceptions.Timeout as e:
            logger.error("❌ ========== 异步初始化请求超时 ==========")
            logger.error(f"❌ 超时详情: {e}")
            logger.error("❌ 可能原因:")
            logger.error("   1. API服务器响应慢")
            logger.error("   2. LLM配置问题（检查.env文件）")
            logger.error("   3. 网络连接问题")
            logger.error("   4. 服务器资源不足")
            self.error_occurred.emit(f"启动异步初始化超时: 请求超过15秒，请检查API服务器状态")
            return None

        except requests.exceptions.ConnectionError as e:
            logger.error("❌ ========== API连接失败 ==========")
            logger.error(f"❌ 连接错误: {e}")
            logger.error("❌ 请检查:")
            logger.error("   1. ChronoForge API服务器是否在运行")
            logger.error("   2. 端口9543是否被占用")
            logger.error("   3. 防火墙设置")
            self.error_occurred.emit(f"API连接失败: {e}")
            return None

        except Exception as e:
            logger.error("❌ ========== 启动异步初始化异常 ==========")
            logger.error(f"❌ 异常详情: {e}")
            import traceback
            logger.error(f"❌ 完整堆栈: {traceback.format_exc()}")
            self.error_occurred.emit(f"启动异步初始化异常: {str(e)}")
            return None

    def _start_async_initialization(self, character) -> str:
        """启动异步初始化任务，返回task_id"""
        logger.info("🚀 ========== 启动异步初始化任务 ==========")
        try:
            import requests
            import hashlib
            import time

            api_base_url = "http://127.0.0.1:9543"

            # 生成一致的会话ID
            character_hash = hashlib.md5(character.name.encode('utf-8')).hexdigest()[:8]
            session_id = f"tavern_{character.name}_{character_hash}"

            logger.info(f"📝 会话信息:")
            logger.info(f"  - 角色名称: {character.name}")
            logger.info(f"  - 角色哈希: {character_hash}")
            logger.info(f"  - 会话ID: {session_id}")

            # 构建请求数据
            character_card = {
                "name": character.name,
                "description": character.description,
                "personality": character.personality,
                "scenario": character.scenario,
                "first_mes": character.first_mes,
                "mes_example": character.example_dialogue,
                "tags": ["tavern_mode"]
            }

            # 构建世界信息
            world_info_text = ""
            for entry in character.world_info:
                if isinstance(entry, dict):
                    keys = entry.get('keys', [])
                    content = entry.get('content', '')
                    if keys and content:
                        world_info_text += f"[{', '.join(keys)}]: {content}\n\n"

            if not world_info_text:
                world_info_text = f"这是{character.name}的世界设定。"

            logger.info(f"📦 请求数据统计:")
            logger.info(f"  - 角色卡字段数: {len(character_card)}")
            logger.info(f"  - 世界书长度: {len(world_info_text)} 字符")
            logger.info(f"  - 世界书条目数: {len(character.world_info)}")

            payload = {
                "session_id": session_id,
                "character_card": character_card,
                "world_info": world_info_text,
                "is_test": False,
                "enable_agent": False,  # 禁用Agent避免超时
                "session_config": {
                    "sliding_window": {
                        "window_size": 4,
                        "processing_delay": 1,
                        "enable_enhanced_agent": True,
                        "enable_conflict_resolution": True
                    }
                }
            }

            # 先测试API服务器健康状态
            logger.info("🔍 测试API服务器健康状态...")
            try:
                health_url = f"{api_base_url}/health"
                logger.info(f"📡 健康检查URL: {health_url}")

                health_response = requests.get(health_url, timeout=10)
                logger.info(f"📨 健康检查响应:")
                logger.info(f"  - HTTP状态: {health_response.status_code}")
                logger.info(f"  - 响应时间: {health_response.elapsed.total_seconds():.2f}秒")

                if health_response.status_code == 200:
                    health_data = health_response.json()
                    logger.info(f"✅ API服务器健康:")
                    logger.info(f"  - 版本: {health_data.get('version', 'Unknown')}")
                    logger.info(f"  - 活跃会话: {health_data.get('active_sessions', 0)}")
                    logger.info(f"  - 已注册角色: {health_data.get('total_characters', 0)}")
                else:
                    logger.warning(f"⚠️ API服务器健康检查异常: {health_response.status_code}")

            except Exception as health_error:
                logger.error(f"❌ API服务器健康检查失败: {health_error}")
                self.error_occurred.emit(f"API服务器不可用: {health_error}")
                return None

            # 发送异步初始化请求
            async_url = f"{api_base_url}/initialize_async"
            logger.info(f"🚀 发送异步初始化请求:")
            logger.info(f"  - URL: {async_url}")
            logger.info(f"  - 超时设置: 15秒")
            logger.info(f"  - 请求大小: {len(str(payload))} 字符")

            start_time = time.time()
            response = requests.post(
                async_url,
                json=payload,
                timeout=15,  # 增加到15秒
                headers={'Content-Type': 'application/json'}
            )
            request_time = time.time() - start_time

            logger.info(f"📨 异步初始化响应:")
            logger.info(f"  - HTTP状态: {response.status_code}")
            logger.info(f"  - 请求耗时: {request_time:.2f}秒")
            logger.info(f"  - 响应大小: {len(response.content)} 字节")
            logger.info(f"  - 响应头: {dict(response.headers)}")

            if response.status_code == 200:
                async_result = response.json()
                task_id = async_result.get("task_id")
                estimated_time = async_result.get("estimated_time", "30-60秒")

                logger.info(f"✅ 异步任务启动成功:")
                logger.info(f"  - 任务ID: {task_id}")
                logger.info(f"  - 预计耗时: {estimated_time}")
                logger.info(f"  - 完整响应: {async_result}")

                self.progress_updated.emit(
                    f"✅ 初始化任务已启动",
                    f"任务ID: {task_id[:8]}... 预计耗时: {estimated_time}"
                )

                return task_id
            else:
                error_text = response.text
                logger.error(f"❌ 异步初始化请求失败:")
                logger.error(f"  - HTTP状态: {response.status_code}")
                logger.error(f"  - 错误内容: {error_text}")
                logger.error(f"  - 响应头: {dict(response.headers)}")

                self.error_occurred.emit(f"启动异步初始化失败: HTTP {response.status_code} - {error_text}")
                return None

        except requests.exceptions.Timeout as e:
            logger.error("❌ ========== 异步初始化请求超时 ==========")
            logger.error(f"❌ 超时详情: {e}")
            logger.error("❌ 可能原因:")
            logger.error("   1. API服务器响应慢")
            logger.error("   2. LLM配置问题（检查.env文件）")
            logger.error("   3. 网络连接问题")
            logger.error("   4. 服务器资源不足")
            self.error_occurred.emit(f"启动异步初始化超时: 请求超过15秒，请检查API服务器状态")
            return None

        except requests.exceptions.ConnectionError as e:
            logger.error("❌ ========== API连接失败 ==========")
            logger.error(f"❌ 连接错误: {e}")
            logger.error("❌ 请检查:")
            logger.error("   1. ChronoForge API服务器是否在运行")
            logger.error("   2. 端口9543是否被占用")
            logger.error("   3. 防火墙设置")
            self.error_occurred.emit(f"API连接失败: {e}")
            return None

        except Exception as e:
            logger.error("❌ ========== 启动异步初始化异常 ==========")
            logger.error(f"❌ 异常详情: {e}")
            import traceback
            logger.error(f"❌ 完整堆栈: {traceback.format_exc()}")
            self.error_occurred.emit(f"启动异步初始化异常: {str(e)}")
            return None

    def _poll_initialization_progress(self, task_id: str, character, connector, connection_result):
        """轮询初始化进度直到完成"""
        try:
            import requests
            import time

            api_base_url = "http://127.0.0.1:9543"
            status_url = f"{api_base_url}/initialize_status/{task_id}"

            max_wait_time = 120  # 最大等待2分钟
            poll_interval = 3   # 每3秒轮询一次
            start_time = time.time()

            self.progress_updated.emit("🔍 开始监控初始化进度...", "每3秒检查一次任务状态")

            while time.time() - start_time < max_wait_time:
                try:
                    # 检查是否需要停止（QThread的标准做法）
                    if self.isInterruptionRequested():
                        self.error_occurred.emit("用户取消了初始化任务")
                        return

                    status_response = requests.get(status_url, timeout=10)

                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        task_status = status_data.get("status")
                        progress = status_data.get("progress", 0.0)
                        message = status_data.get("message", "")

                        # 实时更新进度到UI
                        progress_percent = int(progress * 100)
                        self.progress_updated.emit(
                            f"🧠 初始化进度: {progress_percent}%",
                            f"当前步骤: {message}"
                        )

                        if task_status == "completed":
                            # 任务完成
                            result = status_data.get("result", {})
                            nodes_created = result.get("graph_stats", {}).get("nodes_updated", 0)
                            session_id = result.get("session_id")

                            self.progress_updated.emit("🎉 初始化成功！", f"已创建 {nodes_created} 个节点")

                            # 通知插件连接状态
                            connector.notify_plugin_connection(session_id)

                            # 标记酒馆模式为激活状态
                            self.tavern_manager.is_tavern_mode = True
                            self.tavern_manager.connector = connector

                            # 发送完成信号
                            completed_result = {
                                "success": True,
                                "character": character['name'],
                                "session_id": session_id,
                                "nodes_created": nodes_created,
                                "total_time": f"{time.time() - start_time:.1f}秒",
                                "async_task_id": task_id,
                                "connection": connection_result
                            }

                            self.initialization_completed.emit(completed_result)
                            return

                        elif task_status == "failed":
                            # 任务失败
                            error_message = status_data.get("error", "未知错误")
                            self.progress_updated.emit("❌ 初始化失败", error_message)
                            self.error_occurred.emit(f"异步初始化失败: {error_message}")
                            return

                        # 任务还在运行中，继续等待
                        time.sleep(poll_interval)

                    else:
                        self.progress_updated.emit(
                            "⚠️ 状态查询异常",
                            f"HTTP {status_response.status_code}，将继续重试..."
                        )
                        time.sleep(poll_interval)

                except requests.exceptions.RequestException as e:
                    self.progress_updated.emit(
                        "⚠️ 网络异常",
                        f"连接API失败: {str(e)[:50]}...，将继续重试"
                    )
                    time.sleep(poll_interval)

            # 超时处理
            elapsed_time = int(time.time() - start_time)
            self.progress_updated.emit("⏰ 初始化超时", f"已等待 {elapsed_time} 秒，任务可能仍在后台运行")
            self.error_occurred.emit(f"初始化超时（超过{max_wait_time}秒），请检查API服务器状态")

        except Exception as e:
            self.error_occurred.emit(f"轮询进度异常: {str(e)}")
            import traceback
            logger.error(f"轮询进度异常: {traceback.format_exc()}")

sys.path.append(str(Path(__file__).parent))
from src.memory import GRAGMemory

# 导入重构后的组件
from src.ui.widgets.chat_components import ChatDisplayWidget, ChatBubble, LoadingBubble
from src.ui.managers.conversation_manager import ConversationManager
from src.ui.workers.llm_worker import LLMWorkerThread
from src.ui.managers.scenario_manager import ScenarioManager
from src.ui.managers.window_manager import WindowManager
from src.ui.managers.resource_cleanup_manager import ResourceCleanupManager
# 导入酒馆连接器
from src.tavern.tavern_connector import TavernModeManager, TavernConfig, SillyTavernConnector
from src.ui.generators.graph_html_generator import GraphHTMLGenerator

class ChatBubble(QFrame):
    """聊天气泡组件"""

    # 添加信号
    message_clicked = pyqtSignal(object)  # 点击消息时发出信号

    def __init__(self, message: str, is_user: bool, color: str = None):
        super().__init__()
        self.message = message
        self.is_user = is_user
        self.delete_mode_enabled = False  # 是否处于删除模式
        # 统一的深色主题配色
        if is_user:
            # 用户消息：简洁的蓝色
            self.color = color or "#5865f2"  # Discord蓝
            self.text_color = "#ffffff"
            self.border_color = "transparent"
        else:
            # AI消息：深色背景，浅色文字，微妙边框
            self.color = color or "#36393f"  # Discord深色
            self.text_color = "#dcddde"      # 温和的浅色
            self.border_color = "#40444b"    # 微妙的边框
        self.setup_ui()

    def set_delete_mode(self, enabled: bool):
        """设置删除模式"""
        self.delete_mode_enabled = enabled
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            # 添加删除模式的视觉提示
            self.setStyleSheet(self.styleSheet() + """
                QFrame:hover {
                    border: 2px solid #e74c3c !important;
                    background-color: rgba(231, 76, 60, 0.1) !important;
                }
            """)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setStyleSheet("")  # 重置样式
            self.setup_ui()  # 重新设置UI样式

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if self.delete_mode_enabled and event.button() == Qt.LeftButton:
            self.message_clicked.emit(self)
        super().mousePressEvent(event)

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)

        # 创建消息标签
        message_label = QLabel(self.message)
        message_label.setWordWrap(True)

        if self.is_user:
            # 用户消息样式 - 简洁的蓝色
            message_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {self.color};
                    color: {self.text_color};
                    border-radius: 18px;
                    padding: 12px 16px;
                    font-size: 14px;
                    line-height: 1.4;
                    max-width: 400px;
                    min-height: 20px;
                    border: none;
                    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                    font-weight: 500;
                }}
            """)
        else:
            # AI消息样式 - Discord风格深色
            message_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {self.color};
                    color: {self.text_color};
                    border: 1px solid {self.border_color};
                    border-radius: 8px;
                    padding: 12px 16px;
                    font-size: 14px;
                    line-height: 1.5;
                    max-width: 450px;
                    min-height: 20px;
                    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                }}
            """)

        message_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        if self.is_user:
            # 用户消息右对齐
            layout.addStretch()
            layout.addWidget(message_label)
        else:
            # AI消息左对齐
            layout.addWidget(message_label)
            layout.addStretch()

class LoadingBubble(QFrame):
    """加载动画气泡"""
    def __init__(self):
        super().__init__()
        self.dots_count = 1
        self.max_dots = 6
        self.setup_ui()

        # 设置定时器来更新动画
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(500)  # 每500ms更新一次

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)

        self.message_label = QLabel("助手正在思考...")
        self.message_label.setStyleSheet("""
            QLabel {
                background-color: #36393f;
                color: #72767d;
                border: 1px solid #40444b;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 14px;
                min-width: 120px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-style: italic;
            }
        """)

        layout.addWidget(self.message_label)
        layout.addStretch()

    def update_animation(self):
        dots = "." * self.dots_count
        self.message_label.setText(f"助手正在思考{dots}")
        self.dots_count = (self.dots_count % self.max_dots) + 1

    def stop_animation(self):
        self.timer.stop()

class ChatDisplayWidget(QScrollArea):
    """聊天显示组件"""
    def __init__(self):
        super().__init__()
        self.messages_layout = QVBoxLayout()
        self.current_loading_bubble = None
        self.message_widgets = []  # 存储所有消息组件的引用
        self.setup_ui()

    def setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(400)

        # 创建容器widget
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #2f3136;
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(5)
        container_layout.setContentsMargins(0, 10, 0, 10)

        # 添加消息布局
        container_layout.addLayout(self.messages_layout)
        container_layout.addStretch()  # 推到顶部

        self.setWidget(container)

        # 设置样式 - 现代深色聊天背景（类似Discord/Slack）
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                border-radius: 0px;
                background-color: #2f3136;
            }
            QWidget {
                background-color: #2f3136;
            }
            QScrollBar:vertical {
                width: 8px;
                border-radius: 4px;
                background-color: #2f3136;
                border: none;
            }
            QScrollBar::handle:vertical {
                border-radius: 4px;
                background-color: #202225;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #40444b;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
        """)

    def add_message(self, message: str, is_user: bool, color: str = None):
        # 限制消息历史大小，防止内存泄漏
        MAX_MESSAGES = 1000  # 最多保留1000条消息

        # 如果超过限制，删除最旧的消息
        if len(self.message_widgets) >= MAX_MESSAGES:
            old_msg_info = self.message_widgets.pop(0)
            old_widget = old_msg_info['widget']
            self.messages_layout.removeWidget(old_widget)
            old_widget.deleteLater()
            logger.info(f"🧹 [UI] 删除旧消息以防止内存泄漏，当前消息数: {len(self.message_widgets)}")

        bubble = ChatBubble(message, is_user, color)
        bubble.message_clicked.connect(self.on_message_clicked)  # 连接点击信号
        self.messages_layout.addWidget(bubble)
        self.message_widgets.append({
            'widget': bubble,
            'message': message,
            'is_user': is_user,
            'color': color
        })
        self.scroll_to_bottom()

    def set_delete_mode(self, enabled: bool):
        """设置所有气泡的删除模式"""
        for msg_info in self.message_widgets:
            msg_info['widget'].set_delete_mode(enabled)

    def on_message_clicked(self, bubble):
        """处理消息气泡点击事件"""
        # 找到对应的消息信息
        for i, msg_info in enumerate(self.message_widgets):
            if msg_info['widget'] == bubble:
                # 询问确认删除
                reply = QMessageBox.question(
                    self,
                    "确认删除",
                    f"确定要删除这条{'用户' if msg_info['is_user'] else 'AI'}消息吗？",
                    QMessageBox.Yes | QMessageBox.No
                )

                if reply == QMessageBox.Yes:
                    # 从布局中移除
                    self.messages_layout.removeWidget(bubble)
                    bubble.deleteLater()

                    # 从列表中移除
                    self.message_widgets.pop(i)

                    # 发出删除信号通知父组件更新对话历史
                    # TODO: 实现对话历史同步

                break

    def show_loading_animation(self):
        if self.current_loading_bubble:
            self.remove_loading_animation()

        self.current_loading_bubble = LoadingBubble()
        self.messages_layout.addWidget(self.current_loading_bubble)
        self.scroll_to_bottom()
        return self.current_loading_bubble

    def remove_loading_animation(self):
        if self.current_loading_bubble:
            self.current_loading_bubble.stop_animation()
            self.messages_layout.removeWidget(self.current_loading_bubble)
            self.current_loading_bubble.deleteLater()
            self.current_loading_bubble = None

    def scroll_to_bottom(self):
        # 延迟滚动以确保布局完成
        QTimer.singleShot(50, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))

    def clear_messages(self):
        # 清空所有消息
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.remove_loading_animation()
        self.message_widgets.clear()

    def remove_last_ai_message(self):
        """删除最后一条AI回复"""
        # 从后往前找最后一条AI消息
        for i in range(len(self.message_widgets) - 1, -1, -1):
            if not self.message_widgets[i]['is_user']:
                # 找到最后一条AI消息，删除它
                widget_to_remove = self.message_widgets[i]['widget']
                self.messages_layout.removeWidget(widget_to_remove)
                widget_to_remove.deleteLater()
                self.message_widgets.pop(i)
                return True
        return False

    def get_last_user_message(self):
        """获取最后一条用户消息"""
        for i in range(len(self.message_widgets) - 1, -1, -1):
            if self.message_widgets[i]['is_user']:
                return self.message_widgets[i]['message']
        return None
from src.core.perception import PerceptionModule
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.game_engine import GameEngine
from src.core.validation import ValidationLayer

from typing import Dict, List, Optional


class GraphBridge(QObject):
    """JavaScript和Python之间的桥接类"""

    def __init__(self, graph_page):
        super().__init__()
        self.graph_page = graph_page

    @Slot(str, str)
    def editNode(self, entity_name, entity_type):
        """JavaScript直接调用此方法编辑节点"""
        try:
            logger.info(f"通过WebChannel编辑节点: {entity_name} ({entity_type})")
            self.graph_page.edit_node_with_python_dialog(entity_name, entity_type)
        except Exception as e:
            logger.error(f"WebChannel编辑节点失败: {e}")

    @Slot(str, str, str)
    def createRelation(self, source_name, target_name, relation_type):
        """JavaScript直接调用此方法创建关系"""
        try:
            logger.info(f"通过WebChannel创建关系: {source_name} -> {target_name} ({relation_type})")
            # 可以在这里添加创建关系的逻辑
        except Exception as e:
            logger.error(f"WebChannel创建关系失败: {e}")

    @Slot(str)
    def log(self, message):
        """JavaScript日志输出到Python"""
        logger.debug(f"JS: {message}")


class ConversationManager(QObject):
    """对话管理器，处理本地对话的CRUD操作"""

    conversation_changed = pyqtSignal(str)  # 当前对话改变
    conversation_list_updated = pyqtSignal(list)  # 对话列表更新

    def __init__(self, storage_path: Path):
        super().__init__()
        self.storage_path = storage_path / "conversations"
        self.storage_path.mkdir(exist_ok=True, parents=True)
        self.current_conversation_id: Optional[str] = None
        self.conversations: Dict[str, Dict] = {}
        self.load_conversations()

    def load_conversations(self):
        """加载所有对话"""
        self.conversations.clear()

        for conv_file in self.storage_path.glob("*.json"):
            try:
                with open(conv_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.conversations[data['id']] = data
            except Exception as e:
                logger.error(f"Failed to load conversation {conv_file}: {e}")

        # 按最后修改时间排序
        sorted_conversations = sorted(
            self.conversations.values(),
            key=lambda x: x.get('last_modified', 0),
            reverse=True
        )

        self.conversation_list_updated.emit(sorted_conversations)

        # 如果没有当前对话，选择最新的（但如果已经有了就不要重复触发）
        if not self.current_conversation_id and sorted_conversations:
            self.current_conversation_id = sorted_conversations[0]['id']
            self.conversation_changed.emit(self.current_conversation_id)

    def create_conversation(self, name: str = None) -> str:
        """创建新对话"""
        import uuid
        import time

        conv_id = str(uuid.uuid4())
        if not name:
            name = f"新对话 {len(self.conversations) + 1}"

        conversation = {
            'id': conv_id,
            'name': name,
            'messages': [],
            'created_time': time.time(),
            'last_modified': time.time(),
            'metadata': {}
        }

        self.conversations[conv_id] = conversation
        self._save_conversation(conversation)

        # 切换到新对话
        self.current_conversation_id = conv_id

        # 重新加载更新列表，但不要触发自动选择逻辑
        self.load_conversations()

        # 手动发出对话切换信号
        self.conversation_changed.emit(conv_id)

        return conv_id

    def delete_conversation(self, conv_id: str) -> bool:
        """删除对话"""
        if conv_id not in self.conversations:
            return False

        try:
            conv_file = self.storage_path / f"{conv_id}.json"
            if conv_file.exists():
                conv_file.unlink()

            del self.conversations[conv_id]

            # 如果删除的是当前对话，切换到其他对话
            if self.current_conversation_id == conv_id:
                remaining_convs = list(self.conversations.keys())
                if remaining_convs:
                    self.current_conversation_id = remaining_convs[0]
                    self.conversation_changed.emit(self.current_conversation_id)
                else:
                    self.current_conversation_id = None
                    self.conversation_changed.emit("")

            self.load_conversations()
            return True

        except Exception as e:
            logger.error(f"Failed to delete conversation {conv_id}: {e}")
            return False

    def rename_conversation(self, conv_id: str, new_name: str) -> bool:
        """重命名对话"""
        if conv_id not in self.conversations:
            return False

        try:
            import time
            self.conversations[conv_id]['name'] = new_name
            self.conversations[conv_id]['last_modified'] = time.time()
            self._save_conversation(self.conversations[conv_id])
            self.load_conversations()
            return True

        except Exception as e:
            logger.error(f"Failed to rename conversation {conv_id}: {e}")
            return False

    def switch_conversation(self, conv_id: str):
        """切换对话"""
        if conv_id in self.conversations:
            self.current_conversation_id = conv_id
            self.conversation_changed.emit(conv_id)

    def get_current_conversation(self) -> Optional[Dict]:
        """获取当前对话"""
        if self.current_conversation_id and self.current_conversation_id in self.conversations:
            return self.conversations[self.current_conversation_id]
        return None

    def add_message(self, message: Dict):
        """添加消息到当前对话"""
        conv = self.get_current_conversation()
        if conv:
            import time
            message['timestamp'] = time.time()
            conv['messages'].append(message)
            conv['last_modified'] = time.time()
            self._save_conversation(conv)

    def clear_current_conversation(self):
        """清空当前对话的消息"""
        conv = self.get_current_conversation()
        if conv:
            import time
            conv['messages'] = []
            conv['last_modified'] = time.time()
            self._save_conversation(conv)

    def _save_conversation(self, conversation: Dict):
        """保存对话到文件"""
        conv_file = self.storage_path / f"{conversation['id']}.json"
        try:
            with open(conv_file, 'w', encoding='utf-8') as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")


class IntegratedPlayPage(QWidget):
    """集成的智能对话页面"""

    def __init__(self, engine: GameEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.api_base_url = "http://127.0.0.1:9543"
        self.is_test_mode = True  # 默认测试模式
        self.is_connected_to_api = False
        self.switching_modes = False  # 添加模式切换标志

        # 初始化酒馆管理器
        self.tavern_manager = TavernModeManager(self.engine)

        # 对话管理器
        self.conversation_manager = ConversationManager(Path(__file__).parent / "data" / "local_conversations")

        self.init_ui()
        self.connect_signals()

        # 设置初始状态 - 本地测试模式默认激活
        self.update_status_display("本地测试模式已选择")
        self.is_connected_to_api = True
        # 设置初始按钮状态
        self.local_mode_radio.setEnabled(False)  # 当前选中的模式变灰
        self.tavern_mode_radio.setEnabled(True)

        # 初始化加载现有对话
        self.load_existing_conversations()

    def load_existing_conversations(self):
        """加载现有对话到下拉框"""
        try:
            logger.info("📥 [UI] 开始加载现有对话...")

            # 触发对话管理器加载对话
            self.conversation_manager.load_conversations()

            # 获取排序后的对话列表
            conversations = list(self.conversation_manager.conversations.values())
            logger.info(f"📋 [UI] 找到 {len(conversations)} 个对话")

            if conversations:
                # 按最后修改时间排序
                sorted_conversations = sorted(
                    conversations,
                    key=lambda x: x.get('last_modified', 0),
                    reverse=True
                )

                for i, conv in enumerate(sorted_conversations):
                    logger.info(f"📄 [UI] 对话{i+1}: {conv['name']} (ID: {conv['id']})")

                self.update_conversation_combo(sorted_conversations)

                # 如果有对话，自动选择第一个并加载其内容
                if sorted_conversations:
                    first_conv = sorted_conversations[0]
                    logger.info(f"🎯 [UI] 自动选择第一个对话: {first_conv['name']}")

                    self.conversation_manager.current_conversation_id = first_conv['id']
                    self.load_conversation(first_conv['id'])
                    logger.info(f"✅ [UI] 自动加载对话: {first_conv['name']}")
            else:
                logger.info("📭 [UI] 没有找到现有对话")
        except Exception as e:
            logger.error(f"❌ [UI] 加载现有对话失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    def init_ui(self):
        """初始化UI"""
        # 设置页面背景为深色
        self.setStyleSheet("""
            IntegratedPlayPage {
                background-color: #2f3136;
            }
        """)

        layout = QVBoxLayout(self)

        # 顶部工具栏
        toolbar = self.create_toolbar()
        layout.addWidget(toolbar)

        # 对话管理区域
        conv_management = self.create_conversation_management()
        layout.addWidget(conv_management)

        # 对话显示区域 - 使用新的气泡对话框组件
        self.chat_display = ChatDisplayWidget()
        layout.addWidget(self.chat_display)

        # 输入区域
        input_area = self.create_input_area()
        layout.addWidget(input_area)

    def create_toolbar(self) -> QWidget:
        """创建顶部工具栏"""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)

        # 模式选择组
        mode_group = QGroupBox("测试模式")
        mode_group.setStyleSheet("""
            QGroupBox {
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                font-weight: bold;
                background-color: #36393f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #5865f2;
                font-size: 14px;
            }
            QRadioButton {
                color: #dcddde;
                font-size: 13px;
                spacing: 8px;
                padding: 4px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #4f545c;
                background-color: #40444b;
            }
            QRadioButton::indicator:checked {
                background-color: #5865f2;
                border-color: #5865f2;
            }
            QRadioButton::indicator:hover {
                border-color: #5865f2;
            }
            QRadioButton::indicator:disabled {
                background-color: #2f3136;
                border-color: #72767d;
            }
        """)
        mode_layout = QVBoxLayout(mode_group)

        # 单选按钮组
        self.mode_button_group = QButtonGroup()

        self.local_mode_radio = QRadioButton("本地测试模式")
        self.tavern_mode_radio = QRadioButton("酒馆模式")

        # 默认选择本地测试模式
        self.local_mode_radio.setChecked(True)
        self.is_test_mode = True

        # 添加到按钮组
        self.mode_button_group.addButton(self.local_mode_radio, 0)
        self.mode_button_group.addButton(self.tavern_mode_radio, 1)

        mode_layout.addWidget(self.local_mode_radio)
        mode_layout.addWidget(self.tavern_mode_radio)

        # 连接状态指示器
        self.status_label = QLabel("本地测试模式已选择")
        self.status_label.setStyleSheet("""
            QLabel {
                padding: 5px 10px;
                border-radius: 3px;
                background-color: #27ae60;
                color: white;
                font-weight: bold;
            }
        """)

        layout.addWidget(mode_group)
        layout.addStretch()
        layout.addWidget(self.status_label)

        return toolbar

    def create_conversation_management(self) -> QWidget:
        """创建对话管理区域"""
        group = QGroupBox("对话管理")
        group.setStyleSheet("""
            QGroupBox {
                color: #dcddde;
                border: 1px solid #4f545c;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 15px;
                font-weight: bold;
                background-color: #36393f;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #5865f2;
                font-size: 14px;
            }
            QLabel {
                color: #dcddde;
                font-size: 13px;
            }
        """)
        layout = QHBoxLayout(group)

        # 对话选择下拉框
        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(200)

        # 对话管理按钮
        self.new_conv_btn = QPushButton("新建对话")
        self.new_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))

        self.delete_conv_btn = QPushButton("删除对话")
        self.delete_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))

        self.rename_conv_btn = QPushButton("重命名")
        self.rename_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))

        layout.addWidget(QLabel("当前对话："))
        layout.addWidget(self.conversation_combo)
        layout.addWidget(self.new_conv_btn)
        layout.addWidget(self.rename_conv_btn)
        layout.addWidget(self.delete_conv_btn)
        layout.addStretch()

        return group

    def create_input_area(self) -> QWidget:
        """创建输入区域"""
        widget = QWidget()
        widget.setStyleSheet("""
            QWidget {
                background-color: #36393f;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background-color: #5865f2;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #4752c4;
            }
            QPushButton:pressed {
                background-color: #3c45a5;
            }
            QPushButton:disabled {
                background-color: #4f545c;
                color: #72767d;
            }
            QPushButton:checked {
                background-color: #e74c3c;
                color: #ffffff;
            }
            QPushButton:checked:hover {
                background-color: #c0392b;
            }
        """)
        layout = QVBoxLayout(widget)

        # 输入框
        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(100)
        self.input_text.setPlaceholderText("输入你的消息...")

        # 按钮行
        button_layout = QHBoxLayout()

        # 重新生成按钮
        self.regenerate_btn = QPushButton("重新生成")
        self.regenerate_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.regenerate_btn.setToolTip("重新生成最后一轮AI回复")

        # 删除模式切换按钮
        self.delete_mode_btn = QPushButton("删除模式")
        self.delete_mode_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.delete_mode_btn.setCheckable(True)
        self.delete_mode_btn.setToolTip("切换删除模式，可以选择删除任意对话")

        self.send_btn = QPushButton("发送")
        self.send_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))

        button_layout.addWidget(self.regenerate_btn)
        button_layout.addWidget(self.delete_mode_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.send_btn)

        layout.addWidget(self.input_text)
        layout.addLayout(button_layout)

        return widget

    def connect_signals(self):
        """连接信号"""
        # 模式切换 - 使用单选按钮组
        self.mode_button_group.idClicked.connect(self.on_mode_change)

        # 对话管理
        self.new_conv_btn.clicked.connect(self.create_new_conversation)
        self.delete_conv_btn.clicked.connect(self.delete_current_conversation)
        self.rename_conv_btn.clicked.connect(self.rename_current_conversation)
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)

        # 对话交互
        self.send_btn.clicked.connect(self.send_message)
        self.clear_btn.clicked.connect(self.clear_conversation)
        self.regenerate_btn.clicked.connect(self.regenerate_last_response)
        self.delete_mode_btn.toggled.connect(self.toggle_delete_mode)
        self.input_text.installEventFilter(self)  # 监听快捷键

        # 对话管理器信号
        self.conversation_manager.conversation_list_updated.connect(self.update_conversation_combo)
        self.conversation_manager.conversation_changed.connect(self.load_conversation)

    def eventFilter(self, obj, event):
        """事件过滤器，处理快捷键"""
        if obj == self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def on_mode_change(self, mode_id):
        """模式切换处理 - 重新设计的完整酒馆模式"""
        # 设置模式切换标志，防止自动初始化干扰
        main_window = None
        widget = self.parent()
        while widget is not None:
            if isinstance(widget, ChronoForgeMainWindow):
                main_window = widget
                break
            widget = widget.parent()

        if main_window:
            main_window.switching_modes = True
            logger.info("🔄 设置模式切换标志，暂停对话自动初始化")

        try:
            if mode_id == 0:  # 本地测试模式
                self.is_test_mode = True
                self.tavern_mode_radio.setEnabled(True)
                self.local_mode_radio.setEnabled(False)

                # 退出酒馆模式（如果在酒馆模式中）
                if self.tavern_manager.is_tavern_mode:
                    logger.info("🏠 正在退出酒馆模式...")
                    result = self.tavern_manager.exit_tavern_mode()
                    if result["success"]:
                        logger.info("✅ 已退出酒馆模式")

                        # *** 关键修复：恢复本地知识图谱 ***
                        if main_window:
                            logger.info("🔄 恢复本地知识图谱...")
                            # 重新加载本地实体数据
                            if hasattr(main_window, 'memory'):
                                main_window.memory.reload_entities_from_json()
                                logger.info("✅ 已恢复本地知识图谱数据")

                                # 刷新图谱页面显示本地数据
                                if hasattr(main_window, 'graph_page'):
                                    main_window.graph_page.exit_tavern_mode()  # 切换回本地数据源
                                    main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                                    logger.info("📊 知识图谱页面已恢复本地显示")
                    else:
                        logger.error(f"退出酒馆模式失败: {result.get('error')}")

                # 无条件关闭后端酒馆模式并快速清理，确保彻底回到本地隔离
                try:
                    import requests
                    try:
                        requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=5)
                        logger.info("🛑 已关闭后端酒馆模式（隔离插件）")
                    except Exception as gate_err:
                        logger.warning(f"⚠️ tavern_mode 关闭失败: {gate_err}")
                    try:
                        requests.get(f"{self.api_base_url}/system/quick_reset", timeout=5)
                        logger.info("🧼 已请求后端快速清理（quick_reset）")
                    except Exception as qr_err:
                        logger.warning(f"⚠️ quick_reset 请求失败: {qr_err}")
                except Exception as reset_err:
                    logger.warning(f"⚠️ 清理流程请求失败: {reset_err}")
                # 停止可能存在的酒馆会话轮询
                try:
                    self._stop_tavern_session_polling()
                except Exception:
                    pass


                # 启用对话界面
                self.enable_chat_interface(True)

                self.update_status_display("本地测试模式已选择")
                self.is_connected_to_api = True

            elif mode_id == 1:  # 酒馆模式
                self.is_test_mode = False
                self.local_mode_radio.setEnabled(True)
                self.tavern_mode_radio.setEnabled(False)

                # 开始酒馆模式切换流程
                self.update_status_display("🍺 正在切换到酒馆模式...")
                # 确保后端服务器存活；仅检查，不在此处自启，避免端口竞争
                try:
                    import requests
                    r = requests.get(f"{self.api_base_url}/system/liveness", timeout=5)
                    if not r.ok:
                        self.update_status_display("❌ 会话初始化失败：后端未启动")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "ChronoForge", "会话初始化失败: 后端无法访问，请先启动Python服务器。")

                        # 确保后端处于本地隔离（关闭酒馆模式 + 快速清理）
                        try:
                            requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=3)
                            requests.get(f"{self.api_base_url}/system/quick_reset", timeout=3)
                            logger.info("🛑 已在回退时关闭后端酒馆模式并请求 quick_reset")
                        except Exception as gate_err:
                            logger.warning(f"⚠️ 回退关闭 tavern_mode/quick_reset 失败: {gate_err}")

                        # 回退到本地模式（UI 状态）
                        self.local_mode_radio.setChecked(True)
                        self.tavern_mode_radio.setChecked(False)
                        self.is_test_mode = True
                        self.local_mode_radio.setEnabled(False)
                        self.tavern_mode_radio.setEnabled(True)
                        return

                    # 启用后端酒馆模式开关（允许插件/WS访问）
                    requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": True}, timeout=5)
                    logger.info("✅ 已开启后端酒馆模式（允许插件访问）")
                except Exception as gate_err:
                    logger.warning(f"⚠️ tavern_mode 开启失败: {gate_err}")

                QApplication.processEvents()

                # 禁用对话界面（切换到酒馆模式后，对话由酒馆控制）
                self.enable_chat_interface(False)

                # 不再阻塞等待插件提交角色数据；直接进入“酒馆模式占位”界面，由插件与后端自行完成初始化
                try:
                    self.update_status_display("✅ 酒馆模式已启用（等待SillyTavern角色提交）")
                    if main_window and hasattr(main_window, 'graph_page'):
                        # 显示占位信息；session_id 暂定为 pending，统计为空
                        placeholder_stats = {"graph_nodes": 0, "graph_edges": 0}
                        try:
                            main_window.graph_page._show_tavern_mode_placeholder("pending", placeholder_stats)
                        except Exception as e:
                            logger.warning(f"⚠️ 显示酒馆占位页面失败: {e}")
                except Exception as e:
                    logger.warning(f"⚠️ 进入酒馆占位界面失败: {e}")

        finally:
            # 使用QTimer延迟重置标志，确保所有相关的信号处理完成
            if main_window:
                def reset_switching_flag():
                    main_window.switching_modes = False
                # 启动轮询以自动附着到后端实际会话并刷新图谱
                try:
                    self._start_tavern_session_polling()
                except Exception as _e:
                    logger.warning(f"⚠️ 启动会话轮询失败: {_e}")

                    logger.info("✅ 重置模式切换标志，恢复对话自动初始化")

                QTimer.singleShot(2000, reset_switching_flag)  # 2秒后重置标志

    def enable_chat_interface(self, enabled: bool):

        """启用/禁用对话界面"""
        try:
            # 禁用/启用用户输入框
            if hasattr(self, 'input_text'):
                self.input_text.setEnabled(enabled)
                if not enabled:
                    self.input_text.setPlaceholderText("酒馆模式下，请在SillyTavern中进行对话")
                else:
                    self.input_text.setPlaceholderText("输入你的消息...")

            # 禁用/启用发送按钮
            if hasattr(self, 'send_btn'):
                self.send_btn.setEnabled(enabled)

            # 禁用/启用其他对话相关控件
            controls = ['clear_btn', 'new_conv_btn', 'delete_conv_btn', 'rename_conv_btn', 'regenerate_btn', 'delete_mode_btn']
            for ctrl_name in controls:
                if hasattr(self, ctrl_name):
                    ctrl = getattr(self, ctrl_name)
                    ctrl.setEnabled(enabled)

            logger.info(f"💬 对话界面已{'启用' if enabled else '禁用'}")

        except Exception as e:
            logger.error(f"切换对话界面状态失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    def enter_tavern_mode(self):
        """进入酒馆模式的完整流程 - 使用多线程避免UI卡顿"""
        logger.info("🍺 ========== 开始进入酒馆模式流程（多线程模式）==========")

        try:
            # 立即更新UI状态，告知用户开始初始化
            self.update_status_display("🍺 正在初始化酒馆模式...")
            QApplication.processEvents()

            # 禁用相关UI控件，防止重复操作
            if hasattr(self, 'switch_to_tavern_btn'):
                self.switch_to_tavern_btn.setEnabled(False)
                self.switch_to_tavern_btn.setText("正在初始化...")

            logger.info("📋 步骤1: 准备多线程初始化...")

            # 获取主窗口和相关组件
            # 获取主窗口实例
            main_window = None
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    break
            if not main_window:
                logger.error("❌ 无法获取主窗口实例")
                self.update_status_display("❌ 初始化失败：无法获取主窗口")
                return

            logger.info("📋 步骤2: 获取酒馆连接配置...")
            env_path = Path(__file__).parent / '.env'
            config_data = dotenv_values(env_path) if env_path.exists() else {}
            host = config_data.get("SILLYTAVERN_HOST", "localhost")
            port = int(config_data.get("SILLYTAVERN_PORT", "8000"))

            logger.info(f"🔧 酒馆连接配置:")
            logger.info(f"  - 主机: {host}")
            logger.info(f"  - 端口: {port}")

            tavern_config = TavernConfig(
                host=host,
                port=port,
                timeout=10
            )

            logger.info("📋 步骤3: 启动后台初始化线程...")

            # 创建工作线程
            self.tavern_init_worker = TavernInitWorker(self.tavern_manager, tavern_config)

            # 连接信号槽
            self.tavern_init_worker.progress_updated.connect(self.on_tavern_init_progress)
            self.tavern_init_worker.initialization_completed.connect(self.on_tavern_init_completed)
            self.tavern_init_worker.error_occurred.connect(self.on_tavern_init_error)
            self.tavern_init_worker.finished.connect(self.on_tavern_init_finished)


            # 启动线程
            self.tavern_init_worker.start()
            logger.info("✅ 后台初始化线程已启动，UI保持响应")

        except Exception as e:
            logger.error(f"❌ 酒馆模式初始化准备失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            self.update_status_display(f"❌ 初始化失败: {e}")
            self.reset_tavern_ui_state()

    @Slot(str, str)
    def on_tavern_init_progress(self, status_message: str, step_info: str):
        """处理酒馆初始化进度更新"""
        logger.info(f"🔄 酒馆初始化进度: {status_message} - {step_info}")
        self.update_status_display(f"{status_message}")
        QApplication.processEvents()  # 确保UI立即更新

    @Slot(dict)
    def on_tavern_init_completed(self, result: dict):
        """处理酒馆初始化成功完成"""
        try:
            logger.info("🎉 酒馆模式初始化成功完成！")

            character_name = result.get("character", "Unknown")
            nodes_created = result.get("nodes_created", 0)
            session_id = result.get("session_id", "unknown")

            logger.info(f"✅ 切换成功:")
            logger.info(f"  - 角色名称: {character_name}")
            logger.info(f"  - 创建节点: {nodes_created}")
            logger.info(f"  - 会话ID: {session_id}")

            # 更新UI状态
            self.update_status_display(f"✅ 酒馆模式已启用 - 角色: {character_name}")
            self.is_connected_to_api = True

            # 更新图谱页面
            # 获取主窗口实例
            main_window = None
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    break
            if hasattr(main_window, 'graph_page'):
                try:
                    logger.info("🔄 更新图谱页面显示...")
                    main_window.graph_page.enter_tavern_mode(session_id)
                    main_window.graph_page.refresh_from_api_server(session_id)
                    logger.info("✅ 图谱页面更新完成")
                except Exception as e:
                    logger.warning(f"⚠️ 图谱页面更新失败: {e}")

            # 禁用对话界面
            self.enable_chat_interface(False)

        except Exception as e:
            logger.error(f"❌ 处理酒馆初始化完成时发生错误: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    @Slot(str)
    def on_tavern_init_error(self, error_message: str):
        """处理酒馆初始化错误"""
        logger.error(f"❌ 酒馆初始化失败: {error_message}")
        self.update_status_display(f"❌ 酒馆模式切换失败")
    def _start_tavern_session_polling(self):
        """
        在酒馆模式下轮询后端以获取当前会话，并自动让图谱页附着到该会话。
        """
        try:
            self._stop_tavern_session_polling()
        except Exception:
            pass
        self._tavern_poll_attempts = 0
        self._tavern_session_poll_timer = QTimer(self)
        self._tavern_session_poll_timer.setInterval(1000)  # 1s

        def _tick():
            try:
                self._tavern_poll_attempts += 1
                import requests
                r = requests.get(f"{self.api_base_url}/tavern/current_session", timeout=2)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("has_session") and data.get("session_id"):
                        session_id = data.get("session_id")
                        try:
                            # 找到主窗口
                            main_window = None
                            w = self.parent()
                            while w is not None:
                                if hasattr(w, 'graph_page'):
                                    main_window = w
                                    break
                                w = w.parent()
                            if main_window and hasattr(main_window, 'graph_page'):
                                main_window.graph_page.enter_tavern_mode(session_id)
                                main_window.graph_page.refresh_from_api_server(session_id)
                            self.update_status_display("🍺 酒馆会话已就绪")
                        except Exception as ui_err:

                            logger.warning(f"⚠️ 切换图谱为酒馆会话失败: {ui_err}")
                        finally:
                            self._stop_tavern_session_polling()
                        return
            except Exception as poll_err:
                logger.debug(f"轮询当前会话异常: {poll_err}")
            # 超过 30 次（约 30s）则停止
            if getattr(self, "_tavern_poll_attempts", 0) >= 30:
                self._stop_tavern_session_polling()

        self._tavern_session_poll_timer.timeout.connect(_tick)
        self._tavern_session_poll_timer.start()

    def _stop_tavern_session_polling(self):
        t = getattr(self, "_tavern_session_poll_timer", None)
        if t:
            try:
                t.stop()
            except Exception:
                pass
            self._tavern_session_poll_timer = None

    def auto_switch_to_local_mode(self, reason: str):
        """自动切换到本地测试模式"""
        try:
            logger.info(f"🔄 自动切换到本地测试模式，原因: {reason}")

            # 切换单选按钮状态
            if hasattr(self, 'local_mode_radio') and hasattr(self, 'tavern_mode_radio'):
                self.local_mode_radio.setChecked(True)
                self.tavern_mode_radio.setChecked(False)

                # 更新按钮状态
                self.local_mode_radio.setEnabled(False)  # 当前选中的模式变灰
                self.tavern_mode_radio.setEnabled(True)

            # 设置测试模式标志
            self.is_test_mode = True

            # 关闭后端酒馆模式总开关，确保隔离（并快速清理）
            try:
                import requests
                requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": False}, timeout=3)
                requests.get(f"{self.api_base_url}/system/quick_reset", timeout=3)
                logger.info("🛑 已关闭后端酒馆模式并请求 quick_reset")
            except Exception as gate_err:
                logger.warning(f"⚠️ 自动回退时关闭 tavern_mode/quick_reset 失败: {gate_err}")


            # 退出酒馆模式（如果有）
            if hasattr(self, 'tavern_manager') and self.tavern_manager.is_tavern_mode:
                result = self.tavern_manager.exit_tavern_mode()
                if result["success"]:
                    logger.info("✅ 已退出酒馆模式")

                    # 恢复本地知识图谱
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'memory'):
                        main_window.memory.reload_entities_from_json()
                        logger.info("✅ 已恢复本地知识图谱数据")

                        # 刷新图谱页面显示本地数据
                        if hasattr(main_window, 'graph_page'):
                            main_window.graph_page.exit_tavern_mode()
                            main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                            logger.info("📊 知识图谱页面已恢复本地显示")

            # 启用对话界面
            self.enable_chat_interface(True)

            # 更新状态显示
            self.update_status_display("本地测试模式已选择（自动切换）")
            self.is_connected_to_api = True

            logger.info(f"✅ 已自动切换到本地测试模式，原因: {reason}")

        except Exception as e:
            logger.error(f"❌ 自动切换到本地模式失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    @Slot()
    def on_tavern_init_finished(self):
        """处理线程完成（无论成功或失败）"""
        logger.info("🧵 酒馆初始化线程已结束")

        # 清理线程
        if hasattr(self, 'tavern_init_worker'):
            self.tavern_init_worker.deleteLater()
            self.tavern_init_worker = None

        # 重置UI状态
        if hasattr(self, 'switch_to_tavern_btn'):
            self.switch_to_tavern_btn.setEnabled(True)
            self.switch_to_tavern_btn.setText("切换到酒馆模式")

        # 重置模式切换标志
        # 获取主窗口实例
        main_window = None
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, ChronoForgeMainWindow):
                main_window = widget
                break
        if main_window:
            QTimer.singleShot(1000, lambda: setattr(main_window, 'switching_modes', False))
            logger.info("✅ 重置模式切换标志，恢复正常操作")

    def reset_tavern_ui_state(self):
        """重置酒馆相关的UI状态"""
        try:
            if hasattr(self, 'switch_to_tavern_btn'):
                self.switch_to_tavern_btn.setEnabled(True)
                self.switch_to_tavern_btn.setText("切换到酒馆模式")

            self.enable_chat_interface(True)

        except Exception as e:
            logger.error(f"重置UI状态失败: {e}")
            logger.info("📋 步骤2: 获取主窗口实例...")
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    logger.info("✅ 成功获取主窗口实例")
                    break
                widget = widget.parent()

            if not main_window:
                logger.error("❌ 无法找到主窗口实例")
                raise Exception("无法找到主窗口实例")

            # *** 关键修复：保存当前会话并清空知识图谱 ***
            logger.info("📋 步骤3: 保存当前会话并清空知识图谱...")
            self.update_status_display("💾 保存当前会话并清空知识图谱...")
            QApplication.processEvents()

            # 保存当前对话到历史
            current_conv = self.conversation_manager.get_current_conversation()
            if current_conv:
                logger.info(f"💾 保存本地对话: {current_conv['name']}")
            else:
                logger.info("ℹ️ 当前没有活跃的本地对话")

            # 清空知识图谱
            logger.info("🧹 开始清空本地知识图谱...")
            if hasattr(main_window, 'memory'):
                try:
                    old_nodes = len(main_window.memory.knowledge_graph.graph.nodes())
                    old_edges = len(main_window.memory.knowledge_graph.graph.edges())
                    logger.info(f"📊 清空前状态: {old_nodes} 节点, {old_edges} 边")

                    main_window.memory.clear_all()
                    logger.info("✅ 本地知识图谱已清空")

                    # 刷新图谱页面显示空状态
                    if hasattr(main_window, 'graph_page'):
                        logger.info("🔄 刷新图谱页面显示...")
                        main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                        logger.info("✅ 图谱页面已刷新")
                except Exception as clear_error:
                    logger.error(f"❌ 清空知识图谱失败: {clear_error}")
                    raise clear_error
            else:
                logger.warning("⚠️ 主窗口没有memory属性")

            logger.info("📋 步骤4: 获取酒馆连接配置...")
            env_path = Path(__file__).parent / '.env'
            config_data = dotenv_values(env_path) if env_path.exists() else {}
            host = config_data.get("SILLYTAVERN_HOST", "localhost")
            port = int(config_data.get("SILLYTAVERN_PORT", "8000"))

            logger.info(f"🔧 酒馆连接配置:")
            logger.info(f"  - 主机: {host}")
            logger.info(f"  - 端口: {port}")
            logger.info(f"  - 配置文件: {env_path}")
            logger.info(f"  - 配置存在: {env_path.exists()}")

            tavern_config = TavernConfig(
                host=host,
                port=port,
                timeout=10
            )

            # 使用酒馆管理器进入酒馆模式
            logger.info("📋 步骤5: 调用酒馆管理器...")
            logger.info("🚀 调用 tavern_manager.enter_tavern_mode()")
            result = self.tavern_manager.enter_tavern_mode(tavern_config)

            logger.info("📨 酒馆管理器返回结果:")
            logger.info(f"  - 操作结果: {result}")
            logger.info(f"  - 成功状态: {result.get('success', False)}")

            if result["success"]:
                # 切换成功
                character_name = result["character"]
                nodes_created = result["nodes_created"]
                session_id = result.get("session_id", "unknown")

                logger.info("🎉 酒馆模式切换成功!")
                logger.info(f"  - 角色名称: {character_name}")
                logger.info(f"  - 创建节点: {nodes_created}")
                logger.info(f"  - 会话ID: {session_id}")

                self.update_status_display(f"✅ 酒馆模式已启用 - 角色: {character_name}")
                self.is_connected_to_api = True

                # 从API服务器获取酒馆会话的知识图谱并更新UI显示
                logger.info("📋 步骤6: 更新UI显示...")
                if hasattr(main_window, 'graph_page'):
                    try:
                        logger.info("🔄 通知图谱页面进入酒馆模式...")
                        # 通知图谱页面进入酒馆模式，使用API服务器的数据
                        main_window.graph_page.enter_tavern_mode(session_id)

                        logger.info("🔃 从API服务器刷新图谱...")
                        main_window.graph_page.refresh_from_api_server(session_id)

                        logger.info("📊 更新实体列表和统计...")
                        main_window.graph_page.update_entity_list()
                        main_window.graph_page.update_stats()

                        logger.info(f"✅ UI图谱页面已切换到酒馆会话: {session_id}")
                    except Exception as e:
                        logger.error(f"❌ 更新UI图谱显示失败: {e}")
                        logger.error(f"📋 UI更新异常详情: {traceback.format_exc()}")
                        # 即使UI更新失败，酒馆模式也算成功
                else:
                    logger.warning("⚠️ 主窗口没有graph_page属性")

                # 显示成功消息
                logger.info("📋 步骤7: 显示成功消息...")
                QMessageBox.information(
                    self,
                    "酒馆模式已启用",
                    f"成功连接到SillyTavern！\n\n"
                    f"当前角色: {character_name}\n"
                    f"已初始化 {nodes_created} 个知识图谱节点\n\n"
                    f"现在可以在SillyTavern中进行对话，ChronoForge将提供智能增强。"
                )

                logger.info(f"🎉 酒馆模式启用成功 - 角色: {character_name}, 节点: {nodes_created}")

            else:
                # 切换失败，恢复到本地模式
                error_msg = result.get("error", "未知错误")
                self.update_status_display(f"❌ 酒馆模式切换失败")

                # 重新启用对话界面
                self.enable_chat_interface(True)

                # 切换回本地模式
                self.local_mode_radio.setChecked(True)
                self.tavern_mode_radio.setEnabled(True)
                self.local_mode_radio.setEnabled(False)
                self.is_test_mode = True

                # 显示错误消息
                QMessageBox.warning(
                    self,
                    "酒馆模式切换失败",
                    f"无法切换到酒馆模式：\n\n{error_msg}\n\n"
                    f"请确保：\n"
                    f"1. SillyTavern正在运行 (http://localhost:8000)\n"
                    f"2. 已选择一个角色\n"
                    f"3. ChronoForge插件已安装并启用"
                )

                logger.error(f"❌ 酒馆模式切换失败: {error_msg}")

        except Exception as e:
            logger.error(f"进入酒馆模式异常: {e}")

            # 恢复到本地模式
            self.enable_chat_interface(True)
            self.local_mode_radio.setChecked(True)
            self.update_status_display("❌ 酒馆模式切换异常，已恢复本地模式")

            QMessageBox.critical(
                self,
                "酒馆模式异常",
                f"酒馆模式切换时发生异常：\n{e}"
            )

    def check_api_connection(self):
        """检查API连接状态"""
        if self.is_test_mode:
            # 本地测试模式不需要检查API
            self.is_connected_to_api = True
            self.update_status_display("本地测试模式已选择")
            return

        # 只有酒馆模式才检查API连接
        try:
            # 显示正在连接状态
            self.update_status_display("正在连接酒馆...")
            QApplication.processEvents()

            response = requests.get(f"{self.api_base_url}/system/liveness", timeout=5)
            if response.status_code == 200:
                self.is_connected_to_api = True
                self.update_status_display("酒馆服务在线")
            else:
                self.is_connected_to_api = False
                self.update_status_display("酒馆API连接失败")
        except Exception as e:
            self.is_connected_to_api = False
            self.update_status_display("酒馆API未连接")
            logger.warning(f"酒馆API连接失败: {e}")

    def update_status_display(self, status_text: str):
        """更新状态显示"""
        self.status_label.setText(status_text)

        # 根据状态文本设置不同的样式
        if ("已连接" in status_text or "已选择" in status_text):
            # 成功状态 - 绿色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #27ae60;
                    color: white;
                    font-weight: bold;
                }
            """)
        elif ("正在连接" in status_text or "等待" in status_text):
            # 等待状态 - 蓝色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #3498db;
                    color: white;
                    font-weight: bold;
                }
            """)
        else:
            # 错误/失败状态 - 红色
            self.status_label.setStyleSheet("""
                QLabel {
                    padding: 5px 10px;
                    border-radius: 3px;
                    background-color: #e74c3c;
                    color: white;
                    font-weight: bold;
                }
            """)

    def create_new_conversation(self):
        """创建新对话"""
        name, ok = QInputDialog.getText(
            self,
            "新建对话",
            "请输入对话名称：",
            text=f"新对话 {len(self.conversation_manager.conversations) + 1}"
        )

        if ok and name.strip():
            conv_id = self.conversation_manager.create_conversation(name.strip())
            QMessageBox.information(self, "成功", "对话创建成功")

    def delete_current_conversation(self):
        """删除当前对话"""
        current_conv = self.conversation_manager.get_current_conversation()
        if not current_conv:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除对话 \"{current_conv['name']}\" 吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.conversation_manager.delete_conversation(current_conv['id']):
                # 删除对话时也清空知识图谱
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'memory'):
                        main_window.memory.clear_all()
                        logger.info("✅ 删除对话时已清空知识图谱")

                        # 刷新知识图谱页面显示
                        if hasattr(main_window, 'graph_page'):
                            main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                            logger.info("✅ 知识图谱页面显示已刷新")

                except Exception as e:
                    logger.warning(f"⚠️ 清空知识图谱失败: {e}")

                QMessageBox.information(self, "成功", "对话删除成功")

    def rename_current_conversation(self):
        """重命名当前对话"""
        current_conv = self.conversation_manager.get_current_conversation()
        if not current_conv:
            return

        name, ok = QInputDialog.getText(
            self,
            "重命名对话",
            "请输入新的对话名称：",
            text=current_conv['name']
        )

        if ok and name.strip():
            if self.conversation_manager.rename_conversation(current_conv['id'], name.strip()):
                QMessageBox.information(self, "成功", "对话重命名成功")

    def switch_conversation(self, conv_name: str):
        """切换对话"""
        logger.info(f"🔄 [UI] 尝试切换对话: {conv_name}")

        if not conv_name or not conv_name.strip():
            logger.warning(f"❌ [UI] 对话名称为空，忽略切换")
            return

        # 根据名称找到对话ID
        found_conv_id = None
        for conv_id, conv_data in self.conversation_manager.conversations.items():
            if conv_data['name'] == conv_name:
                found_conv_id = conv_id
                break

        if found_conv_id:
            logger.info(f"✅ [UI] 找到对话ID: {found_conv_id}，开始切换")
            self.conversation_manager.switch_conversation(found_conv_id)
        else:
            logger.error(f"❌ [UI] 未找到对话: {conv_name}")
            logger.info(f"📋 [UI] 可用对话: {list(self.conversation_manager.conversations.keys())}")

    def update_conversation_combo(self, conversations: List[Dict]):
        """更新对话下拉框"""
        logger.info(f"🔄 [UI] 更新对话下拉框，{len(conversations)} 个对话")

        try:
            # 临时断开信号，避免在更新过程中触发切换
            self.conversation_combo.currentTextChanged.disconnect()
            logger.info("🔌 [UI] 临时断开下拉框信号")
        except Exception as e:
            logger.warning(f"⚠️ [UI] 断开信号失败（可能还没连接）: {e}")

        self.conversation_combo.clear()
        for conv in conversations:
            self.conversation_combo.addItem(conv['name'])
            logger.info(f"📝 [UI] 添加对话到下拉框: {conv['name']}")

        # 选中当前对话
        current_conv = self.conversation_manager.get_current_conversation()
        if current_conv:
            logger.info(f"🎯 [UI] 当前对话: {current_conv['name']}")
            index = self.conversation_combo.findText(current_conv['name'])
            if index >= 0:
                self.conversation_combo.setCurrentIndex(index)
                logger.info(f"✅ [UI] 设置下拉框选中索引: {index}")
            else:
                logger.error(f"❌ [UI] 在下拉框中找不到对话: {current_conv['name']}")
        else:
            logger.warning("⚠️ [UI] 没有当前对话可选中")

        # 重新连接信号
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)
        logger.info("🔌 [UI] 重新连接下拉框信号")

        logger.info(f"✅ [UI] 下拉框更新完成，当前项目: {self.conversation_combo.currentText()}")

    def load_conversation(self, conv_id: str):
        """加载对话内容"""
        logger.info(f"📖 [UI] 开始加载对话内容: {conv_id}")

        self.chat_display.clear_messages()

        if not conv_id:
            logger.warning("❌ [UI] 对话ID为空，无法加载")
            return

        conv = self.conversation_manager.get_current_conversation()
        if not conv:
            logger.warning(f"❌ [UI] 找不到对话: {conv_id}")
            return

        logger.info(f"📄 [UI] 找到对话: {conv['name']}")
        messages = conv.get('messages', [])
        logger.info(f"💬 [UI] 对话包含 {len(messages)} 条消息")

        # 显示消息历史
        loaded_messages = 0
        for msg in messages:
            if msg['role'] == 'user':
                self.append_message(msg['content'], is_user=True)
                loaded_messages += 1
            elif msg['role'] == 'assistant':
                self.append_message(msg['content'], is_user=False)
                loaded_messages += 1
            elif msg['role'] == 'system':
                self.append_message(f"系统: {msg['content']}", is_user=False)
                loaded_messages += 1

        logger.info(f"✅ [UI] 成功加载 {loaded_messages} 条消息到聊天界面")

    def append_message(self, message: str, is_user: bool = None, color: str = None):
        """添加消息到显示区域"""
        # 从消息前缀判断类型
        if is_user is None:
            if message.startswith("用户: "):
                is_user = True
                message = message[3:]  # 移除前缀
            elif message.startswith("助手: "):
                is_user = False
                message = message[3:]  # 移除前缀
            else:
                is_user = False

        self.chat_display.add_message(message, is_user, color)

    def show_loading_animation(self):
        """显示加载动画"""
        return self.chat_display.show_loading_animation()

    def remove_loading_animation(self):
        """移除加载动画"""
        self.chat_display.remove_loading_animation()

    def send_message(self):
        """发送消息"""
        message = self.input_text.toPlainText().strip()
        if not message:
            return

        if not self.is_connected_to_api:
            QMessageBox.warning(self, "错误", "连接失败，请检查配置")
            return

        # 清空输入框
        self.input_text.clear()

        # 显示用户消息
        self.append_message(message, is_user=True)

        # 添加到对话历史
        self.conversation_manager.add_message({
            'role': 'user',
            'content': message
        })

        # 显示动态加载状态
        self.loading_message_widget = self.show_loading_animation()

        # 发送到API
        self.process_message(message)

    def process_message(self, message: str):
        """处理消息（发送到API）"""
        if self.is_test_mode:
            self.process_test_message(message)
        else:
            self.process_tavern_message(message)

    def process_test_message(self, message: str):
        """处理测试模式消息 - 使用多线程避免UI阻塞"""
        try:
            # 清理之前的线程
            if hasattr(self, 'llm_worker') and self.llm_worker is not None:
                if self.llm_worker.isRunning():
                    logger.info("🔄 [UI] 停止之前的LLM工作线程")
                    self.llm_worker.terminate()
                    self.llm_worker.wait(1000)  # 等待最多1秒
                self.llm_worker.deleteLater()

            # 创建并启动工作线程
            self.llm_worker = LLMWorkerThread(self.engine, message)

            # 连接信号
            self.llm_worker.response_ready.connect(self.on_llm_response_ready)
            self.llm_worker.error_occurred.connect(self.on_llm_error)
            self.llm_worker.grag_data_ready.connect(self.on_grag_data_ready)
            self.llm_worker.finished.connect(self.on_llm_worker_finished)  # 新增：线程完成清理

            # 启动线程
            logger.info(f"🚀 [UI] 启动LLM工作线程处理消息: {message}")
            self.llm_worker.start()

        except Exception as e:
            logger.error(f"❌ [UI] 启动工作线程失败: {e}")
            self.remove_loading_animation()
            error_response = "抱歉，系统遇到了一些问题。让我们重新开始吧。"
            self.append_message(error_response, is_user=False)

    def on_grag_data_ready(self, grag_data: dict):
        """GRAG数据准备完成的回调"""
        logger.info(f"📊 [UI] 收到GRAG数据 - 实体: {grag_data['entities']}, 上下文长度: {grag_data['context_length']}")

    def on_llm_response_ready(self, llm_response: str):
        """LLM回复准备完成的回调"""
        try:
            logger.info(f"✅ [UI] 收到LLM回复，开始处理UI更新")

            # 移除加载动画并显示回复
            self.remove_loading_animation()
            self.append_message(llm_response, is_user=False)

            # 添加到对话历史
            self.conversation_manager.add_message({
                'role': 'assistant',
                'content': llm_response
            })

            # 处理LLM回复，更新知识图谱
            try:
                logger.info(f"🔄 [GRAG] 开始更新知识图谱...")
                update_results = self.engine.extract_updates_from_response(llm_response, self.llm_worker.message)
                self.engine.memory.add_conversation(self.llm_worker.message, llm_response)
                self.engine.memory.save_all_memory()

                logger.info(f"✅ [GRAG] 知识图谱更新成功: {update_results}")
                logger.info(f"📈 [GRAG] 更新统计: 节点更新={update_results.get('nodes_updated', 0)}, 边添加={update_results.get('edges_added', 0)}")

                # 实时刷新知识图谱页面显示
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'graph_page'):
                        # 重新加载实体数据到知识图谱（这一步已经在GameEngine中通过sync_entities_to_json完成了）
                        # 这里只需要重新加载UI的显示
                        main_window.memory.reload_entities_from_json()
                        # 刷新图谱显示
                        main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                        logger.info("✅ [GRAG] 知识图谱页面已实时刷新")
                except Exception as refresh_error:
                    logger.warning(f"⚠️ [GRAG] 实时刷新知识图谱页面失败: {refresh_error}")

            except Exception as e:
                logger.warning(f"⚠️ [GRAG] 知识图谱更新失败: {e}")

        except Exception as e:
            logger.error(f"❌ [UI] 处理LLM回复时出错: {e}")

    def on_llm_error(self, error_message: str):
        """LLM处理出错的回调"""
        logger.error(f"❌ [UI] LLM处理出错: {error_message}")
        self.remove_loading_animation()
        error_response = "抱歉，系统遇到了一些问题。让我们重新开始吧。"
        self.append_message(error_response, is_user=False)

    def on_llm_worker_finished(self):
        """LLM工作线程完成时的清理回调"""
        logger.info("🧹 [UI] LLM工作线程已完成，进行清理")
        if hasattr(self, 'llm_worker') and self.llm_worker is not None:
            self.llm_worker.deleteLater()
            self.llm_worker = None

    def process_tavern_message(self, message: str):
        """处理酒馆模式消息 - 通过HTTP API与酒馆插件交互"""
        if not self.is_connected_to_api:
            logger.warning("酒馆API未连接，无法处理消息")
            return None

        try:
            logger.info(f"🍺 [酒馆模式] 处理消息: {message[:100]}...")

            # 获取当前有效的酒馆会话ID
            session_id = None
            try:
                main_window = None
                widget = self.parent()
                while widget is not None:
                    if isinstance(widget, ChronoForgeMainWindow):
                        main_window = widget
                        break
                    widget = widget.parent()
                if main_window and hasattr(main_window, 'graph_page') and getattr(main_window.graph_page, 'tavern_mode', False):
                    session_id = getattr(main_window.graph_page, 'tavern_session_id', None)
            except Exception as sid_err:
                logger.warning(f"获取酒馆会话ID失败: {sid_err}")

            if not session_id:
                logger.warning("酒馆模式会话ID未知，无法处理消息")
                return {'status': 'no_session'}

            # 发送到ChronoForge API服务器进行处理
            response = requests.post(
                f"{self.api_base_url}/tavern/process_message",
                json={
                    'message': message,
                    'session_id': session_id,  # 使用当前会话ID
                    'mode': 'tavern_integration',
                    'timestamp': time.time()
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                enhanced_context = data.get('enhanced_context', '')
                nodes_updated = data.get('nodes_updated', 0)
                edges_added = data.get('edges_added', 0)

                if enhanced_context:
                    logger.info(f"✅ [酒馆模式] 消息处理成功 - 上下文长度: {len(enhanced_context)}, 节点更新: {nodes_updated}, 关系添加: {edges_added}")

                    # 更新本地UI显示
                    try:
                        # 获取主窗口实例并刷新知识图谱页面
                        main_window = None
                        widget = self.parent()
                        while widget is not None:
                            if isinstance(widget, ChronoForgeMainWindow):
                                main_window = widget
                                break
                            widget = widget.parent()

                        if main_window and hasattr(main_window, 'graph_page'):
                            main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                            logger.info("📊 [酒馆模式] 知识图谱页面已实时更新")
                    except Exception as refresh_error:
                        logger.warning(f"⚠️ [酒馆模式] 刷新知识图谱页面失败: {refresh_error}")

                    return {
                        'enhanced_context': enhanced_context,
                        'stats': {
                            'nodes_updated': nodes_updated,
                            'edges_added': edges_added
                        },
                        'status': 'success'
                    }
                else:
                    logger.info("📝 [酒馆模式] 消息处理完成，但未生成增强上下文")
                    return {'status': 'no_enhancement'}
            else:
                error_text = response.text
                logger.error(f"❌ [酒馆模式] API调用失败: {response.status_code} - {error_text}")
                return {'status': 'api_error', 'error': f"HTTP {response.status_code}"}

        except requests.exceptions.Timeout:
            logger.error("⏱️ [酒馆模式] API调用超时")
            return {'status': 'timeout', 'error': 'API request timeout'}
        except Exception as e:
            logger.error(f"💥 [酒馆模式] 消息处理异常: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return {'status': 'error', 'error': str(e)}

        return None

    def regenerate_last_response(self):
        """重新生成最后一轮AI回复"""
        try:
            # 获取最后一条用户消息
            last_user_message = self.chat_display.get_last_user_message()
            if not last_user_message:
                QMessageBox.information(self, "提示", "没有找到可重新生成的对话")
                return

            # 删除最后一条AI回复
            if not self.chat_display.remove_last_ai_message():
                QMessageBox.information(self, "提示", "没有找到可删除的AI回复")
                return

            # 从对话历史中删除最后一条AI回复
            current_conv = self.conversation_manager.get_current_conversation()
            if current_conv and current_conv.get('messages'):
                # 从后往前找最后一条AI回复并删除
                for i in range(len(current_conv['messages']) - 1, -1, -1):
                    if current_conv['messages'][i]['role'] == 'assistant':
                        current_conv['messages'].pop(i)
                        self.conversation_manager._save_conversation(current_conv)
                        break

            # 重新发送用户消息（触发新的AI回复）
            self.process_message(last_user_message)

        except Exception as e:
            logger.error(f"重新生成回复失败: {e}")
            QMessageBox.warning(self, "错误", f"重新生成失败：{str(e)}")

    def toggle_delete_mode(self, enabled: bool):
        """切换删除模式"""
        if enabled:
            self.delete_mode_btn.setText("退出删除")
            self.delete_mode_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")
            self.chat_display.set_delete_mode(True)
            QMessageBox.information(self, "删除模式", "删除模式已开启\n点击任意对话气泡可删除该条消息")
        else:
            self.delete_mode_btn.setText("删除模式")
            self.delete_mode_btn.setStyleSheet("")
            self.chat_display.set_delete_mode(False)

    def clear_conversation(self):
        """清空当前对话"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前对话吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.conversation_manager.clear_current_conversation()
            self.chat_display.clear_messages()

            # 清空对话时也清空知识图谱
            try:
                # 获取主窗口实例
                main_window = None
                widget = self.parent()
                while widget is not None:
                    if isinstance(widget, ChronoForgeMainWindow):
                        main_window = widget
                        break
                    widget = widget.parent()

                if main_window and hasattr(main_window, 'memory'):
                    main_window.memory.clear_all()
                    logger.info("✅ 清空对话时已清空知识图谱")

                    # 刷新知识图谱页面显示
                    if hasattr(main_window, 'graph_page'):
                        main_window.graph_page.refresh_graph()  # 已包含更新实体列表和统计
                        logger.info("✅ 知识图谱页面显示已刷新")

            except Exception as e:
                logger.warning(f"⚠️ 清空知识图谱失败: {e}")


class GraphPage(QWidget):
    """知识关系图谱页面"""

    def __init__(self, memory_system, parent=None):
        super().__init__(parent)
        self.memory = memory_system
        self.graph_file_path = Path(__file__).parent / "graph.html"
        self.current_selected_node = None

        # 酒馆模式相关属性
        self.tavern_mode = False
        self.tavern_session_id = None

        # 创建HTML生成器
        self.html_generator = GraphHTMLGenerator()
        # 将输出HTML写到模板目录，保证相对assets路径能加载
        try:
            self.graph_file_path = self.html_generator.template_path.parent / "graph.html"
            logger.info(f"[Graph] HTML输出路径: {self.graph_file_path}")
            from pathlib import Path as _P
            _assets_root = _P(__file__).resolve().parent / 'assets'
            logger.info(f"[Graph] 资源基路径: {_assets_root}")
        except Exception as _e:
            logger.warning(f"[Graph] 设定HTML输出路径失败，退回默认: {_e}")


        # 创建WebChannel桥接
        self.bridge = GraphBridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)

        self.init_ui()
        self.connect_signals()
        self.refresh_graph()

    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setSpacing(10)

        # 左侧：图谱显示区域
        left_panel = self.create_graph_panel()

        # 右侧：控制和信息面板
        right_panel = self.create_control_panel()

        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3)  # 图谱区域占3/4
        splitter.setStretchFactor(1, 1)  # 控制区域占1/4

        layout.addWidget(splitter)

    def create_graph_panel(self) -> QWidget:
        """创建图谱显示面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # 标题和快速操作
        header = QHBoxLayout()
        title = QLabel("知识关系图谱")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #4a90e2; margin-bottom: 10px;")

        # 快速操作按钮
        self.refresh_btn = QPushButton("刷新图谱")
        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))

        self.export_btn = QPushButton("导出图谱")
        self.export_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))

        self.reset_view_btn = QPushButton("重置视图")
        self.reset_view_btn.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        self.init_graph_btn = QPushButton("初始化图谱")
        self.init_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))

        self.clear_graph_btn = QPushButton("清空图谱")
        self.clear_graph_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        header.addWidget(self.export_btn)
        header.addWidget(self.init_graph_btn)
        header.addWidget(self.clear_graph_btn)
        header.addWidget(self.reset_view_btn)

        layout.addLayout(header)

        # 图谱显示区域
        self.graph_view = QWebEngineView()
        self.graph_view.setMinimumHeight(500)

        # 设置WebChannel
        self.graph_view.page().setWebChannel(self.channel)

        # 启用开发者工具 - 方便调试JavaScript
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            settings = self.graph_view.settings()
            # 尝试不同的属性名
            dev_attr = None
            for attr_name in ['DeveloperExtrasEnabled', 'WebAttribute.DeveloperExtrasEnabled', 'JavascriptEnabled']:
                if hasattr(QWebEngineSettings, attr_name):
                    dev_attr = getattr(QWebEngineSettings, attr_name)
                    break
                elif hasattr(QWebEngineSettings, 'WebAttribute') and hasattr(QWebEngineSettings.WebAttribute, 'DeveloperExtrasEnabled'):
                    dev_attr = QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled
                    break

            if dev_attr is not None:
                settings.setAttribute(dev_attr, True)
                logger.info("开发者工具已启用")
            else:
                # 尝试直接设置常见的开发者工具属性
                try:
                    settings.setAttribute(settings.DeveloperExtrasEnabled, True)
                    logger.info("开发者工具已启用(直接属性)")
                except:
                    logger.warning("无法启用开发者工具，但程序继续运行")
        except Exception as e:
            logger.warning(f"启用开发者工具失败: {e}")
            # 即使失败也继续运行

        # 添加右键菜单来打开开发者工具
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt

        def show_context_menu(point):
            menu = QMenu(self.graph_view)

            # 添加开发者工具选项
            dev_action = menu.addAction("打开开发者工具 (F12)")
            dev_action.triggered.connect(self.open_dev_tools)

            # 添加其他调试选项
            reload_action = menu.addAction("重新加载图谱")
            reload_action.triggered.connect(self.refresh_graph)

            debug_action = menu.addAction("调试信息")
            debug_action.triggered.connect(self.show_debug_info)

            menu.exec(self.graph_view.mapToGlobal(point))

        self.graph_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.graph_view.customContextMenuRequested.connect(show_context_menu)

        layout.addWidget(self.graph_view)

        return panel

    def create_control_panel(self) -> QWidget:
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # 搜索区域
        search_group = QGroupBox("搜索与过滤")
        search_layout = QVBoxLayout(search_group)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索节点或关系...")
        self.search_btn = QPushButton("搜索")
        self.clear_search_btn = QPushButton("清除")

        search_button_layout = QHBoxLayout()
        search_button_layout.addWidget(self.search_btn)
        search_button_layout.addWidget(self.clear_search_btn)

        search_layout.addWidget(self.search_input)
        search_layout.addLayout(search_button_layout)

        layout.addWidget(search_group)

        # 实体列表
        entity_group = QGroupBox("实体列表")
        entity_layout = QVBoxLayout(entity_group)

        # 实体类型过滤
        filter_layout = QHBoxLayout()
        self.filter_all_btn = QPushButton("全部")
        self.filter_character_btn = QPushButton("角色")
        self.filter_location_btn = QPushButton("地点")
        self.filter_item_btn = QPushButton("物品")
        self.filter_event_btn = QPushButton("事件")

        # 设置过滤按钮样式
        filter_buttons = [self.filter_all_btn, self.filter_character_btn,
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]

        for btn in filter_buttons:
            btn.setCheckable(True)
            btn.setMaximumHeight(30)
            filter_layout.addWidget(btn)

        self.filter_all_btn.setChecked(True)  # 默认选中全部

        entity_layout.addLayout(filter_layout)

        # 实体列表
        self.entity_list = QListWidget()
        self.entity_list.setMinimumHeight(200)
        entity_layout.addWidget(self.entity_list)

        layout.addWidget(entity_group)

        # 节点详情
        detail_group = QGroupBox("节点详情")
        detail_layout = QVBoxLayout(detail_group)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")

        detail_layout.addWidget(self.detail_text)

        # 节点操作按钮
        node_actions = QHBoxLayout()
        self.add_node_btn = QPushButton("添加节点")
        self.edit_node_btn = QPushButton("编辑节点")
        self.delete_node_btn = QPushButton("删除节点")

        self.add_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.edit_node_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.delete_node_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))

        node_actions.addWidget(self.add_node_btn)
        node_actions.addWidget(self.edit_node_btn)
        node_actions.addWidget(self.delete_node_btn)

        detail_layout.addLayout(node_actions)
        layout.addWidget(detail_group)

        # 图谱统计
        stats_group = QGroupBox("图谱统计")
        stats_layout = QVBoxLayout(stats_group)

        self.stats_label = QLabel("节点数量: 0\n关系数量: 0\n最后更新: 未知")
        self.stats_label.setStyleSheet("color: #cccccc; font-size: 12px;")

        stats_layout.addWidget(self.stats_label)
        layout.addWidget(stats_group)

        layout.addStretch()

        return panel

    def connect_signals(self):
        """连接信号"""
        # 图谱操作
        self.refresh_btn.clicked.connect(self.refresh_graph)
        self.export_btn.clicked.connect(self.export_graph)
        self.init_graph_btn.clicked.connect(self.initialize_graph)
        self.clear_graph_btn.clicked.connect(self.clear_graph)
        self.reset_view_btn.clicked.connect(self.reset_view)

        # 搜索功能
        self.search_btn.clicked.connect(self.search_nodes)
        self.clear_search_btn.clicked.connect(self.clear_search)
        self.search_input.returnPressed.connect(self.search_nodes)

        # 实体过滤
        filter_buttons = [self.filter_all_btn, self.filter_character_btn,
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]

        for btn in filter_buttons:
            btn.clicked.connect(self.filter_entities)

        # 实体列表
        self.entity_list.itemClicked.connect(self.on_entity_selected)
        self.entity_list.itemDoubleClicked.connect(self.focus_on_node)

        # 节点操作
        self.add_node_btn.clicked.connect(self.add_node)
        self.edit_node_btn.clicked.connect(self.edit_node)
        self.delete_node_btn.clicked.connect(self.delete_node)

    def refresh_graph(self):
        """刷新关系图谱（自动根据模式选择数据源）"""
        try:
            if getattr(self, 'tavern_mode', False) and getattr(self, 'tavern_session_id', None):
                logger.info(f"[Graph] 酒馆模式刷新，session={self.tavern_session_id}")
                # 使用API服务器的数据刷新，并直接返回，避免覆盖占位页流程
                self.refresh_from_api_server(self.tavern_session_id)
                return

            logger.info("[Graph] 本地模式刷新知识关系图谱...")
            # 重新加载实体和关系到知识图谱（确保同步，现在包含关系）
            self.memory.reload_entities_from_json()

            # 一次性获取所有实体数据，避免重复调用
            entities = self.get_all_entities()

            # 更新UI显示（传递数据避免重复获取）
            self.update_entity_list_with_data(entities)
            self.update_stats_with_data(entities)

            # 生成图谱HTML（传递数据避免重复获取）
            self.generate_graph_html_with_data(entities)

            # 加载到WebView
            if self.graph_file_path.exists():
                self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
        except Exception as e:
            logger.error(f"刷新图谱失败: {e}")
            QMessageBox.warning(self, "错误", f"刷新图谱失败：{str(e)}")

    def update_entity_list_with_data(self, entities, filter_type: str = "全部"):
        """使用提供的实体数据更新实体列表（避免重复获取）"""
        try:
            self.entity_list.clear()

            # 根据筛选条件过滤实体
            filtered_entities = []
            for entity in entities:
                if filter_type == "全部":
                    filtered_entities.append(entity)
                elif filter_type == "角色" and entity.get('type') == "character":
                    filtered_entities.append(entity)
                elif filter_type == "地点" and entity.get('type') == "location":
                    filtered_entities.append(entity)
                elif filter_type == "物品" and entity.get('type') == "item":
                    filtered_entities.append(entity)
                elif filter_type == "事件" and entity.get('type') == "event":
                    filtered_entities.append(entity)

            # 添加实体到列表
            for entity in filtered_entities:
                item_text = f"【{entity.get('type', '未知')}】{entity.get('name', '未命名')}"
                if entity.get('description'):
                    item_text += f" - {entity['description'][:50]}{'...' if len(entity['description']) > 50 else ''}"

                list_item = QListWidgetItem(item_text)
                list_item.setData(Qt.UserRole, entity)  # 存储完整的实体数据
                self.entity_list.addItem(list_item)

        except Exception as e:
            logger.error(f"更新实体列表失败: {e}")

    def update_stats_with_data(self, entities):
        """使用提供的实体数据更新统计信息（避免重复获取）"""
        try:
            node_count = len(entities)

            # 计算关系数量（简单估算：每个实体平均2个关系）
            relation_count = node_count * 2

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {relation_count}
最后更新: {current_time}"""

            if hasattr(self, 'stats_label'):
                self.stats_label.setText(stats_text)

        except Exception as e:
            logger.error(f"更新统计信息失败: {e}")

    def generate_graph_html_with_data(self, entities):
        """使用提供的实体数据生成图谱HTML文件（避免重复获取）"""
        try:
            # 构建节点和边的数据
            nodes = []
            links = []

            for i, entity in enumerate(entities):
                nodes.append({
                    'id': entity['name'],
                    'name': entity['name'],
                    'type': entity['type'],
                    'description': entity.get('description', ''),
                    'group': self._get_type_group(entity['type'])
                })

            # 获取知识图谱中的真实关系
            graph = self.memory.knowledge_graph.graph
            for source, target, attrs in graph.edges(data=True):
                relationship_type = attrs.get('relationship', 'related_to')
                links.append({
                    'source': source,
                    'target': target,
                    'relation': relationship_type
                })

            logger.info(f"从知识图谱获取了 {len(links)} 个关系连接")

            # 将数据转换为JSON字符串
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)

            # 使用HTML生成器生成文件
            self.html_generator.generate_graph_html(nodes_json, links_json, self.graph_file_path)

        except Exception as e:
            logger.error(f"生成图谱HTML失败: {e}")
            logger.error(f"错误详情: {traceback.format_exc()}")
            # 如果失败，使用HTML生成器的备用方案
            self.html_generator._generate_fallback_html(self.graph_file_path)

    def generate_graph_html(self):
        """生成图谱HTML文件（向后兼容方法）"""
        entities = self.get_all_entities()
        self.generate_graph_html_with_data(entities)

    def _get_type_group(self, entity_type):
        """获取实体类型的分组ID"""
        type_groups = {
            'character': 1,
            'location': 2,
            'item': 3,
            'event': 4,
            'concept': 5
        }
        return type_groups.get(entity_type, 5)

    def update_entity_list(self, filter_type: str = "全部"):
        """更新实体列表（向后兼容方法）"""
        entities = self.get_all_entities()
        self.update_entity_list_with_data(entities, filter_type)

    def get_all_entities(self):
        """获取所有实体（从知识图谱内存状态获取）"""
        try:
            entities = []

            # 在酒馆模式下，尝试从API服务器获取数据
            if hasattr(self, 'tavern_mode') and self.tavern_mode and hasattr(self, 'tavern_session_id') and self.tavern_session_id:
                try:
                    import requests
                    api_base_url = "http://127.0.0.1:9543"
                    export_url = f"{api_base_url}/sessions/{self.tavern_session_id}/export"

                    response = requests.get(export_url, timeout=10)
                    if response.status_code == 200:
                        graph_data = response.json()
                        graph_json = graph_data.get('graph_data', {})
                        nodes_data = graph_json.get('nodes', [])

                        for node_data in nodes_data:
                            entity = {
                                'name': node_data.get('id', ''),
                                'type': node_data.get('type', 'concept'),
                                'description': node_data.get('description', ''),
                                'created_time': time.time(),
                                'last_modified': time.time(),
                                'attributes': {}
                            }
                            entities.append(entity)

                        logger.info(f"📊 从API服务器获取 {len(entities)} 个实体")
                        return entities

                except Exception as api_error:
                    logger.warning(f"从API服务器获取实体失败: {api_error}")
                    # 继续使用本地内存数据作为备用方案

            # 直接从知识图谱内存中获取数据（本地模式或API失败时的备用方案）
            for node_id, attrs in self.memory.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': attrs.get('type', 'concept'),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }

                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value

                entities.append(entity)

            logger.info(f"📊 从知识图谱内存获取 {len(entities)} 个实体")
            return entities

        except Exception as e:
            logger.error(f"从知识图谱获取实体失败: {e}")
            return []

    def save_entities(self, entities):
        """保存实体数据"""
        entities_file = Path(__file__).parent / "data" / "entities.json"
        entities_file.parent.mkdir(exist_ok=True, parents=True)

        try:
            data = {
                'entities': entities,
                'last_modified': time.time()
            }
            with open(entities_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存实体数据失败: {e}")

    def _add_sample_entities(self):
        """添加示例实体（备用方案）"""
        sample_entities = [
            {"name": "克罗诺", "type": "character"},
            {"name": "利恩王国", "type": "location"},
            {"name": "传送装置", "type": "item"},
            {"name": "千年祭", "type": "event"},
            {"name": "玛尔", "type": "character"},
            {"name": "时空之门", "type": "location"},
        ]

        for entity in sample_entities:
            item_text = f"[{entity['type']}] {entity['name']}"
            self.entity_list.addItem(item_text)

    def update_stats(self):
        """更新图谱统计信息（向后兼容方法）"""
        entities = self.get_all_entities()
        self.update_stats_with_data(entities)

    def _get_type_group(self, entity_type):
        """获取实体类型的分组ID"""
        type_groups = {
            'character': 1,
            'location': 2,
            'item': 3,
            'event': 4,
            'concept': 5
        }
        return type_groups.get(entity_type, 5)

    def _generate_fallback_html(self):
        """生成备用的简化HTML"""
        # 使用HTML生成器生成备用HTML
        self.html_generator._generate_fallback_html(self.graph_file_path)

    def update_entity_list(self, filter_type: str = "全部"):
        """更新实体列表"""
        self.entity_list.clear()

        # 从实际的知识图谱获取数据
        try:
            all_entities = self.get_all_entities()

            # 根据筛选条件过滤实体
            filtered_entities = []
            for entity in all_entities:
                if filter_type == "全部":
                    filtered_entities.append(entity)
                elif filter_type == "角色" and entity['type'] == "character":
                    filtered_entities.append(entity)
                elif filter_type == "地点" and entity['type'] == "location":
                    filtered_entities.append(entity)
                elif filter_type == "物品" and entity['type'] == "item":
                    filtered_entities.append(entity)
                elif filter_type == "事件" and entity['type'] == "event":
                    filtered_entities.append(entity)

            # 添加到列表
            for entity in filtered_entities:
                item_text = f"[{entity['type']}] {entity['name']}"
                self.entity_list.addItem(item_text)

        except Exception as e:
            logger.error(f"更新实体列表失败: {e}")
            # 如果获取失败，显示示例数据
            self._add_sample_entities()

    def get_all_entities(self):
        """获取所有实体（从知识图谱内存状态获取）"""
        try:
            entities = []

            # 在酒馆模式下，尝试从API服务器获取数据
            if hasattr(self, 'tavern_mode') and self.tavern_mode and hasattr(self, 'tavern_session_id') and self.tavern_session_id:
                try:
                    import requests
                    api_base_url = "http://127.0.0.1:9543"
                    export_url = f"{api_base_url}/sessions/{self.tavern_session_id}/export"

                    response = requests.get(export_url, timeout=10)
                    if response.status_code == 200:
                        graph_data = response.json()
                        graph_json = graph_data.get('graph_data', {})
                        nodes_data = graph_json.get('nodes', [])

                        for node_data in nodes_data:
                            entity = {
                                'name': node_data.get('id', ''),
                                'type': node_data.get('type', 'concept'),
                                'description': node_data.get('description', ''),
                                'created_time': time.time(),
                                'last_modified': time.time(),
                                'attributes': {}
                            }
                            entities.append(entity)

                        logger.info(f"📊 从API服务器获取 {len(entities)} 个实体")
                        return entities

                except Exception as api_error:
                    logger.warning(f"从API服务器获取实体失败: {api_error}")
                    # 继续使用本地内存数据作为备用方案

            # 直接从知识图谱内存中获取数据（本地模式或API失败时的备用方案）
            for node_id, attrs in self.memory.knowledge_graph.graph.nodes(data=True):
                entity = {
                    'name': node_id,
                    'type': attrs.get('type', 'concept'),
                    'description': attrs.get('description', ''),
                    'created_time': attrs.get('created_time', time.time()),
                    'last_modified': attrs.get('last_modified', time.time()),
                    'attributes': {}
                }

                # 添加动态属性，排除系统属性
                excluded_keys = {'type', 'description', 'created_time', 'last_modified'}
                for key, value in attrs.items():
                    if key not in excluded_keys:
                        entity['attributes'][key] = value

                entities.append(entity)

            logger.info(f"📊 从知识图谱内存获取 {len(entities)} 个实体")
            return entities

        except Exception as e:
            logger.error(f"从知识图谱获取实体失败: {e}")
            return []

    def save_entities(self, entities):
        """保存实体数据"""
        entities_file = Path(__file__).parent / "data" / "entities.json"
        entities_file.parent.mkdir(exist_ok=True, parents=True)

        try:
            data = {
                'entities': entities,
                'last_modified': time.time()
            }
            with open(entities_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存实体数据失败: {e}")

    def _add_sample_entities(self):
        """添加示例实体（备用方案）"""
        sample_entities = [
            {"name": "克罗诺", "type": "character"},
            {"name": "利恩王国", "type": "location"},
            {"name": "传送装置", "type": "item"},
            {"name": "千年祭", "type": "event"},
            {"name": "玛尔", "type": "character"},
            {"name": "时空之门", "type": "location"},
        ]

        for entity in sample_entities:
            item_text = f"[{entity['type']}] {entity['name']}"
            self.entity_list.addItem(item_text)

    def search_nodes(self):
        """搜索节点"""
        search_term = self.search_input.text().strip()
        if not search_term:
            return

        try:
            all_entities = self.get_all_entities()
            matching_entities = []

            # 搜索匹配的实体
            for entity in all_entities:
                if (search_term.lower() in entity['name'].lower() or
                    search_term.lower() in entity.get('description', '').lower() or
                    search_term.lower() in entity['type'].lower()):
                    matching_entities.append(entity)

            # 更新实体列表显示搜索结果
            self.entity_list.clear()
            for entity in matching_entities:
                item_text = f"[{entity['type']}] {entity['name']}"
                self.entity_list.addItem(item_text)

            if not matching_entities:
                self.entity_list.addItem("未找到匹配的节点")

            logger.info(f"搜索节点: {search_term}, 找到 {len(matching_entities)} 个结果")

        except Exception as e:
            logger.error(f"搜索节点失败: {e}")
            QMessageBox.warning(self, "搜索错误", f"搜索失败：{str(e)}")

    def clear_search(self):
        """清除搜索"""
        self.search_input.clear()
        self.update_entity_list()

    def filter_entities(self):
        """过滤实体"""
        sender = self.sender()

        # 取消其他过滤按钮的选中状态
        filter_buttons = [self.filter_all_btn, self.filter_character_btn,
                         self.filter_location_btn, self.filter_item_btn, self.filter_event_btn]

        for btn in filter_buttons:
            if btn != sender:
                btn.setChecked(False)

        sender.setChecked(True)

        # 获取过滤类型并更新列表
        filter_type = sender.text()
        logger.info(f"过滤实体类型: {filter_type}")

        # 清除搜索框并应用过滤
        self.search_input.clear()
        self.update_entity_list(filter_type)

    def on_entity_selected(self, item):
        """实体被选中"""
        entity_name = item.text()

        # 如果是搜索结果为空的提示，不处理
        if entity_name == "未找到匹配的节点":
            self.detail_text.clear()
            return

        try:
            # 解析实体信息
            if '] ' in entity_name:
                entity_type = entity_name.split('[')[1].split(']')[0]
                entity_display_name = entity_name.split('] ', 1)[1]
            else:
                entity_type = "未知"
                entity_display_name = entity_name

            # 从存储中获取完整实体信息
            all_entities = self.get_all_entities()
            selected_entity = None

            for entity in all_entities:
                if entity['name'] == entity_display_name and entity['type'] == entity_type:
                    selected_entity = entity
                    break

            if selected_entity:
                import datetime
                created_time = datetime.datetime.fromtimestamp(
                    selected_entity.get('created_time', time.time())
                ).strftime("%Y-%m-%d %H:%M:%S")

                # 构建属性详情
                attributes = selected_entity.get('attributes', {})
                if attributes:
                    attr_lines = []
                    for key, value in attributes.items():
                        attr_lines.append(f"  • {key}: {value}")
                    attr_text = "\n".join(attr_lines)
                else:
                    attr_text = "  暂无属性"

                detail_text = f"""节点信息:
名称: {selected_entity['name']}
类型: {selected_entity['type']}
描述: {selected_entity.get('description', '暂无描述')}
创建时间: {created_time}
属性:
{attr_text}"""

            else:
                # 备用显示
                detail_text = f"""节点信息:
名称: {entity_display_name}
类型: {entity_type}
创建时间: 未知
描述: 暂无描述
属性: 暂无数据"""

            self.detail_text.setText(detail_text)
            self.current_selected_node = entity_name

        except Exception as e:
            logger.error(f"显示节点详情失败: {e}")
            self.detail_text.setText(f"显示详情时出错：{str(e)}")
            self.current_selected_node = entity_name

    def focus_on_node(self, item):
        """聚焦到节点"""
        entity_name = item.text()

        if entity_name == "未找到匹配的节点":
            return

        # 在WebView中执行JavaScript来高亮节点
        try:
            if '] ' in entity_name:
                node_name = entity_name.split('] ', 1)[1]
            else:
                node_name = entity_name

            # 执行JavaScript来聚焦节点
            js_code = f"""
            // 查找并高亮节点
            const targetNode = d3.selectAll('.node').filter(d => d.name === '{node_name}');
            if (!targetNode.empty()) {{
                const nodeData = targetNode.datum();

                // 将视图中心移动到节点位置
                const svg = d3.select('#graph');
                const transform = d3.zoomTransform(svg.node());
                const scale = Math.max(1, transform.k);

                svg.transition().duration(1000).call(
                    zoom.transform,
                    d3.zoomIdentity
                        .translate(width / 2 - nodeData.x * scale, height / 2 - nodeData.y * scale)
                        .scale(scale)
                );

                // 高亮节点
                targetNode.transition().duration(300)
                    .attr('r', 30)
                    .style('stroke-width', '4px')
                    .style('stroke', '#ff6b6b');

                // 恢复正常大小
                setTimeout(() => {{
                    targetNode.transition().duration(300)
                        .attr('r', 20)
                        .style('stroke-width', '2px')
                        .style('stroke', '#fff');
                }}, 1500);
            }}
            """

            self.graph_view.page().runJavaScript(js_code)
            logger.info(f"聚焦到节点: {node_name}")

        except Exception as e:
            logger.error(f"聚焦节点失败: {e}")

    def add_node(self):
        """添加节点 - 使用Qt原生对话框"""
        try:
            # 直接使用Qt编辑对话框，isNewNode=True表示新增模式
            self.edit_node_with_python_dialog("", "character", is_new_node=True)
            logger.info("打开Qt新增节点对话框")
        except Exception as e:
            logger.error(f"打开Qt新增节点对话框失败: {e}")
            QMessageBox.warning(self, "错误", f"打开对话框失败：{str(e)}")

    def edit_node(self):
        """编辑节点 - 直接使用Python备用编辑对话框"""
        if not self.current_selected_node:
            QMessageBox.information(
                self,
                "提示",
                "请先在实体列表中选择一个节点。"
            )
            return

        # 解析当前选中的节点信息
        node_text = self.current_selected_node

        # 提取节点名称和类型
        if '] ' in node_text:
            entity_type = node_text.split('[')[1].split(']')[0]
            entity_name = node_text.split('] ', 1)[1]
        else:
            entity_name = node_text
            entity_type = "concept"

        logger.info(f"编辑节点: {entity_name} (类型: {entity_type})")

        # 直接使用Python备用编辑方案
        self.edit_node_with_python_dialog(entity_name, entity_type)

    def edit_node_with_python_dialog(self, entity_name: str, entity_type: str, is_new_node: bool = False):
        """使用Python/Qt的完整编辑对话框，支持动态属性"""
        try:
            if is_new_node:
                # 新增模式：创建空实体
                current_entity = {
                    'name': entity_name or '',
                    'type': entity_type or 'character',
                    'description': '',
                    'attributes': {},
                    'created_time': time.time()
                }
                dialog_title = "新增节点"
                success_msg = "节点创建成功"
            else:
                # 编辑模式：获取现有实体数据
                all_entities = self.get_all_entities()
                current_entity = None

                for entity in all_entities:
                    if entity['name'] == entity_name and entity['type'] == entity_type:
                        current_entity = entity
                        break

                if not current_entity:
                    QMessageBox.warning(self, "错误", f"找不到实体: {entity_name}")
                    return

                dialog_title = f"编辑节点: {entity_name}"
                success_msg = "节点更新成功"

            # 创建增强的编辑对话框
            dialog = QDialog(self)
            dialog.setWindowTitle(dialog_title)
            dialog.setMinimumSize(500, 400)
            dialog.setMaximumSize(800, 600)

            # 主布局
            main_layout = QVBoxLayout(dialog)

            # 基本信息分组
            basic_group = QGroupBox("基本信息")
            basic_layout = QFormLayout(basic_group)

            # 名称
            name_edit = QLineEdit(current_entity['name'])
            name_edit.setPlaceholderText("请输入节点名称")
            basic_layout.addRow("名称 *:", name_edit)

            # 类型
            type_combo = QComboBox()
            type_combo.addItems(["character", "location", "item", "event", "concept"])
            type_combo.setCurrentText(current_entity['type'])
            basic_layout.addRow("类型:", type_combo)

            # 描述
            desc_edit = QTextEdit(current_entity.get('description', ''))
            desc_edit.setMaximumHeight(80)
            desc_edit.setPlaceholderText("描述该节点的特征、属性等...")
            basic_layout.addRow("描述:", desc_edit)

            main_layout.addWidget(basic_group)

            # 动态属性分组
            attr_group = QGroupBox("动态属性")
            attr_layout = QVBoxLayout(attr_group)

            # 创建滚动区域
            from PySide6.QtWidgets import QScrollArea
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(200)  # 限制最大高度
            scroll_area.setMinimumHeight(120)  # 设置最小高度
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            # 设置滚动条样式
            scroll_area.setStyleSheet("""
                QScrollArea {
                    border: 1px solid #444;
                    border-radius: 5px;
                    background-color: #2b2b2b;
                }
                QScrollBar:vertical {
                    background-color: #3c3c3c;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #666;
                    border-radius: 6px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #888;
                }
            """)

            # 属性列表容器widget
            attr_scroll = QWidget()
            attr_scroll.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                }
            """)
            attr_scroll_layout = QVBoxLayout(attr_scroll)
            attr_scroll_layout.setSpacing(8)  # 增加行间距
            attr_scroll_layout.setContentsMargins(5, 5, 5, 5)  # 添加边距

            # 设置滚动区域的内容widget
            scroll_area.setWidget(attr_scroll)

            # 存储属性行的列表
            self.attr_rows = []

            def add_attribute_row(key='', value=''):
                """添加一行属性编辑"""
                row_widget = QWidget()
                row_widget.setMinimumHeight(40)  # 设置最小高度
                row_widget.setMaximumHeight(50)  # 设置最大高度
                row_widget.setStyleSheet("""
                    QWidget {
                        background-color: #2b2b2b;
                        border-radius: 3px;
                    }
                """)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(2, 2, 2, 2)
                row_layout.setSpacing(8)

                # 属性名输入框
                key_edit = QLineEdit(key)
                key_edit.setPlaceholderText("属性名")
                key_edit.setMinimumWidth(120)
                key_edit.setMaximumWidth(150)
                key_edit.setMinimumHeight(30)

                # 属性值输入框
                value_edit = QLineEdit(value)
                value_edit.setPlaceholderText("属性值")
                value_edit.setMinimumHeight(30)

                # 删除按钮
                delete_btn = QPushButton("删除")
                delete_btn.setMinimumWidth(60)
                delete_btn.setMaximumWidth(80)
                delete_btn.setMinimumHeight(30)
                delete_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")

                def remove_row():
                    if len(self.attr_rows) > 1:  # 至少保留一行
                        # 从列表中移除这一行
                        self.attr_rows.remove((key_edit, value_edit, row_widget))

                        # 完全重建布局
                        rebuild_layout()

                def rebuild_layout():
                    """重建整个属性布局"""
                    # 清除现有的所有widgets
                    while attr_scroll_layout.count():
                        child = attr_scroll_layout.takeAt(0)
                        if child.widget():
                            child.widget().deleteLater()
                        elif child.spacerItem():
                            # 移除spacer
                            pass

                    # 重新添加所有剩余的行
                    for key_edit, value_edit, old_widget in self.attr_rows:
                        # 获取当前值
                        key_val = key_edit.text()
                        value_val = value_edit.text()

                        # 创建新的行widget
                        new_row_widget = QWidget()
                        new_row_widget.setMinimumHeight(40)
                        new_row_widget.setMaximumHeight(50)
                        new_row_widget.setStyleSheet("""
                            QWidget {
                                background-color: #2b2b2b;
                                border-radius: 3px;
                            }
                        """)
                        new_row_layout = QHBoxLayout(new_row_widget)
                        new_row_layout.setContentsMargins(2, 2, 2, 2)
                        new_row_layout.setSpacing(8)

                        # 创建新的控件
                        new_key_edit = QLineEdit(key_val)
                        new_key_edit.setPlaceholderText("属性名")
                        new_key_edit.setMinimumWidth(120)
                        new_key_edit.setMaximumWidth(150)
                        new_key_edit.setMinimumHeight(30)

                        new_value_edit = QLineEdit(value_val)
                        new_value_edit.setPlaceholderText("属性值")
                        new_value_edit.setMinimumHeight(30)

                        new_delete_btn = QPushButton("删除")
                        new_delete_btn.setMinimumWidth(60)
                        new_delete_btn.setMaximumWidth(80)
                        new_delete_btn.setMinimumHeight(30)
                        new_delete_btn.setStyleSheet("QPushButton { background-color: #e74c3c; }")
                        new_delete_btn.clicked.connect(lambda checked, ke=new_key_edit, ve=new_value_edit, rw=new_row_widget: remove_specific_row(ke, ve, rw))

                        # 添加到布局
                        new_row_layout.addWidget(QLabel("属性:"))
                        new_row_layout.addWidget(new_key_edit)
                        new_row_layout.addWidget(QLabel("值:"))
                        new_row_layout.addWidget(new_value_edit)
                        new_row_layout.addWidget(new_delete_btn)

                        attr_scroll_layout.addWidget(new_row_widget)

                        # 更新列表中的引用
                        idx = self.attr_rows.index((key_edit, value_edit, old_widget))
                        self.attr_rows[idx] = (new_key_edit, new_value_edit, new_row_widget)

                    # 重新添加spacer
                    from PySide6.QtWidgets import QSpacerItem, QSizePolicy
                    spacer = QSpacerItem(1, 1, QSizePolicy.Minimum, QSizePolicy.Expanding)
                    attr_scroll_layout.addItem(spacer)

                def remove_specific_row(ke, ve, rw):
                    """删除指定行"""
                    if len(self.attr_rows) > 1:
                        self.attr_rows.remove((ke, ve, rw))
                        rebuild_layout()

                delete_btn.clicked.connect(remove_row)

                # 添加标签和控件
                row_layout.addWidget(QLabel("属性:"))
                row_layout.addWidget(key_edit)
                row_layout.addWidget(QLabel("值:"))
                row_layout.addWidget(value_edit)
                row_layout.addWidget(delete_btn)

                attr_scroll_layout.addWidget(row_widget)
                self.attr_rows.append((key_edit, value_edit, row_widget))

                return key_edit, value_edit

            # 加载现有属性
            existing_attrs = current_entity.get('attributes', {})
            if existing_attrs:
                for key, value in existing_attrs.items():
                    add_attribute_row(key, str(value))
            else:
                # 如果没有属性，添加一个空行
                add_attribute_row()

            # 在属性列表末尾添加弹簧，确保内容顶部对齐
            # 使用QSpacerItem而不是addStretch()，这样删除widget时布局会自动调整
            from PySide6.QtWidgets import QSpacerItem, QSizePolicy
            spacer = QSpacerItem(1, 1, QSizePolicy.Minimum, QSizePolicy.Expanding)
            attr_scroll_layout.addItem(spacer)

            # 添加滚动区域到属性组布局
            attr_layout.addWidget(scroll_area)

            # 添加属性按钮
            add_attr_btn = QPushButton("+ 添加属性")
            add_attr_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
            add_attr_btn.clicked.connect(lambda: add_attribute_row())
            attr_layout.addWidget(add_attr_btn)

            main_layout.addWidget(attr_group)

            # 按钮区域
            button_layout = QHBoxLayout()
            button_layout.addStretch()

            cancel_btn = QPushButton("取消")
            cancel_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogCancelButton))
            cancel_btn.clicked.connect(dialog.reject)

            save_btn = QPushButton("保存" if not is_new_node else "创建")
            save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            save_btn.setStyleSheet("QPushButton { background-color: #4a90e2; font-weight: bold; }")

            def save_changes():
                # 验证输入
                new_name = name_edit.text().strip()
                if not new_name:
                    QMessageBox.warning(dialog, "验证错误", "节点名称不能为空！")
                    name_edit.setFocus()
                    return

                # 收集动态属性
                new_attributes = {}
                for key_edit, value_edit, _ in self.attr_rows:
                    key = key_edit.text().strip()
                    value = value_edit.text().strip()
                    if key and value:  # 只保存非空的属性
                        new_attributes[key] = value

                # 更新或创建实体数据
                current_entity['name'] = new_name
                current_entity['type'] = type_combo.currentText()
                current_entity['description'] = desc_edit.toPlainText().strip()
                current_entity['attributes'] = new_attributes
                current_entity['last_modified'] = time.time()

                if is_new_node:
                    # 添加新实体
                    all_entities = self.get_all_entities()
                    all_entities.append(current_entity)
                    self.save_entities(all_entities)
                    logger.info(f"创建新节点: {new_name} (类型: {type_combo.currentText()})")
                else:
                    # 更新现有实体
                    all_entities = self.get_all_entities()

                    # 找到并更新对应的实体
                    entity_updated = False
                    for i, entity in enumerate(all_entities):
                        if entity['name'] == entity_name and entity['type'] == entity_type:
                            # 更新找到的实体
                            all_entities[i] = current_entity
                            entity_updated = True
                            logger.info(f"找到并更新实体: {entity_name} -> {new_name}")
                            break

                    if not entity_updated:
                        logger.warning(f"未找到要更新的实体: {entity_name} ({entity_type})")
                        QMessageBox.warning(dialog, "更新失败", f"未找到要更新的实体: {entity_name}")
                        return

                    self.save_entities(all_entities)
                    logger.info(f"实体更新成功: {new_name} (类型: {type_combo.currentText()})")

                    # 同步更新知识图谱中的节点
                    try:
                        # 如果名称改变了，需要先删除旧节点，再创建新节点
                        if new_name != entity_name:
                            # 删除旧节点
                            if self.memory.knowledge_graph.graph.has_node(entity_name):
                                self.memory.knowledge_graph.graph.remove_node(entity_name)
                                logger.info(f"删除旧节点: {entity_name}")

                        # 创建或更新新节点
                        self.memory.knowledge_graph.add_or_update_node(
                            new_name,
                            current_entity['type'],
                            description=current_entity['description'],
                            **current_entity['attributes']
                        )
                        logger.info(f"同步更新知识图谱节点成功: {new_name}")
                    except Exception as e:
                        logger.warning(f"同步知识图谱失败: {e}")

                # 更新界面（refresh_graph 已包含更新实体列表和统计）
                self.refresh_graph()  # 刷新图谱显示

                # 同步到知识图谱
                try:
                    # 获取主窗口实例
                    main_window = None
                    widget = self.parent()
                    while widget is not None:
                        if isinstance(widget, ChronoForgeMainWindow):
                            main_window = widget
                            break
                        widget = widget.parent()

                    if main_window and hasattr(main_window, 'memory'):
                        # 重新加载实体到知识图谱
                        main_window.memory.reload_entities_from_json()
                        logger.info("✅ 实体修改已同步到知识图谱")
                except Exception as e:
                    logger.warning(f"⚠️ 同步到知识图谱失败: {e}")

                QMessageBox.information(dialog, "成功", success_msg)
                dialog.accept()

            save_btn.clicked.connect(save_changes)

            button_layout.addWidget(cancel_btn)
            button_layout.addWidget(save_btn)
            main_layout.addLayout(button_layout)

            # 设置默认焦点
            name_edit.setFocus()

            # 显示对话框
            dialog.exec()

        except Exception as e:
            logger.error(f"Qt编辑对话框失败: {e}")
            QMessageBox.critical(self, "错误", f"编辑失败: {str(e)}")

    def delete_node(self):
        """删除节点"""
        if not self.current_selected_node:
            QMessageBox.warning(self, "提示", "请先选择一个节点")
            return

        # 解析节点名称
        node_text = self.current_selected_node
        if '] ' in node_text:
            node_name = node_text.split('] ', 1)[1]
        else:
            node_name = node_text

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除节点 '{node_name}' 吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 从实际存储中删除节点
            if '] ' in node_text:
                entity_type = node_text.split('[')[1].split(']')[0]
                entity_name = node_text.split('] ', 1)[1]
            else:
                entity_name = node_text
                entity_type = "concept"

            all_entities = self.get_all_entities()
            entity_index = -1
            for i, entity in enumerate(all_entities):
                if entity['name'] == entity_name and entity['type'] == entity_type:
                    entity_index = i
                    break

            if entity_index >= 0:
                # 删除实体
                removed_entity = all_entities.pop(entity_index)
                self.save_entities(all_entities)

                # 清除选择状态
                self.current_selected_node = None
                self.detail_text.clear()
                self.detail_text.setPlaceholderText("选择一个节点查看详细信息...")

                # 更新实体列表和统计
                self.update_entity_list()
                self.update_stats()

                QMessageBox.information(self, "成功", f"节点 '{entity_name}' 删除成功")
                logger.info(f"删除节点: {entity_name}")
            else:
                QMessageBox.warning(self, "错误", "找不到要删除的节点")

    def export_graph(self):
        """导出图谱"""
        try:
            # 选择导出文件位置
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出知识图谱",
                str(Path.home() / "knowledge_graph.json"),
                "JSON 文件 (*.json);;所有文件 (*.*)"
            )

            if not file_path:
                return

            # 获取所有实体数据
            entities = self.get_all_entities()

            # 构建导出数据
            export_data = {
                'metadata': {
                    'title': 'ChronoForge Knowledge Graph',
                    'created_by': 'ChronoForge',
                    'export_time': time.time(),
                    'version': '1.0.0'
                },
                'entities': entities,
                'statistics': {
                    'total_entities': len(entities),
                    'entity_types': {}
                }
            }

            # 统计各类型实体数量
            for entity in entities:
                entity_type = entity.get('type', 'unknown')
                export_data['statistics']['entity_types'][entity_type] = \
                    export_data['statistics']['entity_types'].get(entity_type, 0) + 1

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self,
                "导出成功",
                f"知识图谱已导出到：\n{file_path}\n\n包含 {len(entities)} 个实体"
            )
            logger.info(f"知识图谱导出成功: {file_path}")

        except Exception as e:
            logger.error(f"导出图谱失败: {e}")
            QMessageBox.critical(self, "导出失败", f"导出失败：{str(e)}")

    def reset_view(self):
        """重置视图"""
        try:
            # 在WebView中执行JavaScript重置视图
            js_code = """
            if (typeof resetZoom === 'function') {
                resetZoom();
            }
            """
            self.graph_view.page().runJavaScript(js_code)
            logger.info("图谱视图已重置")

        except Exception as e:
            logger.error(f"重置视图失败: {e}")
            # 如果JavaScript执行失败，重新生成图谱
            self.refresh_graph()

    def clear_graph(self):
        """清空知识图谱"""
        reply = QMessageBox.question(
            self,
            "确认清空",
            "确定要清空当前的知识图谱吗？\n\n此操作将删除所有实体和关系，无法撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            try:
                if self.tavern_mode and self.tavern_session_id:
                    # 酒馆模式下：通过API清空当前会话的图谱
                    import requests
                    api_url = f"http://127.0.0.1:9543/sessions/{self.tavern_session_id}/clear"
                    response = requests.post(api_url, timeout=10)
                    if response.status_code == 200:
                        logger.info("通过API成功清空酒馆会话知识图谱")
                        # 刷新显示
                        self.refresh_from_api_server(self.tavern_session_id)
                    else:
                        raise Exception(f"API清空失败: {response.status_code}")
                else:
                    # 本地模式下：清空内存中的知识图谱
                    self.memory.clear_all()
                    # 刷新显示（已包含统计信息更新）
                    self.refresh_graph()

                QMessageBox.information(self, "清空完成", "知识图谱已成功清空。")
                logger.info("知识图谱已清空")

            except Exception as e:
                logger.error(f"清空知识图谱失败: {e}")
                QMessageBox.warning(self, "清空失败", f"清空知识图谱时出现错误：\n{str(e)}")

    def initialize_graph(self):
        """初始化知识图谱"""
        if self.tavern_mode:
            # --- 酒馆模式下的重新初始化 ---
            if not self.tavern_session_id:
                QMessageBox.warning(self, "操作失败", "无法重新初始化：未找到有效的酒馆会话ID。")
                return

            reply = QMessageBox.question(
                self,
                "确认操作",
                "这将重新初始化知识图谱，确定要继续吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

            try:
                logger.info(f"🚀 [UI] Starting tavern graph initialization for session: {self.tavern_session_id}")

                # 直接调用重新初始化API
                logger.info(f"🔄 [UI] Calling coordinated re-initialization API for session: {self.tavern_session_id}")
                api_url = f"http://127.0.0.1:9543/tavern/sessions/{self.tavern_session_id}/request_reinitialize"

                response = requests.post(api_url, timeout=5)

                if response.status_code == 200:
                    result = response.json()
                    QMessageBox.information(
                        self,
                        "重新初始化已启动",
                        f"知识图谱重新初始化已开始。\n\n{result.get('message', '请稍等片刻...')}"
                    )
                    # 刷新图谱
                    QTimer.singleShot(3000, self.refresh_graph)
                else:
                    try:
                        error_msg = response.json().get("detail", response.text)
                    except:
                        error_msg = response.text[:200]
                    QMessageBox.warning(self, "初始化失败", f"重新初始化失败 (HTTP {response.status_code}):\n{error_msg}")

            except Exception as api_error:
                logger.error(f"❌ [UI] API call failed: {api_error}")
                QMessageBox.warning(self, "网络问题", f"无法连接到服务器，请检查ChronoForge服务是否运行")

        else:
            # --- 本地模式下的初始化 ---
            reply = QMessageBox.question(
                self,
                "初始化知识图谱",
                "是否要创建默认的游戏开局？\n\n这将清空现有图谱并创建新的世界设定。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.create_default_scenario_for_graph()

    def reinitialize_tavern_character_graph(self):
        """重新初始化酒馆角色的知识图谱"""
        try:
            logger.info(f"🍺 重新初始化酒馆角色知识图谱，会话ID: {self.tavern_session_id}")

            # 获取主窗口实例
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()

            if not main_window:
                QMessageBox.warning(self, "初始化失败", "无法找到主窗口实例")
                return

            # 清空当前知识图谱
            if hasattr(main_window, 'memory'):
                main_window.memory.clear_all()
                logger.info("🧹 已清空知识图谱，准备重新获取酒馆数据")

            # 从API服务器重新获取角色数据
            import requests
            api_base_url = "http://127.0.0.1:9543"

            # 调用API服务器的角色初始化端点
            init_url = f"{api_base_url}/sessions/{self.tavern_session_id}/reinitialize"

            response = requests.post(init_url, timeout=30)

            if response.status_code == 200:
                result = response.json()
                nodes_created = result.get('nodes_created', 0)
                edges_created = result.get('edges_created', 0)
                character_name = result.get('character_name', '未知角色')

                logger.info(f"✅ 酒馆角色图谱重新初始化成功: {character_name}, 节点={nodes_created}, 边={edges_created}")

                # 刷新UI显示 - 从API服务器获取最新数据
                self.refresh_from_api_server(self.tavern_session_id)

                QMessageBox.information(
                    self,
                    "初始化成功",
                    f"酒馆角色 '{character_name}' 的知识图谱已重新初始化！\n\n"
                    f"创建了 {nodes_created} 个节点和 {edges_created} 个关系。"
                )

            else:
                error_text = response.text
                logger.error(f"❌ 酒馆角色图谱重新初始化失败: HTTP {response.status_code} - {error_text}")
                QMessageBox.warning(
                    self,
                    "初始化失败",
                    f"无法重新初始化酒馆角色图谱：\nHTTP {response.status_code}\n\n{error_text}"
                )

        except requests.exceptions.Timeout:
            logger.error("⏱️ 酒馆角色图谱初始化超时")
            QMessageBox.warning(self, "初始化超时", "重新初始化请求超时，请检查API服务器状态")

        except Exception as e:
            logger.error(f"💥 酒馆角色图谱重新初始化异常: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            QMessageBox.critical(self, "初始化异常", f"重新初始化时发生异常：\n{str(e)}")

    def create_default_scenario_for_graph(self):
        """为知识图谱创建默认场景（不依赖对话ID）"""
        try:
            # 使用主窗口的方法创建默认开局
            main_window = None
            widget = self.parent()
            while widget is not None:
                if isinstance(widget, ChronoForgeMainWindow):
                    main_window = widget
                    break
                widget = widget.parent()

            if main_window:
                # 先清空现有图谱
                self.memory.clear_all()

                # 创建默认开局
                main_window.create_default_game_scenario("manual_init")

                # 只需要刷新图谱显示，refresh_graph内部会更新实体列表和统计信息
                self.refresh_graph()
                logger.info("✅ 知识图谱初始化完成，页面已刷新")
            else:
                QMessageBox.warning(self, "初始化失败", "无法找到主窗口实例。")

        except Exception as e:
            logger.error(f"初始化知识图谱失败: {e}")
            QMessageBox.warning(self, "初始化失败", f"初始化知识图谱时出现错误：\n{str(e)}")

    def open_dev_tools(self):
        """打开开发者工具"""
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView

            # 创建开发者工具窗口
            if not hasattr(self, 'dev_view'):
                self.dev_view = QWebEngineView()
                self.dev_view.setWindowTitle("开发者工具 - ChronoForge Graph")
                self.dev_view.resize(1000, 600)

            # 设置开发者工具页面
            self.graph_view.page().setDevToolsPage(self.dev_view.page())
            self.dev_view.show()

            logger.info("开发者工具已打开")

        except Exception as e:
            logger.error(f"打开开发者工具失败: {e}")
            QMessageBox.warning(self, "错误", f"无法打开开发者工具：{str(e)}")

    def show_debug_info(self):
        """显示调试信息"""
        try:
            # 执行JavaScript获取调试信息
            js_code = """
            if (typeof window.debugGraph === 'function') {
                window.debugGraph();
                // 返回一些基本信息
                {
                    d3_loaded: typeof d3 !== 'undefined',
                    d3_version: typeof d3 !== 'undefined' ? d3.version : 'not loaded',
                    nodes_count: typeof nodes !== 'undefined' ? nodes.length : 'undefined',
                    links_count: typeof links !== 'undefined' ? links.length : 'undefined',
                    edit_mode: typeof editMode !== 'undefined' ? editMode : 'undefined',
                    selected_node: typeof selectedNode !== 'undefined' && selectedNode ? selectedNode.datum().name : 'none',
                    webchannel_bridge: typeof bridge !== 'undefined' ? 'available' : 'not available'
                };
            } else {
                { error: 'debugGraph function not available' };
            }
            """

            def show_result(result):
                if result:
                    import json
                    debug_text = json.dumps(result, indent=2, ensure_ascii=False)
                    QMessageBox.information(self, "调试信息", f"图谱状态：\n{debug_text}")
                else:
                    QMessageBox.information(self, "调试信息", "无法获取调试信息")

            self.graph_view.page().runJavaScript(js_code, show_result)

        except Exception as e:
            logger.error(f"显示调试信息失败: {e}")
            QMessageBox.warning(self, "错误", f"获取调试信息失败：{str(e)}")

    def enter_tavern_mode(self, session_id: str):
        """进入酒馆模式，切换到使用API服务器的数据源"""
        self.tavern_mode = True
        self.tavern_session_id = session_id

        # 清理本地模式的数据显示
        self.clear_graph_display()

        logger.info(f"GraphPage进入酒馆模式，会话ID: {session_id}")

    def exit_tavern_mode(self):
        """退出酒馆模式，切换回本地数据源"""
        self.tavern_mode = False
        self.tavern_session_id = None

        # 清理酒馆模式的数据显示
        self.clear_graph_display()

        # 重新初始化内存对象，确保指向本地模式路径
        try:
            from pathlib import Path
            from src.memory import GRAGMemory

            base_path = Path(__file__).parent / "data"
            local_mode_path = base_path / "local_mode"
            local_mode_path.mkdir(exist_ok=True)

            # 重新创建内存对象，指向本地模式
            self.memory = GRAGMemory(
                hot_memory_size=10,
                graph_save_path=str(local_mode_path / "knowledge_graph.graphml"),
                entities_json_path=str(local_mode_path / "entities.json"),
                auto_load_entities=True
            )

            logger.info(f"已切换内存对象到本地模式路径: {local_mode_path}")

        except Exception as e:
            logger.error(f"重新初始化本地模式内存对象失败: {e}")

        # 重新加载本地模式的数据
        self.refresh_graph()

        logger.info("GraphPage退出酒馆模式，切换回本地数据源")

    def clear_graph_display(self):
        """清理图谱显示数据"""
        try:
            # 清空图谱显示
            self.graph_view.setHtml("<html><body><p>Loading...</p></body></html>")

            # 清空实体列表
            if hasattr(self, 'entity_list'):
                self.entity_list.clear()

            # 重置统计信息
            if hasattr(self, 'stats_label'):
                self.stats_label.setText("节点: 0 | 关系: 0")

            logger.info("已清理图谱显示数据")
        except Exception as e:
            logger.error(f"清理图谱显示失败: {e}")

    def refresh_from_api_server(self, session_id: str):
        """从API服务器获取知识图谱数据并刷新显示"""
        try:
            logger.info(f"从API服务器获取会话 {session_id} 的知识图谱数据...")

            import requests

            # 获取会话统计信息
            api_base_url = "http://127.0.0.1:9543"  # TODO: 从配置获取
            stats_url = f"{api_base_url}/sessions/{session_id}/stats"

            response = requests.get(stats_url, timeout=10)
            if response.status_code == 200:
                stats = response.json()
                logger.info(f"成功获取会话统计: 节点={stats.get('graph_nodes', 0)}, 边={stats.get('graph_edges', 0)}")

                # 获取会话的知识图谱导出数据
                export_url = f"{api_base_url}/sessions/{session_id}/export"
                export_response = requests.get(export_url, timeout=30)

                if export_response.status_code == 200:
                    graph_data = export_response.json()
                    logger.info("成功获取知识图谱导出数据")

                    # 从导出的图谱数据生成HTML显示
                    self._generate_graph_html_from_api_data(graph_data)

                    # 加载图谱HTML
                    if self.graph_file_path.exists():
                        self.graph_view.load(QUrl.fromLocalFile(str(self.graph_file_path)))
                        logger.info("知识图谱HTML已加载到WebView")

                    # 更新实体列表和统计
                    self._update_ui_from_api_data(graph_data)
                else:
                    logger.warning(f"无法获取图谱导出数据: HTTP {export_response.status_code}")
                    # 尝试仅使用统计数据更新UI
                    self._update_ui_from_stats_only(stats)
                    self._show_tavern_mode_placeholder(session_id, stats)
            else:
                logger.warning(f"无法获取会话统计: HTTP {response.status_code}")
                self._show_tavern_mode_placeholder(session_id, {"graph_nodes": 0, "graph_edges": 0})

        except Exception as e:
            logger.error(f"从API服务器刷新图谱失败: {e}")
            self._show_tavern_mode_placeholder(session_id, {"graph_nodes": 0, "graph_edges": 0})

    def _generate_graph_html_from_api_data(self, graph_data: dict):
        """从API数据生成图谱HTML"""
        try:
            # 解析导出的图谱数据
            graph_json = graph_data.get('graph_data', {})
            nodes_data = graph_json.get('nodes', [])
            links_data = graph_json.get('links', [])

            # 转换为我们的显示格式
            nodes = []
            for node_data in nodes_data:
                node = {
                    'id': node_data.get('id', ''),
                    'name': node_data.get('id', ''),
                    'type': node_data.get('type', 'concept'),
                    'description': node_data.get('description', ''),
                    'group': self._get_type_group(node_data.get('type', 'concept'))
                }
                nodes.append(node)

            # 转换链接数据
            links = []
            for link_data in links_data:
                link = {
                    'source': link_data.get('source', ''),
                    'target': link_data.get('target', ''),
                    'relation': link_data.get('relationship', 'related_to')
                }
                links.append(link)

            logger.info(f"转换API数据: {len(nodes)} 个节点, {len(links)} 个连接")

            # 生成JSON字符串
            nodes_json = json.dumps(nodes, ensure_ascii=False)
            links_json = json.dumps(links, ensure_ascii=False)

            # 使用HTML生成器生成文件
            self.html_generator.generate_graph_html(nodes_json, links_json, self.graph_file_path)

        except Exception as e:
            logger.error(f"从API数据生成图谱HTML失败: {e}")
            # 使用备用方案
            self.html_generator._generate_fallback_html(self.graph_file_path)

    def _update_ui_from_stats_only(self, stats: dict):
        """仅从统计数据更新UI（当无法获取完整图谱数据时的备用方案）"""
        try:
            logger.info("使用统计数据更新UI（备用方案）")

            # 更新统计信息
            node_count = stats.get('graph_nodes', 0)
            edge_count = stats.get('graph_edges', 0)

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {edge_count}
最后更新: {current_time}
数据源: API服务器"""

            self.stats_label.setText(stats_text)

            # 清空实体列表并显示占位信息
            self.entity_list.clear()
            if node_count > 0:
                self.entity_list.addItem(f"[酒馆] 检测到 {node_count} 个实体")
                self.entity_list.addItem("请刷新图谱获取详细信息")
            else:
                self.entity_list.addItem("暂无实体数据")

            logger.info(f"UI已更新（仅统计数据）: {node_count} 节点, {edge_count} 边")

        except Exception as e:
            logger.error(f"从统计数据更新UI失败: {e}")

    def _update_ui_from_api_data(self, graph_data: dict):
        """从API数据更新UI组件"""
        try:
            # 更新统计信息
            stats = graph_data.get('graph_stats', {})
            node_count = stats.get('nodes', 0)
            edge_count = stats.get('edges', 0)

            import datetime
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            stats_text = f"""节点数量: {node_count}
关系数量: {edge_count}
最后更新: {current_time}
数据源: API服务器"""

            self.stats_label.setText(stats_text)

            # 更新实体列表（从图谱数据中提取）
            self.entity_list.clear()
            graph_json = graph_data.get('graph_data', {})
            nodes_data = graph_json.get('nodes', [])

            for node_data in nodes_data:
                node_type = node_data.get('type', 'concept')
                node_name = node_data.get('id', '')

                # 类型映射
                type_display_map = {
                    'character': '角色',
                    'location': '地点',
                    'item': '物品',
                    'event': '事件',
                    'concept': '概念'
                }

                display_type = type_display_map.get(node_type, node_type)
                item_text = f"[{display_type}] {node_name}"
                self.entity_list.addItem(item_text)

            logger.info(f"已更新UI: {len(nodes_data)} 个实体")

        except Exception as e:
            logger.error(f"从API数据更新UI失败: {e}")

    def _show_tavern_mode_placeholder(self, session_id: str, stats: dict):
        """显示酒馆模式的占位信息"""
        try:
            # 创建简单的酒馆模式信息页面
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>ChronoForge - 酒馆模式</title>
                <style>
                    body {{
                        font-family: 'Microsoft YaHei', Arial, sans-serif;
                        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                        color: white;
                        text-align: center;
                        padding: 50px;
                        margin: 0;
                    }}
                    .container {{
                        max-width: 600px;
                        margin: 0 auto;
                        background: rgba(255,255,255,0.1);
                        padding: 40px;
                        border-radius: 20px;
                        backdrop-filter: blur(10px);
                    }}
                    h1 {{ color: #4fc3f7; margin-bottom: 20px; }}
                    h2 {{ color: #81c784; margin: 30px 0 15px 0; }}
                    .stats {{
                        display: flex;
                        justify-content: space-around;
                        margin: 30px 0;
                    }}
                    .stat {{
                        text-align: center;
                        background: rgba(255,255,255,0.1);
                        padding: 20px;
                        border-radius: 10px;
                        min-width: 100px;
                    }}
                    .stat-number {{
                        font-size: 2em;
                        font-weight: bold;
                        color: #4fc3f7;
                    }}
                    .info {{
                        background: rgba(255,255,255,0.1);
                        padding: 20px;
                        border-radius: 10px;
                        margin: 20px 0;
                        text-align: left;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🍺 酒馆模式已激活</h1>
                    <p>ChronoForge正在与SillyTavern协作，提供智能对话增强服务</p>

                    <h2>📊 当前会话统计</h2>
                    <div class="stats">
                        <div class="stat">
                            <div class="stat-number">{stats.get('graph_nodes', 0)}</div>
                            <div>知识节点</div>
                        </div>
                        <div class="stat">
                            <div class="stat-number">{stats.get('graph_edges', 0)}</div>
                            <div>关系边</div>
                        </div>
                        <div class="stat">
                            <div class="stat-number">{stats.get('hot_memory_size', 0)}</div>
                            <div>记忆轮次</div>
                        </div>
                    </div>

                    <div class="info">
                        <h3>🔗 会话信息</h3>
                        <p><strong>会话ID:</strong> {session_id}</p>
                        <p><strong>状态:</strong> 活跃连接</p>
                        <p><strong>模式:</strong> SillyTavern集成</p>
                    </div>

                    <div class="info">
                        <h3>ℹ️ 使用说明</h3>
                        <p>• 在SillyTavern中进行对话，ChronoForge会自动提供智能增强</p>
                        <p>• 知识图谱会根据对话内容动态更新</p>
                        <p>• 可以随时在ChronoForge主界面切换回本地模式</p>
                    </div>
                </div>
            </body>
            </html>
            """

            # 写入临时HTML文件
            temp_file = Path("temp_tavern_graph.html")
            temp_file.write_text(html_content, encoding='utf-8')

            # 加载到WebView
            self.graph_view.load(QUrl.fromLocalFile(str(temp_file.absolute())))

            logger.info("酒馆模式占位页面已显示")

        except Exception as e:
            logger.error(f"显示酒馆模式占位页面失败: {e}")


class ConfigPage(QWidget):
    """系统配置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_path = Path(__file__).parent / '.env'
        self.init_ui()
        self.load_config()

    def init_ui(self):
        layout = QFormLayout(self)

        # LLM配置
        self.api_base_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.stream_checkbox = QCheckBox("启用流式输出")

        # 服务器配置
        self.api_server_port_input = QLineEdit()
        self.api_server_port_input.setValidator(QIntValidator(1024, 65535, self))

        # 酒馆连接配置组
        tavern_group = QGroupBox("SillyTavern连接配置")
        tavern_layout = QFormLayout(tavern_group)

        self.tavern_host_input = QLineEdit()
        self.tavern_port_input = QLineEdit()
        self.tavern_port_input.setValidator(QIntValidator(1024, 65535, self))

        # 测试连接按钮
        self.test_tavern_btn = QPushButton("测试酒馆连接")
        self.test_tavern_btn.clicked.connect(self.test_tavern_connection)

        # 连接状态标签
        self.tavern_status_label = QLabel("未测试")
        self.tavern_status_label.setStyleSheet("color: #888888;")

        tavern_layout.addRow("酒馆地址:", self.tavern_host_input)
        tavern_layout.addRow("酒馆端口:", self.tavern_port_input)
        tavern_layout.addRow("连接状态:", self.tavern_status_label)
        tavern_layout.addRow("", self.test_tavern_btn)

        # 保存按钮
        self.save_button = QPushButton("保存配置")
        self.save_button.clicked.connect(self.save_config)

        # 添加到布局
        layout.addRow("API接口地址:", self.api_base_url_input)
        layout.addRow("API密钥:", self.api_key_input)
        layout.addRow("默认模型:", self.model_input)
        layout.addRow("", self.stream_checkbox)
        layout.addRow("API服务器端口:", self.api_server_port_input)
        layout.addWidget(tavern_group)  # 添加酒馆配置组
        layout.addRow("", self.save_button)

    def load_config(self):
        """加载配置"""
        if not self.env_path.exists():
            self.env_path.touch()

        config = dotenv_values(self.env_path)
        self.api_base_url_input.setText(config.get("OPENAI_API_BASE_URL", ""))
        self.api_key_input.setText(config.get("OPENAI_API_KEY", ""))
        self.model_input.setText(config.get("DEFAULT_MODEL", "deepseek-v3.1"))

        stream_val = config.get("LLM_STREAM_OUTPUT", "false").lower()
        self.stream_checkbox.setChecked(stream_val in ('true', '1', 't'))

        self.api_server_port_input.setText(config.get("API_SERVER_PORT", "9543"))

        # 加载酒馆配置
        self.tavern_host_input.setText(config.get("SILLYTAVERN_HOST", "localhost"))
        self.tavern_port_input.setText(config.get("SILLYTAVERN_PORT", "8000"))

    def save_config(self):
        """保存配置"""
        try:
            set_key(self.env_path, "OPENAI_API_BASE_URL", self.api_base_url_input.text())
            set_key(self.env_path, "OPENAI_API_KEY", self.api_key_input.text())
            set_key(self.env_path, "DEFAULT_MODEL", self.model_input.text())
            set_key(self.env_path, "LLM_STREAM_OUTPUT", str(self.stream_checkbox.isChecked()).lower())
            set_key(self.env_path, "API_SERVER_PORT", self.api_server_port_input.text())

            # 保存酒馆配置
            set_key(self.env_path, "SILLYTAVERN_HOST", self.tavern_host_input.text())
            set_key(self.env_path, "SILLYTAVERN_PORT", self.tavern_port_input.text())

            QMessageBox.information(self, "成功", "配置保存成功")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"配置保存失败：{str(e)}")

    def test_tavern_connection(self):
        """测试酒馆连接"""
        try:
            host = self.tavern_host_input.text().strip() or "localhost"
            port = self.tavern_port_input.text().strip() or "8000"

            self.tavern_status_label.setText("测试中...")
            self.tavern_status_label.setStyleSheet("color: #f39c12;")
            self.test_tavern_btn.setEnabled(False)
            QApplication.processEvents()

            # 创建临时连接器进行测试
            from src.tavern.tavern_connector import SillyTavernConnector, TavernConfig

            config = TavernConfig(host=host, port=int(port), timeout=5)
            connector = SillyTavernConnector(config)

            result = connector.test_connection()

            if result["status"] == "connected":
                self.tavern_status_label.setText("✅ 连接成功")
                self.tavern_status_label.setStyleSheet("color: #27ae60;")

                version = result.get("version", {})
                QMessageBox.information(
                    self,
                    "连接成功",
                    f"成功连接到SillyTavern！\n\n"
                    f"地址: {result['url']}\n"
                    f"版本: {version.get('version', '未知')}"
                )
            else:
                self.tavern_status_label.setText("❌ 连接失败")
                self.tavern_status_label.setStyleSheet("color: #e74c3c;")

                QMessageBox.warning(
                    self,
                    "连接失败",
                    f"无法连接到SillyTavern:\n\n{result['error']}\n\n"
                    f"请确保SillyTavern正在运行并检查地址和端口是否正确。"
                )

            connector.disconnect()

        except ValueError as e:
            self.tavern_status_label.setText("❌ 配置错误")
            self.tavern_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "配置错误", f"端口必须是数字：{e}")

        except Exception as e:
            self.tavern_status_label.setText("❌ 测试异常")
            self.tavern_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.critical(self, "测试异常", f"测试连接时发生异常：{e}")

        finally:
            self.test_tavern_btn.setEnabled(True)


class ChronoForgeMainWindow(QMainWindow):
    """ChronoForge主窗口"""

    def __init__(self):
        super().__init__()

        # 读取配置
        self.env_path = Path(__file__).parent / '.env'
        config = dotenv_values(self.env_path) if self.env_path.exists() else {}
        self.api_server_port = int(config.get("API_SERVER_PORT", "9543"))

        # 模式切换标志，防止自动初始化干扰
        self.switching_modes = False

        # 初始化核心组件
        self.init_components()

        # 初始化管理器
        self.init_managers()

        # 启动API服务器
        self.start_api_server()
        # 在启动或连接到已有API服务器后，强制关闭酒馆模式，确保默认本地隔离
        try:
            import requests
            requests.post(f"http://localhost:{self.api_server_port}/system/tavern_mode", json={"active": False}, timeout=3)
        except Exception:
            pass


        # 初始化UI
        self.init_ui()

        # 设置窗口属性
        WindowManager.setup_window(self)

    def init_components(self):
        """初始化核心组件"""
        logger.info("初始化ChronoForge核心组件...")

        try:
            # 初始化核心系统 - 本地模式使用独立目录
            base_path = Path(__file__).parent / "data"
            local_mode_path = base_path / "local_mode"  # 本地模式专用目录
            local_mode_path.mkdir(exist_ok=True)

            self.memory = GRAGMemory(
                hot_memory_size=10,
                graph_save_path=str(local_mode_path / "knowledge_graph.graphml"),
                entities_json_path=str(local_mode_path / "entities.json"),  # 本地模式专用路径
                auto_load_entities=True  # 本地模式需要加载已有的对话数据
            )
            self.perception = PerceptionModule()
            self.rpg_processor = RPGTextProcessor()
            self.validation_layer = ValidationLayer()

            # 创建游戏引擎
            self.game_engine = GameEngine(
                self.memory,
                self.perception,
                self.rpg_processor,
                self.validation_layer
            )

            # 初始化酒馆模式管理器
            self.tavern_manager = TavernModeManager(self.game_engine)

            logger.info("核心组件初始化完成")

        except Exception as e:
            logger.error(f"核心组件初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化核心组件：\n{e}")
            sys.exit(1)

    def init_managers(self):
        """初始化管理器组件"""
        try:
            # 场景管理器
            self.scenario_manager = ScenarioManager(
                self.memory,
                self.perception,
                self.rpg_processor,
                self.validation_layer
            )

            # 资源清理管理器
            self.cleanup_manager = ResourceCleanupManager(self)

            logger.info("管理器组件初始化完成")

        except Exception as e:
            logger.error(f"管理器初始化失败: {e}")
            QMessageBox.critical(self, "初始化错误", f"无法初始化管理器组件：\n{e}")
            sys.exit(1)

    def check_api_server_running(self):
        """检查API服务器是否已经在运行"""
        try:
            import requests
            # 尝试连接到健康检查端点
            response = requests.get(f"http://localhost:{self.api_server_port}/system/liveness", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            # 连接失败，说明服务器没有运行
            return False
        except Exception as e:
            logger.warning(f"检查API服务器状态时出错: {e}")
            return False

    def start_api_server(self):
        """启动API服务器"""
        try:
            # 首先检查API服务器是否已经在运行
            if self.check_api_server_running():
                logger.info(f"📡 API服务器已在端口 {self.api_server_port} 运行，跳过启动")
                self.api_server_process = None  # 标记为外部进程
                return

            api_server_path = str(Path(__file__).parent / "api_server.py")
            command = [sys.executable, api_server_path, "--port", str(self.api_server_port)]

            logger.info(f"🚀 启动API服务器: {' '.join(command)}")

            # Windows上创建独立进程组
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

            self.api_server_process = subprocess.Popen(
                command,
                creationflags=creation_flags
            )

            logger.info(f"✅ API服务器已启动，PID: {self.api_server_process.pid}")

            # 等待服务器启动
            time.sleep(3)

        except Exception as e:
            logger.error(f"❌ API服务器启动失败: {e}")
            QMessageBox.critical(self, "启动错误", f"无法启动API服务器：\n{e}\n请检查日志获取详细信息。")

    def init_ui(self):
        """初始化用户界面"""
        # 创建标签页
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 智能对话页面
        self.play_page = IntegratedPlayPage(self.game_engine)
        self.tabs.addTab(self.play_page, "智能对话")

        # 知识图谱页面
        self.graph_page = GraphPage(self.memory)
        self.tabs.addTab(self.graph_page, "知识图谱")

        # 系统配置页面
        self.config_page = ConfigPage()
        self.tabs.addTab(self.config_page, "系统配置")

        # 设置对话和知识图谱的联动
        self.setup_cross_page_connections()

    def setup_cross_page_connections(self):
        """设置页面间的联动连接"""
        # 当对话切换时，刷新知识图谱
        self.play_page.conversation_manager.conversation_changed.connect(
            self.on_conversation_changed
        )

    def on_conversation_changed(self, conv_id: str):
        """处理对话切换事件"""
        logger.info(f"对话切换到: {conv_id}")

        # 如果正在切换模式，跳过自动初始化
        if self.switching_modes:
            logger.info("正在切换模式，跳过对话自动初始化")
            return

        # 如果conv_id为空，说明没有剩余对话
        if not conv_id:
            logger.info("没有剩余对话，保持当前状态")
            return

        # 获取对话信息
        conv = self.play_page.conversation_manager.conversations.get(conv_id)
        if not conv:
            logger.warning(f"对话 {conv_id} 不存在")
            return

        # 检查对话是否有消息内容
        messages = conv.get('messages', [])

        if not messages:
            # 新对话或空对话 - 询问是否创建默认开局
            logger.info("这是一个空对话，询问是否创建默认开局")
            self.prompt_initialize_knowledge_graph(conv_id)
        else:
            # 有内容的对话 - 不做任何操作，保持当前知识图谱
            logger.info("切换到有内容的对话，保持当前知识图谱状态")

    def load_conversation_knowledge_graph(self, conv_id: str) -> bool:
        """加载对话相关的知识图谱 - 暂时简化实现"""
        # TODO: 未来可以实现真正的对话-图谱关联机制
        # 现在先简化，只在真正需要时才处理
        return True  # 默认返回True，表示加载成功

    def prompt_initialize_knowledge_graph(self, conv_id: str):
        """提示用户初始化知识图谱"""
        # 防止重复调用的标志
        if hasattr(self, '_initializing_knowledge_graph') and self._initializing_knowledge_graph:
            logger.info("知识图谱正在初始化中，跳过重复调用")
            return

        try:
            self._initializing_knowledge_graph = True

            # 获取对话名称以便更好地提示用户
            conv = self.play_page.conversation_manager.conversations.get(conv_id)
            conv_name = conv.get('name', '当前对话') if conv else '当前对话'

            reply = QMessageBox.question(
                self,
                "知识图谱初始化",
                f"对话 \"{conv_name}\" 还没有开始。\n\n是否要创建默认的奇幻游戏开局来开始你的冒险？\n\n点击\"否\"将保持当前知识图谱状态。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if reply == QMessageBox.Yes:
                self.create_default_game_scenario(conv_id)
        finally:
            self._initializing_knowledge_graph = False

    def create_default_game_scenario(self, conv_id: str):
        """为对话创建默认游戏开局"""
        try:
            logger.info(f"为对话 {conv_id} 创建默认游戏开局")

            # 使用场景管理器创建超时空之轮场景
            opening_story, entity_count, relationship_count = self.scenario_manager.create_chrono_trigger_scenario()

            # 刷新图谱显示（已包含更新实体列表和统计）
            self.graph_page.refresh_graph()
            logger.info("✅ 知识图谱页面已刷新")

            # 在聊天界面显示开场故事
            self.play_page.chat_display.add_message(opening_story, False)  # False表示不是用户消息

            # 将开场故事保存到对话历史中
            self.play_page.conversation_manager.add_message({
                'role': 'assistant',
                'content': opening_story
            })

            # 显示成功消息
            self.scenario_manager.show_scenario_success_message(self, entity_count, relationship_count)

        except Exception as e:
            logger.error(f"创建默认游戏开局失败: {e}")
            self.scenario_manager.show_scenario_error_message(self, e)


    def closeEvent(self, event):
        """关闭事件处理"""
        # 关闭API日志文件
        if hasattr(self, 'api_log_file') and self.api_log_file:
            try:
                logger.info("📝 Closing API log file...")
                self.api_log_file.close()
                self.api_log_file = None
            except Exception as e:
                logger.error(f"❌ Error closing API log file: {e}")

        success = self.cleanup_manager.cleanup_all_resources()
        if success:
            event.accept()
        else:
            event.accept()  # 即使出错也要关闭


def main():
    """主函数"""
    # 配置详细日志系统
    from loguru import logger

    # 清除默认配置
    logger.remove()

    # 添加控制台输出（显示所有级别）
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True
    )

    # 添加文件输出（详细记录）
    logger.add(
        "logs/chronoforge_ui_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip"
    )

    # 添加专门的酒馆模式日志
    logger.add(
        "logs/tavern_mode_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
        filter=lambda record: "酒馆" in record["message"] or "tavern" in record["message"].lower() or "🍺" in record["message"],
        rotation="5 MB",
        retention="7 days"
    )

    logger.info("🚀 ========== ChronoForge UI 启动 ==========")
    logger.info(f"📋 Python版本: {sys.version}")
    logger.info(f"📋 启动参数: {sys.argv}")

    # 确保日志目录存在
    import os
    os.makedirs("logs", exist_ok=True)

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoForge")
    app.setApplicationVersion("1.0.0")

    # 设置深色主题
    logger.info("🎨 应用深色主题...")
    WindowManager.apply_dark_theme(app)

    # 创建主窗口
    try:
        logger.info("🏗️ 创建主窗口...")
        window = ChronoForgeMainWindow()
        window.show()

        logger.info("✅ ChronoForge UI 启动完成")
        logger.info("🍺 ========== 准备就绪，等待用户操作 ==========")

        # 运行应用
        exit_code = app.exec()

        logger.info("🏁 ========== ChronoForge UI 退出 ==========")
        logger.info(f"📋 退出代码: {exit_code}")

        sys.exit(exit_code)

    except Exception as e:
        logger.error("💥 ========== ChronoForge UI 启动失败 ==========")
        logger.error(f"📋 异常详情: {e}")
        logger.error(f"📋 完整堆栈: {traceback.format_exc()}")

        QMessageBox.critical(None, "启动错误", f"ChronoForge启动失败：\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()