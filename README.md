# InstaClip

实时共享剪贴板 —— 多设备间即时同步文本与图片。

单个 Python 文件，HTTP + WebSocket 共用同一端口，零外部静态文件。

## 功能

- **文本同步** — 任一设备输入内容，所有设备实时显示
- **图片共享** — 剪贴板粘贴或打开图片文件，自动压缩后同步（PNG/JPG/GIF/WebP）
- **文件打开** — 加载本地文本文件并同步（txt/csv/md/html/json/yaml/py/js 等）
- **剪贴板复制** — 一键复制文本，兼容 iOS Safari
- **清空** — 一键清空所有设备的文本和图片
- **连接状态** — 实时显示在线设备数，断线自动重连（指数退避，最大 30s）

## 快速开始

```bash
# 安装依赖并运行（推荐 uv）
uv run python instaclip.py

# 或 pip
pip install websockets
python instaclip.py
```

浏览器打开 `http://localhost:8080`，多台设备访问同一地址即可同步。

局域网内其他设备（手机、平板等）访问启动时输出的局域网地址（如 `http://192.168.x.x:8080`）即可同步。

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 绑定地址 |
| `--port` | `8080` | 端口号 |

## 打包为单文件 exe

```bash
uv pip install pyinstaller
uv run pyinstaller --onefile instaclip.py
```

生成 `dist/instaclip.exe`，无需 Python 环境即可运行：

```bash
instaclip.exe --port 8080
```

## 架构

```
浏览器 A ──┐
浏览器 B ──┼── HTTP + WebSocket (同端口) ──> instaclip.py
浏览器 C ──┘                                      │
                                          内存状态 {text, image}
                                          广播给所有已连接客户端
```

- **后端** — Python asyncio + websockets
- **前端** — 原生 HTML/CSS/JS，内嵌于 Python 文件
- **通信** — HTTP 和 WebSocket 共用同一端口（websockets 的 `process_request`）
- **存储** — 纯内存，重启清空

## 项目结构

```
├── instaclip.py    # 完整应用（单文件，含内嵌前端）
├── pyproject.toml   # 项目元数据与依赖
└── .gitignore
```
