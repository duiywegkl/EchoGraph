import sys
import os
from loguru import logger

# 将项目根目录添加到Python路径中
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.memory import GRAGMemory
from src.core.perception import PerceptionModule
from src.core.llm_client import LLMClient
from src.core.game_engine import GameEngine
from src.core.validation import ValidationLayer

def setup_logger():
    """配置logger，确保日志输出到控制台。"""
    logger.remove()
    logger.add(sys.stdout, level="INFO")

def run_chinese_test_demo():
    """运行一个完整的游戏回合，测试中文实体的感知能力。"""
    logger.info("--- EchoGraph 中文感知能力测试 ---")

    # 1. 初始化所有核心组件
    logger.info("[1/4] 初始化核心组件...")
    graph_path = "data/memory/world_graph.graphml"
    memory = GRAGMemory(graph_save_path=graph_path)
    perception = PerceptionModule()
    llm_client = LLMClient()
    # 假设ValidationLayer已存在且可用
    validation_layer = ValidationLayer()

    # 2. 初始化游戏引擎
    logger.info("[2/4] 初始化游戏引擎...")
    engine = GameEngine(memory, perception, llm_client, validation_layer)

    # 3. 开始游戏并设置带有中文别名的实体
    logger.info("正在设置带有中文别名的知识图谱...")
    # 为已有角色添加中文别名，或创建新角色
    memory.add_or_update_node("elara", "character", name="Elara", aliases=["艾拉"], status="mysterious", occupation="shopkeeper")
    memory.add_or_update_node("elaras_shop", "location", name="Elara's Shop", aliases=["艾拉的商店"], description="一家充满神秘气息的小店")
    memory.add_edge("elara", "elaras_shop", "works_at")
    
    welcome_message = engine.start_game(character_name="凯尔") # 使用中文角色名
    print(f"\n--- 游戏开始 ---\n{welcome_message}\n--------------------\n")

    # 4. 执行一个使用中文别名的游戏回合
    logger.info("[3/4] 准备执行中文输入回合...")
    
    user_input = "我想和艾拉聊聊，她在哪里？"
    print(f"> 玩家输入: {user_input}\n")
    
    # GameEngine处理整个回合
    ai_response = engine.process_turn(user_input)
    
    logger.info("\n[4/4] 回合处理完毕。")
    print(f"\n--- DM 回应 ---\n{ai_response}\n------------------\n")

    # 打印知识图谱以供检查
    print("\n--- 最终知识图谱 ---")
    print(memory.knowledge_graph.to_text_representation())
    print("--------------------------")

if __name__ == "__main__":
    setup_logger()
    run_chinese_test_demo()
