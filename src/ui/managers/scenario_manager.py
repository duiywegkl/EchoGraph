"""
场景管理器
处理游戏场景的创建和初始化
"""
from pathlib import Path
from loguru import logger
from PySide6.QtWidgets import QMessageBox


class ScenarioManager:
    """场景管理器，处理游戏场景的创建和管理"""
    
    def __init__(self, memory, perception, rpg_processor, validation_layer):
        self.memory = memory
        self.perception = perception
        self.rpg_processor = rpg_processor
        self.validation_layer = validation_layer
    
    def create_chrono_trigger_scenario(self):
        """创建《超时空之轮》默认场景"""
        try:
            logger.info("开始创建《超时空之轮》默认场景")
            
            # 从独立的场景文件获取超时空之轮场景数据
            from src.scenarios.chrono_trigger_scenario import get_chrono_trigger_scenario
            scenario_data = get_chrono_trigger_scenario()
            
            # 从场景数据创建实体
            logger.info("从场景数据创建《超时空之轮》核心实体...")
            
            created_count = 0
            entities_data = scenario_data["entities"]
            
            # 处理所有类型的实体
            for entity_type, entities_list in entities_data.items():
                for entity in entities_list:
                    try:
                        entity_name = entity["name"]
                        entity_type_val = entity["type"]
                        entity_desc = entity.get("description", "")
                        
                        # 其余属性作为动态属性
                        attributes = {k: v for k, v in entity.items() if k not in ["name", "type"]}
                        
                        self.memory.add_or_update_node(entity_name, entity_type_val, **attributes)
                        created_count += 1
                    except Exception as e:
                        logger.warning(f"创建实体失败: {entity}: {e}")
            
            logger.info(f"✅ 从场景文件创建了 {created_count} 个《超时空之轮》实体")
            
            # 创建关系连接
            relationships = scenario_data.get("relationships", [])
            relationship_count = 0
            
            for rel in relationships:
                try:
                    from_node = rel["from"]
                    to_node = rel["to"]
                    relationship_type = rel["relationship"]
                    rel_description = rel.get("description", "")
                    
                    # 直接添加关系到知识图谱（所有节点都已存在）
                    self.memory.add_edge(
                        from_node, to_node, relationship_type, description=rel_description
                    )
                    relationship_count += 1
                    logger.info(f"✅ 创建关系: {from_node} --{relationship_type}--> {to_node}")
                except Exception as e:
                    logger.warning(f"创建关系失败: {rel}: {e}")
            
            logger.info(f"✅ 从场景文件创建了 {relationship_count} 个关系连接")
            
            # 同步保存数据到entities.json文件
            self.memory.sync_entities_to_json()
            logger.info("✅ 默认开局数据已同步到entities.json文件")
            
            # 返回开场故事
            opening_story = scenario_data["character_card"]["scenario"]
            return opening_story, created_count, relationship_count
            
        except Exception as e:
            logger.error(f"创建默认游戏开局失败: {e}")
            raise e
    
    def show_scenario_success_message(self, parent, entity_count, relationship_count):
        """显示场景创建成功消息"""
        QMessageBox.information(
            parent, 
            "时空之门已开启！", 
            f"《超时空之轮》世界已创建！\n\n"
            f"知识图谱中已包含了 {entity_count} 个实体和 {relationship_count} 个关系，"
            f"现在可以开始你的冒险了！"
        )
    
    def show_scenario_error_message(self, parent, error):
        """显示场景创建失败消息"""
        QMessageBox.warning(
            parent, 
            "初始化失败", 
            f"创建默认游戏开局时出现错误：\n{str(error)}\n\n请检查日志获取详细信息。"
        )