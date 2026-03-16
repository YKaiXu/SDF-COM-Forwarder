#!/usr/bin/env python3
"""
消息存储模块 - SQLite 实现
支持消息持久化、去重、状态标记
"""

import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path('/tmp/sdf_com_messages.db')


class MessageStore:
    """SQLite 消息存储"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        # 对于内存数据库，保持连接打开
        self._conn = None
        if self.db_path == ':memory:':
            self._conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _get_conn(self):
        """获取数据库连接"""
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """初始化数据库"""
        conn = self._get_conn()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_hash TEXT UNIQUE NOT NULL,
                beijing_time TEXT,
                server_time TEXT,
                user TEXT,
                message TEXT,
                msg_type TEXT,
                processed BOOLEAN DEFAULT 0,
                sent_to_feishu BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_processed ON messages(processed)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hash ON messages(message_hash)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON messages(created_at)')
        conn.commit()
        if not self._conn:
            conn.close()
        logger.info(f"✅ 数据库初始化完成: {self.db_path}")

    def _get_hash(self, msg: Dict) -> str:
        """计算消息哈希 - 对于歌曲信息包含时间戳，避免漏掉重复播放的歌曲"""
        msg_type = msg.get('type', '')
        user = msg.get('user', '')
        message = msg.get('message', '')

        # 对于歌曲信息，包含时间戳，因为同一首歌可能重复播放
        if msg_type == 'song':
            beijing_time = msg.get('beijing_time', '')
            content = f"{user}|{message}|{beijing_time}"
        else:
            # 对于普通聊天消息，不包含时间戳，避免重复
            content = f"{user}|{message}"

        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def save_message(self, msg: Dict) -> bool:
        """
        保存消息到数据库
        如果消息已存在（根据哈希），则跳过
        返回 True 表示是新消息，False 表示已存在
        """
        msg_hash = self._get_hash(msg)

        try:
            conn = self._get_conn()
            cursor = conn.execute('''
                INSERT OR IGNORE INTO messages
                (message_hash, beijing_time, server_time, user, message, msg_type)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                msg_hash,
                msg.get('beijing_time'),
                msg.get('server_time'),
                msg.get('user'),
                msg.get('message'),
                msg.get('type')
            ))
            conn.commit()

            if not self._conn:
                conn.close()

            if cursor.rowcount > 0:
                logger.debug(f"✅ 新消息已保存: {msg.get('user')} - {msg.get('message', '')[:30]}...")
                return True
            else:
                logger.debug(f"⏭️ 消息已存在，跳过: {msg.get('user')}")
                return False

        except sqlite3.Error as e:
            logger.error(f"❌ 保存消息失败: {e}")
            return False

    def get_unprocessed_messages(self, limit: int = 100) -> List[Dict]:
        """获取未处理的消息"""
        try:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM messages
                WHERE processed = 0
                ORDER BY id
                LIMIT ?
            ''', (limit,))
            results = [dict(row) for row in cursor.fetchall()]
            if not self._conn:
                conn.close()
            return results
        except sqlite3.Error as e:
            logger.error(f"❌ 查询消息失败: {e}")
            return []

    def mark_as_processed(self, msg_id: int) -> bool:
        """标记消息为已处理"""
        try:
            conn = self._get_conn()
            cursor = conn.execute('''
                UPDATE messages
                SET processed = 1, sent_to_feishu = 1, processed_at = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), msg_id))
            conn.commit()
            if not self._conn:
                conn.close()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"❌ 标记消息失败: {e}")
            return False

    def cleanup_old_messages(self, hours: int = 48) -> int:
        """
        清理旧消息
        默认清理48小时前的消息
        返回清理的消息数量
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        try:
            conn = self._get_conn()
            # 使用 strftime 格式化时间以匹配 SQLite 的 CURRENT_TIMESTAMP 格式
            cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
            cursor = conn.execute('''
                DELETE FROM messages
                WHERE created_at < ?
            ''', (cutoff_str,))
            conn.commit()
            deleted_count = cursor.rowcount
            if not self._conn:
                conn.close()
            if deleted_count > 0:
                logger.info(f"🧹 已清理 {deleted_count} 条旧消息（{hours}小时前）")
            return deleted_count
        except sqlite3.Error as e:
            logger.error(f"❌ 清理旧消息失败: {e}")
            return 0

    def get_stats(self) -> Dict:
        """获取统计信息"""
        try:
            conn = self._get_conn()
            total = conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
            unprocessed = conn.execute('SELECT COUNT(*) FROM messages WHERE processed = 0').fetchone()[0]
            processed = conn.execute('SELECT COUNT(*) FROM messages WHERE processed = 1').fetchone()[0]
            if not self._conn:
                conn.close()
            return {
                'total': total,
                'unprocessed': unprocessed,
                'processed': processed
            }
        except sqlite3.Error as e:
            logger.error(f"❌ 获取统计失败: {e}")
            return {'total': 0, 'unprocessed': 0, 'processed': 0}
