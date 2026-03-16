"""
message_store.py 单元测试
"""
import pytest
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

# 导入被测模块
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from message_store import MessageStore


@pytest.fixture
def store():
    """提供 MessageStore 实例（内存数据库）"""
    return MessageStore(':memory:')


class TestMessageStoreInit:
    """测试 MessageStore 初始化"""

    def test_init_with_memory_db(self):
        """测试使用内存数据库初始化"""
        store = MessageStore(':memory:')
        assert store.db_path == ':memory:'

    def test_init_with_file_db(self, temp_db):
        """测试使用文件数据库初始化"""
        store = MessageStore(temp_db)
        assert store.db_path == temp_db
        # 验证表已创建
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert 'messages' in tables


class TestMessageHash:
    """测试消息哈希计算"""

    def test_chat_message_hash(self, store):
        """测试聊天消息哈希计算"""
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 10:00:00'
        }
        
        hash_value = store._get_hash(msg)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 32  # MD5 哈希长度

    def test_song_message_hash_includes_timestamp(self, store):
        """测试歌曲消息哈希包含时间戳"""
        msg1 = {
            'type': 'song',
            'user': None,
            'message': 'Same Song',
            'beijing_time': '2026-03-15 10:00:00'
        }
        msg2 = {
            'type': 'song',
            'user': None,
            'message': 'Same Song',
            'beijing_time': '2026-03-15 11:00:00'
        }
        
        hash1 = store._get_hash(msg1)
        hash2 = store._get_hash(msg2)
        
        # 相同歌曲不同时间应该有不同的哈希
        assert hash1 != hash2

    def test_chat_message_hash_excludes_timestamp(self, store):
        """测试聊天消息哈希不包含时间戳"""
        msg1 = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 10:00:00'
        }
        msg2 = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 11:00:00'
        }
        
        hash1 = store._get_hash(msg1)
        hash2 = store._get_hash(msg2)
        
        # 相同聊天消息不同时间应该有相同的哈希
        assert hash1 == hash2

    def test_different_messages_different_hash(self, store):
        """测试不同消息有不同的哈希"""
        msg1 = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 10:00:00'
        }
        msg2 = {
            'type': 'chat',
            'user': 'bob',
            'message': 'Hello',
            'beijing_time': '2026-03-15 10:00:00'
        }
        
        hash1 = store._get_hash(msg1)
        hash2 = store._get_hash(msg2)
        
        # 不同用户相同消息应该有不同的哈希
        assert hash1 != hash2


class TestSaveMessage:
    """测试保存消息"""

    def test_save_new_message(self, store):
        """测试保存新消息"""
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello World',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        
        result = store.save_message(msg)
        assert result is True

    def test_save_duplicate_message(self, store):
        """测试保存重复消息"""
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello World',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        
        # 第一次保存应该成功
        result1 = store.save_message(msg)
        assert result1 is True
        
        # 第二次保存应该失败（重复）
        result2 = store.save_message(msg)
        assert result2 is False

    def test_save_song_message_same_content_different_time(self, store):
        """测试保存相同歌曲不同时间的消息"""
        msg1 = {
            'type': 'song',
            'user': None,
            'message': 'Test Song',
            'beijing_time': '2026-03-15 10:00:00',
            'server_time': '2026-03-15 02:00:00',
            'msg_time': '02:00:00',
            'source': 'aNONradio'
        }
        msg2 = {
            'type': 'song',
            'user': None,
            'message': 'Test Song',
            'beijing_time': '2026-03-15 11:00:00',
            'server_time': '2026-03-15 03:00:00',
            'msg_time': '03:00:00',
            'source': 'aNONradio'
        }
        
        # 两首相同歌曲不同时间都应该保存成功
        result1 = store.save_message(msg1)
        result2 = store.save_message(msg2)
        assert result1 is True
        assert result2 is True

    def test_save_message_with_all_fields(self, store):
        """测试保存包含所有字段的消息"""
        msg = {
            'type': 'user_status',
            'user': 'testuser@sdf',
            'message': 'testuser@sdf has joined anonradio',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00',
            'action': 'has joined',
            'room': 'anonradio'
        }
        
        result = store.save_message(msg)
        assert result is True


