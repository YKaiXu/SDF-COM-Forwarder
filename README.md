# SDF COM Forwarder

SDF Community Message Forwarder - 将SDF anonradio聊天室的消息实时转发到飞书（Lark）。

## 功能特性

- **实时消息捕获**: 从tmux pane捕获SDF anonradio聊天消息
- **智能消息解析**: 识别用户聊天、歌曲信息、系统消息
- **自动翻译**: 使用讯飞LLM将英文消息翻译成中文
- **双向通信**: 支持从飞书发送消息到anonradio
- **SSH自动重连**: 系统监控守护进程自动修复SSH连接
- **消息去重**: 基于内容哈希的重复消息过滤

## 系统架构

```
┌─────────────────┐     SSH      ┌─────────────────┐
│   SDF Server    │◄────────────►│  Local Machine  │
│  (anonradio)    │   tmux       │                 │
└────────┬────────┘              └────────┬────────┘
         │                                │
         │ tmux pane                      │ HTTP
         │ capture                        │
         ▼                                ▼
┌─────────────────┐              ┌─────────────────┐
│tmux_capture_    │              │ feishu_event_   │
│  handler.py     │─────────────►│   server.py     │
└─────────────────┘  Unix Socket └─────────────────┘
         │                                │
         │                                │ Feishu API
         ▼                                ▼
┌─────────────────┐              ┌─────────────────┐
│ message_store   │              │   Feishu Bot    │
│   (SQLite)      │              │   (飞书机器人)   │
└─────────────────┘              └─────────────────┘
```

## 核心组件

### 1. tmux_capture_handler.py
- 监控tmux pane内容变化
- 解析聊天消息格式 `[username] message`
- 过滤歌曲信息和系统消息
- 通过Unix Socket发送消息到处理器

### 2. message_processor.py
- 从配置文件加载配置（不再硬编码）
- 接收来自capture_handler的消息
- 调用讯飞LLM进行翻译
- 构建飞书卡片消息
- 发送到飞书群组

### 3. feishu_event_server.py
- 接收飞书事件回调
- 处理用户发送的消息
- 通过SSH转发到anonradio

### 4. system_monitor.py (守护进程)
- 监控所有组件运行状态
- 自动重启崩溃的组件
- **SSH连接自动修复**
- 系统资源监控

## 快速开始

### 1. 配置SSH
```bash
# 确保SSH密钥存在
ls ~/.ssh/sdf_com_mcp

# 配置SSH config
cat > ~/.ssh/config << 'EOF'
Host sdf
    HostName sdf.org
    User your_username
    IdentityFile ~/.ssh/sdf_com_mcp
    StrictHostKeyChecking no
    ServerAliveInterval 30
    ServerAliveCountMax 3
EOF
```

### 2. 配置应用
```bash
# 复制配置模板
cp config.example.json config.json

# 编辑配置，填入你的实际密钥
vim config.json
```

**配置说明**：
- 所有敏感配置（API密钥、App Secret等）都通过 `config.json` 文件加载
- 代码中不再包含任何硬编码的密钥或占位符
- 请勿将 `config.json` 提交到Git仓库（已添加到 .gitignore）

### 3. 启动系统
```bash
# 启动监控守护进程
python3 system_monitor.py --daemon

# 查看状态
python3 system_monitor.py --status

# 查看日志
tail -f /tmp/system_monitor.log
```

## 命令参考

### system_monitor
```bash
# 以守护进程模式启动
python3 system_monitor.py --daemon

# 查看所有组件状态
python3 system_monitor.py --status

# 重启指定组件
python3 system_monitor.py --restart tmux_capture_handler
python3 system_monitor.py --restart message_processor
python3 system_monitor.py --restart feishu_event_server

# 停止守护进程
python3 system_monitor.py --stop
```

### 手动连接SDF
```bash
# 连接到SDF
ssh sdf

# 附加到tmux会话
tmux attach -t sdf-com

# 进入anonradio聊天室
com
j anonradio
```

## 配置文件

### config.json
创建 `config.json` 文件（基于 `config.example.json` 模板）：

```json
{
    "feishu": {
        "app_id": "your_actual_app_id",
        "app_secret": "your_actual_app_secret",
        "encrypt_key": "your_encrypt_key",
        "verification_token": "your_verification_token",
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
        "target_chat_id": "oc_xxx"
    },
    "xunfei": {
        "app_id": "your_xunfei_app_id",
        "api_key": "your_xunfei_api_key",
        "api_secret": "your_xunfei_api_secret"
    },
    "ssh": {
        "host": "sdf.org",
        "user": "your_sdf_username",
        "key_file": "~/.ssh/sdf_com_mcp"
    }
}
```

**安全提示**：
- `config.json` 包含敏感信息，请勿提交到版本控制
- 已添加到 `.gitignore`，不会被Git跟踪
- 如需备份配置，请使用安全的方式存储

## 日志文件

- `/tmp/system_monitor.log` - 系统监控日志
- `/tmp/capture_handler.log` - 消息捕获日志
- `/tmp/message_processor.log` - 消息处理日志
- `/tmp/feishu_event_server.log` - 飞书事件日志

## 数据库

SQLite数据库位于 `/tmp/sdf_com_messages.db`

## 依赖安装

```bash
pip install -r requirements.txt
```

主要依赖：
- psutil - 系统监控
- requests - HTTP请求
- websocket-client - WebSocket连接
- sqlite3 - 数据存储

## 注意事项

1. **SSH连接**: 确保SSH密钥配置正确，system_monitor会自动修复连接
2. **tmux会话**: 系统依赖名为 `sdf-com` 的tmux会话
3. **飞书配置**: 需要在飞书开放平台创建机器人并获取凭证
4. **讯飞翻译**: 需要讯飞开放平台账号和API密钥
5. **配置安全**: 所有敏感信息通过 `config.json` 管理，不要硬编码到代码中

## 故障排查

### SSH连接断开
- system_monitor会自动检测并重连
- 检查 `/tmp/system_monitor.log` 查看重连状态

### 消息未转发
- 检查 `tmux_capture_handler` 是否运行
- 检查消息格式是否匹配 `[username] message`
- 查看 `/tmp/capture_handler.log`

### 翻译失败
- 检查讯飞API配置
- 查看 `/tmp/message_processor.log`

### 配置加载失败
- 确保 `config.json` 文件存在且格式正确
- 检查文件权限
- 查看日志中的错误信息

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！
