"""
资源清理管理器
处理应用程序关闭时的资源清理
"""
import subprocess
from loguru import logger


class ResourceCleanupManager:
    """资源清理管理器，处理应用关闭时的资源清理"""
    
    def __init__(self, main_window):
        self.main_window = main_window
    
    def cleanup_all_resources(self):
        """清理所有资源"""
        try:
            # 清理LLM工作线程
            self.cleanup_llm_threads()
            
            # 关闭API服务器进程
            self.cleanup_api_server()
            
            # 保存数据
            self.save_application_data()
            
            logger.info("[TARGET] EchoGraph已安全关闭")
            return True
            
        except Exception as e:
            logger.error(f"关闭程序时发生错误: {e}")
            return False
    
    def cleanup_llm_threads(self):
        """清理LLM工作线程"""
        try:
            if hasattr(self.main_window, 'play_page') and hasattr(self.main_window.play_page, 'llm_worker'):
                if self.main_window.play_page.llm_worker and self.main_window.play_page.llm_worker.isRunning():
                    logger.info("🧹 正在清理LLM工作线程...")
                    self.main_window.play_page.llm_worker.terminate()
                    self.main_window.play_page.llm_worker.wait(3000)  # 等待最多3秒
                    self.main_window.play_page.llm_worker.deleteLater()
                    logger.info("[OK] LLM工作线程已清理")
        except Exception as e:
            logger.warning(f"清理LLM线程时出错: {e}")
    
    def cleanup_api_server(self):
        """关闭API服务器进程"""
        try:
            # 检查是否是我们启动的进程
            if hasattr(self.main_window, 'api_server_process') and self.main_window.api_server_process:
                logger.info("🔄 正在关闭UI启动的API服务器...")

                # 获取进程PID用于后续检查
                pid = self.main_window.api_server_process.pid
                logger.info(f"[LOG] API服务器PID: {pid}")

                # 首先尝试优雅关闭
                try:
                    self.main_window.api_server_process.terminate()
                    logger.info("📤 已发送SIGTERM信号")

                    # 等待进程结束，最多等待5秒
                    self.main_window.api_server_process.wait(timeout=5)
                    logger.info("[OK] API服务器已正常关闭")

                except subprocess.TimeoutExpired:
                    logger.warning("[WARN] API服务器未响应SIGTERM，尝试强制终止...")
                    try:
                        self.main_window.api_server_process.kill()
                        self.main_window.api_server_process.wait(timeout=3)
                        logger.info("[OK] API服务器已强制关闭")
                    except subprocess.TimeoutExpired:
                        logger.error("❌ 无法终止API服务器进程，可能需要手动清理")

                        # 在Windows上尝试使用taskkill
                        import sys
                        if sys.platform == "win32":
                            try:
                                import subprocess
                                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                             check=False, capture_output=True)
                                logger.info("🔨 已使用taskkill强制终止进程")
                            except Exception as e:
                                logger.error(f"taskkill失败: {e}")

                # 清理进程句柄
                self.main_window.api_server_process = None

            elif hasattr(self.main_window, 'api_server_process') and self.main_window.api_server_process is None:
                logger.info("📡 API服务器由外部启动，UI不进行关闭操作")
            else:
                logger.info("[SEARCH] 未找到API服务器进程句柄")

            # 额外检查：尝试检测端口占用并清理
            self._cleanup_port_if_needed()

        except Exception as e:
            logger.warning(f"❌ 关闭API服务器时出错: {e}")

    def _cleanup_port_if_needed(self):
        """检查并清理端口占用"""
        try:
            import sys
            port = getattr(self.main_window, 'api_server_port', 9543)

            if sys.platform == "win32":
                # Windows: 使用netstat查找占用端口的进程
                result = subprocess.run(
                    ["netstat", "-ano", "-p", "TCP"],
                    capture_output=True, text=True, check=False
                )

                for line in result.stdout.split('\n'):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            logger.warning(f"[SEARCH] 发现端口{port}仍被PID {pid}占用")

                            # 尝试终止占用端口的进程
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", pid],
                                             check=False, capture_output=True)
                                logger.info(f"🔨 已清理占用端口{port}的进程 PID {pid}")
                            except Exception as e:
                                logger.error(f"清理端口占用失败: {e}")
                            break
            else:
                # Linux/Mac: 使用lsof查找占用端口的进程
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True, check=False
                )

                if result.stdout.strip():
                    pid = result.stdout.strip()
                    logger.warning(f"[SEARCH] 发现端口{port}仍被PID {pid}占用")

                    try:
                        subprocess.run(["kill", "-9", pid], check=False)
                        logger.info(f"🔨 已清理占用端口{port}的进程 PID {pid}")
                    except Exception as e:
                        logger.error(f"清理端口占用失败: {e}")

        except Exception as e:
            logger.debug(f"端口清理检查失败: {e}")  # 使用debug级别，因为这不是关键错误
    
    def save_application_data(self):
        """保存应用程序数据"""
        try:
            if hasattr(self.main_window, 'memory') and self.main_window.memory:
                self.main_window.memory.save_all_memory()
                logger.info("知识图谱已保存")
        except Exception as e:
            logger.warning(f"保存数据时出错: {e}")