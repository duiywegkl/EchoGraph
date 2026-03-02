"""
RPG专用文本处理器 - 专门处理角色扮演游戏中的复杂元素
支持数值属性、装备系统、技能树、复杂关系等RPG核心机制
"""
import re
import json
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger

class RPGTextProcessor:
    """RPG专用文本处理器，能够识别和提取复杂的RPG游戏元素"""
    
    def __init__(self):
        # 按策略：图谱维护只允许LLM Agent。正则规则全部停用。
        self.rpg_entity_patterns: Dict[str, List[str]] = {}
        self.numerical_patterns: Dict[str, List[str]] = {}
        self.rpg_relation_patterns: List[Tuple[str, str]] = []
        self.deletion_patterns: List[Tuple[str, str]] = []
        self.skill_patterns: List[str] = []

    def extract_rpg_entities_and_relations(self, text: str) -> Dict[str, Any]:
        """
        从RPG文本中提取实体、数值属性和复杂关系
        返回结构化的RPG游戏数据
        添加文本长度限制和处理时间保护
        """
        nodes_to_add = []
        edges_to_add = []
        nodes_to_delete = []
        edges_to_delete = []
        deletion_events = []
        start_time = 0.0
        
        # 限制文本长度，避免处理过长的文本导致性能问题
        max_text_length = 10000  # 最大处理10000字符
        if len(text) > max_text_length:
            logger.warning(f"文本长度超过限制 ({len(text)} > {max_text_length})，截断处理")
            text = text[:max_text_length]
        
        logger.info(f"开始分析RPG文本: {text[:100]}... (总长度: {len(text)} 字符)")
        
        try:
            # 1. 提取RPG实体 - 添加超时保护
            import time
            start_time = time.time()
            entity_count = 0
            max_processing_time = 15  # 最大处理时间15秒
            
            for entity_type, patterns in self.rpg_entity_patterns.items():
                # 检查是否超时
                if time.time() - start_time > max_processing_time:
                    logger.warning(f"实体提取超时 ({max_processing_time}秒)，停止进一步处理")
                    break
                
                logger.debug(f"正在处理实体类型: {entity_type}")
                
                for pattern in patterns:
                    try:
                        # 为每个正则表达式设置匹配限制
                        matches = re.finditer(pattern, text, re.IGNORECASE)
                        match_count = 0
                        max_matches_per_pattern = 50  # 每个模式最多50个匹配
                        
                        for match in matches:
                            match_count += 1
                            if match_count > max_matches_per_pattern:
                                logger.debug(f"模式 {pattern[:50]}... 匹配数量超限，停止处理")
                                break
                            
                            entity_name = self._extract_entity_name_from_match(match)
                            if entity_name and len(entity_name) > 1:
                                entity_id = self._generate_rpg_entity_id(entity_name, entity_type)
                                
                                # 根据实体类型设置特殊属性
                                attributes = {
                                    "name": entity_name,
                                    "source": "rpg_extraction"
                                }
                                
                                # 为武器和装备提取数值属性
                                if entity_type in ["weapon", "armor"]:
                                    attributes.update(self._extract_equipment_stats(match.group(0)))
                                
                                # 为角色提取等级信息
                                elif entity_type == "character":
                                    level_info = self._extract_character_level(match.group(0))
                                    if level_info:
                                        attributes.update(level_info)
                                
                                nodes_to_add.append({
                                    "node_id": entity_id,
                                    "type": entity_type,
                                    "attributes": attributes
                                })
                                
                                entity_count += 1
                                
                                # 限制总实体数量
                                if entity_count > 100:  # 最多提取100个实体
                                    logger.warning("实体数量超限，停止提取")
                                    break
                    
                    except Exception as regex_error:
                        logger.warning(f"正则表达式处理失败 (模式: {pattern[:50]}...): {regex_error}")
                        continue
                
                if entity_count > 100:
                    break
            
            logger.info(f"实体提取完成: {entity_count} 个实体 (耗时: {time.time() - start_time:.2f}秒)")
            
            # 2. 提取数值属性变化 - 简化处理
            try:
                numerical_updates = self._extract_numerical_changes(text)
                # 限制数值更新的数量
                if len(numerical_updates) > 20:
                    numerical_updates = numerical_updates[:20]
                nodes_to_add.extend(numerical_updates)
                logger.debug(f"数值属性提取完成: {len(numerical_updates)} 个更新")
            except Exception as e:
                logger.warning(f"数值属性提取失败: {e}")
            
            # 3. 提取RPG关系 - 简化处理
            try:
                relation_count = 0
                for pattern, relation_type in self.rpg_relation_patterns:
                    if time.time() - start_time > max_processing_time:
                        logger.warning("关系提取超时，停止处理")
                        break
                    
                    try:
                        matches = re.finditer(pattern, text, re.IGNORECASE)
                        for match in matches:
                            relation_count += 1
                            if relation_count > 30:  # 最多30个关系
                                break
                            
                            # 简化的关系提取
                            groups = match.groups()
                            if len(groups) >= 2:
                                source_entity = self._clean_entity_name(groups[0])
                                target_entity = self._clean_entity_name(groups[1])
                                
                                if source_entity and target_entity and source_entity != target_entity:
                                    edges_to_add.append({
                                        "source": self._generate_rpg_entity_id(source_entity, "character"),
                                        "target": self._generate_rpg_entity_id(target_entity, "character"),
                                        "relationship": relation_type
                                    })
                    except Exception as relation_error:
                        logger.debug(f"关系模式处理失败: {relation_error}")
                        continue
                    
                    if relation_count > 30:
                        break
                
                logger.info(f"关系提取完成: {len(edges_to_add)} 个关系")
                
            except Exception as e:
                logger.warning(f"关系提取失败: {e}")

            # 4. 提取技能与状态效果
            try:
                skill_edges = self._extract_skills_and_effects(text)
                if skill_edges:
                    edges_to_add.extend(skill_edges)
                    for edge in skill_edges:
                        source_id = edge.get("source")
                        if isinstance(source_id, str) and source_id:
                            nodes_to_add.append(
                                {
                                    "node_id": source_id,
                                    "type": "character",
                                    "attributes": {
                                        "name": source_id.replace("character_", ""),
                                        "source": "rpg_skill_extraction",
                                    },
                                }
                            )
                        skill_id = edge.get("target")
                        if isinstance(skill_id, str) and skill_id.startswith("skill_"):
                            nodes_to_add.append(
                                {
                                    "node_id": skill_id,
                                    "type": "skill",
                                    "attributes": {
                                        "name": skill_id.replace("skill_", ""),
                                        "source": "rpg_skill_extraction",
                                    },
                                }
                            )
                logger.info(f"技能提取完成: {len(skill_edges)} 个关系")
            except Exception as e:
                logger.warning(f"技能提取失败: {e}")

            # 5. 提取删除/丢失/断连事件
            try:
                deletion_result = self._extract_deletion_events(text)
                nodes_to_delete.extend(deletion_result.get("nodes_to_delete", []))
                edges_to_delete.extend(deletion_result.get("edges_to_delete", []))
                deletion_events.extend(deletion_result.get("deletion_events", []))
            except Exception as e:
                logger.warning(f"删除事件提取失败: {e}")

            # 去重，避免同一轮多次命中导致重复操作。
            nodes_to_add = self._deduplicate_nodes(nodes_to_add)
            edges_to_add = self._deduplicate_edges(edges_to_add)
            nodes_to_delete = self._deduplicate_node_deletions(nodes_to_delete)
            edges_to_delete = self._deduplicate_edge_deletions(edges_to_delete)
            
        except Exception as e:
            logger.error(f"RPG文本分析过程中发生错误: {e}")
            # 即使发生错误，也返回已经提取的数据
        
        total_time = 0.0
        if start_time:
            import time
            total_time = time.time() - start_time
        logger.info(
            f"RPG文本分析完成: {len(nodes_to_add)} 节点, {len(edges_to_add)} 关系, "
            f"{len(nodes_to_delete)} 节点删除, {len(edges_to_delete)} 关系删除 (总耗时: {total_time:.2f}秒)"
        )
        
        return {
            "nodes_to_add": nodes_to_add,
            "edges_to_add": edges_to_add,
            "nodes_to_delete": nodes_to_delete,
            "edges_to_delete": edges_to_delete,
            "deletion_events": deletion_events,
            "processing_stats": {
                "processing_time": total_time,
                "text_length": len(text),
                "entities_found": len(nodes_to_add),
                "relations_found": len(edges_to_add),
                "node_deletions_found": len(nodes_to_delete),
                "edge_deletions_found": len(edges_to_delete),
            }
        }

    def _extract_deletion_events(self, text: str) -> Dict[str, Any]:
        """
        检测并处理删除/死亡/丢失事件
        
        Returns:
            Dict包含:
            - nodes_to_delete: 需要删除的节点列表
            - edges_to_delete: 需要删除的边列表  
            - deletion_events: 删除事件详情列表
        """
        nodes_to_delete = []
        edges_to_delete = []
        deletion_events = []
        
        for pattern, event_type in self.deletion_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if event_type == "character_death":
                    character_name = match.group(1)
                    char_id = self._generate_rpg_entity_id(character_name, "character")
                    
                    nodes_to_delete.append({
                        "node_id": char_id,
                        "deletion_type": "death",
                        "reason": f"{character_name} died"
                    })
                    
                    deletion_events.append({
                        "type": "character_death",
                        "entity": character_name,
                        "description": match.group(0),
                        "action": "mark_as_deleted"
                    })
                    
                elif event_type == "item_lost":
                    item_name = match.group(1)
                    item_id = self._generate_rpg_entity_id(item_name, "item")
                    
                    nodes_to_delete.append({
                        "node_id": item_id,
                        "deletion_type": "lost",
                        "reason": f"{item_name} was lost"
                    })
                    
                    deletion_events.append({
                        "type": "item_lost",
                        "entity": item_name,
                        "description": match.group(0),
                        "action": "delete_node"
                    })
                    
                elif event_type == "item_stolen":
                    item_name = match.group(1)
                    item_id = self._generate_rpg_entity_id(item_name, "item")
                    
                    # 物品被偷走时直接视为丢失，避免通配符删除被安全策略拦截。
                    nodes_to_delete.append({
                        "node_id": item_id,
                        "deletion_type": "lost",
                        "reason": f"{item_name} was stolen"
                    })
                    
                    deletion_events.append({
                        "type": "item_stolen", 
                        "entity": item_name,
                        "description": match.group(0),
                        "action": "delete_node"
                    })
                    
                elif event_type == "relationship_broken":
                    entity1 = match.group(1)
                    entity2 = match.group(2)
                    entity1_id = self._generate_rpg_entity_id(entity1, "character")
                    entity2_id = self._generate_rpg_entity_id(entity2, "character")
                    
                    # 使用显式关系删除，避免通配符被安全策略拦截。
                    candidate_relationships = ["allied_with", "respects", "member_of", "hostile_to"]
                    for rel in candidate_relationships:
                        edges_to_delete.extend([
                            {
                                "source": entity1_id,
                                "target": entity2_id,
                                "relationship": rel,
                                "reason": f"{entity1} and {entity2} broke their relationship"
                            },
                            {
                                "source": entity2_id,
                                "target": entity1_id,
                                "relationship": rel,
                                "reason": f"{entity2} and {entity1} broke their relationship"
                            }
                        ])
                    
                    deletion_events.append({
                        "type": "relationship_broken",
                        "entities": [entity1, entity2],
                        "description": match.group(0),
                        "action": "remove_relationships"
                    })
                    
                elif event_type == "left_organization":
                    character = match.group(1)
                    organization = match.group(2)
                    char_id = self._generate_rpg_entity_id(character, "character")
                    org_id = self._generate_rpg_entity_id(organization, "guild_organization")
                    
                    edges_to_delete.append({
                        "source": char_id,
                        "target": org_id,
                        "relationship": "member_of",
                        "reason": f"{character} left {organization}"
                    })
                    
                    deletion_events.append({
                        "type": "left_organization",
                        "character": character,
                        "organization": organization,
                        "description": match.group(0),
                        "action": "remove_membership"
                    })
                    
                elif event_type == "left_location":
                    character = match.group(1)
                    location = match.group(2)
                    char_id = self._generate_rpg_entity_id(character, "character")
                    loc_id = self._generate_rpg_entity_id(location, "location")
                    
                    edges_to_delete.append({
                        "source": char_id,
                        "target": loc_id,
                        "relationship": "located_in",
                        "reason": f"{character} left {location}"
                    })
                    
                    deletion_events.append({
                        "type": "left_location",
                        "character": character,
                        "location": location,
                        "description": match.group(0),
                        "action": "remove_location"
                    })
        
        result = {
            "nodes_to_delete": nodes_to_delete,
            "edges_to_delete": edges_to_delete,
            "deletion_events": deletion_events
        }
        
        if deletion_events:
            logger.info(f"检测到 {len(deletion_events)} 个删除事件: {[e['type'] for e in deletion_events]}")
        
        return result

    def _extract_equipment_stats(self, equipment_text: str) -> Dict[str, Any]:
        """从装备文本中提取数值属性"""
        stats = {}
        
        # 提取攻击力
        atk_match = re.search(r"(?:攻击力|伤害|ATK)[+\-]?(\d+)", equipment_text)
        if atk_match:
            stats["attack"] = int(atk_match.group(1))
        
        # 提取防御力
        def_match = re.search(r"(?:防御力|防御|DEF|护甲)[+\-]?(\d+)", equipment_text)
        if def_match:
            stats["defense"] = int(def_match.group(1))
        
        # 提取强化等级
        enhance_match = re.search(r"[+](\d+)", equipment_text)
        if enhance_match:
            stats["enhancement_level"] = int(enhance_match.group(1))
        
        # 提取稀有度
        rarity_match = re.search(r"(史诗|传说|稀有|普通|魔法)", equipment_text)
        if rarity_match:
            stats["rarity"] = rarity_match.group(1)
        
        return stats

    def _extract_character_level(self, character_text: str) -> Optional[Dict[str, Any]]:
        """从角色文本中提取等级信息"""
        level_match = re.search(r"(?:等级|Lv\.?|Level)\s*(\d+)", character_text)
        if level_match:
            return {"level": int(level_match.group(1))}
        return None

    def _extract_numerical_changes(self, text: str) -> List[Dict[str, Any]]:
        """提取数值变化，如血量、经验值等"""
        updates = []
        
        for category, patterns in self.numerical_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    # 根据匹配内容判断是哪个属性
                    attr_name = self._determine_attribute_name(match.group(0))
                    if attr_name:
                        value = int(match.group(1))
                        
                        # 创建虚拟的角色节点来存储数值变化
                        updates.append({
                            "node_id": "player", # 默认假设是玩家
                            "type": "character",
                            "attributes": {attr_name: value}
                        })
        
        return updates

    def _extract_skills_and_effects(self, text: str) -> List[Dict[str, Any]]:
        """提取技能使用和状态效果"""
        relations = []
        
        for pattern in self.skill_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                skill_name = self._clean_entity_name(match.group(1))
                if skill_name:
                    relations.append({
                        "source": "player",
                        "target": self._generate_rpg_entity_id(skill_name, "skill"),
                        "relationship": "has_skill"
                    })
        
        return relations

    def _determine_attribute_name(self, text: str) -> Optional[str]:
        """根据文本内容判断属性名称"""
        if re.search(r"攻击力|伤害|ATK", text):
            return "attack"
        elif re.search(r"防御力|防御|DEF", text):
            return "defense" 
        elif re.search(r"血量|生命|HP", text):
            return "health"
        elif re.search(r"魔法|法力|MP", text):
            return "mana"
        elif re.search(r"等级|级别|Lv", text):
            return "level"
        elif re.search(r"经验|EXP", text):
            return "experience"
        return None

    def _extract_entity_name_from_match(self, match) -> Optional[str]:
        """从正则匹配中提取实体名称"""
        groups = match.groups()
        for group in groups:
            if group and len(group.strip()) > 0:
                # 跳过纯数字组
                if not group.isdigit():
                    return group.strip()
        return None

    def _clean_entity_name(self, value: Any) -> str:
        """清理实体名，避免把噪声字符写入ID。"""
        if value is None:
            return ""
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        cleaned = cleaned.strip("，。,.!?！？:：;；\"'()[]{}")
        return cleaned

    def _deduplicate_nodes(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id", "")).strip()
            if not node_id:
                continue
            node_type = str(node.get("type", "unknown")).strip() or "unknown"
            attrs = node.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}

            entry = merged.setdefault(node_id, {"node_id": node_id, "type": node_type, "attributes": {}})
            if entry.get("type") == "unknown" and node_type != "unknown":
                entry["type"] = node_type
            entry["attributes"].update(attrs)
        return list(merged.values())

    def _deduplicate_edges(self, edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            relationship = str(edge.get("relationship", "")).strip()
            if not source or not target or not relationship:
                continue
            key = (source, target, relationship)
            attrs = edge.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}
            if key not in deduped:
                deduped[key] = {
                    "source": source,
                    "target": target,
                    "relationship": relationship,
                    "attributes": dict(attrs),
                }
            else:
                deduped[key]["attributes"].update(attrs)
        return list(deduped.values())

    def _deduplicate_node_deletions(self, deletions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: Dict[str, Dict[str, Any]] = {}
        for deletion in deletions:
            if not isinstance(deletion, dict):
                continue
            node_id = str(deletion.get("node_id", "")).strip()
            if not node_id:
                continue
            deduped[node_id] = deletion
        return list(deduped.values())

    def _deduplicate_edge_deletions(self, deletions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for deletion in deletions:
            if not isinstance(deletion, dict):
                continue
            source = str(deletion.get("source", "")).strip()
            target = str(deletion.get("target", "")).strip()
            relationship = str(deletion.get("relationship", "")).strip()
            if not source or not target or not relationship:
                continue
            deduped[(source, target, relationship)] = deletion
        return list(deduped.values())

    def _generate_rpg_entity_id(self, name: str, entity_type: str) -> str:
        """生成RPG实体ID"""
        # 清理名称
        clean_name = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', name.lower())
        
        # RPG专用的翻译映射
        rpg_translation_map = {
            # 职业
            "战士": "warrior", "法师": "mage", "盗贼": "thief", "牧师": "priest",
            "骑士": "knight", "弓箭手": "archer", "刺客": "assassin", "德鲁伊": "druid",
            
            # 装备
            "长剑": "longsword", "战斧": "battleaxe", "法杖": "staff", "匕首": "dagger",
            "盔甲": "armor", "盾牌": "shield", "头盔": "helmet", "靴子": "boots",
            
            # 地点
            "酒馆": "tavern", "铁匠铺": "blacksmith", "魔法塔": "magic_tower",
            "地牢": "dungeon", "城堡": "castle", "森林": "forest", "沙漠": "desert",
            
            # 通用
            "玩家": "player", "敌人": "enemy", "NPC": "npc",
        }
        
        if clean_name in rpg_translation_map:
            return rpg_translation_map[clean_name]
        
        # 如果没有映射，使用类型前缀
        if entity_type != "unknown":
            return f"{entity_type}_{clean_name}"
        else:
            return clean_name
