#!/usr/bin/env python3
"""
回执管理器 - 管理消息发送回执
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 北京时区
beijing_tz = timezone(timedelta(hours=8))

class ReceiptManager:
    """回执管理器"""
    
    def __init__(self, receipt_dir: str = '/tmp/receipts'):
        self.receipt_dir = receipt_dir
        Path(receipt_dir).mkdir(parents=True, exist_ok=True)
    
    def create_success_receipt(self, original_message: dict, feishu_message_id: str) -> dict:
        """创建成功回执"""
        receipt = {
            "receipt_id": str(uuid.uuid4()),
            "status": "success",
            "original_message": original_message,
            "feishu_message_id": feishu_message_id,
            "timestamp": datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S"),
            "error_info": None
        }
        
        self._save_receipt(receipt)
        return receipt
    
    def create_failed_receipt(self, original_message: dict, error_info: dict, suggested_action: str) -> dict:
        """创建失败回执"""
        receipt = {
            "receipt_id": str(uuid.uuid4()),
            "status": "failed",
            "original_message": original_message,
            "timestamp": datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S"),
            "error_info": error_info,
            "suggested_action": suggested_action
        }
        
        self._save_receipt(receipt)
        return receipt
    
    def _save_receipt(self, receipt: dict):
        """保存回执到文件"""
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")
        date_dir = Path(self.receipt_dir) / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        
        receipt_file = date_dir / f"{receipt['receipt_id']}.json"
        with open(receipt_file, 'w') as f:
            json.dump(receipt, f, ensure_ascii=False, indent=2)
    
    def get_receipt(self, receipt_id: str) -> dict:
        """获取回执"""
        for date_dir in Path(self.receipt_dir).iterdir():
            if date_dir.is_dir():
                receipt_file = date_dir / f"{receipt_id}.json"
                if receipt_file.exists():
                    with open(receipt_file, 'r') as f:
                        return json.load(f)
        return None