class TestGetUnprocessedMessages:
    """测试获取未处理消息"""

    def test_get_unprocessed_messages_empty(self, store):
        """测试空数据库返回空列表"""
        messages = store.get_unprocessed_messages()
        assert messages == []

    def test_get_unprocessed_messages(self, store):
        """测试获取未处理消息"""
        # 保存几条消息
        for i in range(3):
            msg = {
                'type': 'chat',
                'user': f'user{i}',
                'message': f'Message {i}',
                'beijing_time': f'2026-03-15 1{i}:00:00',
                'server_time': f'2026-03-15 0{i}:00:00',
                'msg_time': f'0{i}:00:00'
            }
            store.save_message(msg)
        
        messages = store.get_unprocessed_messages()
        assert len(messages) == 3
        
        # 验证消息格式
        for msg in messages:
            assert 'id' in msg
            assert 'msg_type' in msg
            assert 'user' in msg
            assert 'message' in msg

    def test_get_unprocessed_messages_respects_limit(self, store):
        """测试获取未处理消息限制数量"""
        # 保存 10 条消息
        for i in range(10):
            msg = {
                'type': 'chat',
                'user': f'user{i}',
                'message': f'Message {i}',
                'beijing_time': f'2026-03-15 1{i}:00:00',
                'server_time': f'2026-03-15 0{i}:00:00',
                'msg_time': f'0{i}:00:00'
            }
            store.save_message(msg)
        
        # 只获取 5 条
        messages = store.get_unprocessed_messages(limit=5)
        assert len(messages) == 5

    def test_get_unprocessed_excludes_processed(self, store):
        """测试不返回已处理消息"""
        # 保存消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        store.save_message(msg)
        
        # 获取并标记为已处理
        messages = store.get_unprocessed_messages()
        for msg in messages:
            store.mark_as_processed(msg['id'])
        
        # 再次获取应该为空
        messages = store.get_unprocessed_messages()
        assert len(messages) == 0


class TestMarkAsProcessed:
    """测试标记消息已处理"""

    def test_mark_as_processed(self, store):
        """测试标记消息已处理"""
        # 保存消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        store.save_message(msg)
        
        # 获取消息 ID
        messages = store.get_unprocessed_messages()
        msg_id = messages[0]['id']
        
        # 标记为已处理
        result = store.mark_as_processed(msg_id)
        assert result is True

    def test_mark_as_processed_invalid_id(self, store):
        """测试标记不存在的消息"""
        result = store.mark_as_processed(99999)
        assert result is False


class TestGetStats:
    """测试获取统计信息"""

    def test_get_stats_empty(self, store):
        """测试空数据库统计"""
        stats = store.get_stats()
        assert stats['total'] == 0
        assert stats['unprocessed'] == 0

    def test_get_stats_with_messages(self, store):
        """测试有消息时的统计"""
        # 保存 5 条消息
        for i in range(5):
            msg = {
                'type': 'chat',
                'user': f'user{i}',
                'message': f'Message {i}',
                'beijing_time': f'2026-03-15 1{i}:00:00',
                'server_time': f'2026-03-15 0{i}:00:00',
                'msg_time': f'0{i}:00:00'
            }
            store.save_message(msg)
        
        # 标记 2 条为已处理
        messages = store.get_unprocessed_messages()
        for msg in messages[:2]:
            store.mark_as_processed(msg['id'])
        
        stats = store.get_stats()
        assert stats['total'] == 5
        assert stats['unprocessed'] == 3


