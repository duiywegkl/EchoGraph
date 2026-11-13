import json
import re
from typing import Dict, Any, List, TYPE_CHECKING
from loguru import logger

from src.graph.node_types import prompt_types
from src.utils.config import config
from src.core.rpg_text_processor import RPGTextProcessor
from src.core.perception import PerceptionModule
from src.memory import GRAGMemory
from src.core.validation import ValidationLayer

if TYPE_CHECKING:
    from src.core.grag_update_agent import GRAGUpdateAgent

class GameEngine:
    """EchoGraph 核心游戏引擎，适配 SillyTavern 插件后端"""
    
    def __init__(self, memory: GRAGMemory, perception: PerceptionModule, rpg_processor: RPGTextProcessor, validation_layer: ValidationLayer, grag_agent: 'GRAGUpdateAgent' = None):
        self.memory = memory
        self.perception = perception
        self.rpg_processor = rpg_processor
        self.validation_layer = validation_layer
        self.grag_agent = grag_agent
        logger.info(f"GameEngine 初始化完成，{'支持智能Agent分析' if grag_agent else '未启用Agent（将跳过自动图谱维护）'}。")

    def initialize_from_tavern_data(self, character_card: Dict[str, Any], world_info: str):
        """Extract card and world book in bounded batches, then commit once."""
        name = character_card.get('name') or 'Unknown Character'
        if not self._is_llm_available():
            raise RuntimeError('酒馆初始化失败：LLM 不可用')
        return self._perform_llm_analysis(
            name, character_card.get('description', ''), character_card.get('personality', ''),
            character_card.get('scenario', ''), character_card.get('first_mes', ''),
            character_card.get('mes_example', ''), world_info,
        )

    def _is_strict_tavern_init(self, character_card: Dict[str, Any]) -> bool:
        """酒馆模式强制LLM初始化：失败直接中止，不回退简化初始化。"""
        tags = character_card.get("tags", [])
        if isinstance(tags, (list, tuple, set)):
            return "tavern_mode" in tags or "plugin_submitted" in tags
        return False
    
    def _is_llm_available(self) -> bool:
        """检查LLM是否可用"""
        try:
            # 检查是否有gRAG Agent
            if not self.grag_agent:
                logger.info("📝 没有gRAG Agent，LLM不可用")
                return False
            
            # 检查是否有LLM客户端
            if not hasattr(self.grag_agent, 'llm_client') or not self.grag_agent.llm_client:
                logger.info("📝 没有LLM客户端，LLM不可用")
                return False
            
            # 检查API密钥配置
            from src.utils.config import config
            if not config.llm.api_key:
                logger.info("📝 LLM API密钥未配置，LLM不可用")
                return False
            
            logger.info("[OK] LLM检查通过，可以使用智能分析")
            return True
            
        except Exception as e:
            logger.warning(f"[WARN] LLM可用性检查失败: {e}")
            return False
    
    def _world_batches(self, world_info: str, budget: int = 6000) -> List[str]:
        """Keep world-book entries intact. Blank lines delimit plain-text entries."""
        if not world_info or world_info == 'No world information available.':
            return []
        try:
            decoded = json.loads(world_info)
            if isinstance(decoded, list):
                entries = [json.dumps(entry, ensure_ascii=False) for entry in decoded]
            else:
                entries = [world_info]
        except (ValueError, TypeError):
            entries = [entry for entry in re.split(r'\n\s*\n', world_info) if entry.strip()]
        batches, current = [], ''
        for entry in entries:
            if current and len(current) + len(entry) + 2 > budget:
                batches.append(current)
                current = ''
            if len(entry) > budget:
                logger.warning(f'⚠️ 单条世界书条目超过 {budget} 字符，保持条目完整: {len(entry)} 字符')
            current = current + ('\n\n' if current else '') + entry
        if current:
            batches.append(current)
        return batches

    def _perform_llm_analysis(self, name: str, description: str, personality: str,
                             scenario: str, first_mes: str, example: str, world_info: str) -> Dict[str, Any]:
        from src.utils.llm_json import request_json, validate_kg
        batches = [''] + self._world_batches(world_info)
        card = (f'主角色：{name}\n描述：{description}\n性格：{personality}\n'
                f'场景：{scenario}\n首条消息：{first_mes}\n示例：{example}')
        entities, relationships = {}, {}
        canonical = {name.strip().casefold(): name}
        main = {'name': name, 'type': 'character', 'attributes': {'is_main_character': True}}
        failures = []
        rounds_used = 0
        for index, world_batch in enumerate(batches):
            known = ', '.join(list(canonical.values())[:80])
            prompt = (f'从以下材料提取知识图谱。主角色始终为 {name}。已知实体：{known}。'
                      '只返回 JSON 对象，包含 main_character、entities、relationships。'
                      '实体需 name/type，可选简短 description/attributes；关系需 source/target/relationship。'
                      '每个描述不超过 60 字；不要重复或编造实体；关系端点使用实体名称。\n'
                      f'角色卡：\n{card}\n世界书条目：\n{world_batch}')
            prompt += "\n" + prompt_types()
            logger.info(f'📚 KG 批次 {index + 1}/{len(batches)} | 输入长度={len(prompt)}')
            try:
                parsed, used = request_json(
                    self.grag_agent.llm_client, prompt,
                    '你是知识图谱提取助手。只输出简洁的 JSON。', validate_kg,
                )
                rounds_used += used
                if isinstance(parsed.get('main_character'), dict):
                    main.update(parsed['main_character'])
                    main['name'] = name
                for entity in parsed['entities']:
                    key = entity['name'].strip().casefold()
                    if key == name.strip().casefold():
                        continue
                    if key in entities:
                        previous = entities[key]
                        previous.setdefault('attributes', {}).update(entity.get('attributes') or {})
                        if not previous.get('description'):
                            previous['description'] = entity.get('description', '')
                    else:
                        entities[key] = entity.copy()
                        canonical[key] = entity['name']
                for rel in parsed['relationships']:
                    source = rel['source'].strip().casefold()
                    target = rel['target'].strip().casefold()
                    if source not in canonical or target not in canonical:
                        continue
                    key = (source, target, rel['relationship'].strip().casefold())
                    relationships[key] = {**rel, 'source': canonical[source], 'target': canonical[target]}
            except Exception as error:
                failures.append(f'批次 {index + 1}/{len(batches)}: {error}')
                logger.error(f'❌ KG 批次 {index + 1}/{len(batches)} 失败: {error}')
            logger.info(f'📚 KG 进度 {index + 1}/{len(batches)} | 实体={len(entities) + 1} | 关系={len(relationships)}')
        if len(failures) == len(batches):
            raise RuntimeError('酒馆初始化失败：' + '；'.join(failures))
        parsed = {'main_character': main, 'entities': list(entities.values()),
                  'relationships': list(relationships.values())}
        nodes, edges = self._apply_llm_analysis_results(parsed, name)
        if self.memory.graph_save_path:
            self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)
        self.memory.sync_entities_to_json()
        reason = '；'.join(failures) if failures else ''
        if rounds_used:
            reason = (reason + '；' if reason else '') + f'JSON 修复 {rounds_used} 轮'
        return {'nodes_added': nodes, 'edges_added': edges,
                'method': 'partial' if failures else 'llm_analysis',
                'reason': reason, 'repair_rounds': rounds_used, 'character_name': name}

    def _build_character_analysis_prompt(self, name: str, description: str, personality: str, 
                                       scenario: str, first_mes: str, example: str, world_info: str) -> str:
        """构建角色分析的LLM提示词"""
        prompt = f"""
你是一个专业的知识图谱构建助手，请仔细分析以下角色扮演游戏角色卡，提取所有实体和关系。

【关键要求】：必须创建尽可能多的关系连接，确保实体之间形成有意义的知识网络！

角色信息：
角色名称: {name}

角色描述:
{description}

性格特征:
{personality}

背景场景:
{scenario}

首次对话:
{first_mes}

对话示例:
{example}

世界设定信息:
{world_info}

请返回完整的JSON结构（不要截断）：
{{
    "main_character": {{
        "name": "角色主名称",
        "type": "character",
        "attributes": {{
            "description": "角色简要描述（不超过200字符）",
            "personality_traits": ["性格特征1", "性格特征2"],
            "background": "背景简述",
            "is_main_character": true
        }}
    }},
    "entities": [
        {{
            "name": "实体名称",
            "type": "character",
            "subtype": "optional specific category",
            "description": "实体描述",
            "attributes": {{
                "key": "value"
            }}
        }}
    ],
    "relationships": [
        {{
            "source": "源实体名称（必须与entities或main_character中的name完全匹配）",
            "target": "目标实体名称（必须与entities或main_character中的name完全匹配）",
            "relationship": "关系类型（朋友/敌人/拥有/位于/属于/掌握/统治/保护/服务等）",
            "description": "关系描述"
        }}
    ]
}}

【重要规则】：
1. 名称匹配：relationships中的source和target必须与entities或main_character中的name完全一致
2. 关系密度：每个实体都应该至少连接到2-3个其他实体
3. 关系类型：包括但不限于：
   - 人际关系：朋友、敌人、同事、家人、师生、恋人、竞争对手
   - 位置关系：居住、工作、访问、统治、守护、位于
   - 物品关系：拥有、使用、制造、寻找、丢失
   - 技能关系：掌握、学习、教授、专长
   - 组织关系：属于、管理、服务、对立
4. 必须完整输出：不要因为长度限制而截断JSON，确保完整的右括号结尾
5. 关系优先：宁可少几个实体，也要确保实体间有充分的关系连接

开始分析并输出完整JSON（确保以}}结尾）：
"""
        return (prompt + "\n" + prompt_types()).strip()
    
    def _apply_llm_analysis_results(self, parsed_data: Dict[str, Any], char_name: str) -> tuple[int, int]:
        """将LLM解析结果应用到知识图谱"""
        nodes_added = 0
        edges_added = 0

        logger.info(f"[Apply Results] 开始应用LLM分析结果到知识图谱")

        try:
            # 1. 添加主角色
            main_char_data = parsed_data.get("main_character")
            if main_char_data:
                char_id = self._generate_entity_id(main_char_data.get("name", char_name), "character")
                attributes = main_char_data.get("attributes", {})
                attributes.update({
                    "name": main_char_data.get("name", char_name),
                    "source": "llm_character_card",
                    "is_main_character": True
                })

                logger.info(f"[Apply Results] 正在添加主角色: {main_char_data.get('name', char_name)} -> {char_id}")
                self.memory.add_or_update_node(char_id, "character", **attributes)
                nodes_added += 1
                logger.info(f"[Apply Results] 主角色添加成功, 当前 nodes_added = {nodes_added}")
            else:
                logger.warning(f"[Apply Results] 未找到主角色数据")

            # 2. 添加其他实体
            entities = parsed_data.get("entities", [])
            logger.info(f"[Apply Results] 开始添加 {len(entities)} 个实体...")
            for i, entity in enumerate(entities):
                if not entity.get("name"):
                    logger.warning(f"[Apply Results] 实体{i+1}缺少名称，跳过")
                    continue

                entity_id = self._generate_entity_id(entity["name"], entity.get("type", "unknown"))
                attributes = entity.get("attributes", {})
                attributes.update({
                    "name": entity["name"],
                    "description": entity.get("description", ""),
                    "source": "llm_analysis",
                    **({"subtype": entity["subtype"]} if entity.get("subtype") else {})
                })

                logger.info(f"[Apply Results] 正在添加实体{i+1}: {entity['name']} ({entity.get('type', 'unknown')}) -> {entity_id}")
                self.memory.add_or_update_node(entity_id, entity.get("type", "unknown"), **attributes)
                nodes_added += 1
                logger.info(f"[Apply Results] 实体{i+1}添加成功, 当前 nodes_added = {nodes_added}")
            
            # 3. 添加关系
            relationships = parsed_data.get("relationships", [])
            logger.info(f"[Apply Results] 开始添加 {len(relationships)} 个关系...")

            # 创建一个实体名称到ID的映射，用于关系建立
            entity_name_to_id = {}

            # 添加主角色到映射
            if main_char_data:
                char_name_final = main_char_data.get("name", char_name)
                char_id = self._generate_entity_id(char_name_final, "character")
                entity_name_to_id[char_name_final] = char_id
                logger.info(f"[Apply Results] 主角色映射: '{char_name_final}' -> '{char_id}'")

            # 添加所有实体到映射
            entities = parsed_data.get("entities", [])
            for entity in entities:
                if entity.get("name"):
                    entity_id = self._generate_entity_id(entity["name"], entity.get("type", "unknown"))
                    entity_name_to_id[entity["name"]] = entity_id
                    logger.debug(f"[Apply Results] 实体映射: '{entity['name']}' -> '{entity_id}'")

            logger.info(f"[Apply Results] 实体名称映射完成，共 {len(entity_name_to_id)} 个映射")

            # 建立关系
            for i, rel in enumerate(relationships):
                source_name = rel.get("source")
                target_name = rel.get("target")

                if not source_name or not target_name:
                    logger.warning(f"[Apply Results] 关系{i+1}缺少源或目标名称，跳过")
                    continue

                # 从映射中获取正确的实体ID
                source_id = entity_name_to_id.get(source_name)
                target_id = entity_name_to_id.get(target_name)

                if not source_id or not target_id:
                    logger.warning(f"[Apply Results] 关系{i+1}找不到实体ID: source='{source_name}' -> {source_id}, target='{target_name}' -> {target_id}")
                    logger.warning(f"[Apply Results] 可用实体映射: {list(entity_name_to_id.keys())}")
                    continue

                relationship = rel.get("relationship", "related")
                logger.info(f"[Apply Results] 正在添加关系{i+1}: {source_name}({source_id}) --{relationship}--> {target_name}({target_id})")

                # 确保源和目标实体存在
                if (self.memory.knowledge_graph.get_node(source_id) and
                    self.memory.knowledge_graph.get_node(target_id)):
                    self.memory.add_edge(source_id, target_id, relationship)
                    edges_added += 1
                    logger.info(f"[Apply Results] 关系{i+1}添加成功, 当前 edges_added = {edges_added}")
                else:
                    logger.warning(f"[Apply Results] 关系{i+1}中的实体不存在: {source_id} 或 {target_id}")

        except Exception:
            logger.exception('❌ 应用 LLM 分析结果失败')
            raise

        logger.info(f"[Apply Results] 应用完成: 最终统计 nodes_added={nodes_added}, edges_added={edges_added}")
        return nodes_added, edges_added
    
    def _generate_entity_id(self, name: str, entity_type: str) -> str:
        """生成一致的实体ID"""
        clean_name = name.strip().lower().replace(" ", "_")
        return f"{entity_type}_{clean_name}"
    
    def _fallback_simple_initialization(self, char_name: str, char_description: str) -> Dict[str, Any]:
        """简化的回退初始化方法，仅创建主角色实体"""
        logger.info("🔄 使用简化模式初始化角色...")
        
        try:
            # 只创建主角色实体
            character_id = self._generate_entity_id(char_name, "character")
            
            attributes = {
                "name": char_name,
                "description": char_description[:200] if char_description else "主要角色",
                "is_main_character": True,
                "source": "simple_fallback"
            }
            
            self.memory.add_or_update_node(character_id, "character", **attributes)
            
            logger.info(f"[OK] 简化初始化完成: 1 个主角色实体")
            
            # 保存图谱到GraphML格式
            if self.memory.graph_save_path:
                self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)

            # 同步实体数据到JSON文件，供UI使用
            self.memory.sync_entities_to_json()
            logger.info("[OK] 简化模式实体数据已同步到 entities.json")

            return {
                "nodes_added": 1,
                "edges_added": 0,
                "method": "simple_fallback",
                "character_name": char_name
            }
            
        except Exception as e:
            logger.error(f"❌ 简化初始化也失败了: {e}")
            return {
                "nodes_added": 0,
                "edges_added": 0,
                "method": "failed",
                "error": str(e)
            }

    def extract_updates_from_response(self, llm_response: str, user_input: str = "") -> Dict[str, Any]:
        """
        智能分析对话内容，生成精确的知识图谱更新操作。
        图谱维护只允许GRAG Agent（LLM）执行，不允许正则回退。
        """
        if self.grag_agent:
            logger.info("使用GRAG智能Agent分析对话更新...")
            return self._extract_with_agent(user_input, llm_response)
        logger.warning("未配置GRAG Agent：按策略跳过图谱更新（禁用正则/规则维护）。")
        return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}
    
    def _extract_with_agent(self, user_input: str, llm_response: str) -> Dict[str, Any]:
        """使用GRAG Agent进行智能分析"""
        try:
            # 1. Agent分析对话生成更新指令
            recent_context = self._get_recent_conversation_context()
            analysis_result = self.grag_agent.analyze_conversation_for_updates(
                user_input=user_input,
                llm_response=llm_response, 
                current_graph=self.memory.knowledge_graph,
                recent_context=recent_context
            )
            
            if "error" in analysis_result:
                logger.warning(f"Agent分析失败，本轮不更新图谱: {analysis_result['error']}")
                return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}
            
            # 2. 将Agent结果转换为执行格式
            execution_format = self.grag_agent.convert_to_execution_format(analysis_result)
            
            # 3. 验证更新
            validated_updates = self.validation_layer.validate(execution_format, self.memory.knowledge_graph)
            
            # 4. 应用更新
            return self._apply_validated_updates(validated_updates, source="grag_agent")
            
        except Exception as e:
            logger.error(f"Agent分析过程出错: {e}")
            return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}
    
    def _extract_with_local_processor(self, llm_response: str) -> Dict[str, Any]:
        """保留历史接口；当前策略禁用本地规则维护。"""
        logger.warning("本地RPG规则更新已禁用，不执行任何图谱维护。")
        return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}
    
    def _apply_validated_updates(self, validated_updates: Dict[str, Any], source: str = "unknown") -> Dict[str, Any]:
        """统一的更新应用逻辑"""
        if not validated_updates:
            logger.info("没有有效的更新需要应用")
            return {"nodes_updated": 0, "edges_added": 0, "nodes_deleted": 0, "edges_deleted": 0}

        nodes_updated_count = len(validated_updates.get("nodes_to_update", []))
        edges_added_count = len(validated_updates.get("edges_to_add", []))
        nodes_deleted_count = 0
        edges_deleted_count = 0

        # 处理删除事件（优先）
        deletion_stats = self._process_deletion_events(validated_updates)
        nodes_deleted_count = deletion_stats.get("nodes_deleted", 0)
        edges_deleted_count = deletion_stats.get("edges_deleted", 0)

        # 应用节点更新
        for node_update in validated_updates.get("nodes_to_update", []):
            try:
                # 检查节点是否存在，如果不存在则创建
                if not self.memory.knowledge_graph.graph.has_node(node_update['node_id']):
                    # 尝试从属性中推断类型
                    node_type = node_update.get('type', 'unknown')
                    if node_type == 'unknown' and "location" in node_update.get('attributes', {}):
                        node_type = "character" # 有位置的通常是角色
                    
                    self.memory.add_or_update_node(
                        node_update['node_id'], 
                        node_type, 
                        **node_update['attributes']
                    )
                else:
                    # 节点存在，只更新属性
                    existing_node = self.memory.knowledge_graph.get_node(node_update['node_id'])
                    node_type = existing_node.get('type', 'unknown')
                    self.memory.add_or_update_node(
                        node_update['node_id'], 
                        node_type, 
                        **node_update['attributes']
                    )
            except Exception as e:
                logger.warning(f"Failed to update node {node_update['node_id']}: {e}")
                nodes_updated_count -= 1
        
        # 应用边更新
        for edge_add in validated_updates.get("edges_to_add", []):
            try:
                self.memory.add_edge(
                    edge_add['source'], 
                    edge_add['target'], 
                    edge_add['relationship']
                )
            except Exception as e:
                logger.warning(f"Failed to add edge {edge_add['source']} -> {edge_add['target']}: {e}")
                edges_added_count -= 1
        
        logger.info(f"成功应用更新({source}): {nodes_updated_count} nodes updated, {edges_added_count} edges added, {nodes_deleted_count} nodes deleted, {edges_deleted_count} edges deleted.")
        
        # 保存知识图谱到GraphML格式
        if self.memory.graph_save_path:
            self.memory.knowledge_graph.save_graph(self.memory.graph_save_path)

        # 同步实体数据到JSON文件，供UI使用
        self.memory.sync_entities_to_json()
        logger.info("[OK] 实体数据已同步到 entities.json")

        return {
            "nodes_updated": nodes_updated_count,
            "edges_added": edges_added_count,
            "nodes_deleted": nodes_deleted_count,
            "edges_deleted": edges_deleted_count
        }
    
    def _get_recent_conversation_context(self) -> str:
        """获取最近的对话上下文用于Agent分析"""
        try:
            recent_history = list(self.memory.basic_memory.conversation_history)[-3:]  # 最近3轮对话
            context_parts = []
            
            for turn in recent_history:
                user_msg = turn.get("user", "")
                assistant_msg = turn.get("assistant") or turn.get("ai", "")
                if user_msg:
                    context_parts.append(f"用户: {user_msg}")
                if assistant_msg:
                    context_parts.append(f"助手: {assistant_msg}")
            
            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.debug(f"获取最近对话上下文失败: {e}")
            return ""

    def _process_deletion_events(self, validated_updates: Dict[str, Any]) -> Dict[str, int]:
        """
        处理删除事件，包括节点删除和边删除
        
        Args:
            validated_updates: 验证后的更新数据
            
        Returns:
            Dict: 删除统计信息
        """
        nodes_deleted = 0
        edges_deleted = 0
        
        # 处理节点删除
        for node_deletion in validated_updates.get("nodes_to_delete", []):
            try:
                node_id = node_deletion["node_id"]
                deletion_type = node_deletion.get("deletion_type", "default")
                reason = node_deletion.get("reason", "No reason provided")
                
                if deletion_type == "death":
                    # 角色死亡使用软删除
                    self.memory.mark_node_as_deleted(node_id, reason)
                    logger.info(f"Character marked as dead: {node_id} - {reason}")
                elif deletion_type == "lost":
                    # 物品丢失使用硬删除
                    if self.memory.delete_node(node_id):
                        logger.info(f"Item permanently deleted: {node_id} - {reason}")
                    else:
                        logger.warning(f"Failed to delete node {node_id}: node not found")
                        continue
                else:
                    # 默认软删除
                    self.memory.mark_node_as_deleted(node_id, reason)
                    logger.info(f"Node marked as deleted: {node_id} - {reason}")
                
                nodes_deleted += 1
                
            except Exception as e:
                logger.warning(f"Failed to process node deletion {node_deletion.get('node_id', 'unknown')}: {e}")
        
        # 处理边删除
        for edge_deletion in validated_updates.get("edges_to_delete", []):
            try:
                source = edge_deletion.get("source")
                target = edge_deletion.get("target") 
                relationship = edge_deletion.get("relationship")
                reason = edge_deletion.get("reason", "No reason provided")
                
                # 支持通配符删除
                if source == "*" or relationship == "*":
                    # 找到所有匹配的边并删除
                    graph = self.memory.knowledge_graph.graph
                    edges_to_remove = []
                    
                    for src, tgt, edge_data in graph.edges(data=True):
                        match = True
                        if source != "*" and src != source:
                            match = False
                        if target != "*" and tgt != target:
                            match = False
                        if relationship != "*" and edge_data.get("relationship") != relationship:
                            match = False
                        
                        if match:
                            edges_to_remove.append((src, tgt, edge_data.get("relationship")))
                    
                    for src, tgt, rel in edges_to_remove:
                        if self.memory.delete_edge(src, tgt, rel):
                            edges_deleted += 1
                            logger.info(f"Edge deleted: {src} --{rel}--> {tgt} - {reason}")
                else:
                    # 精确删除
                    if self.memory.delete_edge(source, target, relationship):
                        edges_deleted += 1
                        logger.info(f"Edge deleted: {source} --{relationship}--> {target} - {reason}")
                    else:
                        logger.warning(f"Failed to delete edge {source} -> {target}: edge not found")
                        
            except Exception as e:
                logger.warning(f"Failed to process edge deletion: {e}")
        
        return {
            "nodes_deleted": nodes_deleted,
            "edges_deleted": edges_deleted
        }
