"""
RPG专用文本处理器 - 专门处理角色扮演游戏中的复杂元素
支持数值属性、装备系统、技能树、复杂关系等RPG核心机制
"""
import re
import json
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger

class RPGTextProcessor:
    """RPG专用文本处理器，能够识别和提取复杂的RPG游戏元素"""
    
    def __init__(self):
        # RPG专用实体识别模式
        self.rpg_entity_patterns = {
            "character": [
                # 基础角色识别
                r"(?:角色|人物|NPC|玩家|敌人)([A-Za-z\u4e00-\u9fa5]+)",
                r"([A-Za-z\u4e00-\u9fa5]+)(?:是一个|是|扮演)(?:战士|法师|盗贼|牧师|骑士|弓箭手|刺客|德鲁伊)",
                # 职业特定识别
                r"(\w+)(?:的|是)(?:等级|Lv\.?|Level)\s*(\d+)(?:的)?(?:战士|法师|盗贼|牧师|骑士|弓箭手|刺客|德鲁伊)",
            ],
            "weapon": [
                # 武器识别 - 支持魔法属性和等级
                r"(?:装备|使用|拿着|挥舞)([+\-]?\d+)?\s*([\u4e00-\u9fa5A-Za-z]+)(?:剑|刀|斧|锤|弓|弩|法杖|魔杖|匕首|长矛)",
                r"([+\-]?\d+)?\s*([\u4e00-\u9fa5A-Za-z]+)(?:剑|刀|斧|锤|弓|弩|法杖|魔杖|匕首|长矛)(?:攻击力|伤害)[+\-]?(\d+)",
                r"(?:史诗|传说|稀有|普通|魔法)(?:级别?的)?([\u4e00-\u9fa5A-Za-z]+)(?:武器|装备)",
            ],
            "armor": [
                # 防具识别
                r"(?:穿着|装备)([+\-]?\d+)?\s*([\u4e00-\u9fa5A-Za-z]+)(?:盔甲|头盔|护甲|盾牌|靴子|手套|戒指|项链)",
                r"([+\-]?\d+)?\s*([\u4e00-\u9fa5A-Za-z]+)(?:盔甲|头盔|护甲|盾牌|靴子|手套|戒指|项链)(?:防御力|护甲值)[+\-]?(\d+)",
            ],
            "consumable": [
                # 消耗品识别
                r"(?:使用|喝|吃|消耗)了?\s*(\d+)?\s*(?:瓶|个|份)?([\u4e00-\u9fa5A-Za-z]+)(?:药水|药剂|卷轴|食物|毒药)",
                r"([\u4e00-\u9fa5A-Za-z]+)(?:药水|药剂|卷轴|食物|毒药)(?:恢复|回复|增加|提升)(?:血量|魔法|生命|MP|HP)\s*(\d+)\s*(?:点|%)",
            ],
            "location": [
                # RPG地点识别
                r"(?:前往|到达|进入|离开)([\u4e00-\u9fa5A-Za-z]+)(?:城镇|村庄|地牢|迷宫|森林|山脉|沙漠|洞穴|神殿|遗迹|要塞|城堡|酒馆|商店|铁匠铺|魔法塔)",
                r"在([\u4e00-\u9fa5A-Za-z]+)(?:城镇|村庄|地牢|迷宫|森林|山脉|沙漠|洞穴|神殿|遗迹|要塞|城堡|酒馆|商店|铁匠铺|魔法塔)",
            ],
            "guild_organization": [
                # 公会/组织识别  
                r"(?:加入|退出|创建)([\u4e00-\u9fa5A-Za-z]+)(?:公会|工会|组织|团队|军团|联盟|阵营|教会|商会)",
                r"([\u4e00-\u9fa5A-Za-z]+)(?:公会|工会|组织|团队|军团|联盟|阵营|教会|商会)的(?:成员|会长|副会长|长老)",
            ],
        }
        
        # RPG数值属性识别模式
        self.numerical_patterns = {
            "stats": [
                # 基础属性
                r"(?:攻击力|伤害|ATK)\s*[：:]?\s*(\d+)\s*(?:点|pts?)?",
                r"(?:防御力|防御|DEF|护甲)\s*[：:]?\s*(\d+)\s*(?:点|pts?)?",
                r"(?:血量|生命|HP|血条)\s*[：:]?\s*(\d+)/?(?:(\d+))?",
                r"(?:魔法|法力|MP|蓝条)\s*[：:]?\s*(\d+)/?(?:(\d+))?",
                r"(?:等级|级别|Lv\.?|Level)\s*[：:]?\s*(\d+)",
                r"(?:经验|经验值|EXP)\s*[：:]?\s*(\d+)\s*(?:点|pts?)?",
                r"(?:力量|STR)\s*[：:]?\s*(\d+)",
                r"(?:敏捷|AGI|DEX)\s*[：:]?\s*(\d+)",
                r"(?:智力|智慧|INT|WIS)\s*[：:]?\s*(\d+)",
                r"(?:体质|耐力|CON|STA)\s*[：:]?\s*(\d+)",
            ],
            "changes": [
                # 数值变化
                r"(?:获得|得到|增加|提升)[+]?(\d+)\s*(?:点|%)\s*(?:攻击力|伤害|ATK)",
                r"(?:获得|得到|增加|提升)[+]?(\d+)\s*(?:点|%)\s*(?:防御力|防御|DEF)",
                r"(?:恢复|回复|治疗)[+]?(\d+)\s*(?:点|%)\s*(?:血量|生命|HP)",
                r"(?:消耗|失去|减少)[\-]?(\d+)\s*(?:点|%)\s*(?:魔法|法力|MP)",
                r"(?:造成|产生)[+]?(\d+)\s*(?:点|%)\s*(?:伤害|损伤)",
                r"(?:经验|经验值|EXP)\s*[+]?(\d+)\s*(?:点|pts?)?",
            ],
        }
        
        # RPG复杂关系模式
        self.rpg_relation_patterns = [
            # 公会关系
            (r"([\w\u4e00-\u9fa5]+)(?:加入|成为)([\w\u4e00-\u9fa5]+)(?:公会|工会|组织|团队|军团)的成员", "member_of"),
            (r"([\w\u4e00-\u9fa5]+)(?:是|担任)([\w\u4e00-\u9fa5]+)(?:公会|工会|组织|团队|军团)的(?:会长|队长|首领)", "leader_of"),
            
            # 敌对关系
            (r"([\w\u4e00-\u9fa5]+)(?:与|和)([\w\u4e00-\u9fa5]+)(?:敌对|为敌|对立|仇视)", "hostile_to"),
            (r"([\w\u4e00-\u9fa5]+)(?:攻击|战斗|对战)([\w\u4e00-\u9fa5]+)", "fighting"),
            
            # 友好关系
            (r"([\w\u4e00-\u9fa5]+)(?:与|和)([\w\u4e00-\u9fa5]+)(?:友好|结盟|合作)", "allied_with"),
            (r"([\w\u4e00-\u9fa5]+)(?:信任|尊敬|崇拜)([\w\u4e00-\u9fa5]+)", "respects"),
            
            # 交易关系
            (r"([\w\u4e00-\u9fa5]+)(?:从|向)([\w\u4e00-\u9fa5]+)(?:购买|买|交易)([\w\u4e00-\u9fa5]+)", "trades_with"),
            (r"([\w\u4e00-\u9fa5]+)(?:卖给|出售给)([\w\u4e00-\u9fa5]+)([\w\u4e00-\u9fa5]+)", "sells_to"),
            
            # 装备关系
            (r"([\w\u4e00-\u9fa5]+)(?:装备|佩戴|使用)([\w\u4e00-\u9fa5]+)", "equipped_with"),
            (r"([\w\u4e00-\u9fa5]+)(?:在|位于)([\w\u4e00-\u9fa5]+)(?:的背包|物品栏|仓库)里", "stored_in"),
            
            # 位置关系 
            (r"([\w\u4e00-\u9fa5]+)(?:在|位于|处于)([\w\u4e00-\u9fa5]+)(?:地区|区域|地图|层)", "located_in"),
            (r"([\w\u4e00-\u9fa5]+)(?:守护|保卫|镇守)([\w\u4e00-\u9fa5]+)", "guards"),
        ]

        # RPG删除/死亡/丢失事件识别模式
        self.deletion_patterns = [
            # 角色死亡
            (r"([\w\u4e00-\u9fa5]+)(?:死了|死亡|阵亡|被杀死|倒下)", "character_death"),
            (r"([\w\u4e00-\u9fa5]+)(?:的)?血量(?:归零|为0|耗尽)", "character_death"),
            
            # 物品丢失/销毁
            (r"(?:丢失|失去|损坏|销毁|破碎)(?:了)?([\w\u4e00-\u9fa5]+)", "item_lost"),
            (r"([\w\u4e00-\u9fa5]+)(?:被)?(?:偷走|抢走|没收|丢弃)", "item_stolen"),
            
            # 关系断绝
            (r"([\w\u4e00-\u9fa5]+)(?:与|和)([\w\u4e00-\u9fa5]+)(?:断绝关系|决裂|敌对|反目)", "relationship_broken"),
            (r"([\w\u4e00-\u9fa5]+)(?:离开|退出)([\w\u4e00-\u9fa5]+)(?:公会|组织|团队)", "left_organization"),
            
            # 位置离开
            (r"([\w\u4e00-\u9fa5]+)(?:离开|撤离|逃离)([\w\u4e00-\u9fa5]+)", "left_location"),
        ]

        # 技能和状态效果模式
        self.skill_patterns = [
            r"(?:学会|习得|掌握|解锁)([\u4e00-\u9fa5A-Za-z]+)(?:技能|法术|魔法|能力)",
            r"(?:释放|使用|施展)([\u4e00-\u9fa5A-Za-z]+)(?:技能|法术|魔法)(?:消耗|花费)(\d+)(?:点|%)(?:MP|魔法|法力)",
            r"(?:获得|受到)([\u4e00-\u9fa5A-Za-z]+)(?:状态|效果|BUFF|DEBUFF)(?:持续|维持)(\d+)(?:回合|秒|分钟)",
        ]

    def extract_rpg_entities_and_relations(self, text: str) -> Dict[str, Any]:
        """
        从RPG文本中提取实体、数值属性和复杂关系
        返回结构化的RPG游戏数据
        """
        nodes_to_add = []
        edges_to_add = []
        
        logger.info(f"开始分析RPG文本: {text[:100]}...")
        
        # 1. 提取RPG实体
        for entity_type, patterns in self.rpg_entity_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    entity_name = self._extract_entity_name_from_match(match)
                    if entity_name and len(entity_name) > 1:
                        entity_id = self._generate_rpg_entity_id(entity_name, entity_type)
                        
                        # 根据实体类型设置特殊属性
                        attributes = {
                            "name": entity_name,
                            "source": "rpg_extraction"
                        }
                        
                        # 为武器和装备提取数值属性
                        if entity_type in ["weapon", "armor"]:
                            attributes.update(self._extract_equipment_stats(match.group(0)))
                        
                        # 为角色提取等级信息
                        elif entity_type == "character":
                            level_info = self._extract_character_level(match.group(0))
                            if level_info:
                                attributes.update(level_info)
                        
                        nodes_to_add.append({
                            "node_id": entity_id,
                            "type": entity_type,
                            "attributes": attributes
                        })
        
        # 2. 提取数值属性变化
        numerical_updates = self._extract_numerical_changes(text)
        for update in numerical_updates:
            nodes_to_add.append(update)
        
        # 3. 提取RPG关系
        for pattern, relation_type in self.rpg_relation_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) >= 2:
                    source_name = match.group(1).strip()
                    target_name = match.group(2).strip()
                    
                    if source_name and target_name:
                        source_id = self._generate_rpg_entity_id(source_name, "unknown")
                        target_id = self._generate_rpg_entity_id(target_name, "unknown")
                        
                        edges_to_add.append({
                            "source": source_id,
                            "target": target_id,
                            "relationship": relation_type
                        })
        
        # 4. 提取技能和状态效果
        skill_updates = self._extract_skills_and_effects(text)
        edges_to_add.extend(skill_updates)
        
        result = {
            "nodes_to_add": nodes_to_add,
            "edges_to_add": edges_to_add,
            "nodes_to_delete": [],
            "edges_to_delete": [],
            "deletion_events": []
        }
        
        # 检测删除事件
        deletion_events = self._extract_deletion_events(text)
        if deletion_events:
            result.update(deletion_events)
        
        logger.info(f"RPG提取完成: {len(nodes_to_add)} 个实体, {len(edges_to_add)} 个关系, {len(result.get('deletion_events', []))} 个删除事件")
        return result

    def _extract_deletion_events(self, text: str) -> Dict[str, Any]:
        """
        检测并处理删除/死亡/丢失事件
        
        Returns:
            Dict包含:
            - nodes_to_delete: 需要删除的节点列表
            - edges_to_delete: 需要删除的边列表  
            - deletion_events: 删除事件详情列表
        """
        nodes_to_delete = []
        edges_to_delete = []
        deletion_events = []
        
        for pattern, event_type in self.deletion_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if event_type == "character_death":
                    character_name = match.group(1)
                    char_id = self._generate_rpg_entity_id(character_name, "character")
                    
                    nodes_to_delete.append({
                        "node_id": char_id,
                        "deletion_type": "death",
                        "reason": f"{character_name} died"
                    })
                    
                    deletion_events.append({
                        "type": "character_death",
                        "entity": character_name,
                        "description": match.group(0),
                        "action": "mark_as_deleted"
                    })
                    
                elif event_type == "item_lost":
                    item_name = match.group(1)
                    item_id = self._generate_rpg_entity_id(item_name, "item")
                    
                    nodes_to_delete.append({
                        "node_id": item_id,
                        "deletion_type": "lost",
                        "reason": f"{item_name} was lost"
                    })
                    
                    deletion_events.append({
                        "type": "item_lost",
                        "entity": item_name,
                        "description": match.group(0),
                        "action": "delete_node"
                    })
                    
                elif event_type == "item_stolen":
                    item_name = match.group(1)
                    item_id = self._generate_rpg_entity_id(item_name, "item")
                    
                    # 物品被偷走，删除装备关系，但保留物品节点
                    edges_to_delete.append({
                        "source_pattern": "*",
                        "target": item_id,
                        "relationship": "equipped_with",
                        "reason": f"{item_name} was stolen"
                    })
                    
                    deletion_events.append({
                        "type": "item_stolen", 
                        "entity": item_name,
                        "description": match.group(0),
                        "action": "remove_ownership"
                    })
                    
                elif event_type == "relationship_broken":
                    entity1 = match.group(1)
                    entity2 = match.group(2)
                    entity1_id = self._generate_rpg_entity_id(entity1, "character")
                    entity2_id = self._generate_rpg_entity_id(entity2, "character")
                    
                    # 删除双向关系
                    edges_to_delete.extend([
                        {
                            "source": entity1_id,
                            "target": entity2_id, 
                            "relationship": "*",
                            "reason": f"{entity1} and {entity2} broke their relationship"
                        },
                        {
                            "source": entity2_id,
                            "target": entity1_id,
                            "relationship": "*", 
                            "reason": f"{entity2} and {entity1} broke their relationship"
                        }
                    ])
                    
                    deletion_events.append({
                        "type": "relationship_broken",
                        "entities": [entity1, entity2],
                        "description": match.group(0),
                        "action": "remove_relationships"
                    })
                    
                elif event_type == "left_organization":
                    character = match.group(1)
                    organization = match.group(2)
                    char_id = self._generate_rpg_entity_id(character, "character")
                    org_id = self._generate_rpg_entity_id(organization, "guild_organization")
                    
                    edges_to_delete.append({
                        "source": char_id,
                        "target": org_id,
                        "relationship": "member_of",
                        "reason": f"{character} left {organization}"
                    })
                    
                    deletion_events.append({
                        "type": "left_organization",
                        "character": character,
                        "organization": organization,
                        "description": match.group(0),
                        "action": "remove_membership"
                    })
                    
                elif event_type == "left_location":
                    character = match.group(1)
                    location = match.group(2)
                    char_id = self._generate_rpg_entity_id(character, "character")
                    loc_id = self._generate_rpg_entity_id(location, "location")
                    
                    edges_to_delete.append({
                        "source": char_id,
                        "target": loc_id,
                        "relationship": "located_in",
                        "reason": f"{character} left {location}"
                    })
                    
                    deletion_events.append({
                        "type": "left_location",
                        "character": character,
                        "location": location,
                        "description": match.group(0),
                        "action": "remove_location"
                    })
        
        result = {
            "nodes_to_delete": nodes_to_delete,
            "edges_to_delete": edges_to_delete,
            "deletion_events": deletion_events
        }
        
        if deletion_events:
            logger.info(f"检测到 {len(deletion_events)} 个删除事件: {[e['type'] for e in deletion_events]}")
        
        return result

    def _extract_equipment_stats(self, equipment_text: str) -> Dict[str, Any]:
        """从装备文本中提取数值属性"""
        stats = {}
        
        # 提取攻击力
        atk_match = re.search(r"(?:攻击力|伤害|ATK)[+\-]?(\d+)", equipment_text)
        if atk_match:
            stats["attack"] = int(atk_match.group(1))
        
        # 提取防御力
        def_match = re.search(r"(?:防御力|防御|DEF|护甲)[+\-]?(\d+)", equipment_text)
        if def_match:
            stats["defense"] = int(def_match.group(1))
        
        # 提取强化等级
        enhance_match = re.search(r"[+](\d+)", equipment_text)
        if enhance_match:
            stats["enhancement_level"] = int(enhance_match.group(1))
        
        # 提取稀有度
        rarity_match = re.search(r"(史诗|传说|稀有|普通|魔法)", equipment_text)
        if rarity_match:
            stats["rarity"] = rarity_match.group(1)
        
        return stats

    def _extract_character_level(self, character_text: str) -> Optional[Dict[str, Any]]:
        """从角色文本中提取等级信息"""
        level_match = re.search(r"(?:等级|Lv\.?|Level)\s*(\d+)", character_text)
        if level_match:
            return {"level": int(level_match.group(1))}
        return None

    def _extract_numerical_changes(self, text: str) -> List[Dict[str, Any]]:
        """提取数值变化，如血量、经验值等"""
        updates = []
        
        for category, patterns in self.numerical_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    # 根据匹配内容判断是哪个属性
                    attr_name = self._determine_attribute_name(match.group(0))
                    if attr_name:
                        value = int(match.group(1))
                        
                        # 创建虚拟的角色节点来存储数值变化
                        updates.append({
                            "node_id": "player", # 默认假设是玩家
                            "type": "character",
                            "attributes": {attr_name: value}
                        })
        
        return updates

    def _extract_skills_and_effects(self, text: str) -> List[Dict[str, Any]]:
        """提取技能使用和状态效果"""
        relations = []
        
        for pattern in self.skill_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                skill_name = match.group(1).strip()
                if skill_name:
                    relations.append({
                        "source": "player",
                        "target": self._generate_rpg_entity_id(skill_name, "skill"),
                        "relationship": "has_skill"
                    })
        
        return relations

    def _determine_attribute_name(self, text: str) -> Optional[str]:
        """根据文本内容判断属性名称"""
        if re.search(r"攻击力|伤害|ATK", text):
            return "attack"
        elif re.search(r"防御力|防御|DEF", text):
            return "defense" 
        elif re.search(r"血量|生命|HP", text):
            return "health"
        elif re.search(r"魔法|法力|MP", text):
            return "mana"
        elif re.search(r"等级|级别|Lv", text):
            return "level"
        elif re.search(r"经验|EXP", text):
            return "experience"
        return None

    def _extract_entity_name_from_match(self, match) -> Optional[str]:
        """从正则匹配中提取实体名称"""
        groups = match.groups()
        for group in groups:
            if group and len(group.strip()) > 0:
                # 跳过纯数字组
                if not group.isdigit():
                    return group.strip()
        return None

    def _generate_rpg_entity_id(self, name: str, entity_type: str) -> str:
        """生成RPG实体ID"""
        # 清理名称
        clean_name = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', name.lower())
        
        # RPG专用的翻译映射
        rpg_translation_map = {
            # 职业
            "战士": "warrior", "法师": "mage", "盗贼": "thief", "牧师": "priest",
            "骑士": "knight", "弓箭手": "archer", "刺客": "assassin", "德鲁伊": "druid",
            
            # 装备
            "长剑": "longsword", "战斧": "battleaxe", "法杖": "staff", "匕首": "dagger",
            "盔甲": "armor", "盾牌": "shield", "头盔": "helmet", "靴子": "boots",
            
            # 地点
            "酒馆": "tavern", "铁匠铺": "blacksmith", "魔法塔": "magic_tower",
            "地牢": "dungeon", "城堡": "castle", "森林": "forest", "沙漠": "desert",
            
            # 通用
            "玩家": "player", "敌人": "enemy", "NPC": "npc",
        }
        
        if clean_name in rpg_translation_map:
            return rpg_translation_map[clean_name]
        
        # 如果没有映射，使用类型前缀
        if entity_type != "unknown":
            return f"{entity_type}_{clean_name}"
        else:
            return clean_name