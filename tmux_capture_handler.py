#!/usr/bin/env python3
"""
Tmux 捕获消息处理器 - SQLite 版本
使用数据库存储消息，支持去重和状态标记
时间戳来源：
- 使用NTP时间服务器获取准确的UTC时间
- 转换为北京时间存储
"""

import json
import subprocess
import re
import time
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))
from message_store import MessageStore
from ntp_time_service import get_current_server_time, get_message_timestamp

# 配置
CAPTURE_LOG = '/tmp/capture_handler.log'
TMUX_SESSION = 'sdf-com'
CHECK_INTERVAL = 3  # 捕获间隔（秒）

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(CAPTURE_LOG),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


def capture_pane():
    """捕获 tmux pane 内容"""
    try:
        result = subprocess.run(
            ['tmux', 'capture-pane', '-t', TMUX_SESSION, '-p'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout
        else:
            logger.error(f"tmux capture-pane failed: {result.stderr}")
            return None
    except Exception as e:
        logger.error(f"Error capturing pane: {e}")
        return None


def parse_date_from_line(line):
    """从行中提取日期 [Sun 15-Mar-26 02:00:00]"""
    date_match = re.match(r'^\[\w{3}\s+(\d{1,2})-(\w{3})-(\d{2})(?:\s+\d{2}:\d{2}:\d{2})?\]', line)
    if date_match:
        day = date_match.group(1)
        month_str = date_match.group(2)
        year_short = date_match.group(3)
        
        months = {
            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
        }
        month = months.get(month_str, '01')
        year = f"20{year_short}"
        
        return f"{year}-{month}-{day.zfill(2)}"
    return None


def parse_time_from_line(line):
    """从行中提取时间戳 [HH:MM:SS]"""
    time_match = re.match(r'^\[(\d{2}:\d{2}:\d{2})\]', line)
    if time_match:
        return time_match.group(1)
    return None


def convert_to_beijing(server_date_str, server_time_str):
    """将服务器时间（UTC）转换为北京时间（UTC+8）"""
    try:
        hour, minute, second = map(int, server_time_str.split(':'))
        beijing_hour = (hour + 8) % 24
        day_offset = (hour + 8) // 24
        
        # 解析日期
        from datetime import datetime as dt
        base_date = dt.strptime(server_date_str, '%Y-%m-%d')
        target_date = base_date + timedelta(days=day_offset)
        
        return target_date.strftime('%Y-%m-%d') + f' {beijing_hour:02d}:{minute:02d}:{second:02d}'
    except Exception as e:
        logger.error(f"时间转换失败: {e}")
        return None


def get_current_server_time():
    """获取当前服务器时间和北京时间（使用NTP时间服务）
    
    Returns:
        Tuple[datetime, datetime, str]: (UTC时间datetime对象, 北京时间datetime对象, 时间来源)
    """
    # 使用NTP时间服务获取准确时间
    from ntp_time_service import get_current_server_time as ntp_get_time
    utc_str, beijing_str, source = ntp_get_time()
    
    # 将字符串转换为datetime对象
    from datetime import datetime
    utc_time = datetime.strptime(utc_str, '%Y-%m-%d %H:%M:%S')
    beijing_time = datetime.strptime(beijing_str, '%Y-%m-%d %H:%M:%S')
    
    logger.debug(f"使用NTP时间: UTC={utc_time}, 北京={beijing_time}, 来源={source}")
    return utc_time, beijing_time, source


def should_ignore_line(line):
    """检查是否应该忽略该行"""
    if not line or not line.strip():
        return True
    # 忽略系统消息行
    if line.startswith('***') or re.match(r'^\[\w{3}\s+\d{1,2}-\w{3}-\d{2}', line):
        return True
    return False


def parse_chat_line(line, msg_time):
    """解析聊天消息行 - 基于tmux原始数据特征设计 (彻底修复版)
    
    从1866行原始数据分析得出的规则:
    - 聊天消息: 358条
    - 动作消息: 48条
    - 歌曲信息: 180条 (排除)
    - 系统消息: 64条 (排除)
    
    用户聊天消息核心特征:
    - [username] message (方括号+用户名+至少1个空格+消息)
    - 用户名只包含字母、数字、下划线
    - 不以时间戳格式开头
    """
    if not line or not line.strip():
        return None
    
    line_stripped = line.strip()
    
    # ===== 快速排除规则 (按优先级排序) =====
    
    # 1. 歌曲信息: [HH:MM:SS] [XX/XX/XX] (source): message
    if re.match(r'^\[\d{2}:\d{2}:\d{2}\]\s+\[\d+/\d+/\d+\]\s+\([^)]+\):', line_stripped):
        return None
    
    # 2. 用户状态: [HH:MM:SS] user@host has joined/left
    if re.match(r'^\[\d{2}:\d{2}:\d{2}\]\s+\S+@\S+\s+has\s+(joined|left)', line_stripped):
        return None
    
    # 3. 听众统计: [HH:MM:SS] N listeners with...
    if re.match(r'^\[\d{2}:\d{2}:\d{2}\]\s+\d+\s+listeners', line_stripped):
        return None
    
    # 4. 日期标记: [Sun 15-Mar-26 HH:MM:SS]
    if re.match(r'^\[\w{3}\s+\d+-\w+-\d+\s+\d{2}:\d{2}:\d{2}\]', line_stripped):
        return None
    
    # ===== 匹配规则 =====
    
    # 规则1: [username] message (至少1个空格)
    # 关键修复: 从\s{2,}改为\s+，因为实际数据中有1个空格的情况
    chat_match = re.match(r'^\[([a-zA-Z0-9_]+)\]\s+(.+)$', line_stripped)
    if chat_match:
        user = chat_match.group(1)
        message = chat_match.group(2).strip()
        
        # 排除时间戳格式作为用户名 (如 14:26:10, 04:23:16)
        if re.match(r'^\d{2}:\d{2}:\d{2}$', user):
            return None
        
        # 排除纯数字用户名
        if re.match(r'^\d+$', user):
            return None
        
        # 排除听众统计消息内容
        if 'listeners' in message.lower():
            return None
        
        # 排除has joined/left消息内容
        if message.startswith('has '):
            return None
        
        # 成功匹配聊天消息
        return {
            'type': 'chat',
            'user': user,
            'message': message,
            'msg_time': msg_time
        }
    
    return None


def parse_user_status_line(line, msg_time):
    """解析用户状态消息行
    
    支持格式:
    - [HH:MM:SS] user@host has joined/left room [from lobby]
    """
    status_match = re.match(r'^\[\d{2}:\d{2}:\d{2}\]\s+(.+)$', line)
    if status_match:
        content = status_match.group(1)
        # 检查是否包含 has joined 或 has left
        if 'has joined' in content or 'has left' in content:
            # 过滤掉歌曲信息
            if '[10/40/81]' in line or '[11/40/81]' in line:
                return None
            
            # 提取用户和完整状态信息
            status_parts = content.split('has joined' if 'has joined' in content else 'has left')
            if len(status_parts) >= 2:
                user = status_parts[0].strip()
                action = 'has joined' if 'has joined' in content else 'has left'
                rest = ('has joined' if 'has joined' in content else 'has left') + status_parts[1]
                
                # 构建完整的消息内容（包含用户名）
                message = f"{user} {rest.strip()}"
                # 提取房间名（第一个单词）
                room = status_parts[1].strip().split()[0] if status_parts[1].strip() else 'unknown'
                
                return {
                    'type': 'user_status',
                    'user': user,
                    'action': action,
                    'room': room,
                    'message': message,
                    'msg_time': msg_time
                }
    
    return None


def parse_song_line(line, msg_time):
    """解析歌曲信息行
    
    支持格式:
    - [HH:MM:SS] [XX/XX/XX] (source): message
    """
    song_match = re.match(r'^\[\d{2}:\d{2}:\d{2}\]\s+\[\d+/\d+/\d+\]\s+\(([^)]+)\):\s*(.+)$', line)
    if song_match:
        source = song_match.group(1)
        message = song_match.group(2)
        return {
            'type': 'song',
            'source': source,
            'message': message,
            'msg_time': msg_time
        }
    
    return None


def parse_messages(text):
    """解析消息 - 统一使用 NTP 时间戳
    
    支持格式:
    - [username] message (聊天消息，使用 NTP 服务器当前时间)
    - [HH:MM:SS] username@host has joined/left room (使用 NTP 时间)
    - [HH:MM:SS] [XX/XX/XX] (source): message (使用 NTP 时间)
    - [Sun 15-Mar-26 02:00:00] 日期标记
    
    注意：所有消息时间戳统一使用 NTP 时间服务获取，不使用 pane 中的本地时间
    """
    messages = []
    lines = text.split('\n')
    
    # 获取当前 NTP 时间作为基准
    ntp_utc, ntp_beijing, ntp_source = get_current_server_time()
    ntp_date = ntp_utc.strftime('%Y-%m-%d')
    
    for line in lines:
        line = line.strip()
        
        # 忽略空行和系统消息
        if should_ignore_line(line):
            continue
        
        # 1. 首先检查是否是日期行 [Sun 15-Mar-26 02:00:00] - 仅用于日志记录
        parsed_date = parse_date_from_line(line)
        if parsed_date:
            logger.debug(f"检测到 pane 日期标记: {parsed_date} (仅参考，使用 NTP 时间)")
            continue
        
        # 2. 提取 pane 中的时间戳 [HH:MM:SS] - 仅用于识别消息顺序
        msg_time = parse_time_from_line(line)
        
        # 3. 尝试解析用户状态消息
        user_status = parse_user_status_line(line, msg_time)
        if user_status:
            # 统一使用 NTP 时间
            user_status['server_time'] = ntp_utc.strftime('%Y-%m-%d %H:%M:%S')
            user_status['beijing_time'] = ntp_beijing.strftime('%Y-%m-%d %H:%M:%S')
            messages.append(user_status)
            continue
        
        # 4. 尝试解析歌曲信息
        song_info = parse_song_line(line, msg_time)
        if song_info:
            # 统一使用 NTP 时间
            song_info['server_time'] = ntp_utc.strftime('%Y-%m-%d %H:%M:%S')
            song_info['beijing_time'] = ntp_beijing.strftime('%Y-%m-%d %H:%M:%S')
            messages.append(song_info)
            continue
        
        # 5. 尝试解析聊天消息
        chat_msg = parse_chat_line(line, msg_time)
        if chat_msg:
            # 统一使用 NTP 时间
            chat_msg['server_time'] = ntp_utc.strftime('%Y-%m-%d %H:%M:%S')
            chat_msg['beijing_time'] = ntp_beijing.strftime('%Y-%m-%d %H:%M:%S')
            messages.append(chat_msg)
    
    return messages


def main():
    """主循环 - 定期捕获消息"""
    logger.info("=" * 60)
    logger.info("Tmux 捕获消息处理器启动 (SQLite 版本 - 修复时间戳)")
    logger.info(f"捕获间隔: {CHECK_INTERVAL} 秒")
    logger.info("=" * 60)
    
    # 初始化消息存储
    store = MessageStore()
    stats = store.get_stats()
    logger.info(f"数据库已有 {stats['total']} 条消息，未处理 {stats['unprocessed']} 条")
    
    new_message_count = 0
    
    try:
        while True:
            # 捕获 pane 内容
            pane_content = capture_pane()
            
            if pane_content:
                # 解析消息
                new_messages = parse_messages(pane_content)
                
                if new_messages:
                    logger.debug(f"捕获到 {len(new_messages)} 条消息")
                    
                    # 保存到数据库（自动去重）
                    added_count = 0
                    for msg in new_messages:
                        if store.save_message(msg):
                            added_count += 1
                            new_message_count += 1
                            # 输出新消息通知
                            print(f"[SDF_COM_CAPTURE] {json.dumps(msg, ensure_ascii=False)}")
                            sys.stdout.flush()
                    
                    if added_count > 0:
                        logger.info(f"发现 {added_count} 条新消息")
            
            # 等待下次捕获
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
    except Exception as e:
        logger.error(f"错误: {e}")
    
    logger.info("=" * 60)
    logger.info(f"Tmux 捕获消息处理器停止，共捕获 {new_message_count} 条新消息")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
