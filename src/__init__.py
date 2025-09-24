"""
EchoGraph项目包信息
"""

from pathlib import Path
import toml

# 读取版本配置文件
config_path = Path(__file__).parent.parent / "version.toml"
if config_path.exists():
    config = toml.load(config_path)
    version_info = config['version']
    project_info = config['project']

    # 版本信息
    __version__ = f"{version_info['major']}.{version_info['minor']}.{version_info['patch']}"
    if 'pre_release' in version_info:
        __version__ += f"-{version_info['pre_release']}"
    if 'build' in version_info:
        __version__ += f"+{version_info['build']}"

    __title__ = project_info['name']
    __description__ = project_info['description']
    __author__ = ', '.join(project_info['authors'])
    __license__ = project_info['license']
    __homepage__ = project_info['homepage']
    __repository__ = project_info['repository']
else:
    # 默认版本信息
    __version__ = "1.1.0"
    __title__ = "EchoGraph"
    __description__ = "智能角色扮演助手 - 集成对话系统和关系图谱"
    __author__ = "EchoGraph Team"
    __license__ = "MIT"
    __homepage__ = "https://github.com/duiywegkl/EchoGraph"
    __repository__ = "https://github.com/duiywegkl/EchoGraph"

# 公开的版本信息
__all__ = [
    "__version__",
    "__title__",
    "__description__",
    "__author__",
    "__license__",
    "__homepage__",
    "__repository__"
]