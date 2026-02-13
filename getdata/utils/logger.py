"""
日志模块 - 统一的日志管理
支持控制台和文件双输出，带自动轮转
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from getdata.config.settings import log_config, storage_config


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器（仅终端）"""
    
    # ANSI 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def format(self, record):
        # 如果不是 TTY，不使用颜色
        if not sys.stdout.isatty():
            return super().format(record)
        
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
            )
        return super().format(record)


def setup_logger(
    name: str = "polymarket_collector",
    level: Optional[str] = None,
    log_file: Optional[Path] = None
) -> logging.Logger:
    """
    配置并返回 logger 实例
    
    Args:
        name: Logger 名称
        level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        log_file: 日志文件路径，None 使用默认路径
    
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # 设置日志级别
    level = level or log_config.LEVEL
    logger.setLevel(getattr(logging, level.upper()))
    
    # 1. 控制台 Handler
    if log_config.CONSOLE_OUTPUT:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        
        console_formatter = ColoredFormatter(
            fmt=log_config.FORMAT,
            datefmt=log_config.DATE_FORMAT
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # 2. 文件 Handler（带自动轮转）
    if log_config.FILE_OUTPUT:
        log_file = log_file or storage_config.LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=log_config.MAX_FILE_SIZE_MB * 1024 * 1024,
            backupCount=log_config.BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        
        file_formatter = logging.Formatter(
            fmt=log_config.FORMAT,
            datefmt=log_config.DATE_FORMAT
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # 防止日志向上传播到 root logger
    logger.propagate = False
    
    return logger


def get_logger(name: str = "polymarket_collector") -> logging.Logger:
    """
    获取已配置的 logger（如果不存在则创建）
    
    Args:
        name: Logger 名称
    
    Returns:
        Logger 实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
