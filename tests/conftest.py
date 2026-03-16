"""
pytest 配置文件 - 共享 fixtures
"""
import pytest
import tempfile
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def temp_db():
    """提供临时数据库"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def sample_chat_messages():
    """提供样本聊天消息"""
    return [
        "[alice] Hello everyone!",
        "[bob] Hi alice!",
        "[10:32:15] [10/43/81] (aNONradio): Test Song",
        "[10:33:00] user@sdf has joined anonradio",
        "[10:34:00] user@sdf has left anonradio",
    ]


@pytest.fixture
def sample_user_status_messages():
    """提供样本用户状态消息"""
    return [
        "[10:14:00] msittig@sdf has joined anonradio from lobby",
        "[11:02:22] msittig@sdf has left anonradio",
        "[10:15:00] alice@example has joined anonradio",
    ]


@pytest.fixture
def sample_song_messages():
    """提供样本歌曲消息"""
    return [
        "[10:36:41] [10/43/81] (aNONradio): Ard Bit & Radboud Mens - Perpendicular",
        "[10:39:46] [10/43/81] (aNONradio): American Institute of Physics - Vibroacoustic",
        "[10:42:01] [10/43/81] (aNONradio): Almost An Island - Palo Verde",
    ]


@pytest.fixture
def mock_feishu_config():
    """提供测试用的飞书配置"""
    return {
        'app_id': 'test_app_id',
        'app_secret': 'test_secret',
        'receive_id': 'test_chat_id',
    }


@pytest.fixture
def temp_pid_file():
    """提供临时 PID 文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pid', delete=False) as f:
        f.write(str(os.getpid()))
        pid_file = f.name
    yield pid_file
    if os.path.exists(pid_file):
        os.unlink(pid_file)


@pytest.fixture
def clean_pid_file():
    """清理 feishu_event_server PID 文件"""
    pid_file = Path('/tmp/feishu_event_server.pid')
    if pid_file.exists():
        pid_file.unlink()
    yield
    if pid_file.exists():
        pid_file.unlink()


@pytest.fixture
def beijing_timezone():
    """提供北京时区"""
    return timezone(timedelta(hours=8))


@pytest.fixture
def utc_timezone():
    """提供 UTC 时区"""
    return timezone.utc


@pytest.fixture
def sample_message_dict():
    """提供样本消息字典"""
    return {
        'type': 'chat',
        'user': 'testuser',
        'message': 'Hello World',
        'beijing_time': '2026-03-15 18:30:00',
        'server_time': '2026-03-15 10:30:00',
        'msg_time': '10:30:00',
    }


@pytest.fixture
def sample_song_dict():
    """提供样本歌曲消息字典"""
    return {
        'type': 'song',
        'user': None,
        'source': 'aNONradio',
        'message': 'Test Song - Test Artist',
        'beijing_time': '2026-03-15 18:30:00',
        'server_time': '2026-03-15 10:30:00',
        'msg_time': '10:30:00',
    }


@pytest.fixture
def sample_user_status_dict():
    """提供样本用户状态消息字典"""
    return {
        'type': 'user_status',
        'user': 'testuser@sdf',
        'action': 'has joined',
        'room': 'anonradio',
        'message': 'testuser@sdf has joined anonradio from lobby',
        'beijing_time': '2026-03-15 18:30:00',
        'server_time': '2026-03-15 10:30:00',
        'msg_time': '10:30:00',
    }
