# 部署说明

## 1. 环境要求

- Python 3.11+
- Node.js 20+（构建前端）
- Windows 10/11 或 Linux
- GPU 可选：NVIDIA 显卡 + 对应 CUDA 版本的 PyTorch / onnxruntime-gpu

Linux 需要系统库：`libgl1`、`libglib2.0-0`、`libgomp1`（不同发行版包名略有差异）。

## 2. 目录与数据

默认数据目录为项目根目录的 `./data`，可在 `url.conf` 中修改为独立数据盘：

```ini
DOCSTUDIO_DATA_DIR=/data/crabapple-docstudio
DOCSTUDIO_BASE_DIR=/data/crabapple-docstudio
```

首次启动会自动创建：

```
data/
├── original/     原始文件
├── target/       转换结果
├── cache/        模型与运行时缓存
├── logs/         日志
├── tmp/          临时文件
└── users.json    用户数据
```

升级前请备份整个数据目录。

## 3. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..
```

离线环境可在有网机器上执行 `pip download -r requirements.txt -d wheels`，再把 `wheels/` 与源码一起拷贝到目标机，使用 `pip install --no-index --find-links=wheels -r requirements.txt`。

## 4. 启动

```bash
python start_server.py
```

默认监听 `0.0.0.0:8000`。生产环境建议用 systemd 托管：

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

## 5. 反向代理

Nginx 示例：

```nginx
server {
    listen 80;
    server_name docstudio.example.com;
    client_max_body_size 1024m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;
    }
}
```

如通过域名访问，在 `url.conf` 中设置：

```ini
DOCSTUDIO_CORS_ORIGINS=http://docstudio.example.com
```

## 6. GPU

```bash
export DOCSTUDIO_USE_GPU=1
export DOCSTUDIO_YOLO_DEVICE=cuda:0
export DOCSTUDIO_OCR_DEVICE=gpu:0
```

CPU 环境设置 `DOCSTUDIO_USE_GPU=0`，并将两个 device 设为 `cpu`。

## 7. 首次登录

首次启动会创建 `admin`：

- 设置 `DOCSTUDIO_ADMIN_PASSWORD` 时使用该口令；
- 未设置时随机生成并打印在启动日志中。

登录后请立即修改口令。旧版兼容登录需要 `DOCSTUDIO_AUTH_HASH`，可用 `python scripts/hash_password.py` 生成。

## 8. 日志与备份

- 日志：`data/logs/crabapple-docstudio.log`
- 备份：停止服务后备份整个 `data/` 目录即可
- 升级：替换程序文件，保留 `data/` 与 `url.conf`
