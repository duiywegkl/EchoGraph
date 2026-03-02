import sys
from pathlib import Path

from loguru import logger

# Add project root to Python path for local execution.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.core.game_engine import GameEngine
from src.core.perception import PerceptionModule
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.validation import ValidationLayer
from src.memory import GRAGMemory


def setup_logger() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logger.remove()
    logger.add(sys.stdout, level="INFO")


def run_chinese_test_demo() -> None:
    logger.info("--- EchoGraph Chinese entity extraction demo ---")

    graph_dir = Path("data/memory")
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_path = graph_dir / "world_graph.graphml"
    entities_path = graph_dir / "entities.json"

    logger.info("[1/4] Initializing core components...")
    memory = GRAGMemory(
        graph_save_path=str(graph_path),
        entities_json_path=str(entities_path),
        auto_load_entities=False,
    )
    perception = PerceptionModule()
    rpg_processor = RPGTextProcessor()
    validation_layer = ValidationLayer()
    engine = GameEngine(memory, perception, rpg_processor, validation_layer)

    logger.info("[2/4] Seeding base graph...")
    memory.add_or_update_node(
        "elara",
        "character",
        name="Elara",
        aliases=["艾拉"],
        status="mysterious",
        occupation="shopkeeper",
    )
    memory.add_or_update_node(
        "elaras_shop",
        "location",
        name="Elara's Shop",
        aliases=["艾拉的商店"],
        description="A small shop full of mysterious items.",
    )
    memory.add_edge("elara", "elaras_shop", "works_at")

    user_input = "我想和艾拉聊聊，她现在在哪里？"
    llm_response = "艾拉正在她的商店里整理药草，你可以在柜台前找到她。"

    logger.info("[3/4] Processing one conversation turn...")
    update_result = engine.extract_updates_from_response(
        llm_response=llm_response,
        user_input=user_input,
    )
    memory.add_conversation(user_input, llm_response)

    logger.info("[4/4] Persisting memory...")
    memory.save_all_memory()

    print("\n--- Update Result ---")
    print(update_result)
    print("\n--- Final Knowledge Graph ---")
    print(memory.knowledge_graph.to_text_representation())


if __name__ == "__main__":
    setup_logger()
    run_chinese_test_demo()