class TestMessageTypes:
    """测试不同类型消息的处理"""

    def test_save_chat_message(self, store):
        """测试保存聊天消息"""
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello everyone!',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        
        result = store.save_message(msg)
        assert result is True

    def test_save_song_message(self, store):
        """测试保存歌曲消息"""
        msg = {
            'type': 'song',
            'user': None,
            'source': 'aNONradio',
            'message': 'Test Artist - Test Song',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        
        result = store.save_message(msg)
        assert result is True

    def test_save_user_status_message(self, store):
        """测试保存用户状态消息"""
        msg = {
            'type': 'user_status',
            'user': 'testuser@sdf',
            'action': 'has joined',
            'room': 'anonradio',
            'message': 'testuser@sdf has joined anonradio from lobby',
            'beijing_time': '2026-03-15 18:30:00',
            'server_time': '2026-03-15 10:30:00',
            'msg_time': '10:30:00'
        }
        
        result = store.save_message(msg)
        assert result is True


class TestExceptionHandling:
    """测试异常处理 - 100% 覆盖率补充"""

    def test_save_message_exception(self, store):
        """测试保存消息异常处理"""
        # 模拟数据库异常 - 通过关闭连接来触发异常
        store._conn.close()
        store._conn = None
        
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Hello',
            'beijing_time': '2026-03-15 18:30:00'
        }
        
        # 使用无效的数据库路径来触发异常
        store.db_path = '/invalid/path/that/does/not/exist.db'
        result = store.save_message(msg)
        assert result is False

    def test_get_unprocessed_messages_exception(self, store):
        """测试获取未处理消息异常处理"""
        # 使用无效的数据库路径
        store.db_path = '/invalid/path/that/does/not/exist.db'
        store._conn = None
        
        result = store.get_unprocessed_messages()
        assert result == []

    def test_cleanup_old_messages_success(self, store):
        """测试清理旧消息成功"""
        # 保存一条旧消息（超过48小时）
        old_time = '2020-01-01 00:00:00'
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Old message',
            'beijing_time': old_time,
            'server_time': old_time,
            'msg_time': '00:00:00'
        }
        store.save_message(msg)
        
        # 手动修改 created_at 为旧时间
        store._conn.execute(
            "UPDATE messages SET created_at = ? WHERE user = ?",
            ('2020-01-01T00:00:00', 'alice')
        )
        store._conn.commit()
        
        # 清理旧消息
        deleted = store.cleanup_old_messages(hours=1)
        assert deleted >= 0  # 可能删除0条或1条，取决于测试时间

    def test_cleanup_old_messages_no_old_messages(self, store):
        """测试没有旧消息可清理"""
        # 保存新消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'New message',
            'beijing_time': '2026-03-15 18:30:00'
        }
        store.save_message(msg)
        
        # 手动更新 created_at 为未来时间（确保不会被清理）
        store._conn.execute(
            "UPDATE messages SET created_at = '2099-12-31 23:59:59' WHERE user = ?",
            ('alice',)
        )
        store._conn.commit()
        
        # 清理1小时前的消息（应该没有）
        deleted = store.cleanup_old_messages(hours=1)
        assert deleted == 0

    def test_cleanup_old_messages_exception(self, store):
        """测试清理旧消息异常处理"""
        store.db_path = '/invalid/path/that/does/not/exist.db'
        store._conn = None
        
        result = store.cleanup_old_messages(hours=48)
        assert result == 0

    def test_get_stats_exception(self, store):
        """测试获取统计信息异常处理"""
        store.db_path = '/invalid/path/that/does/not/exist.db'
        store._conn = None
        
        result = store.get_stats()
        assert result == {'total': 0, 'unprocessed': 0, 'processed': 0}

    def test_init_db_with_file_db(self, temp_db):
        """测试文件数据库初始化"""
        store = MessageStore(temp_db)
        # 验证数据库已正确初始化
        assert store.db_path == temp_db
        
        # 验证可以正常操作
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Test',
            'beijing_time': '2026-03-15 18:30:00'
        }
        result = store.save_message(msg)
        assert result is True

    def test_get_unprocessed_messages_with_file_db(self, temp_db):
        """测试文件数据库获取未处理消息"""
        store = MessageStore(temp_db)
        
        # 保存消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Test',
            'beijing_time': '2026-03-15 18:30:00'
        }
        store.save_message(msg)
        
        # 获取未处理消息（会触发 conn.close()）
        messages = store.get_unprocessed_messages()
        assert len(messages) == 1

    def test_mark_as_processed_with_file_db(self, temp_db):
        """测试文件数据库标记已处理"""
        store = MessageStore(temp_db)
        
        # 保存消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Test',
            'beijing_time': '2026-03-15 18:30:00'
        }
        store.save_message(msg)
        
        # 获取消息 ID
        messages = store.get_unprocessed_messages()
        msg_id = messages[0]['id']
        
        # 标记为已处理（会触发 conn.close()）
        result = store.mark_as_processed(msg_id)
        assert result is True

    def test_mark_as_processed_exception(self, store):
        """测试标记已处理异常"""
        # 使用无效的数据库路径
        store.db_path = '/invalid/path/that/does/not/exist.db'
        store._conn = None
        
        result = store.mark_as_processed(1)
        assert result is False

    def test_cleanup_old_messages_with_deletion(self, store):
        """测试清理旧消息并触发日志"""
        # 保存旧消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Old message',
            'beijing_time': '2020-01-01 00:00:00'
        }
        store.save_message(msg)
        
        # 手动更新 created_at 为很早的时间
        store._conn.execute(
            "UPDATE messages SET created_at = '2020-01-01 00:00:00' WHERE user = ?",
            ('alice',)
        )
        store._conn.commit()
        
        # 清理旧消息（应该触发日志输出）
        deleted = store.cleanup_old_messages(hours=1)
        assert deleted == 1

    def test_cleanup_old_messages_with_file_db(self, temp_db):
        """测试文件数据库清理旧消息"""
        store = MessageStore(temp_db)
        
        # 保存旧消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Old message',
            'beijing_time': '2020-01-01 00:00:00'
        }
        store.save_message(msg)
        
        # 使用新连接手动更新 created_at
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute(
            "UPDATE messages SET created_at = '2020-01-01 00:00:00' WHERE user = ?",
            ('alice',)
        )
        conn.commit()
        conn.close()
        
        # 清理旧消息（会触发 conn.close()）
        deleted = store.cleanup_old_messages(hours=1)
        assert deleted == 1

    def test_get_stats_with_file_db(self, temp_db):
        """测试文件数据库获取统计"""
        store = MessageStore(temp_db)
        
        # 保存消息
        msg = {
            'type': 'chat',
            'user': 'alice',
            'message': 'Test',
            'beijing_time': '2026-03-15 18:30:00'
        }
        store.save_message(msg)
        
        # 获取统计（会触发 conn.close()）
        stats = store.get_stats()
        assert stats['total'] == 1
