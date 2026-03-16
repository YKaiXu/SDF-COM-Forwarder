"""
NTP时间服务模块
提供准确的UTC时间和北京时间获取功能
"""
import ntplib
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# NTP服务器列表（按优先级排序）
NTP_SERVERS = [
    'ntp1.ntsc.ac.cn',      # 国家授时中心（最权威）
    'ntp2.ntsc.ac.cn',
    'ntp3.ntsc.ac.cn',
    'ntp1.aliyun.com',      # 阿里云
    'ntp1.tencent.com',     # 腾讯云
    'ntp1.baidu.com',       # 百度云
    '0.cn.pool.ntp.org',    # NTP Pool中国节点
    '1.cn.pool.ntp.org',
]

# 缓存时间（秒）
CACHE_DURATION = 60  # 1分钟缓存，避免频繁查询NTP服务器


class NTPTimeService:
    """NTP时间服务类"""
    
    def __init__(self):
        self._cached_time: Optional[datetime] = None
        self._cache_timestamp: Optional[datetime] = None
        self._last_ntp_server: Optional[str] = None
        self._ntp_client = ntplib.NTPClient()
    
    def get_ntp_time(self, timeout: float = 2.0) -> Tuple[datetime, str]:
        """
        从NTP服务器获取准确的UTC时间
        
        Args:
            timeout: 每个NTP服务器的超时时间（秒）
            
        Returns:
            Tuple[datetime, str]: (UTC时间, 使用的NTP服务器)
            
        如果所有NTP服务器都失败，则返回本地UTC时间
        """
        # 检查缓存
        if self._is_cache_valid():
            logger.debug(f"使用缓存的NTP时间（来自 {self._last_ntp_server}）")
            return self._cached_time, self._last_ntp_server
        
        # 尝试从NTP服务器获取时间
        for server in NTP_SERVERS:
            try:
                response = self._ntp_client.request(server, timeout=timeout)
                utc_time = datetime.utcfromtimestamp(response.tx_time)
                
                # 更新缓存
                self._cached_time = utc_time
                self._cache_timestamp = datetime.utcnow()
                self._last_ntp_server = server
                
                logger.debug(f"成功从NTP服务器 {server} 获取时间: {utc_time}")
                return utc_time, server
                
            except Exception as e:
                logger.warning(f"NTP服务器 {server} 获取失败: {e}")
                continue
        
        # 所有NTP服务器都失败，使用本地时间作为降级
        fallback_time = datetime.utcnow()
        logger.warning(f"所有NTP服务器都失败，使用本地UTC时间: {fallback_time}")
        return fallback_time, "local"
    
    def get_current_server_time(self) -> Tuple[str, str, str]:
        """
        获取当前服务器时间（UTC和北京时间）
        
        Returns:
            Tuple[str, str, str]: (UTC时间字符串, 北京时间字符串, 时间来源)
            格式: 'YYYY-MM-DD HH:MM:SS'
        """
        utc_time, source = self.get_ntp_time()
        
        # 转换为北京时间（UTC+8）
        beijing_time = utc_time + timedelta(hours=8)
        
        # 格式化为字符串
        utc_str = utc_time.strftime('%Y-%m-%d %H:%M:%S')
        beijing_str = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
        
        return utc_str, beijing_str, source
    
    def get_message_timestamp(self) -> dict:
        """
        获取消息时间戳（完整格式）
        
        Returns:
            dict: 包含server_time, beijing_time, time_source的字典
        """
        utc_str, beijing_str, source = self.get_current_server_time()
        
        return {
            'server_time': utc_str,
            'beijing_time': beijing_str,
            'time_source': 'ntp' if source != 'local' else 'local',
            'ntp_server': source if source != 'local' else None
        }
    
    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cached_time is None or self._cache_timestamp is None:
            return False
        
        elapsed = (datetime.utcnow() - self._cache_timestamp).total_seconds()
        return elapsed < CACHE_DURATION
    
    def clear_cache(self):
        """清除时间缓存"""
        self._cached_time = None
        self._cache_timestamp = None
        logger.debug("NTP时间缓存已清除")


# 全局NTP时间服务实例
_ntp_service: Optional[NTPTimeService] = None


def get_ntp_service() -> NTPTimeService:
    """获取全局NTP时间服务实例（单例模式）"""
    global _ntp_service
    if _ntp_service is None:
        _ntp_service = NTPTimeService()
    return _ntp_service


def get_current_server_time() -> Tuple[str, str, str]:
    """
    便捷函数：获取当前服务器时间
    
    Returns:
        Tuple[str, str, str]: (UTC时间, 北京时间, 时间来源)
    """
    return get_ntp_service().get_current_server_time()


def get_message_timestamp() -> dict:
    """
    便捷函数：获取消息时间戳
    
    Returns:
        dict: 包含server_time, beijing_time, time_source的字典
    """
    return get_ntp_service().get_message_timestamp()


# 向后兼容的函数名
get_server_and_beijing_time = get_current_server_time


if __name__ == '__main__':
    # 测试NTP时间服务
    logging.basicConfig(level=logging.DEBUG)
    
    print("测试NTP时间服务...")
    print("-" * 50)
    
    # 测试获取时间
    utc, beijing, source = get_current_server_time()
    print(f"UTC时间: {utc}")
    print(f"北京时间: {beijing}")
    print(f"时间来源: {source}")
    print("-" * 50)
    
    # 测试获取消息时间戳
    timestamp = get_message_timestamp()
    print(f"消息时间戳: {timestamp}")
    print("-" * 50)
    
    # 测试缓存
    print("测试缓存...")
    utc2, beijing2, source2 = get_current_server_time()
    print(f"第二次获取（应该使用缓存）:")
    print(f"UTC时间: {utc2}")
    print(f"时间来源: {source2}")
    
    print("\n测试完成！")
