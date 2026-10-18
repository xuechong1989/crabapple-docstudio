# 参与贡献

感谢参与海棠文档工坊！

## 环境准备

- Python 3.11+
- Node.js 20+（仅前端）
- Windows 10/11 或 Linux

## 本地开发

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"

cd frontend
npm install
npm run build
cd ..

python start_server.py
```

前端热更新：`cd frontend && npm run dev`，默认 Vite 端口与后端代理配置见 `frontend/vite.config.js`。

## 提交前检查

```bash
ruff check backend scripts tests
pytest
cd frontend && npm run build
```

## 约定

- Python 代码保持 4 空格缩进，新增模块遵循 `backend/` 现有分层；
- 涉及 PDF/OCR/图像处理时，请说明对双层 PDF、页码、字体子集化、空白页判定的影响；
- 不要在提交中包含真实文档、客户数据、口令、令牌、密钥或内部地址；
- 不要提交 `data/`、`.venv/`、`node_modules/`、`frontend/dist/`、`assets/linux/wheels/`、`assets/windows/`；
- 新增依赖时同步更新 `requirements.txt` 与 `pyproject.toml`，并确认许可证与 AGPL-3.0 兼容。

## 许可证

贡献的代码将按 [GNU Affero General Public License v3.0](LICENSE) 发布。
