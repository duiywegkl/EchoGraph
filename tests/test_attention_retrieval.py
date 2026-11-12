from src.graph.knowledge_graph import KnowledgeGraph
from src.memory.grag_memory import GRAGMemory


def make_memory(tmp_path, attention_config):
    return GRAGMemory(
        graph_save_path=str(tmp_path / 'graph.graphml'),
        entities_json_path=str(tmp_path / 'entities.json'),
        auto_load_entities=False,
        attention_config=attention_config,
    )


def test_reverse_edge_retrieval():
    graph = KnowledgeGraph()
    graph.add_or_update_node('elara', 'character')
    graph.add_or_update_node('magic_sword', 'item')
    graph.add_edge('elara', 'magic_sword', 'owns')

    subgraph = graph.get_subgraph_for_context(['magic_sword'])
    assert set(subgraph) == {'elara', 'magic_sword'}
    assert 'elara -> magic_sword (owns)' in graph.to_text_representation(subgraph)
    assert not subgraph.has_edge('magic_sword', 'elara')


def test_deleted_node_does_not_bridge():
    graph = KnowledgeGraph()
    for node in ('start', 'deleted', 'beyond'):
        graph.add_or_update_node(node, 'concept')
    graph.add_edge('start', 'deleted', 'related_to')
    graph.add_edge('deleted', 'beyond', 'related_to')
    graph.mark_node_as_deleted('deleted')

    assert set(graph.get_subgraph_for_context(['start'], depth=2)) == {'start'}
    assert not graph.get_subgraph_for_context(['deleted']).nodes


def populate_hub(memory):
    graph = memory.knowledge_graph
    graph.add_or_update_node('elara', 'character')
    for index in range(20):
        name = f'concept_{index}'
        graph.add_or_update_node(name, 'concept')
        graph.add_edge('elara', name, 'plans')
    for name, kind, relationship in (
        ('lyra', 'character', 'supports'),
        ('tarin', 'character', 'supports'),
        ('magic_sword', 'item', 'owns'),
    ):
        graph.add_or_update_node(name, kind)
        graph.add_edge('elara', name, relationship)
    memory.add_conversation('Lyra and magic_sword helped Elara.', 'Tarin joined Lyra.')


def test_attention_filters_hub_and_reports_scores(tmp_path):
    memory = make_memory(tmp_path, {'max_context_entities': 4})
    populate_hub(memory)

    context = memory.get_optimized_character_context('elara')
    assert all(f'- {name} (type:' in context for name in ('elara', 'lyra', 'tarin', 'magic_sword'))
    assert 'concept_0' not in context
    assert context.count('(type:') == 4
    assert memory.get_knowledge_graph_context(['elara']).count('(type:') == 4
    assert memory.retrieve_context_for_prompt(['elara']).count('(type:') == 4

    report = memory.get_entity_importance_report('elara')
    assert report['character_name'] == 'elara'
    assert report['total_entities'] == 24
    assert report['max_context_entities'] == 4
    assert report['config']['collective_weight'] == 0.6
    assert 0 <= report['filter_ratio'] <= 1
    scores = {row['name']: row for row in report['entity_scores']}
    assert scores['lyra']['importance_score'] > scores['concept_0']['importance_score']
    assert scores['concept_0']['above_threshold'] is False
    assert memory.get_knowledge_graph_context(['elara', 'concept_0']).count('(type:') >= 2


def test_empty_attention_config_preserves_unfiltered_context(tmp_path):
    memory = make_memory(tmp_path, {})
    populate_hub(memory)
    expected = memory.knowledge_graph.to_text_representation(
        memory.knowledge_graph.get_subgraph_for_context(['elara'])
    )
    assert memory.get_knowledge_graph_context(['elara']) == expected
    assert memory.get_optimized_character_context('elara') == expected


def test_default_config_fills_hub_with_allies(tmp_path):
    memory = make_memory(tmp_path, {
        'collective_weight': 0.6,
        'holistic_weight': 0.4,
        'importance_threshold': 0.3,
        'max_context_entities': 15,
    })
    graph = memory.knowledge_graph
    graph.add_or_update_node('hero', 'character')
    for index in range(20):
        name = f'concept_{index}'
        graph.add_or_update_node(name, 'concept')
        graph.add_edge('hero', name, '\u8ba1\u5212')
    for index in range(1, 6):
        name = f'ally{index}'
        graph.add_or_update_node(name, 'character')
        graph.add_edge('hero', name, '\u670b\u53cb')
    memory.add_conversation('hero walks into the tavern', '')

    expected_allies = {f'ally{index}' for index in range(1, 6)}
    for context in (memory.get_knowledge_graph_context(['hero']),
                    memory.get_optimized_character_context('hero')):
        nodes = {line.split(' (type:', 1)[0][2:]
                 for line in context.splitlines() if line.startswith('- ') and ' (type:' in line}
        assert len(nodes) == 15
        assert 'hero' in nodes
        assert expected_allies <= nodes
        assert len({node for node in nodes if node.startswith('concept_')}) == 9


def test_core_entities_survive_when_lowest_scoring_and_over_limit(tmp_path):
    memory = make_memory(tmp_path, {'max_context_entities': 2})
    graph = memory.knowledge_graph
    graph.add_or_update_node('hero', 'character')
    core = {f'concept_{index}' for index in range(3)}
    for name in core:
        graph.add_or_update_node(name, 'concept')
        graph.add_edge('hero', name, '\u8ba1\u5212')
    memory.add_conversation('hero walks into the tavern', '')

    context = memory.get_knowledge_graph_context(sorted(core))
    nodes = {line.split(' (type:', 1)[0][2:]
             for line in context.splitlines() if line.startswith('- ') and ' (type:' in line}
    assert nodes == core
    evaluator = memory._importance_evaluator()
    assert all(evaluator.score('hero')['importance_score'] >
               evaluator.score(name)['importance_score'] for name in core)
