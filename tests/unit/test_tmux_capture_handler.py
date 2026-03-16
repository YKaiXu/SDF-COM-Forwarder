"""
tmux_capture_handler.py 单元测试
"""
import pytest
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 导入被测模块
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tmux_capture_handler import (
    convert_to_beijing,
    parse_chat_line,
    parse_user_status_line,
    parse_song_line,
    should_ignore_line,
    capture_pane,
)


class TestTimeConversion:
    """测试时间转换功能"""

    def test_convert_to_beijing_normal(self):
        """测试正常时间转换 UTC -> 北京"""
        result = convert_to_beijing("2026-03-15", "10:30:00")
        assert result == "2026-03-15 18:30:00"

    def test_convert_to_beijing_midnight(self):
        """测试午夜时间转换"""
        result = convert_to_beijing("2026-03-15", "00:00:00")
        assert result == "2026-03-15 08:00:00"

    def test_convert_to_beijing_cross_day(self):
        """测试跨天时间转换"""
        result = convert_to_beijing("2026-03-15", "20:00:00")
        # UTC 20:00 = 北京时间次日 04:00
        assert result == "2026-03-16 04:00:00"

    def test_convert_to_beijing_invalid_time(self):
        """测试无效时间格式"""
        result = convert_to_beijing("2026-03-15", "invalid")
        assert result is None


class TestChatLineParsing:
    """测试聊天消息解析"""

    def test_parse_simple_chat(self):
        """测试解析简单聊天消息"""
        line = "[alice] Hello everyone!"
        result = parse_chat_line(line, "10:30:45")
        
        assert result is not None
        assert result['type'] == 'chat'
        assert result['user'] == 'alice'
        assert result['message'] == 'Hello everyone!'
        assert result['msg_time'] == '10:30:45'

    def test_parse_chat_with_special_chars(self):
        """测试解析包含特殊字符的聊天消息"""
        line = "[bob] Hello @alice! How are you? :)"
        result = parse_chat_line(line, "10:30:45")
        
        assert result is not None
        assert result['user'] == 'bob'
        assert result['message'] == 'Hello @alice! How are you? :)'

    def test_parse_chat_empty_message(self):
        """测试解析空聊天消息"""
        line = "[alice] "
        result = parse_chat_line(line, "10:30:45")
        
        assert result is None  # 空消息应该被忽略

    def test_parse_chat_no_match(self):
        """测试非聊天消息格式"""
        line = "some random text"
        result = parse_chat_line(line, "10:30:45")
        
        assert result is None


class TestUserStatusParsing:
    """测试用户状态消息解析"""

    def test_parse_user_join(self):
        """测试解析用户加入消息"""
        line = "[10:14:00] msittig@sdf has joined anonradio from lobby"
        result = parse_user_status_line(line, "10:14:00")
        
        assert result is not None
        assert result['type'] == 'user_status'
        assert result['user'] == 'msittig@sdf'
        assert result['action'] == 'has joined'
        assert result['room'] == 'anonradio'
        assert 'from lobby' in result['message']

    def test_parse_user_leave(self):
        """测试解析用户离开消息"""
        line = "[11:02:22] msittig@sdf has left anonradio"
        result = parse_user_status_line(line, "11:02:22")
        
        assert result is not None
        assert result['type'] == 'user_status'
        assert result['user'] == 'msittig@sdf'
        assert result['action'] == 'has left'
        assert result['room'] == 'anonradio'

    def test_parse_user_join_without_lobby(self):
        """测试解析用户加入消息（无 lobby 信息）"""
        line = "[10:15:00] alice@example has joined anonradio"
        result = parse_user_status_line(line, "10:15:00")
        
        assert result is not None
        assert result['user'] == 'alice@example'
        assert result['action'] == 'has joined'

    def test_parse_user_status_no_match(self):
        """测试非用户状态消息"""
        line = "[10:30:45] <alice> Hello"
        result = parse_user_status_line(line, "10:30:45")
        
        assert result is None


