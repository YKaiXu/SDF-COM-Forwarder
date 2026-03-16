#!/usr/bin/env python3
"""
飞书事件服务器 - 使用 Stream 模式（WebSocket 长连接）
接收飞书消息并发送到 SDF COM
不需要公网 IP，客户端主动连接飞书服务器
"""

import os
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 飞书 SDK
from lark_oapi import Client
from lark_oapi.ws import Client as WsClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.core.enum import LogLevel

# LLM 客户端
from message_processor.llm_client import XunfeiLLMClient

# 用户档案管理
from user_profile_manager import get_profile_manager
from llm_analyzer import SimpleLLMAnalyzer

# 配置
CONFIG_DIR = Path.home() / '.trae-cn' / 'configs' / 'sdf-com-chat'
CONFIG_FILE = CONFIG_DIR / 'config.json'
PID_FILE = Path('/tmp/feishu_event_server.pid')

# 北京时区
beijing_tz = timezone(timedelta(hours=8))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('/tmp/feishu_event_server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class FeishuEventServer:
    """飞书事件服务器 - Stream 模式（长连接）"""

    def __init__(self):
        self.config = self._load_config()
        self.ws_client = None
        self.running = False
        self.llm_client = None
        self.profile_manager = None
        self.llm_analyzer = None
        self._init_llm()
        self._init_profile_manager()

    def _load_config(self) -> Dict:
        """加载配置文件"""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.error(f"❌ 配置文件不存在: {CONFIG_FILE}")
                return {}
        except Exception as e:
            logger.error(f"❌ 加载配置失败: {e}")
            return {}

    def _init_llm(self) -> bool:
        """初始化 LLM 客户端"""
        try:
            llm_config = self.config.get('llm', {})
            api_key = llm_config.get('api_key', '')
            api_url = llm_config.get('api_url', '')
            model_id = llm_config.get('model_id', 'xop3qwen1b7')

            if not all([api_key, api_url]):
                logger.warning("⚠️ LLM 配置不完整，翻译功能将不可用")
                return False

            self.llm_client = XunfeiLLMClient(
                api_key=api_key,
                api_url=api_url,
                model_id=model_id
            )
            logger.info("✅ LLM 客户端初始化成功")
            return True

        except Exception as e:
            logger.error(f"❌ 初始化 LLM 客户端失败: {e}")
            return False

    def _init_profile_manager(self) -> bool:
        """初始化用户档案管理器"""
        try:
            self.profile_manager = get_profile_manager()
            self.llm_analyzer = SimpleLLMAnalyzer(self.llm_client) if self.llm_client else None
            logger.info("✅ 用户档案管理器初始化成功")
            return True
        except Exception as e:
            logger.error(f"❌ 初始化用户档案管理器失败: {e}")
            return False

    def _translate_to_english(self, text: str) -> str:
        """将中文翻译为英文"""
        if not self.llm_client:
            logger.warning("⚠️ LLM 客户端未初始化，跳过翻译")
            return text

        try:
            # 检查是否包含中文字符
            if not any('\u4e00' <= char <= '\u9fff' for char in text):
                logger.debug("📝 消息不包含中文，无需翻译")
                return text

            # 调用 LLM 翻译（中文 -> 英文）
            translated = self.llm_client.translate_zh_to_en(text, user="feishu_user")

            if translated:
                logger.info(f"🔄 翻译: '{text[:30]}...' -> '{translated[:30]}...'")
                return translated
            else:
                logger.warning("⚠️ 翻译失败，返回原文")
                return text

        except Exception as e:
            logger.error(f"❌ 翻译异常: {e}")
            return text

    def _init_client(self) -> bool:
        """初始化飞书 WebSocket 客户端（Stream 模式）"""
        try:
            feishu_config = self.config.get('feishu', {})
            app_id = feishu_config.get('app_id', '')
            app_secret = feishu_config.get('app_secret', '')

            if not app_id or not app_secret:
                logger.error("❌ 飞书配置不完整")
                return False

            # 创建事件分发处理器
            event_handler = EventDispatcherHandler.builder(
                encrypt_key="",  # 如果启用了加密，需要填写
                verification_token="",  # 如果启用了验证，需要填写
                level=LogLevel.INFO
            ).register_p2_im_message_receive_v1(
                self._on_message_receive
            ).register_p2_im_message_message_read_v1(
                self._on_message_read
            ).build()

            # 创建 WebSocket 客户端（Stream 模式）
            self.ws_client = WsClient(
                app_id=app_id,
                app_secret=app_secret,
                log_level=LogLevel.INFO,
                event_handler=event_handler,
                domain="https://open.feishu.cn",
                auto_reconnect=True
            )

            logger.info("✅ 飞书事件服务器初始化成功（Stream 模式）")
            return True

        except Exception as e:
            logger.error(f"❌ 初始化飞书客户端失败: {e}")
            return False

    def _on_message_receive(self, event) -> None:
        """处理接收到的消息"""
        try:
            # event 是 P2ImMessageReceiveV1 对象，直接访问属性
            message = event.event.message
            sender = event.event.sender

            # 提取消息信息
            msg_type = message.message_type
            content_str = message.content
            content = json.loads(content_str)
            sender_id = sender.sender_id.open_id if sender.sender_id else 'unknown'

            # 只处理文本消息
            if msg_type == "text":
                text = content.get("text", "")
                logger.info(f"📨 收到飞书消息: {sender_id}: {text}")

                # 翻译中文为英文
                translated_text = self._translate_to_english(text)

                # 发送到 SDF COM（只发送翻译后的文本，不加档案信息）
                self._send_to_sdf_com(translated_text)
            else:
                logger.debug(f"📝 忽略非文本消息: {msg_type}")

        except Exception as e:
            logger.error(f"❌ 处理消息失败: {e}")

    def _on_message_read(self, event) -> None:
        """处理消息已读事件（忽略）"""
        # 消息已读事件不需要处理，直接忽略
        logger.debug("📝 消息已读事件（忽略）")
        pass

    def _send_to_sdf_com(self, message: str) -> bool:
        """发送消息到 SDF COM"""
        try:
            # 使用 tmux 发送消息到 SDF COM
            cmd = f'tmux send-keys -t sdf-com "{message}" Enter'
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                logger.info(f"✅ 消息已发送到 SDF COM: {message[:50]}...")
                return True
            else:
                logger.error(f"❌ 发送消息到 SDF COM 失败: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"❌ 发送消息到 SDF COM 异常: {e}")
            return False

    def start(self) -> None:
        """启动事件服务器（Stream 模式）"""
        if not self._init_client():
            logger.error("❌ 启动失败：初始化客户端失败")
            return

        self.running = True
        logger.info("🚀 飞书事件服务器启动（Stream 模式 - 长连接）")

        try:
            # 启动 WebSocket 连接（长连接）
            self.ws_client.start()

        except KeyboardInterrupt:
            logger.info("🛑 收到停止信号")
        except Exception as e:
            logger.error(f"❌ 事件服务器异常: {e}")
        finally:
            self.stop()

    def stop(self) -> None:
        """停止事件服务器"""
        self.running = False
        
        # 清理 PID 文件
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
                logger.info("✅ PID 文件已清理")
        except Exception as e:
            logger.warning(f"⚠️ 清理 PID 文件失败: {e}")
        
        logger.info("🛑 飞书事件服务器已停止")


def check_single_instance():
    """检查是否已有实例在运行"""
    try:
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    old_pid = int(f.read().strip())

                # 检查进程是否存在
                try:
                    with open(f'/proc/{old_pid}/cmdline', 'r') as f:
                        cmdline = f.read()
                    if 'feishu_event_server' in cmdline:
                        logger.error(f"❌ 已有实例在运行 (PID: {old_pid})")
                        return False
                    else:
                        PID_FILE.unlink()
                except (FileNotFoundError, ProcessLookupError):
                    PID_FILE.unlink()
            except (ValueError, FileNotFoundError):
                PID_FILE.unlink()

        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"✅ 已创建 PID 文件: {PID_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ 检查单实例失败: {e}")
        return True


def main():
    """主函数"""
    if not check_single_instance():
        sys.exit(1)

    server = FeishuEventServer()

    # 注册信号处理
    import signal
    signal.signal(signal.SIGTERM, lambda s, f: server.stop())
    signal.signal(signal.SIGINT, lambda s, f: server.stop())

    server.start()


if __name__ == "__main__":
    main()
