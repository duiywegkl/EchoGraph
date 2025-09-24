# -*- coding: utf-8 -*-
"""
版本管理工具
统一管理项目版本信息
"""

import toml
import re
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class VersionManager:
    """版本管理器"""

    def __init__(self, config_path: str = "version.toml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """加载版本配置"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"版本配置文件不存在: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            return toml.load(f)

    def _save_config(self):
        """保存版本配置"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            toml.dump(self.config, f)

    def get_version_string(self, include_pre_release: bool = True, include_build: bool = False) -> str:
        """获取版本字符串"""
        version = self.config['version']
        version_str = f"{version['major']}.{version['minor']}.{version['patch']}"

        if include_pre_release and 'pre_release' in version:
            version_str += f"-{version['pre_release']}"

        if include_build and 'build' in version:
            version_str += f"+{version['build']}"

        return version_str

    def get_full_version_info(self) -> Dict[str, Any]:
        """获取完整版本信息"""
        return {
            "version": self.get_version_string(),
            "name": self.config['project']['name'],
            "description": self.config['project']['description'],
            "release_date": self.config['release']['date'],
            "release_type": self.config['release']['type'],
            "codename": self.config['release'].get('codename', '')
        }

    def bump_version(self, part: str = 'patch'):
        """升级版本号"""
        version = self.config['version']

        if part == 'major':
            version['major'] += 1
            version['minor'] = 0
            version['patch'] = 0
        elif part == 'minor':
            version['minor'] += 1
            version['patch'] = 0
        elif part == 'patch':
            version['patch'] += 1
        else:
            raise ValueError(f"Invalid version part: {part}")

        # 更新发布日期
        self.config['release']['date'] = datetime.now().strftime("%Y-%m-%d")

        self._save_config()
        return self.get_version_string()

    def update_files_with_version(self):
        """更新所有文件中的版本引用"""
        version_string = self.get_version_string()
        project_root = Path('.')

        # 需要更新版本的文件模式
        file_patterns = [
            ('run_ui.py', r'setApplicationVersion\(["\'][^"\']*["\']\)', f'setApplicationVersion("{version_string}")'),
            ('config/development.yaml', r'version:\s*["\'][^"\']*["\']', f'version: "{version_string}"'),
            ('config/production.yaml', r'version:\s*["\'][^"\']*["\']', f'version: "{version_string}"'),
            ('README.md', r'### v\d+\.\d+\.\d+', f'### v{version_string}'),
        ]

        updated_files = []

        for file_path, pattern, replacement in file_patterns:
            file_path = project_root / file_path
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    new_content = re.sub(pattern, replacement, content)

                    if new_content != content:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        updated_files.append(str(file_path))

                except Exception as e:
                    print(f"更新文件 {file_path} 失败: {e}")

        return updated_files


def main():
    """命令行工具"""
    import argparse

    parser = argparse.ArgumentParser(description="EchoGraph 版本管理工具")
    parser.add_argument('action', choices=['show', 'bump', 'update-files'],
                       help='执行的操作')
    parser.add_argument('--part', choices=['major', 'minor', 'patch'], default='patch',
                       help='升级的版本部分（用于bump操作）')

    args = parser.parse_args()

    try:
        vm = VersionManager()

        if args.action == 'show':
            info = vm.get_full_version_info()
            print(f"项目: {info['name']}")
            print(f"版本: {info['version']}")
            print(f"描述: {info['description']}")
            print(f"发布日期: {info['release_date']}")
            print(f"发布类型: {info['release_type']}")
            print(f"代号: {info['codename']}")

        elif args.action == 'bump':
            new_version = vm.bump_version(args.part)
            print(f"版本已升级到: {new_version}")

        elif args.action == 'update-files':
            updated_files = vm.update_files_with_version()
            if updated_files:
                print("已更新的文件:")
                for file_path in updated_files:
                    print(f"  - {file_path}")
            else:
                print("没有文件需要更新")

    except Exception as e:
        print(f"错误: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())