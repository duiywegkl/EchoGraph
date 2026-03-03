from typing import Dict, Any

from loguru import logger


class TextProcessor:
    """
    Legacy compatibility wrapper.

    Graph maintenance is LLM-only via GRAGUpdateAgent.
    Local rule/regex extraction is intentionally disabled.
    """

    def __init__(self) -> None:
        logger.info(
            "TextProcessor initialized in LLM-only mode. "
            "Local rule/regex extraction is disabled."
        )

    def extract_entities_and_relations(self, text: str) -> Dict[str, Any]:
        logger.warning(
            "TextProcessor.extract_entities_and_relations is disabled by policy. "
            "Use GRAGUpdateAgent/LLM pipeline for graph updates."
        )
        return {"nodes_to_add": [], "edges_to_add": []}

    def extract_state_updates(self, text: str) -> Dict[str, Any]:
        logger.warning(
            "TextProcessor.extract_state_updates is disabled by policy. "
            "Use GRAGUpdateAgent/LLM pipeline for graph updates."
        )
        return {"nodes_to_update": [], "edges_to_add": []}
