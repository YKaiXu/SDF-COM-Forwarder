#!/usr/bin/env python3
"""
飞书 Stream 客户端 - 优化版本：指数退避重试、统一日志
"""

import json
import time
import logging
import urllib.request
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta

# 配置日志
logger = logging.getLogger(__name__)

# 北京时区
beijing_tz = timezone(timedelta(hours=8))


class FeishuClient:
    """飞书客户端 - 支持指数退避重试"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token = None
        self.token_expire_time = 0
        self.max_retries = 5
        self.base_delay = 1  # 基础延迟1秒
        self.max_delay = 60  # 最大延迟60秒

    def _get_access_token(self) -> Optional[str]:
        """获取飞书访问令牌"""
        if self.access_token and time.time() < self.token_expire_time:
            return self.access_token

        for attempt in range(self.max_retries):
            try:
                url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
                data = {
                    'app_id': self.app_id,
                    'app_secret': self.app_secret
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    result = json.loads(response.read().decode('utf-8'))

                    if result.get('code') == 0:
                        self.access_token = result['tenant_access_token']
                        self.token_expire_time = time.time() + result['expire'] - 60
                        logger.info("✅ 飞书 token 获取成功")
                        return self.access_token
                    else:
                        logger.error(f"获取飞书 token 失败: {result}")
                        # 应用级错误，不重试
                        return None

            except urllib.error.HTTPError as e:
                # HTTP 错误，可能需要重试
                wait_time = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"获取 token HTTP 错误 (尝试 {attempt+1}/{self.max_retries}): {e.code}，{wait_time}秒后重试")
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
                else:
                    logger.error(f"获取 token 失败，已达最大重试次数")
                    return None
            except Exception as e:
                logger.error(f"获取飞书 token 异常 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    wait_time = min(self.base_delay * (2 ** attempt), self.max_delay)
                    time.sleep(wait_time)
                else:
                    return None

        return None

    def _calculate_backoff(self, attempt: int, error_code: int = None) -> int:
        """计算退避时间

        Args:
            attempt: 当前尝试次数
            error_code: HTTP 错误码或飞书错误码

        Returns:
            等待时间（秒）
        """
        # 如果是限流错误 (429)，使用更长的退避
        if error_code == 429:
            return min(self.base_delay * (4 ** attempt), self.max_delay)

        # 指数退避: 1, 2, 4, 8, 16...
        return min(self.base_delay * (2 ** attempt), self.max_delay)

    def send_message(self, receive_id: str, content: dict, msg_type: str = "interactive",
                     receive_id_type: str = "open_id") -> Optional[dict]:
        """发送消息到飞书 - 带指数退避重试"""
        for attempt in range(self.max_retries):
            try:
                token = self._get_access_token()
                if not token:
                    logger.error("无法获取飞书 token")
                    return None

                # 根据 receive_id 类型构建 URL
                if receive_id_type == "chat_id" or receive_id.startswith("oc_"):
                    url = f'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'
                elif receive_id_type == "open_id" and receive_id.startswith("ou_"):
                    url = f'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id'
                else:
                    url = 'https://open.feishu.cn/open-apis/im/v1/messages'

                data = {
                    'receive_id': receive_id,
                    'content': json.dumps(content),
                    'msg_type': msg_type
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {token}'
                    },
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    result = json.loads(response.read().decode('utf-8'))

                    if result.get('code') == 0:
                        logger.info(f"✅ 飞书消息发送成功")
                        return {
                            'success': True,
                            'message_id': result['data']['message_id'],
                            'create_time': result['data']['create_time']
                        }
                    else:
                        error_code = result.get('code')
                        logger.error(f"发送飞书消息失败: {result}")

                        # 应用级错误，不重试
                        if error_code in [400, 401, 403, 404]:
                            logger.error(f"应用级错误 {error_code}，停止重试")
                            return None

                        # 其他错误，计算退避时间
                        if attempt < self.max_retries - 1:
                            wait_time = self._calculate_backoff(attempt, error_code)
                            logger.warning(f"{wait_time}秒后重试...")
                            time.sleep(wait_time)
                        else:
                            return None

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8')
                logger.error(f"发送飞书消息 HTTP 错误 (尝试 {attempt+1}/{self.max_retries}): {e.code}")

                # 客户端错误 (4xx)，不重试
                if 400 <= e.code < 500 and e.code != 429:
                    logger.error(f"客户端错误 {e.code}，停止重试")
                    return None

                # 服务器错误或限流，计算退避时间
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt, e.code)
                    logger.warning(f"{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"发送消息失败，已达最大重试次数")
                    return None

            except Exception as e:
                logger.error(f"发送飞书消息异常 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    time.sleep(wait_time)
                else:
                    return None

        return None

    def build_card_message(self, user: str, original: str, translated: str,
                          beijing_time: str, server_time: str) -> dict:
        """构建飞书卡片消息"""
        return {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📻 SDF COM - {user}"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**原文：**\n{original}\n\n**翻译：**\n{translated}"
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"时间：北京 {beijing_time} | 服务器 {server_time}"
                        }
                    ]
                }
            ]
        }
