"""
GRAG更新智能Agent
使用LLM来智能分析对话并生成精确的知识图谱更新指令
"""

import json
from typing import Dict, Any, List, Optional
from loguru import logger
from datetime import datetime

from src.core.llm_client import LLMClient
from src.graph.knowledge_graph import KnowledgeGraph


class GRAGUpdateAgent:
    """
    基于LLM的知识图谱更新智能Agent
    分析用户输入和AI回复，生成精确的图谱更新操作
    """
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        
    def analyze_conversation_for_updates(
        self, 
        user_input: str, 
        llm_response: str, 
        current_graph: KnowledgeGraph,
        recent_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析对话内容，生成知识图谱更新指令
        
        Args:
            user_input: 用户输入
            llm_response: LLM回复
            current_graph: 当前知识图谱状态
            recent_context: 最近的对话上下文
            
        Returns:
            结构化的更新指令
        """
        try:
            # 1. 获取相关的图谱上下文
            relevant_context = self._extract_relevant_graph_context(
                user_input, llm_response, current_graph
            )
            
            # 2. 构建分析Prompt
            analysis_prompt = self._build_analysis_prompt(
                user_input, llm_response, relevant_context, recent_context
            )
            
            # 3. 请求LLM进行分析
            logger.info("正在请求GRAG更新分析...")
            analysis_result = self.llm_client.generate_response(
                analysis_prompt,
                max_tokens=2000,
                temperature=0.1,  # 低温度确保一致性
                system_message="你是一个专门分析RPG对话并生成知识图谱更新指令的智能Agent。请严格按照JSON格式返回分析结果。"
            )
            
            # 4. 解析LLM返回的更新指令
            update_instructions = self._parse_llm_analysis(analysis_result)
            
            logger.info(f"GRAG分析完成: {len(update_instructions.get('operations', []))} 个操作")
            return update_instructions
            
        except Exception as e:
            logger.error(f"GRAG更新分析失败: {e}")
            return {"operations": [], "error": str(e)}
    
    def _extract_relevant_graph_context(
        self, 
        user_input: str, 
        llm_response: str, 
        current_graph: KnowledgeGraph
    ) -> Dict[str, Any]:
        """
        从当前图谱中提取与对话相关的上下文
        """
        # 使用简单的关键词匹配找到相关实体
        # 在实际生产中，这里可以使用更高级的实体识别
        combined_text = f"{user_input} {llm_response}".lower()
        
        relevant_nodes = {}
        relevant_edges = []
        
        # 遍历图中的所有节点，找到可能相关的
        for node_id, node_data in current_graph.graph.nodes(data=True):
            node_name = node_data.get('name', node_id).lower()
            if node_name in combined_text or node_id.lower() in combined_text:
                relevant_nodes[node_id] = node_data
                
                # 获取相关的边
                for src, tgt, edge_data in current_graph.graph.edges(data=True):
                    if src == node_id or tgt == node_id:
                        relevant_edges.append({
                            "source": src,
                            "target": tgt, 
                            "relationship": edge_data.get("relationship", "unknown"),
                            "data": edge_data
                        })
        
        return {
            "nodes": relevant_nodes,
            "edges": relevant_edges,
            "total_nodes": len(current_graph.graph.nodes()),
            "total_edges": len(current_graph.graph.edges())
        }
    
    def _build_analysis_prompt(
        self, 
        user_input: str, 
        llm_response: str, 
        relevant_context: Dict[str, Any],
        recent_context: Optional[str] = None
    ) -> str:
        """
        构建用于LLM分析的Prompt
        """
        current_nodes_desc = ""
        if relevant_context["nodes"]:
            current_nodes_desc = "当前相关节点:\n"
            for node_id, node_data in relevant_context["nodes"].items():
                current_nodes_desc += f"- {node_id}: {node_data}\n"
        
        current_edges_desc = ""
        if relevant_context["edges"]:
            current_edges_desc = "当前相关关系:\n"
            for edge in relevant_context["edges"][:10]:  # 限制显示数量
                current_edges_desc += f"- {edge['source']} --{edge['relationship']}--> {edge['target']}\n"
        
        context_section = ""
        if recent_context:
            context_section = f"\n最近对话上下文:\n{recent_context}\n"
        
        prompt = f"""你是一个RPG知识图谱管理专家。请分析以下对话，确定需要对知识图谱进行的更新操作。

{context_section}
用户输入: {user_input}
AI回复: {llm_response}

当前知识图谱状态:
{current_nodes_desc}
{current_edges_desc}

请仔细分析对话内容，确定需要执行的操作。考虑以下方面:
1. 新出现的实体（角色、物品、地点、组织等）
2. 实体属性的变化（血量、等级、状态、位置等）
3. 实体间关系的变化（装备、位置、敌对、友好等）
4. 实体的消失或删除（死亡、丢失、离开等）
5. 技能学习、状态获得等事件

请严格按照以下JSON格式返回分析结果:

{{
    "analysis_summary": "对话分析总结",
    "operations": [
        {{
            "type": "add_node",
            "node_id": "实体唯一ID",
            "node_type": "实体类型(character/item/location/skill/organization/event)",
            "attributes": {{
                "name": "实体名称",
                "其他属性": "值"
            }},
            "reason": "添加此节点的原因"
        }},
        {{
            "type": "update_node",
            "node_id": "现有节点ID",
            "attributes": {{
                "属性名": "新值"
            }},
            "reason": "更新原因"
        }},
        {{
            "type": "add_edge",
            "source": "源节点ID",
            "target": "目标节点ID", 
            "relationship": "关系类型",
            "attributes": {{}},
            "reason": "添加关系的原因"
        }},
        {{
            "type": "delete_node",
            "node_id": "要删除的节点ID",
            "deletion_type": "death/lost/destroyed/other",
            "reason": "删除原因"
        }},
        {{
            "type": "delete_edge",
            "source": "源节点ID",
            "target": "目标节点ID",
            "relationship": "要删除的关系类型",
            "reason": "删除关系的原因"
        }}
    ],
    "confidence": "分析置信度(0-1)",
    "notes": "额外说明或不确定的地方"
}}

重要提醒:
- 只有在对话中明确提到变化时才生成操作
- 不要重复创建已存在的节点或关系
- 对于模糊或不确定的信息，降低置信度
- 保持节点ID的一致性和可读性
- 优先考虑显式信息，谨慎推断隐含信息"""

        return prompt
    
    def _parse_llm_analysis(self, analysis_result: str) -> Dict[str, Any]:
        """
        解析LLM返回的分析结果
        """
        try:
            # 尝试提取JSON部分
            analysis_result = analysis_result.strip()
            
            # 如果包含代码块，提取JSON
            if "```json" in analysis_result:
                start = analysis_result.find("```json") + 7
                end = analysis_result.find("```", start)
                json_str = analysis_result[start:end].strip()
            elif "```" in analysis_result:
                start = analysis_result.find("```") + 3
                end = analysis_result.rfind("```")
                json_str = analysis_result[start:end].strip()
            else:
                json_str = analysis_result
            
            # 解析JSON
            parsed_result = json.loads(json_str)
            
            # 验证必要字段
            if "operations" not in parsed_result:
                parsed_result["operations"] = []
            
            # 验证每个操作的格式
            validated_operations = []
            for op in parsed_result["operations"]:
                if self._validate_operation(op):
                    validated_operations.append(op)
                else:
                    logger.warning(f"跳过无效操作: {op}")
            
            parsed_result["operations"] = validated_operations
            return parsed_result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.debug(f"原始响应: {analysis_result}")
            return {
                "operations": [],
                "error": "JSON格式解析失败",
                "raw_response": analysis_result
            }
        except Exception as e:
            logger.error(f"分析结果解析失败: {e}")
            return {
                "operations": [],
                "error": str(e),
                "raw_response": analysis_result
            }
    
    def _validate_operation(self, operation: Dict[str, Any]) -> bool:
        """
        验证操作格式是否正确
        """
        if not isinstance(operation, dict):
            return False
        
        op_type = operation.get("type")
        if op_type not in ["add_node", "update_node", "add_edge", "delete_node", "delete_edge"]:
            logger.warning(f"未知操作类型: {op_type}")
            return False
        
        # 验证每种操作的必需字段
        if op_type == "add_node":
            return all(key in operation for key in ["node_id", "node_type", "attributes"])
        elif op_type == "update_node":
            return all(key in operation for key in ["node_id", "attributes"])
        elif op_type == "add_edge":
            return all(key in operation for key in ["source", "target", "relationship"])
        elif op_type in ["delete_node", "delete_edge"]:
            return "reason" in operation
        
        return True
    
    def convert_to_execution_format(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将Agent分析结果转换为执行格式
        """
        nodes_to_add = []
        nodes_to_update = []
        edges_to_add = []
        nodes_to_delete = []
        edges_to_delete = []
        
        for operation in analysis_result.get("operations", []):
            op_type = operation["type"]
            
            if op_type == "add_node":
                nodes_to_add.append({
                    "node_id": operation["node_id"],
                    "type": operation["node_type"],
                    "attributes": operation["attributes"]
                })
            
            elif op_type == "update_node":
                nodes_to_update.append({
                    "node_id": operation["node_id"],
                    "attributes": operation["attributes"]
                })
            
            elif op_type == "add_edge":
                edges_to_add.append({
                    "source": operation["source"],
                    "target": operation["target"],
                    "relationship": operation["relationship"],
                    "attributes": operation.get("attributes", {})
                })
            
            elif op_type == "delete_node":
                nodes_to_delete.append({
                    "node_id": operation["node_id"],
                    "deletion_type": operation.get("deletion_type", "other"),
                    "reason": operation["reason"]
                })
            
            elif op_type == "delete_edge":
                edges_to_delete.append({
                    "source": operation["source"],
                    "target": operation["target"],
                    "relationship": operation.get("relationship"),
                    "reason": operation["reason"]
                })
        
        return {
            "nodes_to_add": nodes_to_add,
            "nodes_to_update": nodes_to_update,
            "edges_to_add": edges_to_add,
            "nodes_to_delete": nodes_to_delete,
            "edges_to_delete": edges_to_delete,
            "analysis_summary": analysis_result.get("analysis_summary", ""),
            "confidence": analysis_result.get("confidence", 0.5),
            "notes": analysis_result.get("notes", "")
        }