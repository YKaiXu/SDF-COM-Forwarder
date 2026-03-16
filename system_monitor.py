#!/usr/bin/env python3
"""
系统级健康监测 - 守护进程版
支持自动修复SSH连接和本地进程
"""

import json
import os
import sys
import time
import signal
import psutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 配置
MONITOR_INTERVAL = 10  # 监测间隔（秒）
PID_FILE = '/tmp/system_monitor.pid'
LOG_FILE = '/tmp/system_monitor.log'
RESTART_SIGNAL_DIR = Path('/tmp/system_monitor_signals')

# SSH配置
SSH_CONFIG = {
    'host': 'sdf.org',
    'user': 'yupeng',
    'key_file': '/home/yupeng/.ssh/sdf_com_mcp',
    'tmux_session': 'sdf-com',
    'enabled': True
}

# 组件配置
COMPONENTS = {
    'tmux_capture_handler': {
        'script': '/home/yupeng/.trae-cn/sdf-com-mcp-python/tmux_capture_handler.py',
        'pid_file': '/tmp/tmux_capture_handler.pid',
        'log_file': '/tmp/capture_handler.log',
        'enabled': True
    },
    'message_processor': {
        'script': '/home/yupeng/.trae-cn/sdf-com-mcp-python/message_processor.py',
        'pid_file': '/tmp/message_processor.pid',
        'log_file': '/tmp/message_processor.log',
        'enabled': True
    },
    'feishu_event_server': {
        'script': '/home/yupeng/.trae-cn/sdf-com-mcp-python/feishu_event_server.py',
        'pid_file': '/tmp/feishu_event_server.pid',
        'log_file': '/tmp/feishu_event_server.log',
        'enabled': True
    }
}