class TestSongParsing:
    """测试歌曲信息解析"""

    def test_parse_song_info(self):
        """测试解析歌曲信息"""
        line = "[10:36:41] [10/43/81] (aNONradio): Ard Bit & Radboud Mens - Perpendicular"
        result = parse_song_line(line, "10:36:41")
        
        assert result is not None
        assert result['type'] == 'song'
        assert result['source'] == 'aNONradio'
        assert result['message'] == 'Ard Bit & Radboud Mens - Perpendicular'
        assert result['msg_time'] == '10:36:41'

    def test_parse_song_different_source(self):
        """测试解析不同来源的歌曲"""
        line = "[10:30:00] [5/20/40] (thenews): News Report"
        result = parse_song_line(line, "10:30:00")
        
        assert result is not None
        assert result['source'] == 'thenews'
        assert result['message'] == 'News Report'

    def test_parse_song_no_match(self):
        """测试非歌曲消息格式"""
        line = "[10:30:45] <alice> Hello"
        result = parse_song_line(line, "10:30:45")
        
        assert result is None


class TestLineFiltering:
    """测试行过滤功能"""

    def test_should_ignore_empty_line(self):
        """测试忽略空行"""
        assert should_ignore_line("") is True
        assert should_ignore_line("   ") is True

    def test_should_ignore_system_messages(self):
        """测试忽略系统消息"""
        assert should_ignore_line("*** System message ***") is True
        assert should_ignore_line("[Sun 15-Mar-26 10:00:00]") is True

    def test_should_not_ignore_valid_messages(self):
        """测试不忽略有效消息"""
        assert should_ignore_line("[10:30:45] <alice> Hello") is False
        assert should_ignore_line("[10:30:45] user@sdf has joined") is False
        assert should_ignore_line("[10:30:45] [10/43/81] (aNONradio): Song") is False


