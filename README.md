# 海棠文档工坊（Crabapple DocStudio）

[![License](https://img.shields.io/badge/License-AGPL--3.0-C9184A?style=flat-square)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11-C9184A?style=flat-square&logo=python&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3-C9184A?style=flat-square&logo=vue.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-C9184A?style=flat-square&logo=fastapi&logoColor=white)

**海棠文档工坊**是本地/内网部署的智能文档扫描与 AI 处理工作台：把扫描件、照片和 PDF 变成干净、可搜索、可归档的文档。

## 项目定位与适用范围

这是一个 **Python FastAPI + Vue 3 的单机/内网文档处理系统**，不是多租户 SaaS：

- 适合扫描室、档案室、个人/小团队的内网文档批处理；
- 适合需要在本机保存原始文件、不把文档上传到第三方云的用户；
- 适合图片转 PDF、图像清洁、OCR、双层 PDF、PDF 编辑、批量归档；
- 默认单进程、本地磁盘存储，不提供分布式任务队列、对象存储集群、HA、多租户隔离或 SSO；
- 默认不带 TLS，生产环境应放在 Nginx/网关后；
- 当前没有多用户组织/权限模型，只有本地用户与任务隔离；
- OCR/版面效果依赖扫描质量、模型和语言，不能保证 100% 识别率。

## 功能范围

- **图片转 PDF**：批量图片自然排序、旋转、排序、页面尺寸、页码
- **图像清洁**：去噪、去污渍、去装订孔、纠偏、方向矫正、边缘漏光处理
- **OCR**：RapidOCR + ONNX Runtime，支持中英文与 GPU
- **双层 PDF**：原图 + 透明可搜索文字层
- **PDF 编辑**：页面预览、旋转、删除、排序、涂抹清洁、批量处理
- **版面分析**：DocLayout-YOLO 检测标题、正文、表格、图片等区域
- **空白页/页码/PDF 瘦身**
- **任务与历史**：上传、转换、下载记录，按用户隔离
- **本地优先**：数据默认在项目下 `./data`

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、Uvicorn |
| OCR | RapidOCR、ONNX Runtime（CPU/GPU） |
| 版面分析 | DocLayout-YOLO、Ultralytics YOLO、PyTorch |
| PDF | PyMuPDF、ReportLab |
| 图像处理 | OpenCV、NumPy、Pillow |
| 前端 | Vue 3、Vite、Pinia、Vue Router |
| 部署 | Windows / Linux；内网、离线、GPU 可选 |

## 环境要求

| 依赖 | 要求 |
|---|---|
| Python | 3.11+（推荐 3.11） |
| Node.js | 20+（仅构建前端） |
| 操作系统 | Windows 10/11 或 Linux |
| Linux 系统库 | `libgl1`、`libglib2.0-0`、`libgomp1`（发行版包名可能不同） |
| GPU（可选） | NVIDIA + 对应 CUDA 的 PyTorch / onnxruntime-gpu |
| 模型 | 仓库自带 `assets/models/doclayout_yolo_docstructbench_imgsz1024.pt`（约 39MB） |

## 部署步骤

### 1. 获取代码并创建虚拟环境

```bash
git clone https://github.com/xuechong1989/crabapple-docstudio.git
cd crabapple-docstudio

python -m venv .venv
# Windows:
# .venv\Scripts\activate
source .venv/bin/activate
```

### 2. 安装后端依赖

```bash
pip install -r requirements.txt
```

GPU 用户建议先按 PyTorch 官方说明安装对应 CUDA 版本的 `torch` / `torchvision`，再安装 `onnxruntime-gpu`；CPU 用户使用默认的 `onnxruntime`。

### 3. 构建前端

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建产物在 `frontend/dist/`，后端启动时会自动挂载。**仓库不提交 `frontend/dist`**，所以直接 `python start_server.py` 前必须先构建。

### 4. 配置数据目录

默认使用项目根目录的 `./data`，可在 [url.conf](url.conf) 修改：

```ini
DOCSTUDIO_DATA_DIR=./data
DOCSTUDIO_BASE_DIR=./data
DOCSTUDIO_TMP_DIR=./data/tmp
```

生产环境建议改到独立数据盘，例如：

```ini
DOCSTUDIO_DATA_DIR=/data/crabapple-docstudio
DOCSTUDIO_BASE_DIR=/data/crabapple-docstudio
```

目录会在首次启动时自动创建：

```text
data/
├── original/     原始文件
├── target/       转换结果
├── cache/        模型与运行时缓存
├── logs/         日志
├── tmp/          临时文件
├── users/        用户数据
└── users.json    用户索引
```

模型文件已包含在 `assets/models/`。如缺失，可从 [HuggingFace](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench) 下载后放入该目录。

### 5. 启动服务

```bash
# 推荐：直接启动（前台）
python start_server.py
```

或使用便利脚本：

```bash
# Linux
bin/start.sh

# Windows
bin\start.bat
```

默认监听 `0.0.0.0:8000`，浏览器访问：

```text
http://localhost:8000
```

API 文档（FastAPI 默认）：

```text
http://localhost:8000/docs
```

### 6. 首次登录

首次启动会创建 `admin` 账户：

- 设置了 `DOCSTUDIO_ADMIN_PASSWORD` 时使用该口令；
- 未设置时随机生成一次性口令，并打印在启动日志中，请登录后立即修改。

```bash
export DOCSTUDIO_ADMIN_PASSWORD='change-me-strong-password'
python start_server.py
```

旧版 `/api/auth/verify` 兼容登录需要额外配置 `DOCSTUDIO_AUTH_HASH`：

```bash
python scripts/hash_password.py
# 将输出写入环境变量或 url.conf 的 DOCSTUDIO_AUTH_HASH=
```

## 配置说明

主要环境变量 / `url.conf`：

| 配置 | 说明 |
|---|---|
| `DOCSTUDIO_DATA_DIR` | 数据根目录，默认 `./data` |
| `DOCSTUDIO_BASE_DIR` | 数据根目录别名，默认 `./data` |
| `DOCSTUDIO_TMP_DIR` | 临时目录，默认 `./data/tmp` |
| `DOCSTUDIO_USE_GPU` | `1`/`0`，是否启用 GPU |
| `DOCSTUDIO_YOLO_DEVICE` | `cuda:0` 或 `cpu` |
| `DOCSTUDIO_OCR_DEVICE` | `gpu:0` 或 `cpu` |
| `DOCSTUDIO_ADMIN_PASSWORD` | 首次启动 admin 口令 |
| `DOCSTUDIO_AUTH_HASH` | 旧版兼容登录口令哈希 |
| `DOCSTUDIO_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 |
| `DOCSTUDIO_MONGODB_KEY` | 可选 form-in 云盘加密密钥；默认关闭 |

GPU 示例：

```bash
export DOCSTUDIO_USE_GPU=1
export DOCSTUDIO_YOLO_DEVICE=cuda:0
export DOCSTUDIO_OCR_DEVICE=gpu:0
```

CPU 环境：

```bash
export DOCSTUDIO_USE_GPU=0
export DOCSTUDIO_YOLO_DEVICE=cpu
export DOCSTUDIO_OCR_DEVICE=cpu
```

CORS 默认只允许 localhost/127.0.0.1 的 5173/8000；通过域名访问时：

```ini
DOCSTUDIO_CORS_ORIGINS=https://docstudio.example.com
```

## 使用流程

1. 启动服务并登录。
2. 选择「图片转 PDF」「编辑 PDF」「转双层 PDF」等功能。
3. 上传图片/PDF，按界面步骤清洁、OCR、排序、加页码、去空白页。
4. 预览结果，下载单个 PDF 或批量 ZIP。
5. 在「转换记录/上传记录」查看历史；数据默认保存在本机 `data/`。

主要能力对应关系：

| 需求 | 使用模块 |
|---|---|
| 扫描件合 PDF | 图片转 PDF |
| 去污渍/纠偏/去孔 | 图像清洁 |
| 扫描件可搜索 | OCR / 双层 PDF |
| 已有 PDF 整理 | 编辑 PDF |
| 批量归档 | 批量任务 + 下载记录 |

## 生产部署

Linux systemd 示例：

```ini
[Unit]
Description=Crabapple DocStudio
After=network.target

[Service]
WorkingDirectory=/opt/crabapple-docstudio
ExecStart=/opt/crabapple-docstudio/.venv/bin/python start_server.py
Restart=on-failure
User=crabapple
Group=crabapple

[Install]
WantedBy=multi-user.target
```

Nginx 反向代理、离线依赖、GPU、数据目录与备份说明见 [docs/DEPLOY.md](docs/DEPLOY.md)。

生产注意：

- 使用独立数据盘，定期备份整个 `data/`；
- 通过 Nginx/网关终止 TLS，限制上传大小（扫描件可能很大）；
- 不要直接把 `8000` 暴露到公网；
- `DOCSTUDIO_ADMIN_PASSWORD` 首次启动后立即改强口令；
- 定期清理 `tmp/` 与旧任务；
- 升级前备份 `data/` 和 `url.conf`，保留 `frontend/dist` 或重新构建。

## 测试与检查

```bash
pip install -e ".[dev]"
ruff check backend scripts tests --select E9,F63,F7,F82
pytest
```

当前测试结果：163 passed / 52 skipped（GPU、样张等条件测试会跳过）。前端：

```bash
cd frontend
npm ci
npm run build
```

## 适用与不适用

**适合：**

- 内网/单机文档扫描与归档；
- 需要本地 OCR、双层 PDF、批量清洁的团队；
- 希望自己掌控模型与数据的用户。

**不适合：**

- 多租户 SaaS、超大并发、分布式任务集群；
- 需要开箱即用的 SSO/RBAC/审计合规平台；
- 不能接受 AGPL-3.0 网络服务源码义务的场景；
- 期望对所有低质量扫描件 100% 准确识别的场景。

## 许可证与第三方组件

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）**，见 [LICENSE](LICENSE)。

这意味着：

- 可以自由使用、修改、分发；
- 如果修改后通过网络向用户提供服务，必须按 AGPL-3.0 向这些用户提供对应完整源代码；
- 分发时必须保留许可证与版权声明。

第三方组件（PyMuPDF、Ultralytics、DocLayout-YOLO、RapidOCR、Noto Serif SC 等）的许可证与署名见 [NOTICE](NOTICE)。其中 PyMuPDF、Ultralytics、DocLayout-YOLO 为 AGPL-3.0，与本项目整体许可证兼容。

## 参与贡献

欢迎 Issue / Pull Request，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
