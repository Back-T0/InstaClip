"""InstaClip - 实时共享剪贴板，多设备间即时同步文本与图片。

单文件服务器，HTTP + WebSocket 共用同一端口。

Usage:
    python instaclip.py [--host HOST] [--port PORT]
    pyinstaller --onefile instaclip.py
"""

import argparse
import asyncio
import json
import logging

import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内嵌前端资源
# ---------------------------------------------------------------------------

CSS = """\
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #f2f2f7;
  --card-bg: #ffffff;
  --text: #1c1c1e;
  --text-secondary: #8e8e93;
  --textarea-bg: #ffffff;
  --textarea-border: #d1d1d6;
  --textarea-text: #1c1c1e;
  --accent: #007aff;
  --green: #34c759;
  --green-bg: rgba(52, 199, 89, 0.12);
  --red: #ff3b30;
  --red-bg: rgba(255, 59, 48, 0.12);
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
  color-scheme: light dark;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #000000;
    --card-bg: #1c1c1e;
    --text: #f2f2f7;
    --text-secondary: #98989d;
    --textarea-bg: #2c2c2e;
    --textarea-border: #3a3a3c;
    --textarea-text: #f2f2f7;
    --accent: #0a84ff;
    --green: #30d158;
    --green-bg: rgba(48, 209, 88, 0.15);
    --red: #ff453a;
    --red-bg: rgba(255, 69, 58, 0.15);
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
  background-color: var(--bg);
  color: var(--text);
  padding: 16px;
  -webkit-font-smoothing: antialiased;
}

#status {
  width: 100%;
  padding: 8px 16px;
  margin-bottom: 12px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  text-align: center;
  transition: all 0.2s ease;
}
#status.connected { background-color: var(--green-bg); color: var(--green); }
#status.disconnected { background-color: var(--red-bg); color: var(--red); }

#image-preview {
  width: 100%;
  margin-bottom: 12px;
  display: none;
}
#image-preview img {
  width: 100%;
  height: auto;
  border-radius: 10px;
  box-shadow: var(--shadow);
}

textarea {
  width: 100%;
  height: calc(100vh - 180px);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
  font-size: 16px;
  padding: 14px;
  border: 1px solid var(--textarea-border);
  border-radius: 12px;
  background-color: var(--textarea-bg);
  color: var(--textarea-text);
  resize: none;
  outline: none;
  transition: border-color 0.2s ease;
  box-shadow: var(--shadow);
}
textarea:focus {
  border-color: var(--accent);
}

.button-container {
  margin-top: 12px;
  display: flex;
  gap: 10px;
}
button {
  flex: 1;
  padding: 12px;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
  font-size: 15px;
  font-weight: 600;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  color: white;
  transition: all 0.15s ease;
  -webkit-tap-highlight-color: transparent;
}
button:active { transform: scale(0.97); }
button.open { background-color: var(--accent); }
button.open:hover { opacity: 0.85; }
button.copy { background-color: var(--green); }
button.copy:hover { opacity: 0.85; }
button.clear { background-color: var(--red); }
button.clear:hover { opacity: 0.85; }

input[type="file"] { display: none; }
"""

