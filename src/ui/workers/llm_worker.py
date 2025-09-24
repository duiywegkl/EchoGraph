"""
LLM工作线程
处理LLM请求，避免UI阻塞
"""
from PySide6.QtCore import QThread, Signal
from loguru import logger


class LLMWorkerThread(QThread):
    """LLM处理工作线程，避免UI阻塞"""
    
    # 定义信号
    response_ready = Signal(str)  # LLM回复准备好
    error_occurred = Signal(str)  # 发生错误
    grag_data_ready = Signal(dict)  # GRAG数据准备好
    
    def __init__(self, engine, message):
        super().__init__()
        self.engine = engine
        self.message = message
        self.grag_data = {}
    
    def run(self):
        """在后台线程中执行LLM处理"""
        try:
            from src.core.llm_client import LLMClient
            
            # 1. 感知用户输入中的实体
            logger.info(f"[SEARCH] [GRAG] 开始分析用户输入: {self.message}")
            
            perceived_entities = self.engine.perception_module.perceive_entities(self.message)
            logger.info(f"[TARGET] [GRAG] 感知到 {len(perceived_entities)} 个相关实体: {perceived_entities}")
            
            # 2. 构建知识图谱上下文
            logger.info(f"[LINK] [GRAG] 开始构建知识图谱上下文...")
            context = self.engine.memory.get_context_for_entities(perceived_entities)
            logger.info(f"[LOG] [GRAG] 构建的上下文长度: {len(context)} 字符")
            
            # 3. 准备GRAG数据供UI显示
            self.grag_data = {
                'entities': perceived_entities,
                'context_length': len(context)
            }
            self.grag_data_ready.emit(self.grag_data)
            
            # 4. 调用LLM生成回复
            logger.info(f"💭 [LLM] 开始生成回复...")
            llm_client = LLMClient()
            
            # 构建完整的提示词
            full_prompt = self.engine._build_full_prompt(self.message, context)
            
            # 调用LLM
            response = llm_client.generate_response(full_prompt)
            logger.info(f"[OK] [LLM] 回复生成完成，长度: {len(response)} 字符")
            
            # 发送回复信号
            self.response_ready.emit(response)
            
        except Exception as e:
            error_msg = f"LLM处理失败: {str(e)}"
            logger.error(f"❌ [GRAG] {error_msg}")
            self.error_occurred.emit(error_msg)