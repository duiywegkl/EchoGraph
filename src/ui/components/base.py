"""
UI组件基类模块
"""

from abc import ABC, ABCMeta, abstractmethod
from PySide6.QtWidgets import QWidget, QDialog
from PySide6.QtCore import QObject, Signal
from loguru import logger
from typing import Optional, Dict, Any

# 创建组合元类解决元类冲突
class QWidgetABCMeta(type(QWidget), ABCMeta):
    """组合QWidget和ABC的元类，解决多重继承的元类冲突"""
    pass

class BaseUIComponent(QWidget, ABC, metaclass=QWidgetABCMeta):
    """UI组件基类"""
    
    # 通用信号 - 注意这里改为Signal
    component_ready = Signal()
    component_error = Signal(str)
    status_changed = Signal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._initialized = False
        self._config: Dict[str, Any] = {}
    
    @abstractmethod
    def setup_ui(self):
        """设置UI界面"""
        pass
    
    @abstractmethod
    def connect_signals(self):
        """连接信号和槽"""
        pass
    
    def initialize(self, config: Optional[Dict[str, Any]] = None):
        """初始化组件"""
        try:
            if config:
                self._config.update(config)
            
            self.setup_ui()
            self.connect_signals()
            self._initialized = True
            self.component_ready.emit()
            logger.debug(f"✓ {self.__class__.__name__} 初始化完成")
            
        except Exception as e:
            error_msg = f"{self.__class__.__name__} 初始化失败: {e}"
            logger.error(error_msg)
            self.component_error.emit(error_msg)
    
    def is_initialized(self) -> bool:
        """检查组件是否已初始化"""
        return self._initialized
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)
    
    def set_config(self, key: str, value: Any):
        """设置配置值"""
        self._config[key] = value
    
    def update_status(self, message: str):
        """更新状态"""
        logger.info(f"[LOG] {self.__class__.__name__}: {message}")
        self.status_changed.emit(message)

# 为BaseDialog也创建一个组合元类
class QObjectABCMeta(type(QObject), ABCMeta):
    """组合QObject和ABC的元类"""
    pass

class BaseDialog(QObject, ABC, metaclass=QObjectABCMeta):
    """对话框基类"""
    
    # 对话框信号
    dialog_accepted = Signal(dict)
    dialog_rejected = Signal()
    dialog_error = Signal(str)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.parent_widget = parent
        self._dialog = None
    
    @abstractmethod
    def create_dialog(self) -> QDialog:  # 改为QDialog类型
        """创建对话框"""
        pass
    
    def show_dialog(self) -> bool:
        """显示对话框"""
        try:
            if not self._dialog:
                self._dialog = self.create_dialog()
            
            result = self._dialog.exec()
            return result == QDialog.Accepted  # 使用正确的常量
            
        except Exception as e:
            error_msg = f"显示对话框失败: {e}"
            logger.error(error_msg)
            self.dialog_error.emit(error_msg)
            return False

class ComponentManager(QObject):
    """组件管理器"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._components: Dict[str, BaseUIComponent] = {}
        self._dialogs: Dict[str, BaseDialog] = {}
    
    def register_component(self, name: str, component: BaseUIComponent):
        """注册组件"""
        self._components[name] = component
        logger.debug(f"[UI] 注册组件: {name}")
    
    def get_component(self, name: str) -> Optional[BaseUIComponent]:
        """获取组件"""
        return self._components.get(name)
    
    def register_dialog(self, name: str, dialog: BaseDialog):
        """注册对话框"""
        self._dialogs[name] = dialog
        logger.debug(f"[UI] 注册对话框: {name}")
    
    def get_dialog(self, name: str) -> Optional[BaseDialog]:
        """获取对话框"""
        return self._dialogs.get(name)
    
    def initialize_all_components(self):
        """初始化所有组件"""
        for name, component in self._components.items():
            if not component.is_initialized():
                component.initialize()
                logger.debug(f"[UI] 初始化组件: {name}")
    
    def cleanup_all_components(self):
        """清理所有组件"""
        for name, component in self._components.items():
            try:
                component.deleteLater()
                logger.debug(f"[UI] 清理组件: {name}")
            except Exception as e:
                logger.error(f"清理组件 {name} 失败: {e}")
        
        self._components.clear()
        self._dialogs.clear()
