"""Strict, repairable LLM extraction of turn-tagged graph operations."""

import json
from collections import defaultdict

from src.graph.node_types import TYPE_IDS, SYNONYMS, normalize_type, prompt_types
from src.utils.llm_json import request_json

from .base import _edge_id
from .graph import GraphState


class ExtractionRequestError(RuntimeError):
    """The LLM request or transport failed."""


class ExtractionValidationError(ValueError):
    """The LLM response remained invalid after repair."""


SYSTEM = '你是知识图谱维护助手。只输出简洁的 JSON。'


class _CheckedClient:
    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        if name not in ('chat_with_metadata', 'generate_response'):
            raise AttributeError(name)
        method = getattr(self.client, name)

        def checked(*args, **kwargs):
            try:
                result = method(*args, **kwargs)
                content = result.content if name == 'chat_with_metadata' else result
                if not isinstance(content, str) or not content.strip():
                    raise ValueError('empty LLM response')
                return result
            except Exception as exc:
                raise ExtractionRequestError(str(exc)) from exc

        return checked


class TimelineExtractor:
    def __init__(self, llm_client, context_size=None):
        self.llm_client = llm_client
        if context_size is None:
            from src.utils.config import config
            context_size = config.llm.context_size
        self.context_size = context_size
        self.model = getattr(llm_client, 'model', '')

    def request_text(self, state, segments):
        graph = {'nodes': [{'id': ident, **node} for ident, node in sorted(state.nodes.items())],
                 'edges': [{'edge_id': ident, **edge} for ident, edge in sorted(state.edges.items())]}
        lines = []
        for segment in segments:
            for message in segment.messages:
                label = '世界书设定' if message['role'] == 'lorebook' else message['role']
                lines.append(f"第 {segment.turn} 轮 {label}：{message['content']}")
        prompt = ('根据当前图谱和对话更新实体及关系。只返回 {"operations": [...]}。'
                  '每项必须有整数 turn 和 op。op 为 add_node、update_node、delete_node、'
                  'add_edge、update_edge、delete_edge。节点用 id/name/type，关系用 source/target/relation；'
                  '更新和删除必须引用现有 id 或 edge_id。新增关系不要写 edge_id。'
                  '新增或更新的实体名称、描述和关系标签必须与对话原文使用相同语言；中文对话用中文。'
                  '关系标签应简短，中文用 2–6 个汉字，如位于、属于、看见、持有；不要用 located_in、part_of 等英文下划线标签。'
                  '允许 description、attributes 和节点 subtype；按轮次顺序输出。\n'
                  + prompt_types() + '\n当前图谱：'
                  + json.dumps(graph, ensure_ascii=False, separators=(',', ':'))
                  + '\n待处理：\n' + '\n'.join(lines))
        return SYSTEM + '\n' + prompt

    def _validate(self, value, state, turns):
        if not isinstance(value, dict) or set(value) != {'operations'} or not isinstance(value['operations'], list):
            raise ValueError('operations 必须是数组')
        trial = state.copy()
        counts = defaultdict(int)
        output = []
        last_turn = min(turns)
        required = {'add_node': {'id', 'name', 'type'}, 'update_node': {'id'},
                    'delete_node': {'id'}, 'add_edge': {'source', 'target', 'relation'},
                    'update_edge': {'edge_id'}, 'delete_edge': {'edge_id'}}
        optional = {'add_node': {'subtype', 'description', 'attributes'},
                    'update_node': {'name', 'type', 'subtype', 'description', 'attributes'},
                    'delete_node': set(),
                    'add_edge': {'description', 'attributes'},
                    'update_edge': {'source', 'target', 'relation', 'description', 'attributes'},
                    'delete_edge': set()}
        for index, raw in enumerate(value['operations']):
            if not isinstance(raw, dict):
                raise ValueError(f'operations[{index}] 非对象')
            turn, action = raw.get('turn'), raw.get('op')
            if type(turn) is not int or turn not in turns or turn < last_turn:
                raise ValueError(f'operations[{index}].turn 无效')
            last_turn = turn
            if action not in required:
                raise ValueError(f'operations[{index}].op 无效')
            fields = set(raw) - {'turn', 'op'}
            if not required[action] <= fields or fields - required[action] - optional[action]:
                raise ValueError(f'operations[{index}] 字段无效')
            if action.startswith('update_') and fields == required[action]:
                raise ValueError('update 必须包含修改字段')
            for field in fields - {'attributes'}:
                if not isinstance(raw[field], str) or not raw[field].strip():
                    raise ValueError(f'operations[{index}].{field} 必须是非空字符串')
            if 'attributes' in raw and not isinstance(raw['attributes'], dict):
                raise ValueError(f'operations[{index}].attributes 必须是对象')
            op = {key: val for key, val in raw.items() if key != 'turn'}
            if 'type' in op:
                raw_type = op['type'].strip()
                if raw_type not in TYPE_IDS and raw_type.casefold() not in SYNONYMS:
                    raise ValueError(f'unknown node type: {raw_type}')
                op['type'], detail = normalize_type(raw_type, op.get('subtype'))
                if detail:
                    op['subtype'] = detail
            if action == 'add_edge':
                triple = (op['source'], op['target'], op['relation'])
                counts[(turn, *triple)] += 1
                op['id'] = _edge_id(*triple, counts[(turn, *triple)], prefix=str(turn))
            elif action.endswith('edge'):
                op['id'] = op.pop('edge_id')
            trial.apply([op])
            output.append({'turn': turn, **op})
        return output

    def extract(self, state: GraphState, segments):
        turns = {segment.turn for segment in segments}
        full = self.request_text(state, segments)
        system, prompt = full.split('\n', 1)
        try:
            result, _ = request_json(_CheckedClient(self.llm_client), prompt, system,
                                     lambda value: self._validate(value, state, turns))
            return result
        except ExtractionRequestError:
            raise
        except ValueError as exc:
            raise ExtractionValidationError(str(exc)) from exc
