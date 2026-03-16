#!/usr/bin/env python3
"""
简化版消息处理器 - SQLite 版本
从数据库读取消息，支持优雅退出
"""

import json
import os
import time
import sys
import signal
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from message_processor.feishu_client import FeishuClient
from message_processor.llm_client import XunfeiLLMClient
from message_store import MessageStore
from ntp_time_service import get_current_server_time

# 配置
CONFIG_DIR = Path.home() / '.trae-cn' / 'configs' / 'sdf-com-chat'
CONFIG_FILE = CONFIG_DIR / 'config.json'
FEISHU_RECEIVE_ID = 'your_feishu_receive_id'
FEISHU_RECEIVE_ID_TYPE = 'open_id'
CHECK_INTERVAL = 3  # 秒
CLEANUP_INTERVAL = 3600  # 清理间隔（1小时）
PID_FILE = Path('/tmp/message_processor.pid')

# 北京时区
beijing_tz = timezone(timedelta(hours=8))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('/tmp/message_processor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def log(msg: str, level: str = 'info'):
    """打印日志"""
    if level == 'error':
        logger.error(msg)
    elif level == 'warning':
        logger.warning(msg)
    else:
        logger.info(msg)


def check_single_instance():
    """检查是否已有实例在运行 - 增强版，处理残留PID文件"""
    try:
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # 检查进程是否存在且是message_processor
                try:
                    with open(f'/proc/{old_pid}/cmdline', 'r') as f:
                        cmdline = f.read()
                    if 'message_processor' in cmdline:
                        logger.error(f"❌ 已有实例在运行 (PID: {old_pid})")
                        return False
                    else:
                        # PID存在但不是message_processor，清理
                        logger.info(f"📝 PID {old_pid} 存在但不是message_processor，清理")
                        PID_FILE.unlink()
                except (FileNotFoundError, ProcessLookupError):
                    # 进程不存在，清理PID文件
                    logger.info("📝 发现旧的 PID 文件，进程已不存在")
                    PID_FILE.unlink()
            except (ValueError, FileNotFoundError):
                # PID文件内容无效，直接删除
                logger.info("📝 PID文件内容无效，清理")
                PID_FILE.unlink()
        
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"✅ 已创建 PID 文件: {PID_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ 检查单实例失败: {e}")
        # 如果无法创建PID文件，也允许启动（降级处理）
        logger.warning("⚠️ 无法创建PID文件，继续启动")
        return True


