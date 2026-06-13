"""多平台 Bot 集成包。对外暴露 BotManager 单例。"""
from .base import BaseBot, BotConfig, BotStatus, LLMConfig
from .manager import bot_manager

__all__ = ["bot_manager", "BaseBot", "BotConfig", "BotStatus", "LLMConfig"]
