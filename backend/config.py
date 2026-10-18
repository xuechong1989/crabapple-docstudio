# -*- coding: utf-8 -*-
"""
Crabapple DocStudio - 核心参数配置

数据目录、YOLO 模型、GPU、OCR 与业务阈值。
磁盘路径优先从项目根目录的 url.conf 读取，默认使用 ./data。
"""

# ============================================================
# YOLO 模型配置
# ============================================================

# YOLO 模型配置
YOLO_MODEL_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
YOLO_MODEL_FILENAME = "doclayout_yolo_docstructbench_imgsz1024.pt"

# 优先使用本地模型（支持多种部署结构）
import os as _os
import sys as _sys
from pathlib import Path as _Path

# xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
# _cs 别名提前到模块级：原实现 import sys as _cs 位于下方 if url.conf 存在 分支内，
# url.conf 缺失时下方 ${...} 目录检查引用 _cs 会抛 NameError
_cs = _sys

# ============================================================
# 解析 url.conf（统一磁盘路径配置，所有路径常量均从此派生）
# ============================================================
_PROJECT_ROOT = _Path(__file__).parent.parent  # 项目根目录
_url_conf = {}
_conf_path = _PROJECT_ROOT / "url.conf"
# 备选：部署时项目可能作为子目录挂载，检查上级目录
if not _conf_path.exists():
    _alt_conf = _PROJECT_ROOT.parent / "url.conf"
    if _alt_conf.exists():
        _conf_path = _alt_conf
if _conf_path.exists():
    for _line in _conf_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k, _v = _k.strip(), _v.strip()
        for _ref in _url_conf:
            _v = _v.replace(f"${{{_ref}}}", _url_conf[_ref])
        _url_conf[_k] = _v

    # 启动诊断：记录配置来源和数据目录
    _cs.stderr.write(f"[config] url.conf: {_conf_path}\n")
    _cs.stderr.write(f"[config] DATA_DIR: {_url_conf.get('DOCSTUDIO_DATA_DIR', '/data/crabapple-docstudio (fallback)')}\n")
else:
    # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    # url.conf 缺失不再静默回退硬编码默认路径（数据根漂移会导致历史/用户数据"看似丢失"），
    # 改为醒目多行警告，写明当前实际生效的数据根与恢复方式
    _fallback_dir = str(_PROJECT_ROOT / "data")
    _cs.stderr.write("[config][错误] 未找到 url.conf 配置文件（已尝试项目根目录与上级目录）！\n")
    _cs.stderr.write(f"[config][错误] 当前后果：所有数据（历史记录/用户/缓存/任务）将使用默认目录 {_fallback_dir}\n")
    _cs.stderr.write("[config][错误] 若此前数据存放在其他目录，界面将表现为\"历史记录全部消失\"（数据并未删除）\n")
    _cs.stderr.write("[config][错误] 恢复方式：将 url.conf 复制到项目根目录并确认 DOCSTUDIO_BASE_DIR_WIN/DOCSTUDIO_DATA_DIR 指向原数据目录\n")

# ============================================================
# 磁盘路径常量（全部从 url.conf 派生，不使用环境变量）
# Windows 读 _WIN 变量，Linux 读同名变量
# ============================================================
if _sys.platform == 'win32':
    DATA_DIR = _Path(_url_conf.get("DOCSTUDIO_BASE_DIR_WIN", str(_PROJECT_ROOT / "data")))
    HF_HOME_DIR = DATA_DIR / "cache" / "huggingface"
    CUDA_CACHE_DIR = DATA_DIR / "cache" / "cuda"
    TMP_DIR = _Path(_url_conf.get("DOCSTUDIO_TMP_DIR_WIN", str(DATA_DIR / "tmp")))
else:
    DATA_DIR = _Path(_url_conf.get("DOCSTUDIO_DATA_DIR", str(_PROJECT_ROOT / "data")))
    TMP_DIR = _Path(_url_conf.get("TMPDIR", str(DATA_DIR / "tmp")))

# 以下缓存目录全部从已计算的 DATA_DIR 派生（不依赖 url.conf 二次展开，避免
# url.conf 中 ${DOCSTUDIO_BASE_DIR} 因定义顺序问题未展开导致字面量路径被创建）
_HF_HOME_DIR = DATA_DIR / "cache" / "huggingface"
_CUDA_CACHE_DIR = DATA_DIR / "cache" / "cuda"
_TORCH_HOME_DIR = DATA_DIR / "cache" / "torch"
_MPLCONFIG_DIR = DATA_DIR / "cache" / "matplotlib"
_ULTRALYTICS_DIR = DATA_DIR / "cache" / "ultralytics"

# 以下环境变量仅供 C 底层库（CUDA/HuggingFace/PyTorch/tempfile）使用
# 向后兼容：保留 _url_conf 读取作为 fallback，但实际路径从 DATA_DIR 派生
HF_HOME_DIR = _HF_HOME_DIR
CUDA_CACHE_DIR = _CUDA_CACHE_DIR
_os.environ.setdefault("DOCSTUDIO_MONGODB_KEY", _url_conf.get("DOCSTUDIO_MONGODB_KEY", ""))
_os.environ.setdefault("DOCSTUDIO_AUTH_HASH", _url_conf.get("DOCSTUDIO_AUTH_HASH", ""))
_os.environ.setdefault("DOCSTUDIO_DATA_DIR", str(DATA_DIR))
_os.environ.setdefault("DOCSTUDIO_BASE_DIR", str(DATA_DIR))
_os.environ.setdefault("HF_HOME", str(HF_HOME_DIR))
_os.environ.setdefault("CUDA_CACHE_PATH", str(CUDA_CACHE_DIR))
_os.environ.setdefault("CUDA_CACHE_MAXSIZE", _url_conf.get("CUDA_CACHE_MAXSIZE", "2147483648"))
_os.environ.setdefault("TMPDIR", str(TMP_DIR))
_os.environ.setdefault("TORCH_HOME", str(_TORCH_HOME_DIR))
_os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG_DIR))
_os.environ.setdefault("ULTRALYTICS_CONFIG_DIR", str(_ULTRALYTICS_DIR))

# xuechong 2026-06-01 检测项目根目录是否存在字面量 ${...} 目录（变量展开失败的产物）
for _item in _PROJECT_ROOT.iterdir():
    if _item.is_dir() and '${' in _item.name:
        _cs.stderr.write(f"[config] 警告: 项目根目录存在未展开变量的目录: {_item}\n")
        _cs.stderr.write(f"[config]   这通常是因为 url.conf 中变量定义顺序错误导致\n")
        _cs.stderr.write(f"[config]   建议手动删除: rm -rf '{_item}'\n")

# 预创建所有缓存目录（matplotlib 等库在 import 时就需要目录存在）
# xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
# 创建失败改为带中文指引的明确报错（原实现裸抛英文 PermissionError，用户无从下手）
for _d in [TMP_DIR, HF_HOME_DIR, CUDA_CACHE_DIR,
           _TORCH_HOME_DIR, _MPLCONFIG_DIR, _ULTRALYTICS_DIR]:
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception as _mkdir_err:
        raise RuntimeError(
            f"[config][错误] 无法创建数据目录 {_d}：{_mkdir_err}\n"
            f"[config][错误] 请检查：1) 磁盘是否已满  2) 对该路径是否有写权限  3) url.conf 中数据根目录配置是否指向了本机不存在的位置"
        ) from _mkdir_err

# ============================================================
# GPU 配置（环境变量可覆盖）
# ============================================================