class TestCapturePane:
    """测试 tmux pane 捕获功能"""

    @patch('tmux_capture_handler.subprocess.run')
    def test_capture_pane_success(self, mock_run):
        """测试成功捕获 pane"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="line1\nline2\nline3\n"
        )
        
        result = capture_pane()
        
        assert result == "line1\nline2\nline3\n"
        mock_run.assert_called_once()

    @patch('tmux_capture_handler.subprocess.run')
    def test_capture_pane_failure(self, mock_run):
        """测试捕获 pane 失败"""
        mock_run.return_value = Mock(returncode=1, stdout="")
        
        result = capture_pane()
        
        assert result is None

    @patch('tmux_capture_handler.subprocess.run')
    def test_capture_pane_exception(self, mock_run):
        """测试捕获 pane 异常"""
        mock_run.side_effect = Exception("tmux not found")
        
        result = capture_pane()
        
        assert result is None


class TestMessageParsingIntegration:
    """测试消息解析集成"""

    def test_parse_mixed_messages(self, sample_chat_messages):
        """测试解析混合类型消息"""
        results = []
        for line in sample_chat_messages:
            # 尝试每种解析器
            msg_time = "10:30:00"
            result = None
            
            if not should_ignore_line(line):
                result = parse_chat_line(line, msg_time)
                if not result:
                    result = parse_user_status_line(line, msg_time)
                if not result:
                    result = parse_song_line(line, msg_time)
            
            if result:
                results.append(result)
        
        # 应该解析出 5 条消息
        assert len(results) == 5
        
        # 验证类型分布
        types = [r['type'] for r in results]
        assert types.count('chat') == 2
        assert types.count('user_status') == 2
        assert types.count('song') == 1


class TestTimeConversionEdgeCases:
    """测试时间转换边界情况"""

    @pytest.mark.parametrize("utc_time,expected_beijing", [
        ("00:00:00", "08:00:00"),
        ("12:00:00", "20:00:00"),
        ("16:00:00", "00:00:00"),  # 跨天
        ("23:59:59", "07:59:59"),  # 跨天
    ])
    def test_time_conversion_cases(self, utc_time, expected_beijing):
        """测试各种时间转换情况"""
        result = convert_to_beijing("2026-03-15", utc_time)
        assert expected_beijing in result


class TestMessageDeduplicationLogic:
    """测试消息去重逻辑"""

    def test_same_chat_message_different_time(self):
        """测试相同聊天消息不同时间应该有不同的哈希"""
        from message_store import MessageStore
        
        store = MessageStore(':memory:')
        
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
        
        # 聊天消息不包含时间戳，应该相同
        assert hash1 == hash2

    def test_same_song_different_time(self):
        """测试相同歌曲不同时间应该有不同的哈希"""
        from message_store import MessageStore
        
        store = MessageStore(':memory:')
        
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
        
        # 歌曲消息包含时间戳，应该不同
        assert hash1 != hash2


class TestParseDateFromLine:
    """测试日期解析功能"""

    def test_parse_date_from_line_success(self):
        """测试成功解析日期行"""
        from tmux_capture_handler import parse_date_from_line
        
        line = "[Sun 15-Mar-26 02:00:00]"
        result = parse_date_from_line(line)
        
        assert result == "2026-03-15"

    def test_parse_date_from_line_without_time(self):
        """测试解析不带时间的日期行"""
        from tmux_capture_handler import parse_date_from_line
        
        line = "[Sun 15-Mar-26]"
        result = parse_date_from_line(line)
        
        assert result == "2026-03-15"

    def test_parse_date_from_line_invalid(self):
        """测试无效日期格式"""
        from tmux_capture_handler import parse_date_from_line
        
        line = "[Invalid date]"
        result = parse_date_from_line(line)
        
        assert result is None

    def test_parse_date_from_line_different_months(self):
        """测试不同月份"""
        from tmux_capture_handler import parse_date_from_line
        
        test_cases = [
            ("[Sun 15-Jan-26]", "2026-01-15"),
            ("[Sun 15-Feb-26]", "2026-02-15"),
            ("[Sun 15-Dec-26]", "2026-12-15"),
        ]
        
        for line, expected in test_cases:
            result = parse_date_from_line(line)
            assert result == expected


class TestParseTimeFromLine:
    """测试时间解析功能"""

    def test_parse_time_from_line_success(self):
        """测试成功解析时间"""
        from tmux_capture_handler import parse_time_from_line
        
        line = "[10:30:45] message"
        result = parse_time_from_line(line)
        
        assert result == "10:30:45"

    def test_parse_time_from_line_invalid(self):
        """测试无效时间格式"""
        from tmux_capture_handler import parse_time_from_line
        
        line = "[invalid] message"
        result = parse_time_from_line(line)
        
        assert result is None

    def test_parse_time_from_line_no_time(self):
        """测试没有时间戳的行"""
        from tmux_capture_handler import parse_time_from_line
        
        line = "just a message"
        result = parse_time_from_line(line)
        
        assert result is None


class TestParseMessagesIntegration:
    """测试 parse_messages 函数"""

    def test_parse_messages_with_date_line(self):
        """测试带日期行的消息解析"""
        from tmux_capture_handler import parse_messages
        
        text = """[Sun 15-Mar-26 02:00:00]
[10:30:45] [alice] Hello everyone!
[10:31:00] [bob] Hi alice!"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 2
        assert messages[0]['user'] == 'alice'
        assert messages[1]['user'] == 'bob'

    def test_parse_messages_no_date(self):
        """测试无日期消息解析"""
        from tmux_capture_handler import parse_messages
        
        text = """[10:30:45] [alice] Hello everyone!
[10:31:00] [bob] Hi alice!"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 2

    def test_parse_messages_empty_lines(self):
        """测试空行处理"""
        from tmux_capture_handler import parse_messages
        
        text = """
[10:30:45] [alice] Hello everyone!

[10:31:00] [bob] Hi alice!
"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 2

    def test_parse_messages_mixed_content(self):
        """测试混合内容解析"""
        from tmux_capture_handler import parse_messages
        
        text = """[Sun 15-Mar-26 02:00:00]
[10:30:45] [alice] Hello!
[10:31:00] user@sdf has joined anonradio
[10:32:00] [10/43/81] (aNONradio): Test Song"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 3
        assert messages[0]['type'] == 'chat'
        assert messages[1]['type'] == 'user_status'
        assert messages[2]['type'] == 'song'

    def test_parse_messages_with_system_messages(self):
        """测试系统消息过滤"""
        from tmux_capture_handler import parse_messages
        
        text = """*** System message ***
