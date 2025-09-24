"""
配置管理组件
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QGroupBox,
    QMessageBox, QFileDialog, QLabel
)
from PySide6.QtCore import Signal  # [OK] 正确的PySide6导入
from dotenv import dotenv_values, set_key
from loguru import logger
from .base import BaseUIComponent

class ConfigPanel(BaseUIComponent):
    """配置面板组件"""
    
    # 配置相关信号 - 使用Signal而不是pyqtSignal
    config_updated = Signal(dict)  # [OK] 正确的PySide6语法
    config_saved = Signal()
    config_loaded = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_file_path = Path(".env")
        self.config_widgets = {}
    
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        
        # API配置组
        api_group = self._create_api_config_group()
        layout.addWidget(api_group)
        
        # 游戏配置组
        game_group = self._create_game_config_group()
        layout.addWidget(game_group)
        
        # SillyTavern配置组
        tavern_group = self._create_tavern_config_group()
        layout.addWidget(tavern_group)
        
        # 操作按钮组
        button_layout = self._create_button_layout()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _create_api_config_group(self) -> QGroupBox:
        """创建API配置组"""
        group = QGroupBox("API配置")
        layout = QFormLayout()
        
        # API提供商
        self.config_widgets['api_provider'] = QComboBox()
        self.config_widgets['api_provider'].addItems(['openai', 'anthropic', 'local'])
        layout.addRow("API提供商:", self.config_widgets['api_provider'])
        
        # API密钥
        self.config_widgets['api_key'] = QLineEdit()
        self.config_widgets['api_key'].setEchoMode(QLineEdit.EchoMode.Password)  # [OK] 修正枚举语法
        layout.addRow("API密钥:", self.config_widgets['api_key'])
        
        # API基础URL
        self.config_widgets['api_base_url'] = QLineEdit()
        self.config_widgets['api_base_url'].setPlaceholderText("https://api.openai.com/v1")
        layout.addRow("基础URL:", self.config_widgets['api_base_url'])
        
        # 模型名称
        self.config_widgets['model_name'] = QLineEdit()
        self.config_widgets['model_name'].setPlaceholderText("deepseek-v3.1")
        layout.addRow("模型名称:", self.config_widgets['model_name'])
        
        # 最大Token数
        self.config_widgets['max_tokens'] = QSpinBox()
        self.config_widgets['max_tokens'].setRange(1000, 32000)
        self.config_widgets['max_tokens'].setValue(16000)
        layout.addRow("最大Token:", self.config_widgets['max_tokens'])
        
        # 温度
        self.config_widgets['temperature'] = QDoubleSpinBox()
        self.config_widgets['temperature'].setRange(0.0, 2.0)
        self.config_widgets['temperature'].setSingleStep(0.1)
        self.config_widgets['temperature'].setValue(0.8)
        layout.addRow("温度:", self.config_widgets['temperature'])
        
        group.setLayout(layout)
        return group
    
    def _create_game_config_group(self) -> QGroupBox:
        """创建游戏配置组"""
        group = QGroupBox("游戏配置")
        layout = QFormLayout()
        
        # 世界名称
        self.config_widgets['world_name'] = QLineEdit()
        self.config_widgets['world_name'].setPlaceholderText("我的世界")
        layout.addRow("世界名称:", self.config_widgets['world_name'])
        
        # 角色名称
        self.config_widgets['character_name'] = QLineEdit()
        self.config_widgets['character_name'].setPlaceholderText("助手")
        layout.addRow("角色名称:", self.config_widgets['character_name'])
        
        # 启用滑动窗口
        self.config_widgets['enable_sliding_window'] = QCheckBox()
        self.config_widgets['enable_sliding_window'].setChecked(True)
        layout.addRow("启用滑动窗口:", self.config_widgets['enable_sliding_window'])
        
        # 滑动窗口大小
        self.config_widgets['sliding_window_size'] = QSpinBox()
        self.config_widgets['sliding_window_size'].setRange(2, 10)
        self.config_widgets['sliding_window_size'].setValue(4)
        layout.addRow("滑动窗口大小:", self.config_widgets['sliding_window_size'])
        
        # 最大热记忆
        self.config_widgets['max_hot_memory'] = QSpinBox()
        self.config_widgets['max_hot_memory'].setRange(5, 50)
        self.config_widgets['max_hot_memory'].setValue(10)
        layout.addRow("最大热记忆:", self.config_widgets['max_hot_memory'])
        
        # 最大上下文长度
        self.config_widgets['max_context_length'] = QSpinBox()
        self.config_widgets['max_context_length'].setRange(1000, 10000)
        self.config_widgets['max_context_length'].setValue(4000)
        layout.addRow("最大上下文长度:", self.config_widgets['max_context_length'])
        
        group.setLayout(layout)
        return group
    
    def _create_tavern_config_group(self) -> QGroupBox:
        """创建SillyTavern配置组"""
        group = QGroupBox("SillyTavern配置")
        layout = QFormLayout()
        
        # SillyTavern URL
        self.config_widgets['tavern_url'] = QLineEdit()
        self.config_widgets['tavern_url'].setPlaceholderText("http://localhost:8000")
        layout.addRow("SillyTavern URL:", self.config_widgets['tavern_url'])
        
        # 启用酒馆模式
        self.config_widgets['enable_tavern_mode'] = QCheckBox()
        self.config_widgets['enable_tavern_mode'].setChecked(False)
        layout.addRow("启用酒馆模式:", self.config_widgets['enable_tavern_mode'])
        
        # 自动连接
        self.config_widgets['auto_connect'] = QCheckBox()
        self.config_widgets['auto_connect'].setChecked(True)
        layout.addRow("自动连接:", self.config_widgets['auto_connect'])
        
        group.setLayout(layout)
        return group
    
    def _create_button_layout(self) -> QHBoxLayout:
        """创建按钮布局"""
        layout = QHBoxLayout()
        
        # 加载配置按钮
        load_btn = QPushButton("加载配置")
        load_btn.clicked.connect(self.load_config)
        layout.addWidget(load_btn)
        
        # 保存配置按钮
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self.save_config)
        layout.addWidget(save_btn)
        
        # 重置配置按钮
        reset_btn = QPushButton("重置配置")
        reset_btn.clicked.connect(self.reset_config)
        layout.addWidget(reset_btn)
        
        # 导入配置按钮
        import_btn = QPushButton("导入配置")
        import_btn.clicked.connect(self.import_config)
        layout.addWidget(import_btn)
        
        # 导出配置按钮
        export_btn = QPushButton("导出配置")
        export_btn.clicked.connect(self.export_config)
        layout.addWidget(export_btn)
        
        return layout
    
    def connect_signals(self):
        """连接信号和槽"""
        # 配置变更时的处理
        for widget_name, widget in self.config_widgets.items():
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._on_config_changed)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(self._on_config_changed)  # [OK] 修正信号名称
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._on_config_changed)  # [OK] 修正信号名称
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._on_config_changed)
    
    def _on_config_changed(self):
        """配置变更处理"""
        config = self.get_current_config()
        self.config_updated.emit(config)
    
    def get_current_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        config = {}
        for key, widget in self.config_widgets.items():
            if isinstance(widget, QLineEdit):
                config[key] = widget.text()
            elif isinstance(widget, QSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                config[key] = widget.value()
            elif isinstance(widget, QCheckBox):
                config[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                config[key] = widget.currentText()
        
        return config
    
    def set_config(self, config: Dict[str, Any]):
        """设置配置"""
        for key, value in config.items():
            if key in self.config_widgets:
                widget = self.config_widgets[key]
                if isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QComboBox):
                    index = widget.findText(str(value))
                    if index >= 0:
                        widget.setCurrentIndex(index)
    
    def load_config(self):
        """加载配置"""
        try:
            if self.env_file_path.exists():
                env_config = dotenv_values(self.env_file_path)
                self.set_config(env_config)
                self.config_loaded.emit()
                self.update_status("配置已加载")
                logger.info("[LOG] 配置文件加载成功")
            else:
                QMessageBox.information(self, "提示", "配置文件不存在，使用默认配置")
        except Exception as e:
            error_msg = f"加载配置失败: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def save_config(self):
        """保存配置"""
        try:
            config = self.get_current_config()
            
            # 保存到.env文件
            for key, value in config.items():
                set_key(self.env_file_path, key.upper(), str(value))
            
            self.config_saved.emit()
            self.update_status("配置已保存")
            logger.info("[LOG] 配置文件保存成功")
            QMessageBox.information(self, "成功", "配置已保存")
            
        except Exception as e:
            error_msg = f"保存配置失败: {e}"
            logger.error(error_msg)
            QMessageBox.critical(self, "错误", error_msg)
    
    def reset_config(self):
        """重置配置"""
        reply = QMessageBox.question(
            self, "确认", "确定要重置所有配置吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,  # [OK] 修正枚举语法
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 重置为默认值
            default_config = {
                'api_provider': 'openai',
                'api_key': '',
                'api_base_url': 'https://api.openai.com/v1',
                'model_name': 'deepseek-v3.1',
                'max_tokens': 16000,
                'temperature': 0.8,
                'world_name': '我的世界',
                'character_name': '助手',
                'enable_sliding_window': True,
                'sliding_window_size': 4,
                'max_hot_memory': 10,
                'max_context_length': 4000,
                'tavern_url': 'http://localhost:8000',
                'enable_tavern_mode': False,
                'auto_connect': True
            }
            
            self.set_config(default_config)
            self.update_status("配置已重置")
    
    def import_config(self):
        """导入配置"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置文件", "", "Environment Files (*.env);;All Files (*)"
        )
        
        if file_path:
            try:
                env_config = dotenv_values(file_path)
                self.set_config(env_config)
                self.update_status("配置已导入")
                QMessageBox.information(self, "成功", "配置文件导入成功")
            except Exception as e:
                error_msg = f"导入配置失败: {e}"
                logger.error(error_msg)
                QMessageBox.critical(self, "错误", error_msg)
    
    def export_config(self):
        """导出配置"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置文件", "echograph_config.env", "Environment Files (*.env);;All Files (*)"
        )
        
        if file_path:
            try:
                config = self.get_current_config()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("# EchoGraph 配置文件\n")
                    for key, value in config.items():
                        f.write(f"{key.upper()}={value}\n")
                
                self.update_status("配置已导出")
                QMessageBox.information(self, "成功", "配置文件导出成功")
            except Exception as e:
                error_msg = f"导出配置失败: {e}"
                logger.error(error_msg)
                QMessageBox.critical(self, "错误", error_msg)
