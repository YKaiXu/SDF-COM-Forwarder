#!/usr/bin/env python3
"""
消息过滤器 - 过滤 SDF COM 消息
"""

import re
from typing import Optional, Dict

class MessageFilter:
    """消息过滤器"""
    
    def __init__(self):
        # 保留的消息类型
        self.include_chat = True
        self.include_join_leave = True
        self.exclude_system = True
    
    def filter_message(self, message: dict) -> Optional[dict]:
        """
        过滤消息
        
        返回:
            - 保留的消息: 返回处理后的消息
            - 过滤的消息: 返回 None
        """
        msg_type = message.get('type', '')
        
        # 1. 用户聊天消息
        if msg_type == 'chat':
            if self.include_chat:
                return self._process_chat_message(message)
            else:
                return None
        
        # 2. 用户进出消息
        elif msg_type == 'user_status':
            if self.include_join_leave:
                return self._process_status_message(message)
            else:
                return None
        
        # 3. 系统消息 - 过滤
        elif msg_type == 'system':
            if self.exclude_system:
                return None
            else:
                return message
        
        # 4. 其他消息 - 过滤
        else:
            return None
    
    def _process_chat_message(self, message: dict) -> dict:
        """处理聊天消息"""
        user = message.get('user', 'unknown')
        msg_text = message.get('message', '')
        
        # 清理消息内容
        msg_text = self._clean_message(msg_text)
        
        return {
            'type': 'chat',
            'user': user,
            'message': msg_text,
            'raw': message
        }
    
    def _process_status_message(self, message: dict) -> dict:
        """处理状态消息（用户进出）"""
        user = message.get('user', 'unknown')
        action = message.get('action', '')
        room = message.get('room', '')
        
        # 构建状态文本
        if 'joined' in action:
            status_text = f"👤 {user} 进入 {room}"
        elif 'left' in action:
            status_text = f"👋 {user} 离开 {room}"
        else:
            status_text = f"{user} {action} {room}"
        
        return {
            'type': 'status',
            'user': user,
            'action': action,
            'room': room,
            'message': status_text,
            'raw': message
        }
    
    def _clean_message(self, text: str) -> str:
        """清理消息内容"""
        # 去除多余空格
        text = text.strip()
        
        # 去除控制字符
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
        
        return text
    
    def is_chinese_message(self, text: str) -> bool:
        """检查是否为中文消息"""
        # 检查是否以 "s:" 开头（发送标记）
        if text.strip().startswith('s:'):
            return True
        
        # 检查中文字符比例
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text.strip())
        
        if total_chars > 0 and chinese_chars / total_chars > 0.3:
            return True
        
        return False
