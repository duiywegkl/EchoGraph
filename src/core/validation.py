from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger


class ValidationLayer:
    """Knowledge-graph update validator with structural and semantic checks."""

    # Known node types used by current extractors and graph pipeline.
    KNOWN_NODE_TYPES: Set[str] = {
        "character",
        "weapon",
        "armor",
        "consumable",
        "location",
        "guild_organization",
        "skill",
        "item",
        "organization",
        "world",
        "unknown",
    }

    # Relation -> (allowed source types, allowed target types)
    RELATION_RULES: Dict[str, Tuple[Set[str], Set[str]]] = {
        "member_of": ({"character"}, {"guild_organization", "organization"}),
        "leader_of": ({"character"}, {"guild_organization", "organization"}),
        "located_in": (
            {"character", "weapon", "armor", "consumable", "item", "guild_organization"},
            {"location"},
        ),
        "equipped_with": (
            {"character"},
            {"weapon", "armor", "item", "consumable"},
        ),
        "stored_in": (
            {"weapon", "armor", "consumable", "item"},
            {"character", "location"},
        ),
        "has_skill": ({"character"}, {"skill"}),
        "guards": ({"character", "guild_organization", "organization"}, {"location", "character"}),
        "trades_with": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "sells_to": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "hostile_to": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "allied_with": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "respects": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "fighting": (
            {"character", "guild_organization", "organization"},
            {"character", "guild_organization", "organization"},
        ),
        "owns": (
            {"character", "guild_organization", "organization"},
            {"weapon", "armor", "consumable", "item", "location"},
        ),
    }

    # Semantic conflicts between relationship labels.
    CONFLICT_RELATION_PAIRS: Set[Tuple[str, str]] = {
        ("hostile_to", "allied_with"),
        ("allied_with", "hostile_to"),
        ("fighting", "allied_with"),
        ("allied_with", "fighting"),
    }

    # Relations that should not have multiple targets for one source in the same graph state.
    SINGLE_TARGET_RELATIONS: Set[str] = {"located_in"}

    RELATION_ALIASES: Dict[str, str] = {
        "friend_of": "allied_with",
        "enemy_of": "hostile_to",
        "is_in": "located_in",
        "belongs_to": "member_of",
        "part_of": "member_of",
        "related_to": "related_to",
    }

    def __init__(self, min_confidence: float = 0.45, allow_wildcard_deletions: bool = False):
        self.min_confidence = float(min_confidence)
        self.allow_wildcard_deletions = allow_wildcard_deletions
        self.enable_embedding_review = self._to_bool(os.getenv("ENABLE_EMBEDDING_REVIEW", "false"))
        self.embedding_review_threshold = self._to_float(os.getenv("EMBEDDING_REVIEW_THRESHOLD"), 0.2)
        self.embedding_review_model = os.getenv("EMBEDDING_REVIEW_MODEL", "text-embedding-3-small").strip()
        self.embedding_review_max_edges = max(1, int(self._to_float(os.getenv("EMBEDDING_REVIEW_MAX_EDGES"), 12)))
        self.embedding_reviewer = _EmbeddingSemanticReviewer(
            enabled=self.enable_embedding_review,
            model=self.embedding_review_model,
            threshold=self.embedding_review_threshold,
            max_edges=self.embedding_review_max_edges,
            api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
            base_url=(os.getenv("OPENAI_API_BASE_URL") or "").strip() or None,
        )
        logger.info(
            f"ValidationLayer initialized (min_confidence={self.min_confidence}, "
            f"allow_wildcard_deletions={self.allow_wildcard_deletions}, "
            f"embedding_review_enabled={self.embedding_reviewer.is_ready()})."
        )

    def validate(self, updates: Dict[str, Any], kg: Any) -> Dict[str, Any]:
        """
        Validate and sanitize graph updates before applying to memory.

        Returns a normalized execution payload. Rejected/filtered operations are
        recorded in `validation_report` for observability.
        """
        if not isinstance(updates, dict):
            logger.warning("Validation received non-dict updates; returning empty update set.")
            return self._empty_result(reason="invalid_payload")

        graph = getattr(kg, "graph", None)
        default_confidence = self._to_float(updates.get("confidence"), 1.0)

        report = {
            "rejected_nodes": [],
            "rejected_edges": [],
            "deferred_edges": [],
            "rejected_deletions": [],
        }

        normalized_nodes, node_types = self._normalize_nodes(updates, graph, report)
        normalized_edges = self._normalize_edges(
            updates=updates,
            graph=graph,
            node_types=node_types,
            default_confidence=default_confidence,
            report=report,
        )
        nodes_to_delete, edges_to_delete, deletion_events = self._normalize_deletions(
            updates=updates,
            graph=graph,
            report=report,
        )
        normalized_edges, embedding_review = self._apply_embedding_review(
            normalized_edges=normalized_edges,
            node_types=node_types,
            graph=graph,
            report=report,
        )

        result = {
            "nodes_to_update": normalized_nodes,
            "edges_to_add": normalized_edges,
            "nodes_to_delete": nodes_to_delete,
            "edges_to_delete": edges_to_delete,
            "deletion_events": deletion_events,
            "analysis_summary": updates.get("analysis_summary", ""),
            "confidence": default_confidence,
            "notes": updates.get("notes", ""),
            "validation_report": {
                "input_nodes": len(updates.get("nodes_to_update", [])) + len(updates.get("nodes_to_add", [])),
                "accepted_nodes": len(normalized_nodes),
                "input_edges": len(updates.get("edges_to_add", [])),
                "accepted_edges": len(normalized_edges),
                "rejected_nodes": len(report["rejected_nodes"]),
                "rejected_edges": len(report["rejected_edges"]),
                "deferred_edges": len(report["deferred_edges"]),
                "rejected_deletions": len(report["rejected_deletions"]),
                "embedding_review": embedding_review, 
                "details": report,
            },
        }

        logger.info(
            "Validation completed: "
            f"nodes {result['validation_report']['accepted_nodes']}/{result['validation_report']['input_nodes']}, "
            f"edges {result['validation_report']['accepted_edges']}/{result['validation_report']['input_edges']}."
        )
        if report["rejected_nodes"] or report["rejected_edges"] or report["rejected_deletions"]:
            logger.warning(f"Validation filtered operations: {result['validation_report']['details']}")

        return result

    def _normalize_nodes(
        self,
        updates: Dict[str, Any],
        graph: Any,
        report: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        normalized: Dict[str, Dict[str, Any]] = {}
        node_types: Dict[str, str] = {}

        for raw_node in list(updates.get("nodes_to_update", [])) + list(updates.get("nodes_to_add", [])):
            if not isinstance(raw_node, dict):
                report["rejected_nodes"].append({"reason": "node_update_not_dict", "value": raw_node})
                continue

            node_id = self._clean_str(raw_node.get("node_id"))
            if not node_id:
                report["rejected_nodes"].append({"reason": "missing_node_id", "value": raw_node})
                continue

            node_type = self._normalize_node_type(raw_node.get("type"))
            attrs = raw_node.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}

            sanitized_attrs = {k: v for k, v in attrs.items() if isinstance(k, str) and not k.startswith("__")}
            sanitized_attrs.pop("type", None)

            if node_type == "unknown":
                existing_type = self._get_existing_node_type(graph, node_id)
                if existing_type:
                    node_type = existing_type

            if node_type not in self.KNOWN_NODE_TYPES:
                # Unknown custom types are downgraded to "unknown" to avoid hard failure.
                logger.warning(f"Unsupported node type '{node_type}' for node '{node_id}', fallback to 'unknown'.")
                node_type = "unknown"

            entry = normalized.setdefault(node_id, {"node_id": node_id, "type": node_type, "attributes": {}})
            if entry["type"] == "unknown" and node_type != "unknown":
                entry["type"] = node_type
            entry["attributes"].update(sanitized_attrs)
            node_types[node_id] = entry["type"]

        return list(normalized.values()), node_types

    def _normalize_edges(
        self,
        updates: Dict[str, Any],
        graph: Any,
        node_types: Dict[str, str],
        default_confidence: float,
        report: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        normalized_edges: List[Dict[str, Any]] = []

        for raw_edge in updates.get("edges_to_add", []):
            if not isinstance(raw_edge, dict):
                report["rejected_edges"].append({"reason": "edge_update_not_dict", "value": raw_edge})
                continue

            source = self._clean_str(raw_edge.get("source"))
            target = self._clean_str(raw_edge.get("target"))
            relation_raw = self._clean_str(raw_edge.get("relationship"))
            relationship = self._normalize_relationship(relation_raw)

            if not source or not target or not relationship:
                report["rejected_edges"].append({"reason": "missing_edge_fields", "value": raw_edge})
                continue
            if source == target:
                report["rejected_edges"].append({"reason": "self_loop_blocked", "value": raw_edge})
                continue

            if not self._node_exists(graph, source) and source not in node_types:
                report["rejected_edges"].append({"reason": "source_node_not_found", "value": raw_edge})
                continue
            if not self._node_exists(graph, target) and target not in node_types:
                report["rejected_edges"].append({"reason": "target_node_not_found", "value": raw_edge})
                continue

            source_type = node_types.get(source) or self._get_existing_node_type(graph, source) or "unknown"
            target_type = node_types.get(target) or self._get_existing_node_type(graph, target) or "unknown"

            if not self._is_relation_type_compatible(relationship, source_type, target_type):
                report["rejected_edges"].append(
                    {
                        "reason": "relation_type_mismatch",
                        "edge": raw_edge,
                        "source_type": source_type,
                        "target_type": target_type,
                    }
                )
                continue

            existing_rel = self._get_existing_relationship(graph, source, target)
            if existing_rel == relationship:
                report["rejected_edges"].append({"reason": "duplicate_edge", "edge": raw_edge})
                continue

            if existing_rel and existing_rel != relationship:
                if self._is_conflicting_relationship(existing_rel, relationship):
                    report["rejected_edges"].append(
                        {
                            "reason": "conflicting_with_existing_edge",
                            "edge": raw_edge,
                            "existing_relationship": existing_rel,
                        }
                    )
                    continue
                # DiGraph stores only one edge per pair; require explicit deletion before replacing relation label.
                report["rejected_edges"].append(
                    {
                        "reason": "existing_edge_requires_explicit_delete",
                        "edge": raw_edge,
                        "existing_relationship": existing_rel,
                    }
                )
                continue

            if relationship in self.SINGLE_TARGET_RELATIONS:
                current_targets = self._find_targets_by_relation(graph, source, relationship)
                current_targets.discard(target)
                if current_targets:
                    report["rejected_edges"].append(
                        {
                            "reason": "single_target_relation_conflict",
                            "edge": raw_edge,
                            "existing_targets": sorted(current_targets),
                        }
                    )
                    continue

            edge_confidence = self._extract_confidence(raw_edge, default_confidence)
            if edge_confidence < self.min_confidence:
                report["deferred_edges"].append(
                    {
                        "reason": "low_confidence",
                        "edge": raw_edge,
                        "confidence": edge_confidence,
                        "threshold": self.min_confidence,
                    }
                )
                continue

            edge_attrs = raw_edge.get("attributes", {})
            if not isinstance(edge_attrs, dict):
                edge_attrs = {}
            edge_attrs = {k: v for k, v in edge_attrs.items() if isinstance(k, str) and not k.startswith("__")}

            normalized_edges.append(
                {
                    "source": source,
                    "target": target,
                    "relationship": relationship,
                    "attributes": edge_attrs,
                }
            )

        return normalized_edges

    def _normalize_deletions(
        self,
        updates: Dict[str, Any],
        graph: Any,
        report: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        nodes_to_delete: List[Dict[str, Any]] = []
        for raw_node in updates.get("nodes_to_delete", []):
            if not isinstance(raw_node, dict):
                report["rejected_deletions"].append({"reason": "node_delete_not_dict", "value": raw_node})
                continue
            node_id = self._clean_str(raw_node.get("node_id"))
            if not node_id:
                report["rejected_deletions"].append({"reason": "missing_node_id", "value": raw_node})
                continue
            if not self._node_exists(graph, node_id):
                report["rejected_deletions"].append({"reason": "node_not_found", "value": raw_node})
                continue
            nodes_to_delete.append(raw_node)

        edges_to_delete: List[Dict[str, Any]] = []
        for raw_edge in updates.get("edges_to_delete", []):
            if not isinstance(raw_edge, dict):
                report["rejected_deletions"].append({"reason": "edge_delete_not_dict", "value": raw_edge})
                continue

            source = self._clean_str(raw_edge.get("source"))
            target = self._clean_str(raw_edge.get("target"))
            relationship = self._clean_str(raw_edge.get("relationship"), allow_none=True)

            wildcard_used = source == "*" or target == "*" or relationship == "*"
            if wildcard_used and not self.allow_wildcard_deletions:
                report["rejected_deletions"].append(
                    {"reason": "wildcard_deletion_blocked", "value": raw_edge}
                )
                continue

            if not source or not target:
                report["rejected_deletions"].append({"reason": "missing_edge_delete_fields", "value": raw_edge})
                continue

            normalized_edge_delete = dict(raw_edge)
            if relationship:
                normalized_edge_delete["relationship"] = self._normalize_relationship(relationship)
            edges_to_delete.append(normalized_edge_delete)

        deletion_events = [e for e in updates.get("deletion_events", []) if isinstance(e, dict)]
        return nodes_to_delete, edges_to_delete, deletion_events

    def _apply_embedding_review(
        self,
        normalized_edges: List[Dict[str, Any]],
        node_types: Dict[str, str],
        graph: Any,
        report: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not normalized_edges:
            return normalized_edges, {"enabled": self.embedding_reviewer.is_enabled(), "reviewed": 0, "filtered": 0}

        reviewed_edges, deferred_entries, info = self.embedding_reviewer.review_edges(
            edges=normalized_edges,
            node_types=node_types,
            graph=graph,
            get_node_type=self._get_existing_node_type,
        )
        if deferred_entries:
            report["deferred_edges"].extend(deferred_entries)
        return reviewed_edges, info

    def _is_relation_type_compatible(self, relationship: str, source_type: str, target_type: str) -> bool:
        rule = self.RELATION_RULES.get(relationship)
        if not rule:
            # Unknown relations are allowed (for extensibility), but known-type mismatches are blocked.
            return True

        source_allowed, target_allowed = rule
        source_known = source_type in self.KNOWN_NODE_TYPES and source_type != "unknown"
        target_known = target_type in self.KNOWN_NODE_TYPES and target_type != "unknown"

        if source_known and source_type not in source_allowed:
            return False
        if target_known and target_type not in target_allowed:
            return False
        return True

    def _is_conflicting_relationship(self, existing_rel: str, new_rel: str) -> bool:
        return (existing_rel, new_rel) in self.CONFLICT_RELATION_PAIRS

    @staticmethod
    def _node_exists(graph: Any, node_id: str) -> bool:
        try:
            return bool(graph is not None and graph.has_node(node_id))
        except Exception:
            return False

    @staticmethod
    def _get_existing_node_type(graph: Any, node_id: str) -> str:
        try:
            if graph is None or not graph.has_node(node_id):
                return ""
            return str(graph.nodes[node_id].get("type", "")).strip().lower()
        except Exception:
            return ""

    @staticmethod
    def _get_existing_relationship(graph: Any, source: str, target: str) -> str:
        try:
            if graph is None or not graph.has_edge(source, target):
                return ""
            edge_data = graph.get_edge_data(source, target) or {}
            return str(edge_data.get("relationship", "")).strip().lower()
        except Exception:
            return ""

    @staticmethod
    def _find_targets_by_relation(graph: Any, source: str, relationship: str) -> Set[str]:
        targets: Set[str] = set()
        try:
            if graph is None or not graph.has_node(source):
                return targets
            for _, tgt, edge_data in graph.out_edges(source, data=True):
                rel = str((edge_data or {}).get("relationship", "")).strip().lower()
                if rel == relationship:
                    targets.add(str(tgt))
        except Exception:
            return targets
        return targets

    def _normalize_node_type(self, node_type: Any) -> str:
        cleaned = self._clean_str(node_type)
        return cleaned.lower() if cleaned else "unknown"

    def _normalize_relationship(self, relationship: str) -> str:
        normalized = relationship.lower().strip()
        return self.RELATION_ALIASES.get(normalized, normalized)

    @staticmethod
    def _extract_confidence(edge: Dict[str, Any], default_confidence: float) -> float:
        attrs = edge.get("attributes", {})
        if isinstance(attrs, dict) and "confidence" in attrs:
            return ValidationLayer._to_float(attrs.get("confidence"), default_confidence)
        if "confidence" in edge:
            return ValidationLayer._to_float(edge.get("confidence"), default_confidence)
        return default_confidence

    @staticmethod
    def _to_bool(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_str(value: Any, allow_none: bool = False) -> str:
        if value is None:
            return "" if not allow_none else None
        return str(value).strip()

    @staticmethod
    def _empty_result(reason: str) -> Dict[str, Any]:
        return {
            "nodes_to_update": [],
            "edges_to_add": [],
            "nodes_to_delete": [],
            "edges_to_delete": [],
            "deletion_events": [],
            "analysis_summary": "",
            "confidence": 1.0,
            "notes": "",
            "validation_report": {"reason": reason},
        }


class _EmbeddingSemanticReviewer:
    """Optional paid semantic review using embedding similarity."""

    RELATION_REFERENCE_TEXTS: Dict[str, str] = {
        "member_of": "A character belongs to an organization, guild, or faction.",
        "leader_of": "A character is the leader of an organization, guild, or faction.",
        "located_in": "An entity is physically located in a location.",
        "equipped_with": "A character equips an item, weapon, armor, or consumable.",
        "stored_in": "An item is stored by a character or in a location inventory.",
        "has_skill": "A character has a skill or ability.",
        "guards": "A character or group guards a location or protects someone.",
        "trades_with": "Two characters or organizations conduct trade with each other.",
        "sells_to": "A seller sells goods to a buyer.",
        "hostile_to": "Two characters or groups are hostile enemies.",
        "allied_with": "Two characters or groups are allies.",
        "respects": "A character or group respects another character or group.",
        "fighting": "Two characters or groups are in active combat.",
        "owns": "A character or organization owns an item or place.",
    }

    def __init__(
        self,
        enabled: bool,
        model: str,
        threshold: float,
        max_edges: int,
        api_key: str,
        base_url: Optional[str],
    ):
        self.enabled = enabled
        self.model = model
        self.threshold = threshold
        self.max_edges = max_edges
        self.api_key = api_key
        self.base_url = base_url
        self._client = None

        if self.enabled and not self.api_key:
            logger.warning("Embedding semantic review enabled but OPENAI_API_KEY is empty; feature disabled.")
            self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled

    def is_ready(self) -> bool:
        return self.enabled and bool(self.api_key)

    def review_edges(
        self,
        edges: List[Dict[str, Any]],
        node_types: Dict[str, str],
        graph: Any,
        get_node_type,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        info = {
            "enabled": self.is_enabled(),
            "reviewed": 0,
            "filtered": 0,
            "model": self.model,
            "threshold": self.threshold,
            "max_edges": self.max_edges,
        }
        if not self.is_ready():
            return edges, [], info

        review_targets = []
        passthrough = []
        for edge in edges:
            if edge.get("relationship") in self.RELATION_REFERENCE_TEXTS:
                review_targets.append(edge)
            else:
                passthrough.append(edge)

        if not review_targets:
            return edges, [], info

        # Cap reviewed edges per batch to control paid API usage.
        review_now = review_targets[: self.max_edges]
        review_later = review_targets[self.max_edges :]

        texts: List[str] = []
        pairs: List[Tuple[Dict[str, Any], int, int]] = []
        for edge in review_now:
            source = edge.get("source", "")
            target = edge.get("target", "")
            relationship = edge.get("relationship", "")
            source_type = node_types.get(source) or get_node_type(graph, source) or "unknown"
            target_type = node_types.get(target) or get_node_type(graph, target) or "unknown"

            candidate_text = (
                f"{source} ({source_type}) --{relationship}--> {target} ({target_type}). "
                f"This is a knowledge-graph relation assertion."
            )
            reference_text = self.RELATION_REFERENCE_TEXTS[relationship]
            idx_a = len(texts)
            texts.append(candidate_text)
            idx_b = len(texts)
            texts.append(reference_text)
            pairs.append((edge, idx_a, idx_b))

        try:
            embeddings = self._embed_texts(texts)
        except Exception as exc:
            logger.warning(f"Embedding semantic review failed, fallback to rule-only validation: {exc}")
            info["error"] = str(exc)
            return edges, [], info

        accepted = list(passthrough)
        deferred: List[Dict[str, Any]] = []

        for edge, cand_idx, ref_idx in pairs:
            score = self._cosine_similarity(embeddings[cand_idx], embeddings[ref_idx])
            info["reviewed"] += 1
            if score < self.threshold:
                info["filtered"] += 1
                deferred.append(
                    {
                        "reason": "embedding_semantic_low_score",
                        "edge": edge,
                        "score": round(score, 4),
                        "threshold": self.threshold,
                        "model": self.model,
                    }
                )
            else:
                accepted.append(edge)

        # Edges beyond max review budget pass through to avoid blocking.
        accepted.extend(review_later)
        return accepted, deferred, info

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        client = self._get_client()
        response = client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    def _get_client(self):
        if self._client is not None:
            return self._client

        import openai

        kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = openai.OpenAI(**kwargs)
        return self._client

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return -1.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return -1.0
        return dot / (norm_a * norm_b)