def log(msg, level='INFO'):
    """记录日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"{timestamp} [{level}] {msg}"
    print(log_line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')


class SSHConnectionManager:
    """SSH连接管理器 - 自动检测和修复SSH连接"""
    
    def __init__(self, config):
        self.config = config
        self.ssh_process = None
        self.last_check_time = None
        self.reconnect_count = 0
        
    def is_connected(self) -> bool:
        """检查SSH连接是否活跃"""
        try:
            # 检查是否有到sdf.org的SSH连接
            result = subprocess.run(
                ['pgrep', '-f', f'ssh.*{self.config["host"]}'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            
            # 检查tmux会话是否存在
            result = subprocess.run(
                ['tmux', 'has-session', '-t', self.config['tmux_session']],
                capture_output=True
            )
            return result.returncode == 0
            
        except Exception as e:
            log(f"检查SSH连接失败: {e}", 'ERROR')
            return False
    
    def reconnect(self) -> bool:
        """重新建立SSH连接并利用tmux会话恢复功能自动进入anonradio"""
        log("🔄 尝试重新建立SSH连接...")
        
        try:
            # 1. 清理现有SSH进程
            self._cleanup_ssh()
            
            # 2. 建立SSH连接（后台模式，只建立隧道）
            ssh_cmd = [
                'ssh',
                '-i', self.config['key_file'],
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ServerAliveInterval=30',
                '-o', 'ServerAliveCountMax=3',
                '-o', 'TCPKeepAlive=yes',
                '-o', 'ConnectTimeout=10',
                '-N',  # 不执行远程命令
                '-f',  # 后台运行
                f'{self.config["user"]}@{self.config["host"]}'
            ]
            
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
            
            if result.returncode != 0:
                log(f"❌ SSH连接失败: {result.stderr}", 'ERROR')
                return False
            
            log("✅ SSH连接已建立")
            
            # 3. 等待连接稳定（增加等待时间）
            log("⏳ 等待SSH连接稳定...")
            time.sleep(5)
            
            # 4. 检查服务器端tmux会话是否存在（带重试）
            session_exists = False
            for attempt in range(3):
                log(f"🔄 检查tmux会话 (尝试 {attempt + 1}/3)...")
                session_exists = self._check_remote_tmux_session()
                if session_exists:
                    break
                time.sleep(2)
            
            if session_exists:
                log("✅ 服务器端tmux会话存在")
                # 检查是否已经在anonradio中
                if self._check_in_anonradio():
                    log("✅ 已经在anonradio中")
                else:
                    log("🔄 发送进入anonradio命令...")
                    self._send_remote_command('j anonradio')
                    time.sleep(2)
            else:
                log("⚠️ 服务器端tmux会话不存在，创建新会话...")
                # 创建新会话并启动com
                if self._create_remote_tmux_session():
                    time.sleep(5)  # 等待com启动
                    log("🔄 发送进入anonradio命令...")
                    self._send_remote_command('j anonradio')
                    time.sleep(2)
            
            self.reconnect_count += 1
            log(f"✅ SSH连接已恢复并进入anonradio (重连次数: {self.reconnect_count})")
            return True
            
        except subprocess.TimeoutExpired:
            log("❌ SSH连接超时", 'ERROR')
            return False
        except Exception as e:
            log(f"❌ SSH重连失败: {e}", 'ERROR')
            return False
    
    def _cleanup_ssh(self):
        """清理现有SSH进程"""
        try:
            result = subprocess.run(
                ['pkill', '-f', f'ssh.*{self.config["host"]}'],
                capture_output=True
            )
            time.sleep(1)
            log("🧹 已清理现有SSH进程")
        except Exception as e:
            log(f"清理SSH进程失败: {e}", 'WARNING')
    
    def _check_tmux_session(self) -> bool:
        """检查tmux会话是否存在"""
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', self.config['tmux_session']],
                capture_output=True
            )
            return result.returncode == 0
        except:
            return False
    
    def _create_tmux_session(self) -> bool:
        """创建新的tmux会话"""
        try:
            result = subprocess.run(
                ['tmux', 'new-session', '-d', '-s', self.config['tmux_session']],
                capture_output=True
            )
            if result.returncode == 0:
                log(f"✅ tmux会话已创建: {self.config['tmux_session']}")
                return True
            else:
                log(f"❌ 创建tmux会话失败: {result.stderr.decode()}", 'ERROR')
                return False
        except Exception as e:
            log(f"❌ 创建tmux会话失败: {e}", 'ERROR')
            return False
    
    def _check_remote_tmux_session(self) -> bool:
        """检查服务器端tmux会话是否存在"""
        try:
            ssh_cmd = [
                'ssh',
                '-T',  # 禁用伪终端分配
                '-i', self.config['key_file'],
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=5',
                '-o', 'BatchMode=yes',  # 禁用密码提示
                f'{self.config["user"]}@{self.config["host"]}',
                f'tmux has-session -t {self.config["tmux_session"]} 2>/dev/null && echo "EXISTS" || echo "NOT_EXISTS"'
            ]
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            return "EXISTS" in result.stdout
        except subprocess.TimeoutExpired:
            log("⚠️ 检查tmux会话超时", 'WARNING')
            return False
        except Exception as e:
            log(f"❌ 检查远程tmux会话失败: {e}", 'ERROR')
            return False
    
    def _create_remote_tmux_session(self) -> bool:
        """在服务器端创建tmux会话并启动com"""
        try:
            # 创建新会话并启动com
            ssh_cmd = [
                'ssh',
                '-T',  # 禁用伪终端分配
                '-i', self.config['key_file'],
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=5',
                '-o', 'BatchMode=yes',  # 禁用密码提示
                f'{self.config["user"]}@{self.config["host"]}',
                f'tmux new-session -d -s {self.config["tmux_session"]} "com"'
            ]
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                log(f"✅ 服务器端tmux会话已创建")
                return True
            else:
                log(f"❌ 创建远程tmux会话失败: {result.stderr}", 'ERROR')
                return False
        except subprocess.TimeoutExpired:
            log("❌ 创建tmux会话超时", 'ERROR')
            return False
        except Exception as e:
            log(f"❌ 创建远程tmux会话失败: {e}", 'ERROR')
            return False
    
    def _send_remote_command(self, command: str) -> bool:
        """通过SSH发送远程命令到tmux会话"""
        try:
            ssh_cmd = [
                'ssh',
                '-T',  # 禁用伪终端分配
                '-i', self.config['key_file'],
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=5',
                '-o', 'BatchMode=yes',  # 禁用密码提示
                f'{self.config["user"]}@{self.config["host"]}',
                f'tmux send-keys -t {self.config["tmux_session"]} "{command}" Enter'
            ]
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log("⚠️ 发送远程命令超时", 'WARNING')
            return False
        except Exception as e:
            log(f"❌ 发送远程命令失败: {e}", 'ERROR')
            return False
    
    def _check_in_anonradio(self) -> bool:
        """检查是否已经在anonradio中"""
        try:
            ssh_cmd = [
                'ssh',
                '-T',  # 禁用伪终端分配
                '-i', self.config['key_file'],
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=5',
                f'{self.config["user"]}@{self.config["host"]}',
                f'tmux capture-pane -t {self.config["tmux_session"]} -p'
            ]
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            content = result.stdout
            return '[you are in' in content or '(anonradio)' in content
        except subprocess.TimeoutExpired:
            log("⚠️ 检查anonradio状态超时", 'WARNING')
            return False
        except Exception as e:
            log(f"❌ 检查anonradio状态失败: {e}", 'ERROR')
            return False


class SystemMonitor:
    """系统健康监测器"""

    def __init__(self):
        self.components = COMPONENTS.copy()
        self.ssh_manager = SSHConnectionManager(SSH_CONFIG)
        self.repair_queue = []
        self.health_stats = {
            'checks': 0,
            'repairs': 0,
            'ssh_reconnects': 0,
            'last_check': None
        }

    def check_ssh_connection(self) -> bool:
        """检查SSH连接状态"""
        if not SSH_CONFIG['enabled']:
            return True
            
        is_connected = self.ssh_manager.is_connected()
        self.last_check_time = datetime.now()
        
        if not is_connected:
            log("⚠️ SSH连接断开", 'WARNING')
            return False
        
        return True

    def repair_ssh_connection(self) -> bool:
        """修复SSH连接"""
        if self.ssh_manager.reconnect():
            self.health_stats['ssh_reconnects'] += 1
            return True
        return False

    def register_component(self, name: str, config: dict):
        """注册组件"""
        self.components[name] = config
        log(f"📝 注册组件: {name}")

    def check_component(self, name: str) -> bool:
        """检查组件状态"""
        config = self.components.get(name)
        if not config or not config.get('enabled', True):
            return True

        pid_file = config['pid_file']
        script_name = config['script']

        try:
            # 首先检查 PID 文件
            if os.path.exists(pid_file):
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())

                # 检查进程是否存在
                if psutil.pid_exists(pid):
                    return True
                else:
                    log(f"⚠️ {name}: PID文件存在但进程不存在 (PID: {pid})", 'WARNING')
                    return False
            
            # PID 文件不存在，检查是否有同名进程在运行
            script_basename = os.path.basename(script_name)
            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if script_basename in cmdline and 'python' in cmdline.lower():
                        log(f"⚠️ {name}: 进程在运行但PID文件不存在 (PID: {proc.info['pid']})", 'WARNING')
                        # 重新创建 PID 文件
                        with open(pid_file, 'w') as f:
                            f.write(str(proc.info['pid']))
                        log(f"✅ {name}: 已重建PID文件")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            log(f"⚠️ {name}: 未运行", 'WARNING')
            return False

        except Exception as e:
            log(f"❌ 检查 {name} 失败: {e}", 'ERROR')
            return False

    def restart_component(self, name: str) -> bool:
        """重启组件"""
        config = self.components.get(name)
        if not config:
            log(f"❌ 未知组件: {name}", 'ERROR')
            return False

        log(f"🔄 重启 {name}...")

        # 1. 停止现有进程
        self._stop_component(name)

        # 2. 清理 PID 文件
        pid_file = config['pid_file']
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except:
                pass

        # 3. 启动新进程
        script = config['script']
        log_file = config['log_file']

        try:
            # 使用 nohup 启动，确保进程在后台运行
            cmd = f"nohup python3 {script} > {log_file} 2>&1 &"
            os.system(cmd)

            # 等待进程启动
            time.sleep(2)

            # 检查是否启动成功
            if self.check_component(name):
                log(f"✅ {name} 重启成功")
                return True
            else:
                log(f"❌ {name} 重启失败", 'ERROR')
                return False

        except Exception as e:
            log(f"❌ 重启 {name} 失败: {e}", 'ERROR')
            return False

    def _stop_component(self, name: str):
        """停止组件 - 清理所有相关进程"""
        config = self.components.get(name)
        if not config:
            return

        pid_file = config['pid_file']
        script_name = config['script']
        script_basename = os.path.basename(script_name)

        stopped_count = 0

        try:
            # 1. 从 PID 文件停止
            if os.path.exists(pid_file):
                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())

                    if psutil.pid_exists(pid):
                        os.kill(pid, signal.SIGTERM)
                        log(f"🛑 停止 {name} (PID: {pid})")
                        time.sleep(1)

                        if psutil.pid_exists(pid):
                            os.kill(pid, signal.SIGKILL)
                            log(f"💀 强制终止 {name} (PID: {pid})")
                        stopped_count += 1
                except Exception as e:
                    log(f"⚠️ 从PID文件停止 {name} 失败: {e}", 'WARNING')

            # 2. 扫描并停止所有同名进程
            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if script_basename in cmdline and 'python' in cmdline.lower():
                        pid = proc.info['pid']
                        try:
                            os.kill(pid, signal.SIGTERM)
                            log(f"🛑 停止残留进程 {name} (PID: {pid})")
                            time.sleep(0.5)

                            if psutil.pid_exists(pid):
                                os.kill(pid, signal.SIGKILL)
                                log(f"💀 强制终止残留进程 {name} (PID: {pid})")
                            stopped_count += 1
                        except Exception as e:
                            log(f"⚠️ 停止残留进程失败: {e}", 'WARNING')
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if stopped_count > 1:
                log(f"⚠️ 发现 {stopped_count} 个 {name} 实例，已全部停止")

        except Exception as e:
            log(f"⚠️ 停止 {name} 时出错: {e}", 'WARNING')

    def check_and_repair(self):
        """检查并修复所有组件"""
        self.health_stats['checks'] += 1
        self.health_stats['last_check'] = datetime.now().isoformat()

        log("=" * 60)
        log("执行系统级健康检查...")

        # 1. 检查SSH连接
        if SSH_CONFIG['enabled']:
            if not self.check_ssh_connection():
                log("🔧 尝试修复SSH连接...")
                if self.repair_ssh_connection():
                    log("✅ SSH连接已修复")
                else:
                    log("❌ SSH连接修复失败", 'ERROR')

        # 2. 检查所有本地组件
        for name in self.components:
            if not self.check_component(name):
                self.repair_queue.append(name)

        # 3. 执行修复
        if self.repair_queue:
            log(f"发现 {len(self.repair_queue)} 个组件需要修复")
            self._execute_repairs()
        else:
            log("✅ 所有本地组件运行正常")

        # 4. 检查系统资源
        self._check_system_resources()

    def _execute_repairs(self):
        """执行修复操作"""
        log(f"执行修复操作，共 {len(self.repair_queue)} 个任务...")

        for name in self.repair_queue[:]:
            log(f"🔧 修复 {name}...")
            if self.restart_component(name):
                self.repair_queue.remove(name)
                self.health_stats['repairs'] += 1
            else:
                log(f"❌ {name} 修复失败，将在下次检查时重试", 'ERROR')

    def _check_system_resources(self):
        """检查系统资源"""
        try:
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            log(f"系统资源:")
            log(f"  CPU: {cpu}%")
            log(f"  内存: {memory.percent}%")
            log(f"  磁盘: {disk.percent}%")

            # 资源告警
            if cpu > 90:
                log(f"⚠️ CPU使用率过高: {cpu}%", 'WARNING')
            if memory.percent > 90:
                log(f"⚠️ 内存使用率过高: {memory.percent}%", 'WARNING')
            if disk.percent > 90:
                log(f"⚠️ 磁盘使用率过高: {disk.percent}%", 'WARNING')

        except Exception as e:
            log(f"❌ 检查系统资源失败: {e}", 'ERROR')


def check_single_instance() -> bool:
    """检查是否已有实例在运行"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())

            if psutil.pid_exists(old_pid):
                log(f"❌ 已有实例在运行 (PID: {old_pid})", 'ERROR')
                return False
            else:
                os.remove(PID_FILE)
        except:
            pass

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    return True


