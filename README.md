# ear-tag-reader · 猪耳标编号识别系统

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg)](https://www.python.org/)

一套跑在局域网内的轻量级**猪耳标编号识别**服务：手机浏览器打开摄像头对准耳标拍照，后端调用本地 LM Studio 上的视觉大模型读号，把 8 位编号返回给前端，并自动落库到 CSV 便于后续导出。

> 零云端依赖 —— 图片不出内网，模型本地跑，适合养殖场、检疫点等对数据隐私有要求的场景。

---

## 目录

- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 接口](#api-接口)
- [识别流程详解](#识别流程详解)
- [数据记录](#数据记录)
- [配置项](#配置项)
- [常见问题](#常见问题)
- [已知限制](#已知限制)

---

## 核心功能

| 功能 | 说明 |
|------|------|
| 摄像头拍照识别 | 调用浏览器 `getUserMedia`，优先后置摄像头，拍照后直接上传识别 |
| 图片上传识别 | 从相册/文件选择图片识别，支持 PC 端调试 |
| 本地大模型读号 | 走 OpenAI 兼容协议调用 LM Studio，视觉模型直接输出编号，无需传统 OCR |
| 推理链兜底提取 | 兼容推理型模型把答案写在 `reasoning_content` 的情况，双通道提取编号 |
| 自动记录留痕 | 每次识别成功追加一条 CSV（时间戳、编号、耗时、来源），可一键下载 |
| 移动端优先 UI | 单文件深色界面，视频比例 4:3，含对位虚线、快门白闪、加载动画 |

---

## 技术栈

| 层次 | 选型 |
|------|------|
| 后端框架 | Python 3.12 + FastAPI + Uvicorn |
| 视觉模型 | `qwen/qwen3-vl-2b`（经 LM Studio 本地部署，OpenAI 兼容接口） |
| 模型调用 | `openai` SDK（`base_url` 指向 `http://127.0.0.1:1234/v1`） |
| 图像预处理 | Pillow（缩放 + 格式归一） |
| 前端 | 原生 HTML + CSS + JavaScript，浏览器 Camera API，无构建步骤 |
| 持久化 | 追加式 CSV 文件，不引入数据库 |

---

## 系统架构

```
手机 / PC 浏览器
   │  ① getUserMedia 取流 → canvas 抓帧 → JPEG Blob
   ▼
POST /api/recognize  (multipart/form-data, 字段 file)
   │
   ▼
FastAPI  main.py
   ├─ ② Pillow 预处理：长边 >1024 等比缩小 → RGBA 转 RGB → JPEG(q=85) → Base64
   ├─ ③ openai SDK → LM Studio (127.0.0.1:1234/v1) → qwen/qwen3-vl-2b
   ├─ ④ 正则提取 8 位编号（content 优先，reasoning_content 兜底）
   ├─ ⑤ 成功则 append 到 ear_tag_records.csv
   └─ ⑥ 返回 { code, data: { text, cost_ms, source } }
   ▼
前端渲染编号 + 耗时，并显示 CSV 下载入口
```

请求是**同步阻塞**的：FastAPI 的 `async def` 里直接调用了同步的模型 SDK，单次耗时从本地测试看约 **1～15 秒**（见下方 CSV 样本），因此并发能力有限，适合单人单手操作的使用节奏。

---

## 快速开始

### 0. 克隆仓库

```bash
git clone https://github.com/<your-username>/ear-tag-reader.git
cd ear-tag-reader
```

### 环境要求

- Python **3.12+**
- [LM Studio](https://lmstudio.ai/) 已安装，能加载视觉模型

### 1. 创建虚拟环境

```bash
python -m venv .venv
```

### 2. 安装依赖

```bash
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
```

### 3. 启动 LM Studio 服务

1. 打开 LM Studio → 搜索并下载 `qwen/qwen3-vl-2b`（或任意具备视觉能力的模型）
2. 在 **Developer / Local Server** 面板加载该模型
3. 点击 **Start Server**，确认监听 `http://127.0.0.1:1234`

> 换用其他模型时，需同步修改 `main.py` 中的 `model=` 字段（见[配置项](#配置项)）。

### 4. 启动本服务

```bash
.venv\Scripts\python.exe main.py
```

看到下面这行即启动成功：

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

服务以 `reload=True` 运行，改完代码自动重载（生产使用请关闭）。

### 5. 访问使用

| 场景 | 地址 | 摄像头可用性 |
|------|------|--------------|
| 本机调试 | `http://localhost:8000` | ✅ 可用 |
| 局域网手机 | `http://<电脑IP>:8000` | ❌ 浏览器仅在 HTTPS / localhost 下放行摄像头，此方式只能**上传图片** |

要在手机上用摄像头，需为服务配上 HTTPS（自签证书 + 浏览器手动信任，或用内网穿透工具颁发证书）。详见[常见问题](#常见问题)。

---

## 项目结构

```
ear-tag-reader/
├── main.py                 # FastAPI 应用：路由、模型调用、CSV 落库
├── static/
│   └── index.html          # 单文件前端：摄像头、拍照、上传、结果展示
├── ear_tag_records.csv     # 运行时自动生成的识别记录（已被 .gitignore 忽略）
├── ear_tag_records.example.csv  # 记录文件格式示例（假数据）
├── requirements.txt        # 运行依赖
├── pyproject.toml          # 项目元信息（名称/版本/许可/Python 版本）
├── LICENSE                 # Apache License 2.0 全文
├── README.md               # 本文档
├── .python-version         # 3.12
├── .gitignore              # 忽略 __pycache__、.venv、*.csv
└── .venv/                  # 本地虚拟环境（不入库）
```

---

## API 接口

### `GET /` — 前端页面

返回 `static/index.html` 的内容，`Content-Type: text/html`。

### `GET /api/health` — 健康检查

```json
{ "status": "ok" }
```

### `POST /api/recognize` — 上传图片识别

**请求**：`multipart/form-data`，文件字段名固定为 `file`。

```bash
curl -X POST http://localhost:8000/api/recognize -F "file=@ear_tag.jpg"
```

**成功响应**（HTTP 200）：

```json
{
  "code": 0,
  "data": {
    "text": "BB134C83",
    "cost_ms": 4545,
    "source": "vlm"
  }
}
```

> 模型调用失败或未提取到编号时，`code` 仍为 `0`，但 `text` 为空字符串。前端需以 `text` 是否为空判断识别是否成功。

**失败响应**（HTTP 500）：

```json
{ "code": -1, "message": "识别失败: <异常信息>" }
```

### `GET /api/download` — 下载识别记录

- 记录存在：返回 `text/csv` 附件，文件名 `ear_tag_records.csv`
- 记录不存在：HTTP 404，`{ "code": -1, "message": "暂无记录" }`

### 静态资源

`app.mount("/static", ...)` 将 `static/` 目录挂载在 `/static` 路径下；启动时若目录缺失会自动创建。

---

## 识别流程详解

### 1. 前端抓帧

```
getUserMedia({ facingMode: 'environment', width: 1280, height: 960, audio: false })
  → <video> 实时预览
  → canvas.drawImage(video) 按原始分辨率抓帧
  → canvas.toBlob(..., 'image/jpeg', 0.9) 生成上传 Blob
```

拍照瞬间叠加 150ms 白色闪光反馈；界面上有一条虚线对位线提示"对准耳标，保持清晰"。

### 2. 后端图像预处理

| 步骤 | 处理内容 | 目的 |
|------|----------|------|
| 等比缩放 | 长边超过 **1024px** 时按 `Image.LANCZOS` 缩小 | 显著降低视觉 token 消耗与推理耗时 |
| 通道归一 | `RGBA` → `RGB` | 避免带透明通道的图片编码失败 |
| 重编码 | JPEG，`quality=85` | 压缩体积，统一为模型友好的格式 |
| 编码 | Base64 → `data:image/jpeg;base64,...` | 走 OpenAI 多模态消息格式 |

### 3. 模型调用参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `model` | `qwen/qwen3-vl-2b` | 需与 LM Studio 中已加载模型一致 |
| `temperature` | `0.0` | 确定性输出，减少编号乱编 |
| `max_tokens` | `200` | 只需返回一个短编号 |
| `timeout` | `120` 秒 | 冷启动 / 低配机器留足余量 |

提示词要求模型输出 **8 位大写字母与数字组合**（示例 `BB134C83`），并强调"只回复这 8 个字符，不要其他内容"。

### 4. 编号提取策略（关键设计）

模型可能把答案放在 `content`，也可能放在推理型模型的 `reasoning_content` 里（参考代码中出现的 Gemma 系列推理模型行为）。因此采用**双通道提取**：

1. **`content` 通道**：整体转大写后匹配 `(?=[A-Z]*[0-9])[A-Z0-9]{4,}` —— 前瞻断言强制结果中**至少包含一个数字**，从而排除 `THINKING`、`RESULT` 这类纯字母词。
2. **`reasoning_content` 通道**（前一步失败时）：先尝试定位 `Result Formulation` / `number is` 等关键词附近的值，再退化为同样的正则全文扫描。
3. 两通道均无命中则返回 `None`，后端不写 CSV，前端提示重试。

同时记录 `finish_reason`、`usage` 和推理链末尾 200 字，便于排查"模型答了但没提取到"的情况。

---

## 数据记录

每次**识别成功**追加一行到 `ear_tag_records.csv`（UTF-8，带表头，文件不存在时自动创建）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | ISO 8601 | 服务端写入时间，如 `2026-07-24T11:19:21.855457` |
| `ear_tag` | string | 提取到的编号，如 `BB134C83` |
| `cost_ms` | int | 从收到请求到模型返回的毫秒耗时 |
| `source` | string | `upload` / `camera` |

示例内容（见 `ear_tag_records.example.csv`）：

```csv
timestamp,ear_tag,cost_ms,source
2026-01-01T09:00:00.000000,BB0000A1,14305,upload
2026-01-01T09:01:12.000000,BB0000A2,1490,camera
2026-01-01T09:03:45.000000,BB0000A1,4545,upload
```

实测性能特征：**首次请求（模型冷启动）约 14～15 秒，模型热起来后降至 1～5 秒**，差异主要来自模型权重加载与 KV Cache 预热。

> 记录文件已被 `.gitignore` 的 `*.csv` 规则忽略，本地产生的业务数据不会误提交；仅 `ear_tag_records.example.csv` 作为格式样例入库。

---

## 配置项

均集中在 `main.py` 顶部，改完自动重载：

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `LM_STUDIO_URL` | 第 40 行 | `http://127.0.0.1:1234/v1` | LM Studio 服务地址 |
| `model` | 第 64 行 | `qwen/qwen3-vl-2b` | 视觉模型 ID |
| `max_size` | 第 50 行 | `1024` | 预处理长边上限，调小更快、调大更准 |
| `HISTORY_CSV` | 第 26 行 | `ear_tag_records.csv` | 记录文件路径 |
| 端口 | 第 184 行 | `8000` | Uvicorn 监听端口 |
| `reload` | 第 184 行 | `True` | 开发热重载 |

`openai` 客户端在每次请求内部创建，`api_key` 传占位值 `"lm-studio"`（LM Studio 不校验）。

---

## 常见问题

**Q：页面提示"摄像头访问失败"？**
A：三种原因，按顺序排查 —— ① 浏览器未授权摄像头；② 通过 `http://局域网IP` 访问（非安全上下文，浏览器直接拒绝）；③ 设备被其他应用占用。PC 上 `localhost` 一定可用。

**Q：识别结果为空，日志里有模型输出？**
A：看日志 `大模型返回: '...'` 那一行。若模型返回了中文说明或多位噪音，说明它没遵守"只回复编号"的约束——换更强模型、或把 `temperature` 保持 0、或收紧提示词。若答案在 `reasoning_content` 里却没提到，检查正则是否被 `\n`、`-` 等符号隔断。

**Q：第一次识别特别慢？**
A：LM Studio 模型冷启动，属于正常现象。跑一两次后耗时稳定在数秒内。可让模型常驻显存（不自动卸载）来避免。

**Q：想让手机用摄像头？**
A：给服务套一层 HTTPS。最省事的做法是用内网穿透工具（自动颁发受信证书）反代到 8000 端口。

**Q：能识别其他编号格式吗？**
A：当前正则按"4 位以上、含数字"的字母数字串匹配，并靠提示词约束 8 位。若耳标是纯数字或含连字符，需要同时调整提示词与正则。

---

## 已知限制

| 项目 | 现状 | 影响 |
|------|------|------|
| `source` 字段 | 前端拍照时传入固定文件名 `ear_tag.jpg`，后端按 `file.filename` 是否为空判断来源，导致**拍照也记成 `upload`** | 统计数据无法区分拍照/上传 |
| 空结果提示 | 前端读取 `json.data.all_texts`，但后端从未返回该字段 | 空结果时总是走"未对准耳标"文案 |
| 并发 | 同步调用模型，无队列、无并发控制 | 多人同时用会互相排队 |
| 安全 | 无鉴权、无 CORS 配置、无上传大小/类型校验 | 仅适合内网可信环境 |
| 记录清理 | CSV 只追加，无分页/轮转 | 长期运行需手工归档 |
| 前端状态 | 上传图片后若摄像头已开，会被强制关闭 | 属交互取舍，非缺陷 |

### 可演进方向

- 引入 `asyncio.to_thread` 或线程池，避免阻塞事件循环
- 用 SQLite 替换 CSV，支持按时间/编号查询与去重
- 加一个 `/api/records` 分页接口，前端做列表与搜索
- 前置轻量 OCR 或检测框裁剪，把耳标区域先截出来再喂大模型，提升小字号准确率
- 多帧投票（连拍 3 张取众数）提升稳定性

---

## 许可

本项目基于 **Apache License 2.0** 发布，全文见 [LICENSE](LICENSE)。

```
Copyright 2026 ztf3 Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

简要说明：

| 你可以 | 你必须 |
|--------|--------|
| 商用、修改、分发、私用、专利授权 | 保留版权与许可声明、附上 LICENSE 副本、标注修改过的文件 |

该协议**不提供任何担保**，作者不对使用后果承担责任；同时明确授予贡献者的专利许可，适合需要对外开源或商业集成的场景。

