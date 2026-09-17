"""
Pytest configuration - 自动加载环境变量和配置日志
"""
import os
import logging
from pathlib import Path
import pytest

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass


def configure_logging():
    """配置测试环境的日志 - 自动为所有app模块启用日志"""
    # 设置日志格式
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(name)s - %(message)s',
        force=True  # 强制重新配置
    )
    
    # 获取根logger
    root_logger = logging.getLogger()
    
    # 设置app下所有模块为INFO级别
    root_logger.setLevel(logging.INFO)
    
    # 只对app模块启用INFO，其他默认WARNING
    for name, logger in root_logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            if name.startswith('app'):
                logger.setLevel(logging.INFO)
            elif name in ('urllib3', 'httpx', 'openai', 'httpx'):
                logger.setLevel(logging.WARNING)


def load_env_file():
    """根据 ENVIRONMENT 加载 .env.development 或 .env.production"""
    root_dir = Path(__file__).parent.parent
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment == "production":
        env_file = root_dir / ".env.production"
    else:
        env_file = root_dir / ".env.development"

    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
        print(f"✅ 已加载环境变量: {env_file.name}")
    else:
        print(f"⚠️  环境文件不存在: {env_file}")


# Load env before importing app modules that read settings at import time.
load_env_file()


def pytest_addoption(parser):
    """为 I2I 镜头测试等提供的可选参数"""
    parser.addoption("--limit", type=int, default=None, help="I2I test: max categories to run")
    parser.addoption("--dry-run", action="store_true", help="I2I test: no API calls")
    parser.addoption("--tools", type=str, default=None, help="I2I test: comma-separated tool names")


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """在整个测试会话开始时自动配置测试环境"""
    # 配置日志
    configure_logging()
    
    # 环境变量已经在模块顶层加载了，这里不需要再加载
    
    yield
