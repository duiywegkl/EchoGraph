from typing import Any, Dict

from loguru import logger


class RPGTextProcessor:
    """
    Compatibility wrapper kept for older call sites.

    Graph maintenance is LLM-only via GRAGUpdateAgent. Local regex extraction
    is intentionally disabled.
    """

    def __init__(self) -> None:
        logger.info(
            "RPGTextProcessor initialized in LLM-only mode. "
            "Local regex graph extraction is disabled."
        )

    def extract_rpg_entities_and_relations(self, text: str) -> Dict[str, Any]:
        """
        Deprecated no-op method.

        Returns an empty update payload so existing integrations do not break.
        """
        text = text or ""
        logger.warning(
            "extract_rpg_entities_and_relations is disabled by policy. "
            "Use GRAGUpdateAgent/LLM pipeline for graph updates."
        )
        return {
            "nodes_to_add": [],
            "edges_to_add": [],
            "nodes_to_delete": [],
            "edges_to_delete": [],
            "deletion_events": [],
            "processing_stats": {
                "mode": "llm_only",
                "text_length": len(text),
                "entities_found": 0,
                "relations_found": 0,
                "node_deletions_found": 0,
                "edge_deletions_found": 0,
            },
        }