JS = """\
const IMAGE_MAX_SIZE = 1920;
const IMAGE_QUALITY = 0.8;
const COPY_FEEDBACK_DURATION = 3000;
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;

const textarea = document.getElementById('shared-text');
const imagePreview = document.getElementById('image-preview');
const statusEl = document.getElementById('status');
const copyButton = document.getElementById('copy-button');
const clearButton = document.getElementById('clear-button');
const openButton = document.getElementById('open-button');
const fileInput = document.getElementById('file-input');

let socket = null;
let isProgrammaticChange = false;

function setStatus(connected, clients) {
  if (connected) {
    statusEl.className = 'connected';
    statusEl.textContent = `Connected (${clients})`;
  } else {
    statusEl.className = 'disconnected';
    statusEl.textContent = 'Disconnected';
  }
}

function compressImage(file, callback) {
  const img = new Image();
  img.onload = () => {
    let w = img.width, h = img.height;
    if (w > IMAGE_MAX_SIZE || h > IMAGE_MAX_SIZE) {
      const ratio = Math.min(IMAGE_MAX_SIZE / w, IMAGE_MAX_SIZE / h);
      w = Math.round(w * ratio);
      h = Math.round(h * ratio);
    }
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
    callback(canvas.toDataURL('image/jpeg', IMAGE_QUALITY));
  };
  img.src = URL.createObjectURL(file);
}

function setImage(base64) {
  imagePreview.innerHTML = '';
  if (base64) {
    const img = document.createElement('img');
    img.src = base64;
    img.alt = 'Shared image';
    imagePreview.appendChild(img);
    imagePreview.style.display = 'block';
  } else {
    imagePreview.style.display = 'none';
  }
}

function applyState(data) {
  isProgrammaticChange = true;
  textarea.value = data.text || '';
  setImage(data.image || '');
  isProgrammaticChange = false;
  if (data.clients !== undefined) {
    setStatus(true, data.clients);
  }
}

function sendText() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ text: textarea.value }));
  }
}

function sendImage(base64) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ image: base64 }));
  }
}

textarea.addEventListener('input', () => {
  if (isProgrammaticChange) return;
  sendText();
});

const wsUrl = `ws://${location.host}/ws`;
let reconnectAttempts = 0;

function connect() {
  socket = new WebSocket(wsUrl);
  socket.addEventListener('open', () => {
    textarea.readOnly = false;
    reconnectAttempts = 0;
  });
  socket.addEventListener('message', (event) => {
    applyState(JSON.parse(event.data));
  });
  socket.addEventListener('close', () => {
    textarea.readOnly = true;
    setStatus(false, 0);
    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts),
      RECONNECT_MAX_DELAY
    );
    reconnectAttempts++;
    setTimeout(connect, delay);
  });
}
connect();

async function copyTextIosSafe(text) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:absolute;opacity:0;height:0;width:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, 99999);
  try {
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    document.body.removeChild(ta);
    return false;
  }
}

copyButton.addEventListener('click', async () => {
  if (await copyTextIosSafe(textarea.value)) {
    copyButton.textContent = 'Copied!';
    setTimeout(() => { copyButton.textContent = 'Copy'; }, COPY_FEEDBACK_DURATION);
  }
});

clearButton.addEventListener('click', () => {
  isProgrammaticChange = true;
  textarea.value = '';
  setImage('');
  isProgrammaticChange = false;
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ text: '', image: '' }));
  }
});

openButton.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.type?.startsWith('image/')) {
    compressImage(file, (base64) => { setImage(base64); sendImage(base64); });
  } else {
    const reader = new FileReader();
    reader.onload = (e) => {
      isProgrammaticChange = true;
      textarea.value = e.target.result;
      isProgrammaticChange = false;
      sendText();
    };
    reader.readAsText(file);
  }
  fileInput.value = '';
});

document.addEventListener('paste', (event) => {
  const items = event.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.includes('image')) {
      event.preventDefault();
      const file = item.getAsFile();
      if (file) compressImage(file, (base64) => { setImage(base64); sendImage(base64); });
      return;
    }
  }
});
"""

HTML = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>InstaClip</title>
  <style>{CSS}</style>
</head>
<body>
  <div id="status" class="disconnected">Disconnected</div>
  <div id="image-preview"></div>
  <textarea id="shared-text"></textarea>
  <div class="button-container">
    <button id="open-button" class="open">Open</button>
    <button id="copy-button" class="copy">Copy</button>
    <button id="clear-button" class="clear">Clear</button>
  </div>
  <input type="file" id="file-input" accept=".txt,.csv,.md,.html,.xml,.json,.yaml,.yml,.log,.py,.js,.sh,.png,.jpg,.jpeg,.gif,.webp,image/*,text/*">
  <script>{JS}</script>
</body>
</html>
"""

HTML_BYTES = HTML.encode("utf-8")

# ---------------------------------------------------------------------------
# 共享状态
# ---------------------------------------------------------------------------

state: dict[str, str] = {"text": "", "image": ""}
connected_clients: set[ServerConnection] = set()


async def broadcast() -> None:
    payload = json.dumps({**state, "clients": len(connected_clients)})
    for client in connected_clients.copy():
        try:
            await client.send(payload)
        except Exception:
            connected_clients.discard(client)


# ---------------------------------------------------------------------------
# 请求处理（HTTP + WebSocket 同端口）
# ---------------------------------------------------------------------------

async def handler(ws: ServerConnection):
    # 非 /ws 路径的普通 HTTP 请求由 process_request 处理并返回 None
    # WebSocket 升级请求走到这里
    connected_clients.add(ws)
    logger.info("Client connected. Total: %d", len(connected_clients))
    try:
        await ws.send(json.dumps({**state, "clients": len(connected_clients)}))
        await broadcast()
        async for message in ws:
            data = json.loads(message)
            if "text" in data:
                state["text"] = data["text"]
            if "image" in data:
                state["image"] = data["image"]
            await broadcast()
    except websockets.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(ws)
        logger.info("Client disconnected. Total: %d", len(connected_clients))
        await broadcast()


def process_request(connection, request):
    """拦截 HTTP 请求，非 WebSocket 路径直接返回 HTML 页面。"""
    if request.path == "/ws":
        return None  # 放行，走 WebSocket 握手
    headers = Headers([
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(HTML_BYTES))),
    ])
    return Response(200, "OK", headers, HTML_BYTES)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def main(host: str, port: int) -> None:
    async with serve(handler, host, port, process_request=process_request):
        logger.info("running on http://%s:%d", host, port)
        await asyncio.Future()  # 永久运行


def cli() -> None:
    parser = argparse.ArgumentParser(description="实时共享剪贴板")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="端口 (default: 8080)")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))


if __name__ == "__main__":
    cli()
