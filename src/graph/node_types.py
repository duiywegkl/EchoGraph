"""The canonical public entity categories and legacy type migration rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeType:
    id: str
    label: str
    definition: str


NODE_TYPES = (
    NodeType("character", "角色", "人物、NPC、怪物、精英怪物、生物及怪物群体（有属性面板）"),
    NodeType("location", "地点", "地点、建筑或区域"),
    NodeType("item", "物品", "物资、装备、武器或载具等可使用的实物"),
    NodeType("event", "事件", "发生的事件、任务或行动"),
    NodeType("concept", "概念", "组织、势力、阵营、世界观设定、设定、规则、体系或抽象概念"),
    NodeType("other", "其他", "异能、技能、能力及 skill、ability、power；具体词放 subtype，或其他实体"),
)
TYPE_IDS = tuple(item.id for item in NODE_TYPES)
TYPE_LABELS = {item.id: item.label for item in NODE_TYPES}

SYNONYMS = {
    "人物": "character", "角色": "character", "npc": "character", "怪物": "character",
    "精英怪物": "character", "怪物群体": "character", "player": "character", "monster": "character", "creature": "character",
    "地点": "location", "场所": "location", "建筑": "location", "区域": "location", "place": "location", "building": "location", "site": "location",
    "物资": "item", "物品": "item", "装备": "item", "载具": "item", "道具": "item",
    "武器": "item", "equipment": "item", "vehicle": "item", "weapon": "item", "armor": "item",
    "consumable": "item", "resource": "item", "supplies": "item",
    "事件": "event", "任务": "event", "quest": "event",
    "异能": "other", "技能": "other", "能力": "other", "组织": "concept",
    "势力": "concept", "阵营": "concept", "世界观": "concept", "世界观设定": "concept",
    "设定": "concept", "规则": "concept", "体系": "concept", "概念": "concept", "skill": "other", "organization": "concept", "guild_organization": "concept",
    "ability": "other", "power": "other", "faction": "concept", "world": "concept",
    "其他": "other", "unknown": "other",
}


def prompt_types():
    return "实体 type 只能使用以下英文 id；细分类别放在可选 subtype 字符串中：\n" + "\n".join(
        f"- {item.id}（{item.label}）：{item.definition}" for item in NODE_TYPES
    )


def normalize_type(raw, subtype=None):
    """Return (category, subtype), retaining the original noncanonical word."""
    word = str(raw or "").strip()
    category = word if word in TYPE_IDS else SYNONYMS.get(word.casefold(), "other")
    detail = str(subtype or "").strip()
    if not detail and word and word != category and word != TYPE_LABELS[category]:
        detail = word
    return category, detail


def normalize_node(attrs):
    """Normalize a graph node in memory without touching its identifier."""
    category, detail = normalize_type(attrs.get("type"), attrs.get("subtype"))
    attrs["type"] = category
    if detail:
        attrs["subtype"] = detail
    else:
        attrs.pop("subtype", None)
    return attrs


def display_name(node_id, name=None):
    if isinstance(name, str) and name.strip():
        return name.strip()
    identifier = str(node_id)
    if "_" in identifier:
        prefix, rest = identifier.split("_", 1)
        if prefix in TYPE_IDS or prefix.casefold() in SYNONYMS:
            return rest.replace("_", " ")
    return identifier