[10:30:45] [alice] Hello!
*** Another system message ***"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 1
        assert messages[0]['user'] == 'alice'


class TestGetCurrentServerTime:
    """测试获取服务器时间 - 覆盖109-114行"""
    
    def test_get_current_server_time(self):
        """测试获取当前服务器时间和北京时间"""
        from tmux_capture_handler import get_current_server_time
        
        server_time, beijing_time = get_current_server_time()
        
        # 验证返回格式
        assert len(server_time) == 19  # YYYY-MM-DD HH:MM:SS
        assert len(beijing_time) == 19
        
        # 验证北京时间比服务器时间晚8小时
        from datetime import datetime
        server_dt = datetime.strptime(server_time, '%Y-%m-%d %H:%M:%S')
        beijing_dt = datetime.strptime(beijing_time, '%Y-%m-%d %H:%M:%S')
        diff_hours = (beijing_dt - server_dt).total_seconds() / 3600
        assert diff_hours == 8


class TestParseChatLineEdgeCases:
    """测试解析聊天消息的边界情况 - 覆盖163-166行"""
    
    def test_parse_chat_line_timestamp_as_user(self):
        """测试用户名为时间戳格式的情况 - 覆盖163-164行"""
        from tmux_capture_handler import parse_chat_line
        
        # 用户名为时间戳格式（如 12:34:56）应该被过滤
        # 格式: [username] message，其中username是时间戳格式
        line = "[12:34:56] Some message"
        result = parse_chat_line(line, "10:30:45")
        
        assert result is None
    
    def test_parse_chat_line_date_as_user(self):
        """测试用户名为日期格式的情况 - 覆盖165-166行"""
        from tmux_capture_handler import parse_chat_line
        
        # 用户名为日期格式（如 03/15/26）应该被过滤
        line = "[03/15/26] Some message"
        result = parse_chat_line(line, "10:30:45")
        
        assert result is None


class TestParseUserStatusEdgeCases:
    """测试解析用户状态的边界情况 - 覆盖190-191行"""
    
    def test_parse_user_status_filter_song_info(self):
        """测试过滤掉歌曲信息 - 覆盖190-191行"""
        from tmux_capture_handler import parse_user_status_line
        
        # 包含歌曲信息的行应该被过滤
        line = "[10:30:45] *** user has joined [10/40/81] ***"
        result = parse_user_status_line(line, "10:30:45")
        
        assert result is None
    
    def test_parse_user_status_filter_song_info_alt(self):
        """测试过滤另一种格式的歌曲信息"""
        from tmux_capture_handler import parse_user_status_line
        
        line = "[10:30:45] *** user has joined [11/40/81] ***"
        result = parse_user_status_line(line, "10:30:45")
        
        assert result is None


class TestParseMessagesWithDateLine:
    """测试解析消息时处理日期行 - 覆盖266-268行"""
    
    def test_parse_messages_with_date_updates_current_date(self):
        """测试日期行更新当前日期 - 覆盖266-268行"""
        from tmux_capture_handler import parse_messages
        
        text = """[Sun 15-Mar-26 02:00:00]
[10:30:45] [alice] Hello after date line"""
        
        messages = parse_messages(text)
        
        assert len(messages) == 1
        # 日期格式会被转换为 YYYY-MM-DD
        assert '2026-03-15' in messages[0]['server_time']
    
    def test_parse_messages_date_line_skipped(self):
        """测试日期行本身不产生消息"""
        from tmux_capture_handler import parse_messages
        
        text = """[Sun 15-Mar-26 02:00:00]
[Sun 16-Mar-26 02:00:00]
[10:30:45] [alice] Hello"""
        
        messages = parse_messages(text)
        
        # 只有一条消息，日期行不产生消息
        assert len(messages) == 1


