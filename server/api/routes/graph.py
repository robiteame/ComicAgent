from fastapi import APIRouter

from agent.graph import GRAPH_NODE_META, get_graph

router = APIRouter(prefix="/api/graph", tags=["graph"])

_SPECIAL_NODES = {
    "__start__": {"label": "开始", "type": "input", "description": "自动流水线入口"},
    "__end__": {"label": "完成", "type": "output", "description": "输出可播放成片"},
}


@router.get("/structure")
async def get_graph_structure():
    """从 build_graph() 派生的真实图结构(自动模式执行器),供前端可视化。

    与 agent/graph.py 单一事实源同步,杜绝手写结构漂移。
    """
    drawable = get_graph().get_graph()

    nodes = []
    for node_id in drawable.nodes:
        meta = _SPECIAL_NODES.get(node_id) or GRAPH_NODE_META.get(
            node_id, {"label": node_id, "type": "process", "description": ""}
        )
        nodes.append({"id": node_id, **meta})

    edges = [{"source": edge.source, "target": edge.target, "label": ""} for edge in drawable.edges]

    return {"nodes": nodes, "edges": edges}
