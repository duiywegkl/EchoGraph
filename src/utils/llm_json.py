"""Validated JSON extraction from LLM responses, with bounded repair."""
import json
import re
from typing import Callable

import json_repair
from loguru import logger
from src.graph.node_types import TYPE_IDS, SYNONYMS, normalize_type


def validate_kg(value):
    if not isinstance(value, dict):
        raise ValueError('顶层必须是对象')
    for key in ('entities', 'relationships'):
        if not isinstance(value.get(key), list):
            raise ValueError(f'{key} 必须是数组')
    main = value.get('main_character')
    if main is not None and (not isinstance(main, dict) or not isinstance(main.get('name'), str) or not main['name'].strip()):
        raise ValueError('main_character.name 无效')
    if main is not None:
        raw_main = main.get('type', 'character')
        if not isinstance(raw_main, str) or raw_main.strip() not in TYPE_IDS and raw_main.strip().casefold() not in SYNONYMS:
            raise ValueError('main_character.type ??')
        main['type'], detail = normalize_type(raw_main, main.get('subtype'))
        if detail:
            main['subtype'] = detail
    for index, item in enumerate(value['entities']):
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('name', 'type')):
            raise ValueError(f'entities[{index}] 缺少 name/type')
        if 'subtype' in item and not isinstance(item['subtype'], str):
            raise ValueError(f'entities[{index}].subtype ??')
        raw = item['type'].strip()
        if raw not in TYPE_IDS and raw.casefold() not in SYNONYMS:
            raise ValueError(f'entities[{index}].type 无效: {raw}')
        item['type'], detail = normalize_type(raw, item.get('subtype'))
        if detail:
            item['subtype'] = detail
    for index, item in enumerate(value['relationships']):
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('source', 'target', 'relationship')):
            raise ValueError(f'relationships[{index}] 缺少 source/target/relationship')
    return value


def validate_operations(value):
    if not isinstance(value, dict) or not isinstance(value.get('operations'), list):
        raise ValueError('operations 必须是数组')
    if any(not isinstance(op, dict) for op in value['operations']):
        raise ValueError('operations 含非对象项目')
    for index, op in enumerate(value['operations']):
        if op.get('type') == 'add_node':
            if 'subtype' in op and not isinstance(op['subtype'], str):
                raise ValueError(f'operations[{index}].subtype ??')
            raw = op.get('node_type')
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(f'operations[{index}].node_type 无效')
            if raw.strip() not in TYPE_IDS and raw.strip().casefold() not in SYNONYMS:
                raise ValueError(f'operations[{index}].node_type 无效: {raw}')
            op['node_type'], detail = normalize_type(raw, op.get('subtype'))
            if detail:
                op['subtype'] = detail
        attrs = op.get('attributes')
        if isinstance(attrs, dict) and 'type' in attrs:
            raw = attrs['type']
            if not isinstance(raw, str) or (raw.strip() not in TYPE_IDS and raw.strip().casefold() not in SYNONYMS):
                raise ValueError(f'operations[{index}].attributes.type ??')
            attrs['type'], detail = normalize_type(raw, attrs.get('subtype'))
            if detail:
                attrs['subtype'] = detail
    return value


def _json_text(raw):
    raw = raw.strip()
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)(?:```|$)', raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    start = min((i for i in (raw.find('{'), raw.find('[')) if i >= 0), default=-1)
    return raw[start:] if start >= 0 else raw


def _parse(raw, validator, truncated):
    source = _json_text(raw)
    try:
        value = json.loads(source)
        return validator(value)
    except (json.JSONDecodeError, ValueError, TypeError) as strict_error:
        logger.warning(f'⚠️ LLM JSON 严格解析失败: {strict_error}; 长度={len(source)}')
    value = json_repair.loads(source)
    if truncated and isinstance(value, dict):
        for key, required in (('entities', ('name', 'type')), ('relationships', ('source', 'target', 'relationship'))):
            items = value.get(key)
            if isinstance(items, list) and items and isinstance(items[-1], dict) and any(not items[-1].get(field) for field in required):
                items.pop()
                logger.warning(f'⚠️ 截断响应丢弃末尾不完整的 {key} 项')
    return validator(value)


def request_json(llm_client, prompt: str, system_message: str, validator: Callable,
                 temperature: float = 0.1):
    """Initial call plus at most three continuation/correction calls."""
    messages = [{'role': 'system', 'content': system_message}, {'role': 'user', 'content': prompt}]

    def call(items, json_mode):
        if hasattr(llm_client, 'chat_with_metadata'):
            result = llm_client.chat_with_metadata(items, json_mode=json_mode,
                                                   temperature=temperature)
            return result.content, result.finish_reason
        # Compatibility with older test doubles and third-party clients.
        return llm_client.generate_response(items[-1]['content'], system_message=system_message,
                                            json_mode=json_mode,
                                            temperature=temperature), None

    raw, finish = call(messages, True)
    last_error = ''
    for round_number in range(4):
        try:
            parsed = _parse(raw, validator, finish == 'length')
            if finish != 'length':
                return parsed, round_number
            last_error = 'LLM 输出达到长度限制，JSON 可能只包含部分内容'
        except Exception as error:
            last_error = str(error)
        if round_number == 3:
            break
        logger.warning(f'🔧 LLM JSON 修复第 {round_number + 1}/3 轮 | 错误={last_error} | 长度={len(raw)} | finish_reason={finish}')
        if finish == 'length':
            # The tail anchors the exact continuation; do not ask for the whole document again.
            repair_prompt = ('下面的 JSON 在输出长度限制处被截断。仅续写缺失的原始字符，'
                             '从截断处直接开始，不要重写前文、不要代码块。末尾上下文：\n' + raw[-3000:])
            addition, finish = call(messages + [{'role': 'assistant', 'content': raw[-3000:]},
                                              {'role': 'user', 'content': repair_prompt}], False)
            raw += addition
        else:
            repair_prompt = (f'修复下面的 JSON。错误：{last_error}。只返回完整 JSON。\n' + raw)
            raw, finish = call([messages[0], {'role': 'user', 'content': repair_prompt}], True)
    raise ValueError(f'LLM 返回的 JSON 经 3 轮修复仍无法解析：{last_error}')
