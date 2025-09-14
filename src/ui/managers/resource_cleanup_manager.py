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
            
            logger.info("🎯 ChronoForge已安全关闭")
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
                    logger.info("✅ LLM工作线程已清理")
        except Exception as e:
            logger.warning(f"清理LLM线程时出错: {e}")
    
    def cleanup_api_server(self):
        """关闭API服务器进程"""
        try:
            # 检查是否是我们启动的进程
            if hasattr(self.main_window, 'api_server_process') and self.main_window.api_server_process:
                logger.info("🔄 正在关闭UI启动的API服务器...")
                self.main_window.api_server_process.terminate()
                
                # 等待进程结束，最多等待5秒
                try:
                    self.main_window.api_server_process.wait(timeout=5)
                    logger.info("✅ API服务器已正常关闭")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ API服务器未响应，强制终止...")
                    self.main_window.api_server_process.kill()
                    self.main_window.api_server_process.wait()
                    logger.info("✅ API服务器已强制关闭")
            elif hasattr(self.main_window, 'api_server_process') and self.main_window.api_server_process is None:
                logger.info("📡 API服务器由外部启动，UI不进行关闭操作")
            else:
                logger.info("🔍 未找到API服务器进程句柄")
        except Exception as e:
            logger.warning(f"❌ 关闭API服务器时出错: {e}")
    
    def save_application_data(self):
        """保存应用程序数据"""
        try:
            if hasattr(self.main_window, 'memory') and self.main_window.memory:
                self.main_window.memory.save_all_memory()
                logger.info("知识图谱已保存")
        except Exception as e:
            logger.warning(f"保存数据时出错: {e}")