def send_restart_signal(component: str):
    """发送重启信号"""
    RESTART_SIGNAL_DIR.mkdir(exist_ok=True)
    signal_file = RESTART_SIGNAL_DIR / f"restart_{component}.json"
    signal_data = {
        'action': 'restart',
        'component': component,
        'timestamp': datetime.now().isoformat()
    }
    with open(signal_file, 'w') as f:
        json.dump(signal_data, f)
    print(f"✅ 已发送重启信号: {component}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='SDF COM 系统健康监测守护进程')
    parser.add_argument('--restart', '-r', metavar='COMPONENT',
                        help='重启指定组件 (tmux_capture_handler/message_processor/feishu_event_server)')
    parser.add_argument('--status', '-s', action='store_true',
                        help='查看所有组件状态')
    parser.add_argument('--daemon', '-d', action='store_true',
                        help='以守护进程模式运行')
    parser.add_argument('--stop', action='store_true',
                        help='停止守护进程')

    args = parser.parse_args()

    # 停止守护进程
    if args.stop:
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                print(f"✅ 已停止守护进程 (PID: {pid})")
                os.remove(PID_FILE)
            except Exception as e:
                print(f"❌ 停止失败: {e}")
        else:
            print("守护进程未运行")
        return

    # 如果指定了重启组件
    if args.restart:
        if args.restart in COMPONENTS:
            send_restart_signal(args.restart)
            return
        else:
            print(f"❌ 未知组件: {args.restart}")
            print(f"可用组件: {', '.join(COMPONENTS.keys())}")
            sys.exit(1)

    # 如果指定了查看状态
    if args.status:
        monitor = SystemMonitor()
        print("=" * 60)
        print("系统状态检查")
        print("=" * 60)
        
        # 检查SSH连接
        print("\nSSH连接状态:")
        if monitor.check_ssh_connection():
            print("  ✅ SSH连接正常")
        else:
            print("  ❌ SSH连接断开")
        
        # 检查组件
        print("\n组件状态:")
        for name in COMPONENTS:
            status = "✅ 运行中" if monitor.check_component(name) else "❌ 未运行"
            print(f"  {name}: {status}")
        return

    # 以守护进程模式运行
    if args.daemon:
        # 后台运行
        pid = os.fork()
        if pid > 0:
            print(f"✅ 守护进程已启动 (PID: {pid})")
            sys.exit(0)
        
        # 子进程继续执行
        os.setsid()
        os.umask(0)
        
        # 第二次fork
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    
    # 启动监测服务
    if not check_single_instance():
        sys.exit(1)

    log("=" * 60)
    log("系统健康监测守护进程启动")
    log("支持SSH连接自动修复")
    log("=" * 60)

    monitor = SystemMonitor()

    def signal_handler(signum, frame):
        log(f"收到停止信号 {signum}，正在停止...")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        while True:
            monitor.check_and_repair()

            # 检查重启信号
            if RESTART_SIGNAL_DIR.exists():
                for signal_file in RESTART_SIGNAL_DIR.glob('restart_*.json'):
                    try:
                        with open(signal_file, 'r') as f:
                            data = json.load(f)
                        component = data.get('component')
                        if component and component in COMPONENTS:
                            log(f"📨 收到重启信号: {component}")
                            monitor.restart_component(component)
                        signal_file.unlink()
                    except Exception as e:
                        log(f"处理信号文件失败: {e}", 'ERROR')
                        try:
                            signal_file.unlink()
                        except:
                            pass

            time.sleep(MONITOR_INTERVAL)

    except KeyboardInterrupt:
        log("健康监测已停止")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


if __name__ == "__main__":
    main()