def _is_truthy_env(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

# 总开关：是否允许使用 GPU（默认开启）
USE_GPU = _is_truthy_env(_os.environ.get("DOCSTUDIO_USE_GPU", "1"))

# 指定 OCR 设备（示例: "gpu:0" / "cpu"）
OCR_DEVICE = _os.environ.get("DOCSTUDIO_OCR_DEVICE", "")

# 指定 YOLO 设备（示例: "cuda:0" / "cpu"）
YOLO_DEVICE = _os.environ.get("DOCSTUDIO_YOLO_DEVICE", "")

def _find_local_model():
    """查找本地模型文件（兼容开发和打包后的目录结构）"""
    config_dir = _Path(__file__).parent.resolve()

    # 可能的模型路径（按优先级）
    possible_paths = [
        # 1. 外部存储目录/models/（持久化目录，升级时不丢失）
        DATA_DIR / 'models' / YOLO_MODEL_FILENAME,
        # 2. 项目根目录/models/
        config_dir / 'models' / YOLO_MODEL_FILENAME,
        # 3. 上级目录/assets/models/（开发仓库布局）
        config_dir.parent / 'assets' / 'models' / YOLO_MODEL_FILENAME,
    ]
    # 4. HF 缓存目录
    _hf_path = HF_HOME_DIR / 'hub' / 'models--juliozhao--DocLayout-YOLO-DocStructBench'
    possible_paths.append(_hf_path)
    
    for path in possible_paths:
        if path.is_file():
            return str(path)
        elif path.is_dir():
            # 搜索 HF 缓存目录
            for pt_file in path.rglob(YOLO_MODEL_FILENAME):
                return str(pt_file)
    
    return None

YOLO_MODEL_PATH = _find_local_model()

# YOLO 推理参数
YOLO_IMGSZ = 1024       # 推理图片尺寸（官方推荐）
YOLO_CONF = 0.2         # 检测置信度阈值（官方推荐 0.2，降低以检测更多区域）

# 保护区置信度阈值（按标签类型区分）
# 文字类标签：低阈值保护（即使置信度不高也要保护，避免误删文字）
# abandon标签：高阈值，低置信度(0.3~0.5)通常是钉痕误识别
TEXT_PROTECT_CONF = 0.2      # title、plain text 等文字类阈值
ABANDON_PROTECT_CONF = 0.35  # abandon 阈值（0.35以下如污迹等不保护）
DEFAULT_PROTECT_CONF = 0.25  # 其他标签默认阈值

# 需要保护的标签及其阈值分组
# 文字类：即使低置信度也保护
TEXT_LABELS = {'title', 'plain text'}

# abandon类：需要高置信度才保护
ABANDON_LABELS = {'abandon'}

# 其他需要保护的标签
OTHER_PROTECT_LABELS = {
    'figure', 'figure_caption',
    'table', 'table_caption', 'table_footnote',
    'isolate_formula', 'formula_caption'
}

# 需要向上扩展保护区的标签（table、plain text上方可能有遗漏的标题）
EXTEND_UP_LABELS = {'table', 'plain text'}
# 向上扩展的像素数（覆盖可能遗漏的标题行）
EXTEND_UP_PIXELS = 40

# ============================================================
# 文字连通域保护（补充 YOLO 漏检的文字）
# ============================================================
# 启用文字连通域保护
ENABLE_TEXT_BLOB_PROTECTION = True

# 面积阈值：超过此面积的连通域视为文字
# 英文字母/数字面积通常 80-250 像素，汉字 300+ 像素
# 钉痕通常 100-500 像素但形状不规则
TEXT_BLOB_MIN_AREA = 60  # 降低以保护英文和数字

# 宽度阈值：超过此宽度的连通域视为文字
# 英文字母宽度通常 8-20px，数字 10-18px
TEXT_BLOB_MIN_WIDTH = 8  # 降低以保护英文和数字

# 高度范围：正常字高（太高可能是框线）
# 英文/数字高度通常 10-25px
TEXT_BLOB_MIN_HEIGHT = 8   # 降低以保护小字
TEXT_BLOB_MAX_HEIGHT = 150 # 提高以保护大字

# 保护区膨胀半径
TEXT_BLOB_PROTECT_RADIUS = 5  # 稍微增大保护范围

# 文字孤立判定半径（像素）
TEXT_BLOB_ISOLATION_RADIUS = 60

# 英文/数字专用保护（更精细的检测）
ENABLE_ALPHANUMERIC_PROTECTION = True
# 英文/数字的长宽比通常在 0.3-3.0 之间
ALPHANUMERIC_MIN_ASPECT = 0.2
ALPHANUMERIC_MAX_ASPECT = 4.0


# ============================================================
# 黑斑噪点检测参数
# ============================================================

# 是否启用噪点检测（关闭后只依赖背景白化处理噪点）
ENABLE_NOISE_DETECT = True

# 二值化阈值（灰度 < 此值 为黑色）
BINARY_THRESHOLD = 200

# 文字区域判定：面积 > 此值 或 宽/高 > 40 认为是文字
MIN_TEXT_AREA = 150     # 降低以保护更多文字
MIN_TEXT_DIM = 30       # 降低以保护英文数字

# 文字保护区膨胀半径（像素）
TEXT_PROTECT_RADIUS = 30  # 稍微减小，避免保护到附近的噪点

# 噪点判定阈值（更激进）
MAX_NOISE_AREA = 800    # 增大以清理更大的钉痕和污点
MAX_NOISE_DIM = 60      # 增大以清理更大的噪点
MAX_NOISE_ASPECT = 8.0  # 增大以清理较细长的杂质线条

# zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
# 微小深色孤立斑强制清除（REQ-004）：**默认关闭**。两轮实验证实几何/灰度判据不可行：
# ①200 口径下淡印刷文字碎化成小域，孤立性误清整页文字（024 整页文字只剩单字）；
# ②深色文字笔画碎片的灰度均值（最低 36）比浅色碎屑斑（75~181）更深，灰度判据同样误清。
# 区分"碎屑斑"与"文字笔画碎片"需要语义理解，超出传统 CV 能力边界。代码保留备查，
# 如未来启用须先解决上述两类误清（评测样张：0006 右上碎屑群 / 024 淡印刷整页）。
ENABLE_TINY_SPOT_CLEAN = False
TINY_SPOT_MAX_AREA = 450
TINY_SPOT_MAX_DIM = 28

# ============================================================
# 空白页检测（研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能）
# ============================================================
# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
# 空白页定义：无文字、无签章、无表格等有效内容，完全空白或只含无效杂质
# （灰尘、装订孔/钉痕残留等——净化链路已将其清除，检测在净化后进行）。
# 判定口径：非白像素掩码 + 8连通域分析，任一连通域面积达到有效内容阈值即视为
# 非空白页；阈值对齐 TEXT_BLOB_MIN_AREA（最小文字保护阈值），宁可不删、绝不误删。

# 非白判定亮度阈值（任一灰度 < 此值为非白像素，与 app.py 页码区域检测 _PAGENUM_NON_WHITE 同口径）
BLANK_NON_WHITE_THRESHOLD = 245

# 有效内容最小连通域面积（300DPI 基准，对齐 TEXT_BLOB_MIN_AREA=60：
# 任何不小于最小文字的连通域都算有效内容，保证含字/签章/表格线的页绝不被判空白）
BLANK_MIN_CONTENT_AREA_300DPI = 60

# 掩码分析归一化 DPI（图像按此 DPI 缩放、PDF 页按此 DPI 渲染后再做连通域分析；
# 速度与灵敏度折中：A4 约 992x1403px，实际阈值=60*(120/300)^2=10px）
BLANK_ANALYSIS_DPI = 120

# 孤立散点内容确认阈值（300DPI 基准，对齐净化链路"孤立文字连通域 <500px 不保护"的
# 既有口径 protect.py _detect_text_blobs）：页面上全部非白连通域面积均小于此值时，
# 说明整页只有孤立灰尘点/透印痕/细线碎片等无效杂质，无一达到"可确认内容"的规模
# → 判空白。实测依据：453 张内容页样张归一后最大连通域最小值 2138px@120DPI
# （=6681px@300DPI），与阈值 500px 相差 13 倍，安全边际充足。
# 现场实测场景（pic5/空白2.png）：空白纸+散点灰尘斑+透印痕的纯杂质页散点域均<100px。
BLANK_ISOLATED_CONTENT_AREA_300DPI = 500

# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
# 透印鬼影判据（实测定案）：双面扫描的空白背面会透出正面内容的浅灰鬼影（几何上是
# 文字/表格形状，连通域判据无法识别），实测（桌面"新建文件夹"样本）：
#   透印页净化后无彩色非白像素中深色(<200)占比 7.5%~9.5%（中位灰度242）；
#   453张内容页同口径最小值 25.1%（黄色票据底色为彩色被排除后正文黑字占比回升），
#   净化后内容页实测 61.7%~78.4%（含最淡的"024淡印刷整页"69.9%）。
# 判据：无彩色非白像素中深色占比 < BLANK_GHOST_DARK_RATIO → 整页痕迹以浅色鬼影为主
# → 判空白。阈值18%取两侧约1.9/1.4倍余量的平衡点，且偏向"宁可不删"方向。
# 双重安全阀：①彩色像素达到彩色下限时直接判内容（背面带红章/黄票底色的页永不判
# 空白——彩色签章必须保留）；②计算剔除装订孔豁免组件（深色孔不拉高占比）。
# 残余风险：无彩色且浅于200灰度的淡字签名（物理上与鬼影无法区分）会被判空白。
BLANK_GHOST_EXEMPT = True
BLANK_GHOST_DARK_GRAY = 200
BLANK_GHOST_DARK_RATIO = 0.18
# 彩色安全阀下限（300DPI 基准）：彩色像素达到此量才认定"存在真实彩色内容"（红章/黄底
# 票据，直接判内容不判空白）。实测空白页3.tif 上彩色印章的透印鬼影仅约175px@120DPI
# （1.3x2.2cm 区域内填充率2.7%），真实印章为上万px实心块——下限2000px@300DPI（≈5mm
# 实心彩斑/彩色签名笔画量级）恰好隔开两者；低于此量的彩色噪点/彩色鬼影不触发保护
BLANK_GHOST_COLORED_FLOOR_300DPI = 2000

# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
# 装订孔豁免（实测定案）：净化链路的文字连通域保护会把整块深色圆斑（≥500px）当
# "文字"保护，导致钉痕清除被跳过——双面扫描的空白背面透出的装订孔会残留在净化结果
# 中（实测页边渐变孔仍残留约2100px@120dpi）。因此空白判定对同时满足以下全部条件的
# 连通域不计为内容（只豁免不删除，不改动净化链路）：
#   ①近页边（组件中心距最近页边 ≤ 页宽/高的15%，装订孔物理位置）
#   ②近似圆形（连通域面积/外接矩形 ≥0.55；宽高比在0.4~2.6，含边缘裁半孔）
#   ③尺寸窗（外接矩形长边 50~150px@300DPI，标准装订孔5-6mm=59-71px；
#     下限50排除正文字号圆形字符如12pt"O"≈50px，上限对齐 PUNCH_HOLE_MAX_DIM=150）
#   ④无彩色（组件内RGB通道极差均值<40——彩色圆形签章不豁免，签章必须保留）
# 误删风险评估：一页内容仅为1-2个"页边无色深圆斑"的真实文档不存在；任何正文行、
# 线条、签章、大号圆字符（>150px）均不满足全部条件仍判非空白。
BLANK_PUNCH_EXEMPT = True
BLANK_PUNCH_MIN_DIM_300DPI = 50
BLANK_PUNCH_MAX_DIM_300DPI = 150
BLANK_PUNCH_MIN_EXTENT = 0.55
BLANK_PUNCH_ASPECT_MIN = 0.4
BLANK_PUNCH_ASPECT_MAX = 2.6
BLANK_PUNCH_EDGE_RATIO = 0.15
BLANK_PUNCH_MAX_SATURATION = 40

# ============================================================
# 目录虚线保护参数
# ============================================================

# 虚线点的最大尺寸（宽和高）
DOTLINE_MAX_SIZE = 15

# 虚线点的最大面积
DOTLINE_MAX_AREA = 150

# 同一行判定：Y坐标差值 < 此值认为同一行
DOTLINE_Y_TOLERANCE = 10


# ============================================================
# 上传限制
# ============================================================

# 单文件最大上传大小 (MB)，TIF 扫描件可能较大
MAX_UPLOAD_SIZE_MB = 200
# 对应字节数
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# 水平间距范围：相邻点间距在此范围内认为是虚线
DOTLINE_MIN_GAP = 5
DOTLINE_MAX_GAP = 50

# 至少连续多少个点才认为是虚线
DOTLINE_MIN_COUNT = 5


# ============================================================
# 纵向推土机（黑边检测）参数
# ============================================================

# 边缘区域占图片尺寸的比例（四边各 10%）
# 增大范围以确保检测到边缘钉痕
EDGE_MARGIN_RATIO = 0.10

# xuechong 2026-06-01 框线保护中排除边缘杂质：
# 边缘杂质（扫描阴影）紧贴绝对边缘但后有纯白间隙；真实框线后紧跟文档内容
# _detect_frame_lines 对边缘区域的 frame 列检查后续间隙密度，低密度确认杂质
FRAME_EDGE_STRIP_MARGIN = 30    # 绝对边缘向内30px内的frame线需检查
FRAME_EDGE_GAP_CHECK = 40       # 检查frame线后40px的暗像素密度
FRAME_EDGE_GAP_DENSITY = 0.01   # 密度<1%确认边缘杂质

# xuechong 2026-06-01 边缘杂质线独立检测（5条标准）：
# 1.非票据 2.紧贴图片边缘 3.连续但不太长 4.周围有空白间隙 5.黑色非印章
# 在普通文档路径中独立执行，结果不受 YOLO/frame 保护掩码清除
ENABLE_EDGE_IMPURITY_DETECT = True
EDGE_IMPURITY_BLACK_THRESHOLD = 80      # 灰度<80视为黑色杂质
EDGE_IMPURITY_MIN_RUN = 40              # 最小连续暗段长度px（排除散点噪点）
EDGE_IMPURITY_MAX_RUN_RATIO = 0.25      # 最大连续暗段占图高/宽比（排除贯穿型表格框线）
EDGE_IMPURITY_MAX_STRIP_WIDTH = 60      # 杂质条最大宽度px
EDGE_IMPURITY_GAP_CHECK = 40            # 杂质条后间隙检测列/行数
EDGE_IMPURITY_GAP_DENSITY = 0.01        # 间隙暗像素密度<1%确认空白
EDGE_IMPURITY_SEAL_S_THRESHOLD = 50     # 饱和度>50不算黑色杂质（排除印章），扫描色偏通常<50

# zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
# 散点杂质带内文字行豁免：贴边孤立成行小字（页码"- N -"/网址/地址行）整行暗密度<10%，
# 与扫描散点同判据会被整行刷白。带内连通域字高达到该值（参考DPI=300，随DPI缩放）判为文字豁免；
# 真散点颗粒通常1~5px、细线宽<3px，维持清除
EDGE_SCATTER_TEXT_MIN_H = 10            # 散点带内文字连通域最小高度px（参考DPI=300）
# 边缘杂质特征：frame_line连续块紧贴图片边缘，且块后有纯白间隙
# 表格框线特征：frame_line后紧跟文档内容，无大段空白间隙
# 检测frame_line连续块后N列的平均暗像素密度
EDGE_STRIP_GAP_CHECK = 40     # 检查frame_line块后40列
EDGE_STRIP_GAP_DENSITY = 0.01 # 间隙暗像素密度<1%确认为边缘杂质

# 同一列（±此像素内）的噪点合并统计
EDGE_X_MERGE_DISTANCE = 5

# 至少多少个噪点才认为是黑边列
MIN_EDGE_NOISE_COUNT = 2

# 黑边判定阈值：列中黑色像素比例超过此值认为是黑边
# 值越小越敏感（会检测到更多边缘）
EDGE_BLACK_RATIO_THRESHOLD = 0.1


# ============================================================
# 钉痕迹检测参数（更激进）
# ============================================================

# 钉痕迹专用二值化阈值（比普通阈值高，捕获浅色污点）
# 值越高，越能捕获浅色钉痕
PUNCH_HOLE_BINARY_THRESHOLD = 245  # 提高以检测更浅的钉痕

# 钉痕迹最大尺寸（比普通噪点大）
PUNCH_HOLE_MAX_AREA = 8000   # 增大以清理更大的钉痕
PUNCH_HOLE_MAX_DIM = 150     # 增大以清理更大的钉痕

# 钉痕迹最小面积
PUNCH_HOLE_MIN_AREA = 15     # 降低以检测更小的钉痕

# 钉痕最大长宽比（放宽以检测不规则形状的钉痕）
PUNCH_HOLE_MAX_ASPECT = 8.0  # 增大以检测更多形状的钉痕

# 是否在全图范围检测钉痕（而不仅是边缘区域）
PUNCH_HOLE_FULL_IMAGE = True

# xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-003 钉痕严格模式
# 边缘带（四边 margin，复用 EDGE_MARGIN_RATIO=0.10）外的候选需同时满足
# bbox填充率 extent>=0.5 与面积>=50 才清除——60张样张统计锚定：带外候选1959个中
# 仅1%（29个）通过收紧，真钉痕（实心圆 extent≈0.785、面积数百+）可安全通过；
# 带内（装订边）维持现行宽松判定，真钉痕清除能力不变。False=完全回退现行行为。
PUNCH_HOLE_STRICT_MODE = True
PUNCH_HOLE_MIN_EXTENT = 0.5
PUNCH_HOLE_STRICT_MIN_AREA = 50

# xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-004 覆盖率保护（OR 语义）
# 原判据（质心单点/9点采样命中即保护）保留不变，覆盖率达标作为新增保护条件，保护范围只增不减；
# False=完全回退原判据（ratio 置 0 会"保护一切"，不能作为回退手段）
NOISE_PROTECT_COVER_MODE = True
NOISE_PROTECT_COVER_RATIO = 0.3      # 噪点域 bbox 与文字本体重叠率达到此值即保护
STRAY_LINE_PROTECT_COVER_RATIO = 0.05  # 杂质线 bbox 与膨胀保护区重叠率（细长形态取低值）

# xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-002 小噪点例外
# 残留普查根因：TEXT_PROTECT_RADIUS=30 膨胀保护区在密集票据上连片，字缝小黑点（2~8px）被误保护未清。
# 例外：保护区内的孤立微小噪点（面积<=60 且与最近文字连通域距离>=8px）不再豁免清除；
# False=回退（保护区内噪点一律豁免的现行行为）
NOISE_TEXT_GAP_EXCEPTION = True
NOISE_TEXT_GAP_NOISE_MAX_AREA = 60
NOISE_TEXT_GAP_MIN_DIST = 8

# xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 修复票外大块污染被内容保护误保
# 单据模式"票据外内容保护"的深色连通域面积上限：真文字/条码/印章碎块为小连通域（实测票外
# 文字连片最大 21029px），黑渍/扫描黑框为巨型连通域（实测 16万~196万px）。超过此值的域视为
# 扫描污染不再保护（彩色印章通道不受影响）；置足够大（如 10^9）即回退"全深色保护"行为。
RECEIPT_OUTSIDE_CONTENT_MAX_AREA = 50000

# xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 印章形状判别保护
# 票外深色域被清除前先做形状判别（圆/椭圆/方形，含残缺形态，见 receipt._blob_shape_regular）：
# 外接尺寸达到此值（默认120px≈300DPI 下10mm）且形状规则的深色块判为疑似印章，恢复保护；
# 只有外边界不规则的深色块才放心抹除。置 0 = 关闭形状豁免（回到纯判据剔除）。
SEAL_SHAPE_MIN_DIM = 120

# ============================================================
# 杂质线条检测参数（新增）
# ============================================================
# 检测并清除文档中的杂质黑线（非表格框线）

# 是否启用杂质线条检测
ENABLE_STRAY_LINE_DETECTION = True

# 杂质线条的最大宽度（像素）- 表格框线通常 >= 2px
STRAY_LINE_MAX_WIDTH = 4

# 杂质线条的最小长度（像素）
STRAY_LINE_MIN_LENGTH = 30

# 杂质线条的最小长宽比
STRAY_LINE_MIN_ASPECT = 10.0

# 杂质线条与保护区的最小距离
STRAY_LINE_PROTECT_DISTANCE = 20


# ============================================================
# 折痕检测参数
# ============================================================

# 是否启用折痕检测
ENABLE_CREASE_DETECTION = True

# 折痕二值化阈值（捕获浅色折痕线）
CREASE_BINARY_THRESHOLD = 220

# 折痕最小长度（像素）- 折痕通常是长条形
CREASE_MIN_LENGTH = 200

# 折痕最大宽度（像素）- 折痕通常很细
CREASE_MAX_WIDTH = 15

# 折痕最小长宽比（长/宽）- 折痕是细长的
CREASE_MIN_ASPECT_RATIO = 15.0


# ============================================================
# 清除处理参数
# ============================================================

# 噪点区域向外膨胀像素数（确保清除干净）
EXPAND_PIXELS = 10

# 激进清理模式：YOLO保护区外的所有深色像素直接刷白
ENABLE_AGGRESSIVE_CLEAN = True
# 激进清理的灰度阈值（低于此值的像素视为"深色"）
# 值越高，越多浅灰色像素会被刷白，背景越干净
AGGRESSIVE_CLEAN_THRESHOLD = 245

# OCR文字保护：在激进清理前用OCR检测文字区域，防止文字被误删
# 开启后会增加一些处理时间，但能有效保护文字内容
ENABLE_OCR_TEXT_PROTECT = True

# 智能污渍清除：清除灰色低饱和度污渍（扫描阴影、纸张老化痕迹等）
# 只保护真正的内容（深色文字<180 或 高饱和度彩色>40），清除其他灰色区域
# 适用于背景有大片灰色污渍的扫描文档
ENABLE_SMART_STAIN_CLEAN = True

# 文档边界外净化：检测文档/票据的矩形边界，边界外的污渍、曝光等全部刷白
# 适用于扫描文档/票据，边界外区域通常是A4纸背景或扫描仪漏光区域
ENABLE_BOUNDARY_CLEAN = False  # 仅票据路径使用边界净化（_process_receipt_document / _process_color_receipt 独立实现），普通文档不执行

# 基于纸张亮度的票据边界检测（大尺度模糊 + Otsu 阈值）
# 适用于白色/浅色票据纸张。与饱和度方法互补：饱和度方法检测有色纸张，亮度方法检测白色纸张
ENABLE_RECEIPT_BOUNDARY_BY_TEXTURE = True   # 是否启用纸张边界检测
RECEIPT_BOUNDARY_MIN_AREA_RATIO = 0.05      # 票据最小面积比（小于此值视为检测失败）
RECEIPT_BOUNDARY_MAX_AREA_RATIO = 0.98      # 票据最大面积比（大于此值视为检测失败）

# 边界检测调试模式：保存中间结果图片用于诊断
# 开启后会在 BOUNDARY_DEBUG_PATH 目录保存：
#   - *_1_paper_mask.jpg: 有色纸张检测结果
#   - *_2_paper_closed.jpg: 形态学处理后
#   - *_3_outside.jpg: 外部区域标记（红色）和票据矩形（绿框）
#   - *_4_result.jpg: 最终结果
BOUNDARY_DEBUG = False  # 调试完成
BOUNDARY_DEBUG_PATH = str(TMP_DIR / "boundary_debug")

# xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
# 贴边漏光净化总开关：扫描仪漏光在纸张边界外留下的浅色污渍（灰度190~245、几乎无颜色）
# 会被灰色内容保护误当成图纸灰内容，背景白化清不动；本开关控制在普通文档路径最后
# 新增一步"贴边漏光净化"，只在四边边缘带内按多个窄判据刷白。置 False 完全跳过，行为与 3.3.01 一致
ENABLE_EDGE_LIGHTLEAK_CLEAN = True

# xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
# 贴边漏光净化6个判定参数（全部要同时满足才刷白，宁漏清不误伤）：
EDGE_LIGHTLEAK_MARGIN_RATIO = 0.05  # 边缘带宽度占图宽/图高的比例，只清四边各5%以内
EDGE_LIGHTLEAK_GRAY_LOW = 190       # 灰度下限：与灰色内容保护带下限一致，更深的污渍由既有机制处理
EDGE_LIGHTLEAK_GRAY_HIGH = 245      # 灰度上限：与灰色内容保护带上限一致，更浅的背景白化已清
EDGE_LIGHTLEAK_SAT_MAX = 20         # 饱和度上限：与全色域彩色保护种子阈值一致，淡印章/彩笔迹不碰
EDGE_LIGHTLEAK_SAT_DOMAIN_RATIO = 0.6  # 域级低饱和占比：候选连成片后，片内S<20像素占比达60%才整片清理（浓渍块主体浅淡能过，真彩色内容进不来）
EDGE_LIGHTLEAK_TEXTURE_MAX = 0.03   # 域内深灰纹理占比上限：剖面线/网纹区域纹理密，超3%整域不清
EDGE_LIGHTLEAK_CLEARANCE = 15       # 深色内容净空半径（像素，DPI自适应）：距文字/框线15px内不清
EDGE_LIGHTLEAK_BLUISH_DIFF = 8      # 页内补扫蓝偏阈值：蓝色通道比红色通道高出的差值，图纸灰色填充是中性灰不带蓝偏
EDGE_LIGHTLEAK_INTERIOR_MIN_AREA = 3000  # 页内补扫最小连通域面积（300dpi基准，按DPI平方缩放）：只清大块云斑，零碎小点不碰
EDGE_LIGHTLEAK_TAIL_MIN_AREA = 3       # 渍尾碎渣最小连通域面积（300dpi基准，按DPI平方缩放）：边缘带内3px以上碎片一律清
EDGE_LIGHTLEAK_TAIL_GRAY_LOW = 180     # 渍尾碎渣灰度下限：蓝渍深核可到185
EDGE_LIGHTLEAK_TAIL_GRAY_HIGH = 255    # 渍尾碎渣灰度上限：浅尾可达254，255纯白不算
EDGE_LIGHTLEAK_TAIL_SAT_MAX = 45       # 渍尾碎渣饱和度上限：蓝渍核S可达40，红章S≥80仍被挡
EDGE_LIGHTLEAK_TAIL_BAND = 0.10        # 渍尾碎渣带宽度：比主清理带（5%）更宽，右边缘雾带实测深入到10%处
EDGE_LIGHTLEAK_TAIL_CLEARANCE = 1      # 渍尾碎渣与深色内容的净空半径：表格边框/标题的压缩振铃带紧贴线缘1~3px，15px连边框外侧纸面一起保护（用户复验斑点根因），1px只保线缘本体
EDGE_LIGHTLEAK_TAIL_FRAGMENT_MAX_IN = 150   # 框内小碎屑面积上限（300dpi基准）：YOLO框内空白纸面的孤立小渍，大块内容（图纸填充/长线）远超此值不受影响
EDGE_LIGHTLEAK_TAIL_FRAGMENT_MAX_OUT = 2000 # 框外页边距碎屑面积上限（300dpi基准）：同上，保护框外的大块内容
EDGE_LIGHTLEAK_TAIL_DARK_MAX = 200     # 暗色碎屑档：页边距深色小标记（笔痕/渍核）最大面积（300dpi基准），页码字符/长线远超此值不受影响
EDGE_LIGHTLEAK_STREAK_THICK = 14       # 细长黑痕条短边上限（像素，DPI自适应）：划痕宽仅3~13px，表格边框线由框线保护排除
EDGE_LIGHTLEAK_STREAK_MIN_LEN = 60     # 细长黑痕条长边下限（像素，DPI自适应）：划痕长99~181px
EDGE_LIGHTLEAK_STREAK_MAX_AREA = 8000  # 细长黑痕条面积上限（300dpi基准，按DPI平方缩放）：防纸边整条阴影带误清
EDGE_LIGHTLEAK_STREAK_EDGE = 30        # 细长黑痕条贴边判定：连通域外接框距某条纸边不超过此值（划痕实测距右纸边9~18px）

# xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
# 贴边漏光净化内容救援总开关：BUG-0073 引入的暗色碎屑档/细长黑痕条档/渍尾碎屑档
# （集合a/b）四档清除有意不尊重既有保护，全量测试实测把页边真实内容成批误删
# （序号列数字/页眉标题字符/页码/封底条形码/表格线端段/红章淡笔画）。本开关在四档
# 清除执行前插入内容识别过滤：六条判据（A=OCR文字形状复核、B=条形码条纹群、
# C=成排成列等距群体、D=页码位置先验、E=行线共线延伸、F=红域色相）任一命中即把
# 该候选块从清除名单排除。置 False 完全回退 3.3.03 行为
EDGE_LIGHTLEAK_CONTENT_RESCUE_ENABLE = True
# 判据A（RapidOCR文字形状复核）：四边10%带裁三张条带图各跑一次文字检测（只检测
# 不识别），det_limit 须不小于整页长边（300dpi竖版约3537），条带原尺寸进模型保
# 小字符召回（全图缩放检测对8×28px小字符召回不足，实测标题字符检不出）
EDGE_LIGHTLEAK_RESCUE_OCR_DET_LIMIT = 4000  # 条带OCR检测最大边长：条带保持原尺寸不缩放
# 判据B（条形码条纹群）：≥5根等宽等距平行细竖条判定为条形码，群体及正下方人读
# 字符区一并救援（010封底条形码14根条纹+MOH0025700-6）
EDGE_LIGHTLEAK_RESCUE_BAR_MIN_BARS = 5    # 条纹群最少根数
EDGE_LIGHTLEAK_RESCUE_BAR_W_MIN = 2       # 单根条纹最小宽度（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_BAR_W_MAX = 8       # 单根条纹最大宽度（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_BAR_MIN_H = 40      # 条纹最小高度（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_BAR_TOL = 0.40      # 等宽等距容差：条纹宽度极差/中位、相邻间距极差/中位均不超过此值
EDGE_LIGHTLEAK_RESCUE_BAR_TEXT_RATIO = 1.5  # 条纹群正下方字符区高度=条纹高度×此比例
# 判据C（成排成列等距群体）：同一行/列≥3块且相邻间距等距判定为印刷内容救援
# （08-05批标题字符行、序号列1~9、页眉虚线段）；针式走纸孔链同样等距成排但该清，
# 按近圆形+贴纸边豁免本判据
EDGE_LIGHTLEAK_RESCUE_ROW_MIN_COUNT = 3   # 成排/成列最少块数
EDGE_LIGHTLEAK_RESCUE_ROW_TOL = 0.40      # 等距容差：相邻中心间距极差/中位间距不超过此值
EDGE_LIGHTLEAK_RESCUE_HOLE_AR_MIN = 0.7   # 走纸孔豁免：外接框宽高比下限（近圆形）
EDGE_LIGHTLEAK_RESCUE_HOLE_AR_MAX = 1.4   # 走纸孔豁免：外接框宽高比上限（近圆形）
EDGE_LIGHTLEAK_RESCUE_HOLE_EDGE = 30      # 走纸孔豁免：外接框距任一纸边不超过此值（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_DOT_MAX_DIM = 14    # 微圆块豁免：近圆形且最长边不超过此值（像素，300dpi基准，DPI自适应）的块不参与成排成列救援——灰尘点/走纸孔残点特征形态（全量实测6~12px成列），真字符微块由判据A/B/E兜底
# 判据D（页码位置先验）：页底水平中央的1~3个孤立字符块判定为页码救援
# （10-09三个封面页码"1"、07-20批002/003/006页码）；坐标基准为传入净化方法的图
# （页面方向矫正之后的图），横版样本转正后按实际页底判定
EDGE_LIGHTLEAK_RESCUE_PAGENUM_X_LO = 0.35   # 页码窗口x下限（占图宽比例）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_X_HI = 0.65   # 页码窗口x上限（占图宽比例）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_Y_LO = 0.88    # 页码窗口y下限（占图高比例）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_Y_HI = 0.985   # 页码窗口y上限（占图高比例）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_H_MIN = 14     # 页码字符最小高度（像素，300dpi基准，DPI自适应；07-20批低分辨率样张页码实测高19px，20会漏）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_H_MAX = 60     # 页码字符最大高度（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_PAGENUM_MAX_BLOCKS = 3  # 页码窗口内孤立块数量上限（超过判定为内容区域不救）
# 判据E（行线共线延伸）：与同一直线上≥150px连续暗线共线的细长块判定为表格线端
# 段救援（08-14/05-20-8批约40处表格线端部缺口、10-09顶边框断口）；补强：候选块
# 距每条纸边>30px才救——贴边黑痕是细长黑痕条档的本职清理对象，永不救（防纸边
# 黑痕与表格边框共线误救，014/015右缘黑痕清零为硬性验收门槛）
EDGE_LIGHTLEAK_RESCUE_LINE_MIN_LEN = 150  # 共线基准线最小连续长度（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_LINE_TOL = 3        # 共线容差：候选块与基准线的垂直距离（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_LINE_GAP = 30       # 候选块与基准线端头的最大间隙（像素，300dpi基准，DPI自适应）
EDGE_LIGHTLEAK_RESCUE_LINE_EDGE_MIN = 30  # 补强：候选块外接框距每条纸边必须大于此值才救（像素，300dpi基准，DPI自适应）
# 判据F（红域色相）：块内红域像素占比达标判定为印章笔画救援（08-05批044/048/
# 052/056红章淡笔画残块，seal_mask按饱和度识别挡不住低饱和淡红）。饱和度下限
# 必须有——白色背景像素的色相值恰好为0落在红域数值区间，不加饱和度条件会把
# 白色背景误算成红域
EDGE_LIGHTLEAK_RESCUE_RED_H_LOW = 10      # 红域色相下限（OpenCV H<10）
EDGE_LIGHTLEAK_RESCUE_RED_H_HIGH = 170    # 红域色相上限（OpenCV H>170，红色环绕色相环两侧）
EDGE_LIGHTLEAK_RESCUE_RED_S_MIN = 25      # 红域判定饱和度下限：白色背景H=0但S=0不算红
EDGE_LIGHTLEAK_RESCUE_RED_RATIO = 0.30    # 块内红域像素占比下限

EDGE_LIGHTLEAK_CLEAN_ENABLE_SPECK = True  # 蓝渍碎屑档总开关：清标题周围带蓝偏的小碎屑（不尊重YOLO文字框，文字本体黑色够不到灰度门槛）
EDGE_LIGHTLEAK_SPECK_MIN_AREA = 80      # 蓝渍碎屑最小连通域面积（300dpi基准，按DPI平方缩放）
EDGE_LIGHTLEAK_SPECK_BAND = 0.15        # 蓝渍碎屑活动范围：页顶/页底各15%带（漏光渍不深入页面中部）
EDGE_LIGHTLEAK_SPECK_BG_DELTA = 14      # 字缝灰雾档：像素灰度与局部背景估计（21px闭运算）差值低于此值视为雾
EDGE_LIGHTLEAK_SPECK_BG_MIN_AREA = 60   # 字缝灰雾最小连通域面积（300dpi基准，按DPI平方缩放）

# xuechong 2026-10-11 研发BUG-0073 灰雾页纸面灰雾漂白（默认开启）：
# 封面页的纸面灰雾（亮度236~252）被YOLO文字大保护框和灰色保护同时罩住，尊重保护框
# 的清理绕不开。图纸页的浅灰填充与封面灰雾像素特征完全无差别（实测八类判据全部
# 重叠，无法算法区分），本系统服务对象为电力工程文档（无图纸类灰填充扫描件），
# 按用户验收标准"背景必须完全干净"默认开启。误漂图纸浅灰填充时置 False 关闭回退。
# 生效时六道保护齐上：figure框（照片）、印章、彩色种子、页码豁免、深色净空、碎片门槛
EDGE_LIGHTLEAK_WASH_ENABLE = True          # 灰雾漂白总开关：False=封面/文字页纸面灰雾保留不清
EDGE_LIGHTLEAK_WASH_KEEP_LABELS = {'figure'}  # 漂白时仍要尊重的YOLO图片类标签（照片/图片本体）
EDGE_LIGHTLEAK_WASH_GRAY_LOW = 236          # 灰雾亮度下限（高于图纸灰填充206-218，防止误伤）
EDGE_LIGHTLEAK_WASH_GRAY_HIGH = 252         # 灰雾亮度上限
EDGE_LIGHTLEAK_WASH_MIN_AREA = 800          # 灰雾连通域最小面积（300dpi基准，按DPI平方缩放）：文字行会把雾切成小片，2500会漏清
EDGE_LIGHTLEAK_WASH_CLEARANCE = 6           # 灰雾与深色内容的净空半径（像素，DPI自适应）：文字抗锯齿晕仅2-4px，6px护住字缘即可
EDGE_LIGHTLEAK_WASH_TEXTURE_MAX = 0.20      # 灰雾域邻域中灰密度上限：实心图纸灰填充邻域密度≈1.0从这里拒绝；文字抗锯齿薄晕使文字页雾域密度达0.065~0.09须放行（8%旧值会误拦文字页），孤立浅腔本就不靠此参数拦
EDGE_LIGHTLEAK_WASH_MIN_FRAGMENT = 400      # 漂白碎片最小面积（300dpi基准，按DPI平方缩放）：滤掉零星噪点，图纸实心填充的伤害从来是大块碎片不靠此参数拦

# 普通文档模式是否启用框线保护（检测横竖直线并保护）
# 文档模式使用 120px 长度阈值，只保护真正的长线条（分隔线、表格框线）
ENABLE_FRAME_PROTECTION = True


# ============================================================
# 条形码保护参数
# ============================================================

# 是否启用条形码保护（检测条形码区域并防止被修图净化误删）
ENABLE_BARCODE_PROTECTION = True

# 条形码检测：单根条的最大宽度（像素，DPI自适应）
BARCODE_BAR_MAX_WIDTH = 12

# 条形码检测：单根条的最小高度（像素，DPI自适应）
BARCODE_BAR_MIN_HEIGHT = 20

# 条形码检测：最小聚集密度 - 区域内条形码候选组件的最小数量
BARCODE_MIN_CLUSTER_COUNT = 8

# 条形码检测：条间距最大距离（像素，DPI自适应），用于判断是否属于同一组条形码
BARCODE_CLUSTER_DISTANCE = 30

# 条形码检测：膨胀保护半径（像素，DPI自适应）
BARCODE_PROTECT_RADIUS = 15


# ============================================================
# 大面积灰色内容保护（工程图纸剖面线/阴影/材料标识）
# xuechong 2026-07-21 修复：工程图纸灰色背景区域被误删
# ============================================================

# 是否启用大面积灰色内容保护
ENABLE_GRAY_CONTENT_PROTECTION = True

# 灰色内容保护：最小连通域面积（像素数），小于此值的灰色区域视为污渍不保护
GRAY_CONTENT_MIN_AREA = 200
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 L1 面积上限比例
# 0 = 不限制（对齐 3.0.03 行为）；>0 时连通域面积占图片面积比例超过此值则不保护
# 之前设 0.05 导致 002/003 等样张的大面积灰色内容被全部过滤，灰色保护归零
GRAY_CONTENT_MAX_AREA_RATIO = 0.0

# 灰色内容保护 Layer2：填充率阈值，高于此值的区域填充外接矩形（修复扫描边缘间隙）
GRAY_FILL_RATIO_THRESHOLD = 0.65

# 灰色内容保护 Layer2：外接矩形填充的最小面积（像素数），避免小区域误填充
GRAY_RECT_MIN_AREA = 500

# xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景 L1.5 碎片聚合总开关
# False（默认）= 修复生效：跳过 L1.5 碎片聚合。正常白底文档的文字抗锯齿碎片（每个<200px）
#   经 15x15 闭运算聚合后整体外接矩形填充，生成覆盖全页 23%~69% 的虚假保护掩码，
#   阻断高白保守白化，输出残留灰色背景/灰色方块（本BUG根因）；实测全部已知样张的
#   L1.5 只保护噪点雾（聚合簇碎片真实密度≤0.12），图纸实心灰色内容由 Layer1/Layer2 承担，不受影响。
# True = 恢复 v3.1.04 行为（诊断/对比/回退用）：仅当真实剖面线短碎段样张验证有保护必要时才考虑重开
ENABLE_GRAY_CLUSTER_L15 = False

# 灰色内容保护 Layer1.5：小碎片聚合（剖面线区域检测）
# 闭运算内核大小（像素），用于连接邻近小碎片
GRAY_CLUSTER_CLOSE_KSIZE = 15
# 聚合后的最小面积（像素），小于此值的聚合区域不保护
GRAY_CLUSTER_MIN_AREA = 5000
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 L1 核心区域填充率阈值
# 0 = 不过滤（对齐 3.0.03 行为）；>0 时填充率低于此值的连通域不保护
# 之前设 0.30 加上 texture 过滤导致 L1 全灭，灰色保护完全失效
GRAY_CONTENT_L1_FILL_RATIO = 0.0
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 深灰纹理判定阈值
# 0 = 不过滤（对齐 3.0.03 行为）；>0 时区域深灰纹理低于此比例则不保护
# 之前设 0.005 过于激进，实际文档样张几乎没有深灰纹理但需要保护
GRAY_CONTENT_TEXTURE_MIN_RATIO = 0.0
# 深灰纹理判定阈值（灰度低于此值视为深灰纹理，与 <190 深色内容口径一致）
GRAY_CONTENT_DARK_TEXTURE_HIGH = 190
# Layer1.5 聚合区域填充率阈值
# 0 = 不过滤；>0 时聚合连通域面积/外接矩形面积 ≥ 此值才填充
GRAY_CLUSTER_FILL_RATIO = 0.0
# Layer1.5 碎片聚合保护面积占图片面积的最大比例
# 0 = 不限制（对齐 3.0.03 行为）；>0 时超过此比例则跳过碎片聚合
# 之前设 0.05 导致 002.tif 39.8% 聚合被整批跳过，灰色保护完全失效
# xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景 本次维持 0.0 不启用硬上限：
# L1.5 已由 ENABLE_GRAY_CLUSTER_L15 默认关闭，硬上限叠加无必要且不可测（关闭后正常页 L1.5=0 永不触发）
GRAY_CLUSTER_MAX_RATIO = 0.0
# Layer3 边缘膨胀迭代次数
GRAY_EDGE_DILATE_ITERATIONS = 2
# Layer3 边缘膨胀核半径
GRAY_EDGE_DILATE_RADIUS = 5

# zhaoqiaotong 2026-08-31 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化 REQ-010 整页灰雾门控
# 扫描灰雾（整页细粒度灰底）与图纸剖面线/表格印刷底纹（局部灰内容）在域级特征上不可分
# （Phase 1 双向实测：σ/深灰纹理/填充率全部重叠，见工作目录 研发需求-0139-校准-灰雾豁免.py），
# 唯整页浅灰覆盖率可分：灰雾页 16.2%（010）~20.0%（020），保护侧样张全部 ≤8%，间隔 2~3 倍。
# 覆盖率超阈值的页判为灰雾页，灰色保护整体跳过，灰雾由既有清除链路（智能污渍清除/散点清理）接管。
# 端到端仿真（2026-08-31）：020 灰雾 21.0%→5.1%、010 13.4%→5.0%，老002 图纸/019 底纹页输出零变化。
ENABLE_GRAY_MOTTLE_EXEMPT = True   # 灰雾页门控开关（2026-08-31 单图验证通过后启用，全量两层测试为最终验收）
GRAY_MOTTLE_PAGE_RATIO = 0.15      # 灰雾页判定阈值：浅灰([190,245)+S<35)整页覆盖占比超过此值即门控

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 灰色保护区噪声清理
# 灰色保护掩码覆盖大面积区域，但保护区内含大量扫描仪噪声（灰度 240-250 的散点）。
# 不清理则输出“稀碎花里哨哨”（002.tif 产生 14,178 个碎片）。
# 旧策略（灰度阈值刷白 ≥238）能减碎片但误删灰色矩形内容（002.tif 灰色保留率仅 24%）。
# 新策略两步：①中值滤波平滑保护区内边缘噪声，保留灰色矩形大块结构；
# ②只清理“纯白噪声碎片”（面积 < min_area 且平均灰度 > mean_gray），不伤灰色内容。
# 实测：002.tif 灰色保留率从 24% 提升至 87%，小碎片从 14192 降至 349
GRAY_PROTECT_MEDIAN_KSIZE = 3      # 中值滤波核大小（3x3，0=禁用）
GRAY_PROTECT_NOISE_MIN_AREA = 200  # 纯白噪声碎片最大面积（0=禁用）
GRAY_PROTECT_NOISE_MEAN_GRAY = 235 # 碎片平均灰度高于此值才清理（区分噪声与灰色内容）

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 灰色内容保护通道（Layer2.5）
# 保护灰色文字/手写/细线形态连通域，防止误删灰色内容
# 深灰色像素灰度上限（灰度 190 ~ 此值的像素视为深灰色文字候选）
GRAY_CONTENT_DEEP_HIGH = 220
# 深灰色文字连通域面积范围（单个字/手写笔画）
GRAY_CONTENT_TEXT_MIN_AREA = 5
GRAY_CONTENT_TEXT_MAX_AREA = 2000
# 深灰色文字填充率阈值（笔画密集度高）
GRAY_CONTENT_TEXT_FILL_RATIO = 0.3
# 细线结构宽高比阈值（线条特征：极宽或极高）
GRAY_CONTENT_LINE_ASPECT_RATIO = 3.0
# 细线结构最小面积
GRAY_CONTENT_LINE_MIN_AREA = 20
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 灰色内容保护通道开关
# 实测（005 样张）：L2.5 保护像素中 83.6% 被 3.0.03 刷白（实为背景/噪点而非内容），
# 仅 16.4% 为真内容（已由文字保护/框线保护/OCR 保护覆盖）→ 默认关闭避免过度保护
# ⚠ 真实工程图纸样张（灰色手写/笔迹）到位后验证，若确需此通道再开启
ENABLE_GRAY_CONTENT_CHANNEL = False

# ============================================================
# 背景/阴影消除参数（Phase 2.1）- 基于 noteshrink 算法
# ============================================================

# 是否启用背景增强（抠图式背景白化）
ENABLE_BACKGROUND_ENHANCE = True

# 明度差异阈值（0-255）
# 像素明度与背景明度差异超过此值，视为前景
# 值越小越敏感（更多像素被保留）
# 值越大，越多浅色污迹会被白化
BACKGROUND_VALUE_THRESHOLD = 40  # 更激进白化背景（原50）

# 饱和度差异阈值（0-255）
# 像素饱和度与背景差异超过此值，视为前景（用于保护彩色内容如印章）
BACKGROUND_SAT_THRESHOLD = 25    # 保护彩色内容（原40）


# ============================================================
# 透光消除参数（Phase 2.2）
# ============================================================

# 是否启用透光消除
ENABLE_BLEEDTHROUGH_REMOVAL = True

# 透光检测阈值范围（低对比度的浅色干扰）
BLEEDTHROUGH_LOW_THRESHOLD = 180    # 低于此值不是透光
BLEEDTHROUGH_HIGH_THRESHOLD = 240   # 高于此值是正常背景

# 中值滤波核大小（用于平滑透光区域）
BLEEDTHROUGH_MEDIAN_SIZE = 5


# ============================================================
# 公章/硬章保护参数（Phase 2.3）
# ============================================================

# 是否启用公章保护
ENABLE_SEAL_PROTECTION = True

# 红色 HSV 阈值（红色在 HSV 空间分两段）
# 第一段：H 0~10
SEAL_RED_H1_LOW = 0
SEAL_RED_H1_HIGH = 10
# 第二段：H 170~180
SEAL_RED_H2_LOW = 170
SEAL_RED_H2_HIGH = 180

# 饱和度和亮度阈值
SEAL_S_LOW = 80         # 最低饱和度（稍微降低以捕获褪色印章）
SEAL_V_LOW = 50         # 最低亮度

# 公章保护区膨胀迭代次数（确保边缘不被误删）
SEAL_DILATE_ITERATIONS = 2
SEAL_DILATE_KERNEL_SIZE = 5


# ============================================================
# 彩色区域保护参数（保护所有彩色区域，包括各种颜色的单据）
# ============================================================
# 中国单据/票据颜色多样：黄色、粉色、蓝色、绿色、橙色、紫色等
# 为避免彩色单据内容被误处理，保护所有有饱和度的彩色区域

# 是否启用彩色区域保护
ENABLE_COLOR_PROTECTION = True

# 是否启用全色域保护（保护所有有饱和度的彩色区域）
# True: 保护所有彩色区域（推荐，适用于彩色单据）
# False: 只保护特定颜色（黄色、粉色、蓝色/青色）
ENABLE_FULL_COLOR_PROTECTION = True

# 全色域保护的饱和度阈值（饱和度大于此值的区域都会被保护）
# 值越低保护范围越大，但可能保护到一些不需要的区域
FULL_COLOR_SATURATION_THRESHOLD = 20

# 通用饱和度阈值（用于特定颜色检测）
COLOR_SATURATION_THRESHOLD = 30

# 亮度范围（排除过暗或过亮的像素）
COLOR_VALUE_MIN = 30        # 最低亮度（排除纯黑）
COLOR_VALUE_MAX = 250       # 最高亮度（排除纯白）

# 黄色 HSV 范围 (OpenCV 中 H 范围是 0-180)
# 黄色色相约在 20-40，宽松范围 15-50
YELLOW_H_LOW = 15
YELLOW_H_HIGH = 50

# 粉色 HSV 范围
# 粉色是红色偏白，色相在红色附近 (0-10 或 140-180)
# 粉色饱和度较低（红色+白色混合）
PINK_H_LOW1 = 140           # 粉色第一段起始
PINK_H_HIGH1 = 180          # 粉色第一段结束
PINK_H_LOW2 = 0             # 粉色第二段起始（红色附近）
PINK_H_HIGH2 = 10           # 粉色第二段结束
PINK_S_THRESHOLD = 20       # 粉色饱和度阈值（较低，因为粉色偏淡）

# 蓝色/青色/蓝青色 HSV 范围
# 用于保护蓝色/青色/蓝青色的长方形章
# 青色 H: 80-100, 蓝色 H: 100-130, 蓝青色涵盖 80-130
BLUE_CYAN_H_LOW = 80        # 蓝青色色相起始（包含青色）
BLUE_CYAN_H_HIGH = 130      # 蓝青色色相结束（包含蓝色）
BLUE_CYAN_S_THRESHOLD = 25  # 蓝青色饱和度阈值（稍低以捕获浅色印章）
BLUE_CYAN_V_MIN = 50        # 蓝青色最低亮度
BLUE_CYAN_V_MAX = 250       # 蓝青色最高亮度

# 绿色 HSV 范围（用于保护绿色单据）
GREEN_H_LOW = 35            # 绿色色相起始
GREEN_H_HIGH = 85           # 绿色色相结束
GREEN_S_THRESHOLD = 25      # 绿色饱和度阈值

# 橙色 HSV 范围（用于保护橙色单据）
ORANGE_H_LOW = 5            # 橙色色相起始
ORANGE_H_HIGH = 25          # 橙色色相结束
ORANGE_S_THRESHOLD = 30     # 橙色饱和度阈值

# 紫色 HSV 范围（用于保护紫色单据）
PURPLE_H_LOW = 125          # 紫色色相起始
PURPLE_H_HIGH = 160         # 紫色色相结束
PURPLE_S_THRESHOLD = 20     # 紫色饱和度阈值

# 彩色区域保护膨胀参数（确保边缘不被误删）
COLOR_DILATE_ITERATIONS = 2
COLOR_DILATE_KERNEL_SIZE = 5

# 彩色票据/单据检测阈值
# 如果彩色像素占比超过此值，认为是彩色票据，使用彩色票据保护模式
# 值越小越敏感（更多图片被识别为彩色票据）
# 值越大越严格（只有真正的彩色票据才会被识别）
# 建议值：0.05 (5%) - 0.15 (15%)
COLOR_RECEIPT_THRESHOLD = 0.15  # 15%（只有真正的彩色票据才会达到此比例）

# 高白比例图片跳过背景白化的阈值
# 如果图片白色像素比例超过此阈值，跳过背景白化处理
# 目的：避免对已经很白的扫描件进行背景白化时误伤淡色文字
# 值越大越保守（更多图片会正常执行背景白化）
# 值越小越激进（更多图片会跳过背景白化）
# 建议值：0.85 (85%) - 0.90 (90%)
HIGH_WHITE_SKIP_THRESHOLD = 0.85  # 85%

# 保守白化的近白阈值
# 对于高白比例图片，只将RGB都大于此阈值的像素变成纯白
# 目的：将#FEFEFE等接近白色的背景变成纯白#FFFFFF，但不影响文字
# 值越大越保守（只白化非常接近白色的像素）
# 值越小越激进（更多浅色像素会被白化）
# 建议值：235-245
NEAR_WHITE_THRESHOLD = 240  # RGB > 240 的像素变为纯白


# ============================================================
# 图纸模式参数（Phase 2.4）
# ============================================================

# 是否启用图纸模式（保护细线）
ENABLE_DRAWING_MODE = False

# 线条判定：长宽比阈值（大于此值视为线条而非噪点）
LINE_ASPECT_RATIO_THRESHOLD = 4.0

# 最小线条长度（像素），短于此值的细长物体可能是噪点
MIN_LINE_LENGTH = 30

# 图纸模式下噪点的最大面积（比普通模式更严格）
DRAWING_MAX_NOISE_AREA = 150

# 线条保护区膨胀半径
LINE_PROTECT_RADIUS = 5


# ============================================================
# 框线保护参数
# ============================================================

# 框线检测：形态学核的最小长度（像素）
# 只检测长线条，避免误保护污渍
FRAME_LINE_MIN_LENGTH_DOC = 120

# 框线保护区膨胀半径
FRAME_PROTECT_RADIUS = 3


# ============================================================
# 倾斜矫正参数
# ============================================================

# 是否启用倾斜矫正
ENABLE_DESKEW = True

# 最大允许的倾斜角度（度），超过此值不矫正（可能是横向文档）
DESKEW_MAX_ANGLE = 15.0

# 最小需要矫正的角度（度），小于此值认为不需要矫正
# 降低到0.1度，确保微小的倾斜也能被矫正
DESKEW_MIN_ANGLE = 0.1

# 霍夫变换参数（更敏感的检测配置）
DESKEW_HOUGH_THRESHOLD = 30        # 霍夫变换累加器阈值（降低以检测更多线条）
DESKEW_HOUGH_MIN_LINE_LENGTH = 30  # 最小线段长度（降低以检测更短线条）
DESKEW_HOUGH_MAX_LINE_GAP = 30     # 最大线段间隙（增加以连接断开的线条）

# 旋转后填充颜色（白色）
DESKEW_FILL_COLOR = (255, 255, 255)

# xuechong 2026-08-19 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题
# 投影法仲裁门控参数（依据：456 张全样张库通道普查+门控仿真——v1 网格定参、v2 全库方向核验，30 张改变全部改善 0 劣化）
# 门控逻辑：文字行样本数在 [2, DESKEW_TEXT_MIN_SAMPLES) 且投影置信度>CONF_MIN 且与现有决策分歧>DIFF 时采纳投影角
DESKEW_PROJ_ARBITRATION = True   # 门控总开关，False 时完全回滚 3.1.06 决策行为
DESKEW_TEXT_MIN_SAMPLES = 10     # 文字行通道小样本上限（<此值视为不可靠；下限 2 为硬编码有效性条件，见 skew.py）
DESKEW_PROJ_CONF_MIN = 1.15      # 投影法置信度门限（必要非充分条件，须与 n_text>=2 串联；改善组最低 1.1688/劣化组最高 1.0919）
DESKEW_PROJ_DIFF = 0.4           # 投影角与现有决策最终角的分歧阈值（度）

# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 二次倾斜矫正（REQ-003）：竖版A4扫描+票据内容横放（需90°旋转）场景，首轮倾斜检测在旋转前
# 执行，票据文字行近垂直致文字通道0样本，灰度霍夫测的是页框角（d001 实测-6.96°过矫，
# 输出残留+3.6°）。旋转后内容文字行才近水平，此时补一次检测矫正。
# 门控（全满足才触发，普通文档零行为变化）：发生过90°旋转 且 首轮文字行样本<2 且 累计角在上限内
DESKEW_SECOND_PASS = True
DESKEW_SECOND_PASS_MAX_TOTAL = 15.0  # 首轮+二次累计矫正角上限（度），超出跳过二次矫正防叠加过矫
# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 二次矫正投影一致性门控（首轮回归暴露6张劣化后收紧）：
# 探针实测 改善组 |angle2-投影角| 全部≤0.25（d001=0.13）、劣化组全部≥0.84（最差4.60），
# 0.5 居中两侧各留0.25+边际；二次检测必须与投影法一致才执行，否则拒绝
DESKEW_SECOND_PASS_PROJ_DIFF = 0.5

# ============================================================
# 页面方向矫正参数（90度旋转检测）
# ============================================================

# 是否启用页面方向矫正（检测并修正90度旋转的页面）
ENABLE_PAGE_ORIENTATION = True

# 宽高比阈值（宽/高 > 此值认为已经是横向，不需要旋转）
PAGE_ORIENTATION_RECEIPT_RATIO = 1.2

# 最少需要检测到的文字框数量（少于此值则不做方向判断）
PAGE_ORIENTATION_MIN_BOXES = 3

# 方向检测时的图像最大边长（640是速度和精度的平衡点）
PAGE_ORIENTATION_MAX_DIM = 640

# 方向检测置信度阈值（竖向文字框占比超过此值就旋转）
# 设为0.5意味着只要竖向框多于横向框就旋转
PAGE_ORIENTATION_CONFIDENCE = 0.5

# zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
# cls 投票判定翻转（180°）的强证据阈值：表格类文档小字方向判别接近随机（如 0.52:0.48），
# 微弱多数不得翻转整页；介于 CONFIDENCE 与此值之间的投票视为不明确，回退 4 方向 det+rec 复核
PAGE_ORIENTATION_FLIP_CONFIDENCE = 0.7


# ============================================================
# 单据/票据检测参数
# ============================================================
# 中国的单据/票据通常尺寸小于A4纸的2/3，粘贴到A4纸上扫描
# 单据颜色多样（黄色、粉色、蓝色、绿色、白色等）
# 检测到单据时，完全保护单据区域，仅刷白A4纸背景
#
# 单据与普通文档的关键区别：
# 1. 单据被白色A4纸背景包围，不贴边
# 2. 单据是独立的矩形区域，通常有彩色背景
# 3. 单据四周都有明显的白色背景区域
# 普通文档/表格：内容铺满整个页面，没有被白色包围

# 是否启用单据/票据检测
ENABLE_RECEIPT_DETECTION = True

# 单据面积占图片总面积的比例范围
RECEIPT_MIN_AREA_RATIO = 0.03       # 最小面积占比 3%（非常小的票据）
RECEIPT_MAX_AREA_RATIO = 0.60       # 最大面积占比 60%（超过则可能是普通文档）

# 背景采样区域（图片边缘的百分比，用于确定背景色）
RECEIPT_BG_SAMPLE_MARGIN = 0.05     # 采样边缘 5% 区域

# 颜色差异阈值（LAB 色彩空间的欧氏距离）
# 与背景色差异超过此值的像素被视为单据区域
# 值越高越严格，避免将普通文字误识别为单据
RECEIPT_COLOR_DIFF_THRESHOLD = 15   # 颜色差异阈值（LAB 空间）

# 轮廓筛选参数
RECEIPT_MIN_CONTOUR_AREA = 10000    # 最小轮廓面积（像素），提高以排除小区域

# 单据区域膨胀参数（确保边缘完全保护）
RECEIPT_DILATE_KERNEL_SIZE = 5      # 膨胀核大小
RECEIPT_DILATE_ITERATIONS = 3       # 膨胀迭代次数

# 边缘白色背景要求（用于区分单据和普通文档）
# 单据必须被白色背景包围，至少3边有白色背景
RECEIPT_EDGE_WHITE_THRESHOLD = 230  # 白色像素的灰度阈值
RECEIPT_EDGE_WHITE_RATIO = 0.70     # 边缘区域白色像素占比阈值
RECEIPT_MIN_WHITE_EDGES = 3         # 至少几边是白色背景（最大4）

# 单据周围背景检查
RECEIPT_SURROUNDING_CHECK_MARGIN = 30  # 检查单据周围多少像素
RECEIPT_SURROUNDING_WHITE_RATIO = 0.50 # 周围区域白色占比阈值

# xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化
# REQ-001 纸张边界与彩色区域最小重叠率（占两者较小者面积的比例），低于此值视为误判拒绝并入
# 实测锚点：票据-粉色 0.997 / 票据-绿色 0.999 / 误判样张 002.tif 0.000，阈值 0.1 对真票据留 10 倍余量
# 注意：receipt.py 经 cfg. 直接访问（未走 ConfigCache，新增键无需同步 cleaner/cache.py 预载列表）
RECEIPT_PAPER_OVERLAP_MIN_RATIO = 0.1

# REQ-002 单据底色近白时纸内背景白化兜底开关（黑白打印单据纸内统一刷白，消除与外部色差）
# 彩色底票据（纸内中位饱和度>=20，如黄/粉/绿纸）不触发白化，行为不受此开关影响（b001/b002 教训）
RECEIPT_NEARWHITE_WHITEN = True

# zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
# REQ-005 票据边缘带浅色划痕修补：**默认关闭**。ae/014 实测划痕为"深色钉帽+浅色杆+褶皱
# 阴影"复合特征，四轮参数调整中浅色域候选始终无法稳定命中杆部，且放宽阈值后出现票据
# 边界粉色涂抹副作用。与 REQ-004 微斑清除同理：物理损伤的语义级修复（区分"划痕"与
# "内容"）超出传统 CV 几何/颜色判据能力边界。代码保留备查（receipt.py 单据模式尾部）。
ENABLE_RECEIPT_SCRATCH_FIX = False


# ============================================================
# 性能优化配置
# ============================================================

# 是否启用性能优化模式
# 开启后会使用 ImageCache 缓存中间结果，减少重复计算
ENABLE_PERFORMANCE_OPTIMIZATION = True

# OCR 性能配置（图片清洁模块）
OCR_MAX_DIMENSION = 2000      # OCR 处理时的最大边长（大图会先缩放）
OCR_DOWNSCALE_THRESHOLD = 2500  # 超过此尺寸才进行缩放
OCR_MIN_DIMENSION = 800       # OCR 最小边长（保证识别精度）

# ============================================================
# 双层PDF OCR 性能配置（极速版）
# ============================================================

# OCR引擎：RapidOCR 3.x，基于ONNX Runtime，GPU/CPU自适应
# 可通过环境变量 DOCSTUDIO_OCR_ENGINE 覆盖（仅支持 "rapidocr"）
OCR_ENGINE = _os.environ.get("DOCSTUDIO_OCR_ENGINE", "rapidocr")

# OCR 快速模式（默认启用，可显著提升速度）
# True: 禁用方向分类器、优化检测边长（提速40-50%，适合正向扫描文档）
# False: 启用方向分类器（识别更准确，但速度慢）
# 可通过环境变量 DOCSTUDIO_OCR_FAST_MODE 覆盖
OCR_FAST_MODE = _os.environ.get("DOCSTUDIO_OCR_FAST_MODE", "1").lower() in ("1", "true", "yes", "y", "on")

# GPU加速配置（自动检测，GPU 优先，无 GPU 自动回退 CPU）
# 程序会自动检测NVIDIA GPU并使用CUDA加速：
#   - YOLO 修图: 通过 PyTorch CUDA 加速（需 torch+cu128）
#   - RapidOCR: 通过 onnxruntime-gpu 加速（需 onnxruntime-gpu 替代 onnxruntime）
# 如需强制使用CPU，设置环境变量: DOCSTUDIO_USE_GPU=0
# 如需指定YOLO GPU，设置环境变量: DOCSTUDIO_YOLO_DEVICE=cuda:0 或 cuda:1
# 如需指定OCR GPU，设置环境变量: DOCSTUDIO_OCR_DEVICE=gpu:0

# 是否强制禁用方向检测（优先级高于前端设置）
# True: 无论前端如何设置，都跳过方向检测，速度提升约50%
# False: 由前端"自动旋转90度页面"选项控制
# 注意：方向检测功能当前不可用
OCR_FORCE_SKIP_ORIENTATION = True

# 双层PDF转换时是否自动修正72DPI的PDF
# True: 如果检测到PDF是72DPI，自动修正页面尺寸
# False: 保持原PDF尺寸不变
OCR_FIX_72DPI_PDF = True

# 当无法从图像读取DPI时，使用此默认DPI值进行修正
# 常见值: 300（扫描仪默认）、200、150
OCR_DEFAULT_DPI = 300

# OCR 检测阶段最大边长
# 值越小速度越快，但可能漏检小字
# 640是极速值，800是快速值，960是平衡值，1280是高精度值，1920是高精度值
# 使用1920确保手写小字和密集表格场景下的检测精度
OCR_DET_LIMIT_SIDE_LEN = 1920

# OCR 识别批次大小
# 值越大速度越快，但内存占用更高
# GPU建议8-16，CPU建议4-6
OCR_REC_BATCH_NUM = 8

# 方向检测使用的缩略图最大边长（方向检测已禁用，此项暂不生效）
OCR_ORIENTATION_MAX_DIM = 960

# ============================================================
# OCR 图像预处理配置（关键性能优化）
# ============================================================

# OCR处理前的最大图像边长（超过此值会先缩放再处理）
# 值越大识别越准确，但速度越慢
# 2048: 平衡模式（推荐）
# 960: 极速模式（可能漏识别小字）
# 4096: 高精度模式（速度慢但识别全）
OCR_MAX_IMAGE_DIM = 4096

# 是否启用OCR图像预缩放
# True: 所有图像都会先缩放再OCR（速度快但可能漏字）
# False: 不主动缩放，但大图(>2048px)仍会自动缩放以提升速度
OCR_PRESCALE_ENABLED = False

# 分块OCR阈值（预缩放后通常不需要分块）
# 设为很大的值，等于禁用分块处理
OCR_TILE_THRESHOLD = 9999

# 分块大小（像素）- 由于禁用分块，此值不影响
OCR_TILE_SIZE = 1000

# 分块重叠（像素）- 由于禁用分块，此值不影响
OCR_TILE_OVERLAP = 50

# CPU线程数（关键加速参数）
# 设置为CPU核心数可获得最大加速
# 0=自动检测CPU核心数
OCR_CPU_THREADS = 0

# 多页并行处理（PaddleOCR 路径，TODO — 未实现）
# 注意：RapidOCR 引擎（ocr_rapid.py）已内置 GPU 串行/CPU 多线程并行，
# 此参数仅影响 ocr_pdf.py 的 PaddleOCR 遗留路径
OCR_MAX_PARALLEL_PAGES = 0

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-004 OCR 流水线预取页数上限
# GPU 模式下，渲染/解码（CPU）与 OCR 推理（GPU）流水线重叠执行
# 预取队列上限：32 页（估算 1650×2396×3 ≈ 11.8MB/页，32 页 ≈ 378MB）
# 生产 30GB 内存可配置 64（约 756MB）
OCR_PAGE_PREFETCH_LIMIT = 32
# 预取线程数（min(cpu_count-1, 4)），渲染/解码线程池大小
OCR_PREFETCH_WORKERS = 0  # 0=自动 min(cpu_count-1, 4)

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-008/015 GPU 并发与多进程配置
# GPU 并发许可数：1=独占（等价于旧 Lock），2+ = 允许多任务同时使用 GPU
# 生产 RTX 5070 12GB 显存实测单进程约 5.9GB，2 进程并发约 11.8GB（接近上限）
# 默认 1（保守），生产验证后可调 2
GPU_CONCURRENCY_PERMITS = 1

# 多进程 worker 配置（默认关闭，需生产实测后开启）
# GPU OCR 并行进程上限（0=禁用多进程，使用单进程线程池）
GPU_OCR_PARALLEL_PROCESSES = 0
# 清洁器并行进程上限（0=禁用多进程，使用单进程串行）
CLEANER_PARALLEL_PROCESSES = 0

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-009 上传预解码缓存
# 上传完成后预解码图片到内存缓存，一键修图与生成PDF复用
# 减少重复 imdecode 与 DPI 读取
# True=启用预解码缓存，False=禁用（每次从磁盘读取）
UPLOAD_PREDECODE_CACHE_ENABLED = False
# 预解码缓存最大图片数（超出时 LRU 淘汰）
UPLOAD_PREDECODE_CACHE_MAX = 50

# PDF 渲染配置
PDF_BASE_DPI = 300            # PDF 渲染基础 DPI
PDF_MAX_RENDER_DIM = 2000     # PDF 渲染的最大边长

# 图片处理配置
# 大图预缩放由 OCR_PRESCALE_ENABLED / OCR_MAX_IMAGE_DIM 控制（见 ocr_rapid.py / ocr_pdf.py）


# ============================================================
# DPI 自适应缩放
# ============================================================

REFERENCE_DPI = 300  # 所有半径参数的参考 DPI


def scale_radius(radius: int, dpi: int) -> int:
    """将半径从参考 DPI 缩放到实际 DPI"""
    if dpi == REFERENCE_DPI or dpi <= 0:
        return radius
    return max(1, round(radius * dpi / REFERENCE_DPI))


# ============================================================
# 形态学操作核尺寸（DPI自适应缩放）
# ============================================================

# xuechong 2026-07-19 研发需求-0203-cleaner模块魔法数字优化
# 以下参数用于 cleaner.py 中的形态学操作（膨胀、腐蚀、开闭运算）
# 所有尺寸通过 scale_radius() 进行 DPI 自适应缩放

# 轻量级核（膨胀/腐蚀）
MORPH_KERNEL_TINY = 2         # 轻度膨胀/腐蚀（如杂质掩码膨胀）
MORPH_KERNEL_SMALL = 3        # 内容膨胀、腐蚀（如内容区域处理）
MORPH_KERNEL_MEDIUM = 5       # 中等膨胀/腐蚀（如印章膨胀、纸张腐蚀）

# 中等核（闭操作）
MORPH_KERNEL_LARGE = 20       # 闭操作、椭圆核（如票据边界闭操作）
MORPH_KERNEL_XLARGE = 25      # 椭圆核（如OCR保护区域膨胀）

# 大核（闭操作）
MORPH_KERNEL_XXLARGE = 40     # 大闭操作（如纸张区域闭操作）
MORPH_KERNEL_HUGE = 50        # 超大闭操作（如票据边界闭操作）

# 椭圆核宽高（用于椭圆形形态学操作）
MORPH_ELLIPSE_WIDTH = 20      # 椭圆核宽度
MORPH_ELLIPSE_HEIGHT = 10     # 椭圆核高度


# ============================================================
# xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# form-in 文件库推送与云盘存储连接：从 url.conf 读取，默认全部关闭/为空。
# FORM_IN_ENABLED 不为 true 时推送模块完全不工作，scanner 行为与升级前一致
# ============================================================

# 推送总开关（true 才推送，其余任何值都视为关闭）
FORM_IN_ENABLED = _url_conf.get("FORM_IN_ENABLED", "false").strip().lower() == "true"
# form-in 服务地址（含协议与端口，不带末尾斜杠，如 http://192.168.1.10:4102）
FORM_IN_ADDRESS = _url_conf.get("FORM_IN_ADDRESS", "").strip().rstrip("/")
# form-in 推送专用账号（form-in 用户管理里预先建好）
FORM_IN_USERNAME = _url_conf.get("FORM_IN_USERNAME", "").strip()
# form-in 推送专用账号口令（只放 url.conf，不进代码）
FORM_IN_PASSWORD = _url_conf.get("FORM_IN_PASSWORD", "").strip()
# 存储模式：mongodb=直写 MongoDB（服务器环境）；localdisk=写本地 bddata 目录（Windows 本地开发，与 form-in IDEA 环境共用）
STORE_MODE = _url_conf.get("STORE_MODE", "mongodb").strip().lower()
# MongoDB 连接（host:port）
MONGO_HOST = _url_conf.get("MONGO_HOST", "").strip()
# MongoDB 库名（云盘库）
MONGO_DBNAME = _url_conf.get("MONGO_DBNAME", "").strip()
# MongoDB 账号
MONGO_USERNAME = _url_conf.get("MONGO_USERNAME", "").strip()
# MongoDB 口令（只放 url.conf，不进代码）
MONGO_PASSWORD = _url_conf.get("MONGO_PASSWORD", "").strip()
# localdisk 模式的 bddata 目录（form-in Windows 开发环境的云盘模拟目录）
LOCAL_DISK_DIR = _url_conf.get("LOCAL_DISK_DIR", "").strip()
