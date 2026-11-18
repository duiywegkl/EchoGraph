"""Shared character-card extraction prompt and world-book batching."""

import json
import re

from loguru import logger
from src.graph.node_types import prompt_types


COMPACT_GRAPH_RULES = (
    '只保留对故事有持续意义的具体实体；不要提取游戏或叙述系统、AI、作为系统的玩家、UI、状态栏、输出格式、'
    '角色扮演或写作规则、提示词指令及卡片标题。'
    '不要把异能、技能、能力、天赋建成节点；写入所属角色的 attributes（如"异能":"力量系强化（C+）"），'
    '多项可用简短列表字符串。只有对故事重要的世界级异能体系才可建 concept 节点。'
    '物品仅保留有名称或对故事长期关键的物品，如命名武器、作为基地的载具；'
    '普通消耗品、道具、补给不记录，连 attributes 也不写。'
    '不要把异能、强者、幸存者、进化者、物资、食物、资源等泛称或仅泛指的群体建成节点；'
    '有名称的势力或反复出现的具体怪物种类可以保留。'
    '关系只连接保留的实体，必须具体且有意义；不要把每个实体都连到主角，也不要连接泛泛概念；'
    '同一实体对不要重复关系，层级关系只选包含或属于一个方向（包括视为包含）。'
)


def world_batches(world_info: str, budget: int = 6000) -> list[str]:
    if not world_info or world_info == 'No world information available.':
        return []
    try:
        decoded = json.loads(world_info)
        entries = ([json.dumps(entry, ensure_ascii=False) for entry in decoded]
                   if isinstance(decoded, list) else [world_info])
    except (ValueError, TypeError):
        entries = [entry for entry in re.split(r'\n\s*\n', world_info) if entry.strip()]
    batches, current = [], ''
    for entry in entries:
        if current and len(current) + len(entry) + 2 > budget:
            batches.append(current)
            current = ''
        if len(entry) > budget:
            logger.warning(f'单条世界书条目超过 {budget} 字符，保持条目完整: {len(entry)} 字符')
        current += ('\n\n' if current else '') + entry
    if current:
        batches.append(current)
    return batches


def extraction_prompt(name, description, personality, scenario, first_mes,
                      example, world_batch, known):
    card = (f'主角色：{name}\n描述：{description}\n性格：{personality}\n'
            f'场景：{scenario}\n首条消息：{first_mes}\n示例：{example}')
    return (f'从以下材料提取知识图谱。主角色始终为 {name}。已知实体：{known}。'
            '只返回 JSON 对象，包含 main_character、entities、relationships。'
            '实体需 name/type，可选简短 description/attributes；关系需 source/target/relationship。'
            '实体名称、描述和关系标签必须与原文使用相同语言；中文原文用中文，不要译成英文。'
            '关系标签应简短，中文用 2–6 个汉字，如位于、属于、看见、持有；不要使用 located_in、part_of 等英文下划线标签。'
            '每个描述不超过 60 字；不要重复或编造实体；关系端点使用实体名称。'
            + COMPACT_GRAPH_RULES
            + '整个基础图谱跨所有批次力求约 30 个节点以内；本批只新增确实重要且未在已知实体中的实体。\n'
            f'角色卡：\n{card}\n世界书条目：\n{world_batch}\n' + prompt_types())
