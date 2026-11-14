"""Shared character-card extraction prompt and world-book batching."""

import json
import re

from loguru import logger
from src.graph.node_types import prompt_types


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
            '每个描述不超过 60 字；不要重复或编造实体；关系端点使用实体名称。\n'
            f'角色卡：\n{card}\n世界书条目：\n{world_batch}\n' + prompt_types())
