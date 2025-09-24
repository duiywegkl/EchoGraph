# -*- coding: utf-8 -*-
import sys
import toml
import re
from pathlib import Path
from datetime import datetime

def get_version_info():
    """获取版本信息"""
    config = toml.load('version.toml')
    version = config['version']
    version_str = f"{version['major']}.{version['minor']}.{version['patch']}"

    return {
        "version": version_str,
        "name": config['project']['name'],
        "description": config['project']['description'],
        "release_date": config['release']['date'],
        "release_type": config['release']['type'],
        "codename": config['release'].get('codename', '')
    }

def bump_version(part='patch'):
    """升级版本号"""
    config = toml.load('version.toml')
    version = config['version']

    if part == 'major':
        version['major'] += 1
        version['minor'] = 0
        version['patch'] = 0
    elif part == 'minor':
        version['minor'] += 1
        version['patch'] = 0
    elif part == 'patch':
        version['patch'] += 1

    # 更新发布日期
    config['release']['date'] = datetime.now().strftime("%Y-%m-%d")

    # 保存配置
    with open('version.toml', 'w', encoding='utf-8') as f:
        toml.dump(config, f)

    return f"{version['major']}.{version['minor']}.{version['patch']}"

def update_version_in_files():
    """更新文件中的版本引用"""
    info = get_version_info()
    version_str = info['version']

    files_to_update = [
        ('run_ui.py', r'setApplicationVersion\(["\'][^"\']*["\']\)', f'setApplicationVersion("{version_str}")'),
        ('config/development.yaml', r'version:\s*["\'][^"\']*["\']', f'version: "{version_str}"'),
        ('config/production.yaml', r'version:\s*["\'][^"\']*["\']', f'version: "{version_str}"'),
        ('README.md', r'### v\d+\.\d+\.\d+', f'### v{version_str}'),
    ]

    updated_files = []
    for file_path, pattern, replacement in files_to_update:
        path = Path(file_path)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()

                new_content = re.sub(pattern, replacement, content)

                if new_content != content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    updated_files.append(file_path)
            except Exception as e:
                print(f"Failed to update {file_path}: {e}")

    return updated_files

def main():
    if len(sys.argv) < 2:
        print("Usage: python version.py [show|bump|update] [patch|minor|major]")
        return

    action = sys.argv[1]

    if action == 'show':
        info = get_version_info()
        print("=" * 40)
        print("EchoGraph Version Info")
        print("=" * 40)
        print(f"Name: {info['name']}")
        print(f"Version: {info['version']}")
        print(f"Release Type: {info['release_type']}")
        print(f"Release Date: {info['release_date']}")
        print(f"Codename: {info['codename']}")
        print("=" * 40)

    elif action == 'bump':
        part = sys.argv[2] if len(sys.argv) > 2 else 'patch'
        new_version = bump_version(part)
        print(f"Version bumped to: {new_version}")

        # 自动更新文件
        updated = update_version_in_files()
        if updated:
            print("Updated files:")
            for f in updated:
                print(f"  - {f}")

    elif action == 'update':
        updated = update_version_in_files()
        if updated:
            print("Updated files:")
            for f in updated:
                print(f"  - {f}")
        else:
            print("No files needed updating")

if __name__ == "__main__":
    main()