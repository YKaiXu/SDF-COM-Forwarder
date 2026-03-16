#!/usr/bin/env python3
"""
时间戳处理器 - 管理北京时间和服务器时间
"""

from datetime import datetime, timezone, timedelta

# 时区定义
beijing_tz = timezone(timedelta(hours=8))
utc_tz = timezone.utc

class TimestampHandler:
    """时间戳处理器"""
    
    @staticmethod
    def get_current_timestamps() -> dict:
        """获取当前时间戳"""
        now = datetime.now(timezone.utc)
        
        return {
            "beijing_time": now.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S"),
            "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone_info": {
                "beijing": "CST+8",
                "server": "UTC"
            }
        }
    
    @staticmethod
    def format_timestamp(beijing_time: str, server_time: str) -> str:
        """格式化时间戳显示"""
        return f"• 北京：{beijing_time} (CST+8)\n• 服务器：{server_time} (UTC)"
    
    @staticmethod
    def add_timestamps_to_message(message: dict) -> dict:
        """为消息添加时间戳"""
        timestamps = TimestampHandler.get_current_timestamps()
        message["timestamps"] = timestamps
        return message