class SimpleMessageProcessor:
    """简化版消息处理器 - SQLite 版本"""

    def __init__(self):
        self.feishu_client = None
        self.llm_client = None
        self.store = None
        self._shutdown = False
        self.config = self._load_config()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """设置信号处理"""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        log("信号处理已设置")

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        log(f"收到信号 {signum}，准备优雅退出...")
        self._shutdown = True

    def _load_config(self):
        """加载配置文件"""
        # 从环境变量或配置文件加载，避免硬编码敏感信息
        default_config = {}

        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log(f"加载配置失败: {e}", 'error')

        return default_config

    def _init_clients(self):
        """初始化客户端"""
        try:
            feishu_config = self.config.get('feishu', {})
            self.feishu_client = FeishuClient(
                app_id=feishu_config.get('app_id', ''),
                app_secret=feishu_config.get('app_secret', '')
            )
            log("✅ 飞书客户端初始化成功")
        except Exception as e:
            log(f"❌ 飞书客户端初始化失败: {e}", 'error')

        try:
            llm_config = self.config.get('llm', {})
            self.llm_client = XunfeiLLMClient(
                api_key=llm_config.get('api_key', ''),
                api_url=llm_config.get('api_url', ''),
                model_id=llm_config.get('model_id', 'xop3qwen1b7')
            )
            log("✅ LLM客户端初始化成功")
        except Exception as e:
            log(f"❌ LLM客户端初始化失败: {e}", 'error')

        try:
            self.store = MessageStore()
            log("✅ 消息存储初始化成功")
        except Exception as e:
            log(f"❌ 消息存储初始化失败: {e}", 'error')



    def _translate(self, text, user):
        """翻译文本"""
        if not self.llm_client:
            return None
        try:
            return self.llm_client.translate_en_to_zh(text, user)
        except Exception as e:
            log(f"❌ 翻译失败: {e}", 'error')
            return None

    def _format_time_display(self, msg):
        """格式化时间显示 [UTC HH:MM:SS][北京 HH:MM:SS]"""
        server_time = msg.get('server_time', '')
        beijing_time = msg.get('beijing_time', '')

        # 提取时间部分 (HH:MM:SS)
        if server_time and ' ' in server_time:
            server_time_str = server_time.split(' ')[1]
        else:
            server_time_str = server_time

        if beijing_time and ' ' in beijing_time:
            beijing_time_str = beijing_time.split(' ')[1]
        else:
            beijing_time_str = beijing_time

        # 格式: [UTC HH:MM:SS][北京 HH:MM:SS]
        return f"[UTC {server_time_str}][北京 {beijing_time_str}]"

    def _send_to_feishu(self, msg):
        """发送消息到飞书"""
        if not self.feishu_client:
            return False

        msg_type = msg.get('msg_type', msg.get('type', 'unknown'))
        user = msg.get('user', 'unknown')
        message = msg.get('message', '')
        time_display = self._format_time_display(msg)

        try:
            if msg_type == 'chat':
                translated = self._translate(message, user)
                if not translated:
                    translated = "[翻译失败]"

                # 构建消息卡片
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": f"{time_display} 💬 {user}"},
                        "template": "blue"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {"tag": "plain_text", "content": f"原文: {message}"}
                        },
                        {
                            "tag": "div",
                            "text": {"tag": "plain_text", "content": f"翻译: {translated}"}
                        }
                    ]
                }

            elif msg_type == 'user_status':
                # 使用完整的 message 字段，包含 from lobby 等信息
                status_text = msg.get('message', '')
                if not status_text:
                    action = msg.get('action', '')
                    room = msg.get('room', '')
                    status_text = f"{user} {action} {room}"

                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": f"{time_display} 📢 SDF COM 状态"},
                        "template": "green"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {"tag": "plain_text", "content": status_text}
                        }
                    ]
                }

            elif msg_type == 'song':
                source = msg.get('source', 'aNONradio')
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": f"{time_display} 🎵 {source}"},
                        "template": "orange"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {"tag": "plain_text", "content": message}
                        }
                    ]
                }
            else:
                return False

            result = self.feishu_client.send_message(
                FEISHU_RECEIVE_ID,
                card,
                receive_id_type=FEISHU_RECEIVE_ID_TYPE
            )

            if result and result.get('success'):
                # 对于 user_status 类型，message 已经包含用户名，避免重复显示
                if msg_type == 'user_status':
                    log(f"✅ 消息发送成功: {message}")
                else:
                    log(f"✅ 消息发送成功: {user} - {message}")
                return True
            else:
                log(f"❌ 消息发送失败: {result}", 'error')
                return False

        except Exception as e:
            log(f"❌ 发送消息异常: {e}", 'error')
            return False

    def process_messages(self):
        """处理消息 - 从数据库读取，逐条处理立即标记"""
        if not self.store:
            log("❌ 消息存储未初始化", 'error')
            return

        # 每次只处理一条消息，避免批量处理被中断导致重复
        messages = self.store.get_unprocessed_messages(limit=1)

        if not messages:
            return

        msg = messages[0]
        msg_id = msg['id']
        user = msg.get('user', 'unknown')
        msg_type = msg.get('msg_type', msg.get('type', 'unknown'))

        # 过滤自己的消息
        if user == 'yupeng':
            self.store.mark_as_processed(msg_id)
            return

        # 过滤歌曲信息，不再转发到飞书
        if msg_type == 'song':
            log(f"🎵 歌曲信息已过滤（不发送到飞书）: {msg.get('message', '')[:30]}...")
            self.store.mark_as_processed(msg_id)
            return

        # 发送消息
        if self._send_to_feishu(msg):
            # 立即标记为已处理
            if self.store.mark_as_processed(msg_id):
                log(f"✅ 消息 {msg_id} 已标记为已处理")
            else:
                log(f"⚠️ 消息 {msg_id} 标记失败", 'warning')
        else:
            log(f"❌ 消息 {msg_id} 发送失败，保留未处理状态", 'warning')



    def _cleanup(self):
        """清理资源"""
        log("正在清理资源...")
        if self.llm_client:
            try:
                self.llm_client.close()
                log("✅ LLM客户端已关闭")
            except Exception as e:
                log(f"❌ 关闭LLM客户端失败: {e}", 'error')
        log("👋 再见！")

    def run(self):
        """主循环"""
        log("🚀 简化版消息处理器启动 (SQLite 版本)")
        self._init_clients()

        last_cleanup = time.time()

        try:
            while not self._shutdown:
                try:
                    self.process_messages()

                    # 定期清理旧消息（48小时）
                    if time.time() - last_cleanup > CLEANUP_INTERVAL:
                        if self.store:
                            deleted = self.store.cleanup_old_messages(hours=48)
                            if deleted > 0:
                                log(f"🧹 清理了 {deleted} 条48小时前的旧消息")
                        last_cleanup = time.time()

                except Exception as e:
                    log(f"❌ 处理异常: {e}", 'error')

                time.sleep(CHECK_INTERVAL)
        finally:
            self._cleanup()


if __name__ == '__main__':
    if not check_single_instance():
        sys.exit(1)
    
    processor = SimpleMessageProcessor()
    try:
        processor.run()
    finally:
        # 清理 PID 文件
        if PID_FILE.exists():
            PID_FILE.unlink()
            logger.info("🧹 已清理 PID 文件")