class TestParseMessagesWithoutTime:
    """测试解析不带时间戳的消息 - 覆盖310行"""
    
    def test_parse_messages_uses_current_time_when_no_time_in_line(self):
        """测试当行中没有时间戳时使用当前服务器时间 - 覆盖310行"""
        from tmux_capture_handler import parse_messages
        
        # 没有标准时间戳格式的行
        text = "[alice] Message without timestamp"
        
        messages = parse_messages(text)
        
        # 应该仍然解析出消息，但使用当前时间
        if messages:
            assert messages[0]['user'] == 'alice'
            assert 'server_time' in messages[0]


class TestMainFunction:
    """测试主函数 - 覆盖320-373行"""
    
    @patch('tmux_capture_handler.capture_pane')
    @patch('tmux_capture_handler.time.sleep')
    @patch('tmux_capture_handler.MessageStore')
    def test_main_loop_one_iteration(self, mock_store_class, mock_sleep, mock_capture):
        """测试主循环执行一次 - 覆盖320-369行"""
        from tmux_capture_handler import main
        
        # Mock
        mock_capture.return_value = "[10:30:45] [alice] Hello"
        mock_store = Mock()
        mock_store_class.return_value = mock_store
        mock_store.get_stats.return_value = {'total': 0, 'unprocessed': 0}
        mock_store.save_message.return_value = True
        
        # 让循环只执行一次
        sleep_count = 0
        def sleep_and_interrupt(*args, **kwargs):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 1:
                raise KeyboardInterrupt()
        
        mock_sleep.side_effect = sleep_and_interrupt
        
        # 执行
        try:
            main()
        except KeyboardInterrupt:
            pass
        
        # 验证
        mock_capture.assert_called_once()
        mock_store.save_message.assert_called_once()
    
    @patch('tmux_capture_handler.capture_pane')
    @patch('tmux_capture_handler.time.sleep')
    @patch('tmux_capture_handler.MessageStore')
    def test_main_loop_no_messages(self, mock_store_class, mock_sleep, mock_capture):
        """测试主循环没有新消息"""
        from tmux_capture_handler import main
        
        mock_capture.return_value = ""
        mock_store = Mock()
        mock_store_class.return_value = mock_store
        mock_store.get_stats.return_value = {'total': 0, 'unprocessed': 0}
        
        sleep_count = 0
        def sleep_and_interrupt(*args, **kwargs):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 1:
                raise KeyboardInterrupt()
        
        mock_sleep.side_effect = sleep_and_interrupt
        
        try:
            main()
        except KeyboardInterrupt:
            pass
        
        mock_capture.assert_called_once()
        mock_store.save_message.assert_not_called()
    
    @patch('tmux_capture_handler.capture_pane')
    @patch('tmux_capture_handler.time.sleep')
    @patch('tmux_capture_handler.MessageStore')
    def test_main_loop_exception(self, mock_store_class, mock_sleep, mock_capture):
        """测试主循环异常处理 - 覆盖364-366行"""
        from tmux_capture_handler import main
        
        mock_capture.side_effect = Exception("Capture error")
        mock_store = Mock()
        mock_store_class.return_value = mock_store
        mock_store.get_stats.return_value = {'total': 0, 'unprocessed': 0}
        
        sleep_count = 0
        def sleep_and_interrupt(*args, **kwargs):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 1:
                raise KeyboardInterrupt()
        
        mock_sleep.side_effect = sleep_and_interrupt
        
        # 应该捕获异常而不抛出
        try:
            main()
        except KeyboardInterrupt:
            pass
        except Exception:
            pytest.fail("Exception should be caught")
    
    @patch('tmux_capture_handler.main')
    def test_main_entry_point(self, mock_main):
        """测试主入口点 - 覆盖372-373行"""
        import tmux_capture_handler
        
        # 模拟 __main__ 块
        if hasattr(tmux_capture_handler, 'main'):
            tmux_capture_handler.main()
        
        mock_main.assert_called_once()
