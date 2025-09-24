"""
图谱管理路由
处理知识图谱的节点和边操作
"""

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger

from ..models.requests import NodeUpdateRequest, EdgeCreateRequest
from ..models.responses import NodeOperationResponse, EdgeOperationResponse
from ..services.memory_service import MemoryService, get_memory_service
from ...utils.exceptions import SessionError, GraphError, ValidationError

router = APIRouter(prefix="/graph", tags=["graph"])


@router.put("/sessions/{session_id}/nodes/{old_node_name}", response_model=NodeOperationResponse)
async def update_node(
    session_id: str,
    old_node_name: str,
    node_data: NodeUpdateRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """更新节点（覆盖信息，支持重命名）"""
    try:
        result = await memory_service.update_node(session_id, old_node_name, node_data)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except GraphError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 更新节点失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update node: {e}")


@router.delete("/sessions/{session_id}/nodes/{node_name}", response_model=NodeOperationResponse)
async def delete_node(
    session_id: str,
    node_name: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """删除节点"""
    try:
        result = await memory_service.delete_node(session_id, node_name)
        return result
    except GraphError as e:
        if e.error_code.value == 5001:  # NODE_NOT_FOUND
            raise HTTPException(status_code=404, detail=e.to_dict())
        else:
            raise HTTPException(status_code=500, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 删除节点失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete node: {e}")


@router.post("/sessions/{session_id}/edges", response_model=EdgeOperationResponse)
async def create_edge(
    session_id: str,
    edge_data: EdgeCreateRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """创建关系"""
    try:
        result = await memory_service.create_edge(session_id, edge_data)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except GraphError as e:
        if e.error_code.value == 5001:  # NODE_NOT_FOUND
            raise HTTPException(status_code=404, detail=e.to_dict())
        else:
            raise HTTPException(status_code=500, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 创建关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create edge: {e}")


@router.get("/sessions/{session_id}/nodes")
async def list_nodes(
    session_id: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """列出所有节点"""
    try:
        # 获取会话引擎
        if session_id not in memory_service._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id
            )

        engine = memory_service._sessions[session_id]
        nodes = []

        for node_id, node_data in engine.memory.knowledge_graph.graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "name": node_data.get("name", node_id),
                "type": node_data.get("type", "unknown"),
                "description": node_data.get("description", ""),
                "attributes": {k: v for k, v in node_data.items()
                             if k not in ["name", "type", "description"]}
            })

        return {
            "nodes": nodes,
            "total_count": len(nodes)
        }

    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 列出节点失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list nodes: {e}")


@router.get("/sessions/{session_id}/edges")
async def list_edges(
    session_id: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """列出所有关系"""
    try:
        # 获取会话引擎
        if session_id not in memory_service._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id
            )

        engine = memory_service._sessions[session_id]
        edges = []

        for source, target, edge_data in engine.memory.knowledge_graph.graph.edges(data=True):
            edges.append({
                "source": source,
                "target": target,
                "relationship": edge_data.get("relationship", "related_to"),
                "description": edge_data.get("description", ""),
                "attributes": {k: v for k, v in edge_data.items()
                             if k not in ["relationship", "description"]}
            })

        return {
            "edges": edges,
            "total_count": len(edges)
        }

    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 列出关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list edges: {e}")


@router.get("/sessions/{session_id}/visualization")
async def get_graph_visualization_data(
    session_id: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """获取图谱可视化数据"""
    try:
        # 获取会话引擎
        if session_id not in memory_service._sessions:
            raise SessionError(
                f"Session {session_id} not found",
                session_id=session_id
            )

        engine = memory_service._sessions[session_id]
        graph = engine.memory.knowledge_graph.graph

        # 构造可视化数据
        nodes = []
        edges = []

        # 节点数据
        for node_id, node_data in graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "label": node_data.get("name", node_id),
                "group": node_data.get("type", "unknown"),
                "title": node_data.get("description", ""),
                "color": _get_node_color(node_data.get("type", "unknown"))
            })

        # 边数据
        for source, target, edge_data in graph.edges(data=True):
            edges.append({
                "from": source,
                "to": target,
                "label": edge_data.get("relationship", ""),
                "title": edge_data.get("description", ""),
                "arrows": "to"
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges)
            }
        }

    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 获取可视化数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get visualization data: {e}")


def _get_node_color(node_type: str) -> str:
    """根据节点类型获取颜色"""
    color_map = {
        "character": "#FF6B6B",
        "location": "#4ECDC4",
        "item": "#45B7D1",
        "skill": "#96CEB4",
        "organization": "#FECA57",
        "event": "#FF9FF3",
        "concept": "#A8E6CF"
    }
    return color_map.get(node_type, "#DDA0DD")