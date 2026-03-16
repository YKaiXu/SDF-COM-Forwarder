#!/usr/bin/env python3
"""
讯飞 Qwen3 1.7B LLM 客户端 - 支持16并发
优化版本：统一日志、完善资源管理
"""

import json
import time
import logging
import urllib.request
from typing import Optional, List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 配置日志
logger = logging.getLogger(__name__)


class XunfeiLLMClient:
    """讯飞 LLM 客户端 - 支持并发翻译"""

    def __init__(self, api_key: str, api_url: str, model_id: str = "xop3qwen1b7", max_workers: int = 16):
        self.api_key = api_key
        self.api_url = api_url
        self.model_id = model_id
        self.max_retries = 3
        self.retry_delay = 5
        self.max_workers = max_workers
        self._executor = None
        self._lock = Lock()
        self._closed = False  # 关闭标志

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

    def __del__(self):
        """析构函数"""
        self.close()

    def _get_executor(self) -> ThreadPoolExecutor:
        """获取线程池（懒加载）"""
        if self._closed:
            raise RuntimeError("客户端已关闭，无法获取线程池")

        if self._executor is None:
            with self._lock:
                if self._executor is None and not self._closed:
                    self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
                    logger.info(f"✅ 线程池已创建 (max_workers={self.max_workers})")
        return self._executor

    def translate_en_to_zh(self, text: str, user: str = "") -> Optional[str]:
        """英文翻译为中文"""
        if self._closed:
            logger.error("❌ 客户端已关闭，无法翻译")
            return None

        prompt = self._build_translate_prompt(text, user, "en_to_zh")
        return self._call_api(prompt)

    def translate_zh_to_en(self, text: str, user: str = "") -> Optional[str]:
        """中文翻译为英文"""
        if self._closed:
            logger.error("❌ 客户端已关闭，无法翻译")
            return None

        prompt = self._build_translate_prompt(text, user, "zh_to_en")
        return self._call_api(prompt)

    def translate_batch(self, items: List[Tuple[str, str]]) -> List[Optional[str]]:
        """批量翻译 - 支持16并发

        Args:
            items: List of (text, user) tuples

        Returns:
            List of translated texts (None if failed)
        """
        if not items:
            return []

        if self._closed:
            logger.error("❌ 客户端已关闭，无法批量翻译")
            return [None] * len(items)

        executor = self._get_executor()
        futures = []

        # 提交所有翻译任务
        for text, user in items:
            future = executor.submit(self.translate_en_to_zh, text, user)
            futures.append(future)

        # 收集结果
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"批量翻译任务异常: {e}")
                results.append(None)

        return results

    def _build_translate_prompt(self, text: str, user: str, direction: str) -> str:
        """构建翻译提示词"""
        if direction == "en_to_zh":
            return f"""你是一位专业的翻译助手。请将以下英文消息翻译成自然流畅的中文。

原文：{text}
发送者：{user}
来源：SDF COM anonradio 聊天室

翻译规则：
1. 只翻译消息内容，保持用户名（发送者）不翻译
2. 保持原意，翻译自然流畅，符合中文表达习惯
3. 保留网络用语、俚语和口语化表达的韵味
4. 对于技术术语，使用通用的中文技术术语
5. 保留原文中的表情符号（如 :) :D 等）
6. 只返回翻译结果，不要添加任何解释或前缀

中文翻译："""
        else:
            return f"""You are a professional translator. Please translate the following Chinese message into natural English.

Original: {text}
Sender: {user}
Context: Message to be sent to SDF COM anonradio chat room

Translation Rules:
1. Only translate the message content, keep the username (sender) untranslated
2. Keep the original meaning, translate naturally and fluently
3. Maintain the tone, style, and internet slang
4. Use common English technical terms for technical content
5. Preserve emoticons (e.g., :) :D, etc.)
6. Return only the translation, no explanation or prefix

English translation:"""

    def _call_api(self, prompt: str) -> Optional[str]:
        """调用讯飞 API"""
        for attempt in range(self.max_retries):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self.api_key}'
                }

                data = {
                    'model': self.model_id,
                    'messages': [
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.3,
                    'max_tokens': 2048
                }

                req = urllib.request.Request(
                    self.api_url,
                    data=json.dumps(data).encode('utf-8'),
                    headers=headers,
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode('utf-8'))

                    if 'choices' in result and len(result['choices']) > 0:
                        return result['choices'][0]['message']['content'].strip()
                    else:
                        logger.warning(f"API 返回异常: {result}")
                        return None

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8')
                logger.error(f"LLM API HTTP 错误 (尝试 {attempt+1}/{self.max_retries}): {e.code}")
                logger.error(f"错误详情: {error_body}")

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error("LLM API 调用失败，已达最大重试次数")
                    return None
            except Exception as e:
                logger.error(f"LLM API 调用失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error("LLM API 调用失败，已达最大重试次数")
                    return None

        return None

    def close(self):
        """关闭线程池"""
        if self._closed:
            return

        with self._lock:
            if self._executor and not self._closed:
                logger.info("正在关闭线程池...")
                self._executor.shutdown(wait=True)
                self._executor = None
                logger.info("✅ 线程池已关闭")

            self._closed = True

    def is_closed(self) -> bool:
        """检查客户端是否已关闭"""
        return self._closed
