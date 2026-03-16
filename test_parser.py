#!/usr/bin/env python3
"""测试新的消息解析规则"""

import re

def parse_chat_line(line, msg_time=None):
    """解析聊天消息行 - 基于tmux原始数据特征设计"""
    if not line or not line.strip():
        return None
    
    line_stripped = line.strip()
    
    # ===== 排除规则 =====
    
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
    
    # 5. 命令行: ssh ... / com (单独一行)
    if line_stripped.startswith('ssh ') or line_stripped == 'com':
        return None
    
    # 6. ASCII艺术/表格: 包含特定模式
    if re.search(r'/\$\$|\\\$\$|\|\s*\$\$', line_stripped):
        return None
    
    # 7. 表格分隔线: 多个连续的 -
    if re.match(r'^[-]{10,}$', line_stripped.replace(' ', '')):
        return None
    
    # ===== 匹配规则 =====
    
    # 规则1: [username]   message (至少2个空格)
    chat_match = re.match(r'^\[([a-zA-Z0-9_]+)\]\s{2,}(.+)$', line_stripped)
    if chat_match:
        user = chat_match.group(1)
        message = chat_match.group(2).strip()
        if message and not message.startswith('has '):
            return {
                'type': 'chat',
                'user': user,
                'message': message,
                'msg_time': msg_time
            }
    
    # 规则2: <username action> (动作消息)
    action_match = re.match(r'^<([a-zA-Z0-9_]+)\s+(.+)>$', line_stripped)
    if action_match:
        user = action_match.group(1)
        action = action_match.group(2).strip()
        return {
            'type': 'action',
            'user': user,
            'message': f"* {user} {action}",
            'msg_time': msg_time
        }
    
    # 规则3: 纯文本消息 (从飞书转发)
    if not line_stripped.startswith('[') and not line_stripped.startswith('<'):
        if re.match(r'^\d+$', line_stripped):
            return None
        if len(line_stripped) < 2:
            return None
        if re.match(r'^https?://', line_stripped):
            return None
        if re.match(r'^/', line_stripped):
            return None
        
        return {
            'type': 'chat',
            'user': 'unknown',
            'message': line_stripped,
            'msg_time': msg_time
        }
    
    return None


# 测试数据 - 从原始1024行数据中提取的样本
test_lines = [
    # 应该被识别为聊天消息
    ("[x2180]   china?", True, "x2180", "china?"),
    ("[optfx]   that's nice. But this is an english language, US based service.", True, "optfx", "that's nice. But this is an english language, US based service."),
    ("[jwh]     say that to tob :)", True, "jwh", "say that to tob :)"),
    ("[ratxue]  the final plan?", True, "ratxue", "the final plan?"),
    ("[kuma]    i am crying optfx", True, "kuma", "i am crying optfx"),
    ("<x2180 guessing based on what was translated>", True, "x2180", "* x2180 guessing based on what was translated"),
    ("Is anyone chatting?", True, "unknown", "Is anyone chatting?"),
    ("Good evening everyone!", True, "unknown", "Good evening everyone!"),
    
    # 应该被排除
    ("[05:43:48] [21/38/81] (openmic): Blare The Airport - Aoudaghost Bazaar", False, None, None),
    ("[05:44:23] jasmaz@faeroes has left anonradio", False, None, None),
    ("[Sun 15-Mar-26 05:45:00]", False, None, None),
    ("[05:56:07] 20 listeners with a daily peak of 38 and 81 peak for the month.", False, None, None),
    ("ssh -i ~/.ssh/sdf_com_mcp -o StrictHostKeyChecking=no yupeng@sdf.org", False, None, None),
    ("com", False, None, None),
    ("  /$$$$$$$ $$  $$$$ $$  | $$ $$  $$$$ $$  \\__//$$$$$$$ $$  | $$ $$ $$  \\ $$", False, None, None),
    ("--------------------------------------------------------------------------------", False, None, None),
]

print("=" * 80)
print("测试新的消息解析规则")
print("=" * 80)

passed = 0
failed = 0

for line, should_match, expected_user, expected_msg in test_lines:
    result = parse_chat_line(line)
    
    if should_match:
        if result:
            user_ok = result['user'] == expected_user
            msg_ok = result['message'] == expected_msg
            if user_ok and msg_ok:
                print(f"✅ PASS: {line[:50]}...")
                print(f"   用户: {result['user']}, 消息: {result['message'][:40]}...")
                passed += 1
            else:
                print(f"❌ FAIL: {line[:50]}...")
                print(f"   期望: user={expected_user}, msg={expected_msg}")
                print(f"   实际: user={result['user']}, msg={result['message']}")
                failed += 1
        else:
            print(f"❌ FAIL: 应该匹配但未匹配: {line[:50]}...")
            failed += 1
    else:
        if result:
            print(f"❌ FAIL: 应该排除但被匹配: {line[:50]}...")
            print(f"   错误匹配为: {result}")
            failed += 1
        else:
            print(f"✅ PASS: 正确排除: {line[:40]}...")
            passed += 1

print("=" * 80)
print(f"测试结果: 通过 {passed}/{passed+failed}, 失败 {failed}/{passed+failed}")
print("=" * 80)
