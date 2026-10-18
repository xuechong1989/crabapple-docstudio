# 海棠文档工坊（Crabapple DocStudio）

[![License](https://img.shields.io/badge/License-AGPL--3.0-C9184A?style=flat-square)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11-C9184A?style=flat-square&logo=python&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3-C9184A?style=flat-square&logo=vue.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-C9184A?style=flat-square&logo=fastapi&logoColor=white)

**海棠文档工坊**是一个本地部署的智能文档扫描与 AI 处理工作台：把扫描件、照片和 PDF 变成干净、可搜索、可归档的文档。

## 功能

- **图片转 PDF**：批量图片按自然顺序合成 PDF，支持旋转、排序、页面尺寸与页码
- **图像清洁**：去噪、去污渍、去装订孔、纠偏、方向矫正、边缘漏光处理
- **OCR 识别**：RapidOCR + ONNX Runtime，支持中英文与 GPU 加速
- **双层 PDF**：原图 + 透明可搜索文字层，保留版面又支持检索/复制
- **PDF 编辑**：页面预览、旋转、删除、排序、涂抹清洁、批量处理
- **版面分析**：DocLayout-YOLO 检测标题、正文、表格、图片等区域
- **去除空白页 / 添加页码 / PDF 瘦身**：面向批量归档的收尾处理
- **任务与历史**：上传、转换、下载记录，按用户隔离
- **本地优先**：数据保存在本机 `./data`，不依赖云服务

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.11、FastAPI、Uvicorn |
| OCR | RapidOCR、ONNX Runtime（CPU/GPU） |
| 版面分析 | DocLayout-YOLO、Ultralytics YOLO、PyTorch |
| PDF | PyMuPDF、ReportLab |
| 图像处理 | OpenCV、NumPy、Pillow |
| 前端 | Vue 3、Vite、Pinia、Vue Router |
| 部署 | Windows / Linux，支持完全离线、内网与 GPU |

## 目录结构

```
crabapple-docstudio/
├── backend/              FastAPI 应用、清洁引擎、OCR、PDF、任务与用户
├── frontend/             Vue 3 + Vite 前端
├── assets/models/        DocLayout-YOLO 版面检测模型（约 39 MB）
├── bin/                  启动、停止、构建脚本
├── scripts/              发版、测试、口令哈希等工程脚本
├── tests/                pytest 测试
├── docs/                 部署与开发文档
├── url.conf              运行时路径配置（默认 ./data）
├── pyproject.toml
└── requirements.txt
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+（仅构建前端需要）
- Windows 10/11 或 Linux

### 1. 安装后端依赖

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
```

GPU 用户请按 PyTorch 官方说明安装对应 CUDA 版本的 `torch` / `torchvision`，再安装 `onnxruntime-gpu`。

### 2. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

构建产物在 `frontend/dist/`，后端启动时会自动挂载。

### 3. 配置数据目录

默认使用项目根目录下的 `./data`，可在 [url.conf](url.conf) 中修改：

```ini
DOCSTUDIO_DATA_DIR=./data
DOCSTUDIO_BASE_DIR=./data
```

模型文件已包含在 `assets/models/doclayout_yolo_docstructbench_imgsz1024.pt`。如缺失，可从 [HuggingFace](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench) 下载后放入该目录。

### 4. 启动

```bash
python start_server.py
# 或 Linux: bin/start.sh
# 或 Windows: bin/start.bat
```

浏览器访问 `http://localhost:8000`。

首次启动会创建 `admin` 账户：

- 设置了 `DOCSTUDIO_ADMIN_PASSWORD` 时使用该口令；
- 未设置时随机生成一次性口令，并打印在启动日志中，请登录后立即修改。

旧版 `/api/auth/verify` 兼容登录需要额外配置 `DOCSTUDIO_AUTH_HASH`：

```bash
python scripts/hash_password.py
# 将输出写入环境变量或 url.conf 的 DOCSTUDIO_AUTH_HASH=
```

## 配置

主要环境变量 / `url.conf` 配置项：

| 配置 | 说明 |
| --- | --- |
| `DOCSTUDIO_DATA_DIR` | 数据根目录，默认 `./data` |
| `DOCSTUDIO_TMP_DIR` | 临时目录，默认 `./data/tmp` |
| `DOCSTUDIO_USE_GPU` | `1`/`0`，是否启用 GPU |
| `DOCSTUDIO_YOLO_DEVICE` | `cuda:0` 或 `cpu` |
| `DOCSTUDIO_OCR_DEVICE` | `gpu:0` 或 `cpu` |
| `DOCSTUDIO_ADMIN_PASSWORD` | 首次启动的 admin 口令 |
| `DOCSTUDIO_AUTH_HASH` | 旧版兼容登录口令哈希 |
| `DOCSTUDIO_CORS_ORIGINS` | 允许的跨域来源，逗号分隔 |

完整配置见 [url.conf](url.conf) 与 [backend/config.py](backend/config.py)。

## 测试与检查

```bash
pip install -e ".[dev]"
ruff check backend scripts tests
pytest
```

前端：

```bash
cd frontend
npm run build
```

## 部署

Linux 内网、离线依赖、GPU、反向代理与数据目录说明见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 许可证

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）**，见 [LICENSE](LICENSE)。

这意味着：

- 你可以自由使用、修改、分发本项目；
- 如果你修改后通过网络向用户提供服务，必须按 AGPL-3.0 向这些用户提供对应的完整源代码；
- 分发时必须保留许可证与版权声明。

第三方组件（PyMuPDF、Ultralytics、DocLayout-YOLO、RapidOCR、Noto Serif SC 等）的许可证与署名见 [NOTICE](NOTICE)。

## 参与贡献

欢迎提交 Issue / Pull Request，请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
