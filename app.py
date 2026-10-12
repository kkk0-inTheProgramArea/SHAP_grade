"""
成绩数据清洗 + 成绩预测(SHAP) 网页小程序 后端
- 上传 xlsx / csv（兼容不同表头，网页内做列映射）
- 自动剔除「缺扫 / 缺考 / 0分 / 空值」等无效学生
- 可选：训练 LightGBM 预测科目成绩，输出 SHAP 特征重要性叠加图
"""
import os
import io
import json
import uuid
import base64
import threading
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from flask import Flask, request, jsonify, send_file

BASE = Path(__file__).resolve().parent
FONT_PATH = BASE / "static" / "NotoSansSC.ttf"


# ══════════════════════════════════════════════════════════════════════
#  ★★★ 常用设置区 ★★★
#  想调整网页的默认行为，只需要改这一段就够了（改完重新发布即可生效）。
#  每一行右边的注释说明了它的作用，不确定的就别动。
# ══════════════════════════════════════════════════════════════════════

# 默认要剔除的“无效成绩”文本标记（网页第3步的输入框默认值，老师仍可在页面上改）
DEFAULT_INVALID_TEXT = "缺扫,缺考"

# 默认是否剔除「0 分」「空值」（True=默认勾选）
DEFAULT_DROP_ZERO = True
DEFAULT_DROP_BLANK = True

# SHAP 分成两张图分别展示，这里分别设置每张图最多显示多少个特征
SHAP_TOP_N_SCORE = 20    # 图1：各题/各科「得分」类特征，最多显示多少个
SHAP_TOP_N_OPTION = 20   # 图2：各题「选项」类特征（如 12_选项_C），最多显示多少个

# 为了「让 SHAP 值更稳定」，会做多次随机拆分建模、再取平均 SHAP 值。
# 跑的轮数越多、结果越稳定，但越慢（一般 10 轮就够；建议 5~30）
SHAP_N_RUNS = 10

# SHAP 图清晰度，越大越清晰但文件也越大（建议 150~400）
FIG_DPI = 300

# SHAP 柱状图的颜色（可填英文色名或 #十六进制）
BAR_COLOR = "#c6dbef"

# 单次上传文件的大小上限（单位：MB）
MAX_UPLOAD_MB = 50

# ══════════════════════════════════════════════════════════════════════
#  ★ 页脚「反馈方式」★  —— 填了哪个就显示哪个，没填的会自动隐藏
#   想加联系方式，就把对应的引号里填上；不想要的就留空 ""。
# ══════════════════════════════════════════════════════════════════════

# 反馈邮箱：页脚会显示成「✉ 邮箱地址」，点一下自动打开邮件软件，主题和正文都写好了
FEEDBACK_EMAIL = "dmeiyue@gmail.com"

# 反馈 QQ 号：页脚显示「QQ：号码」，点一下自动复制到剪贴板
FEEDBACK_QQ = ""

# 反馈微信号：页脚显示「微信：号码」，点一下自动复制
FEEDBACK_WECHAT = ""

# 在线问卷 / 收集表链接（腾讯问卷、问卷星、腾讯文档收集表、金数据…都可以）
# 优点：能收集结构化信息、可以匿名、手机上填更方便
FEEDBACK_URL = ""
FEEDBACK_URL_TEXT = "📝 在线反馈表"      # 上面那个链接显示成什么文字

# 一句话说明，显示在反馈方式前面（不想要就留空 ""）
FEEDBACK_TIP = "使用中遇到问题或有建议？欢迎反馈："

# 本机调试时的端口（云端发布会自动使用平台分配的端口，不受这里影响）
LOCAL_PORT = 5000

# ══════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024  # 单文件上限

# ---------- 重量级依赖延迟加载 ----------
# matplotlib / lightgbm / shap / sklearn 体积大、占用内存多、导入慢。
# 若在模块顶层导入，容器冷启动会变慢、内存压力大，容易被平台判定异常而返回 502。
# 因此仅在真正需要跑 SHAP 时才导入，让「上传 / 健康检查」保持轻量快速。
_PLT = None


def init_plotting():
    """按需初始化绘图环境（含中文字体），返回 pyplot 模块。"""
    global _PLT
    if _PLT is not None:
        return _PLT
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    if FONT_PATH.exists():
        font_manager.fontManager.addfont(str(FONT_PATH))
        _fp = font_manager.FontProperties(fname=str(FONT_PATH))
        plt.rcParams["font.sans-serif"] = [_fp.get_name()]
    else:
        plt.rcParams["font.sans-serif"] = [
            "SimHei", "Microsoft YaHei", "WenQuanYi Zen Hei",
            "Noto Sans CJK SC", "Arial Unicode MS",
        ]
    plt.rcParams["axes.unicode_minus"] = False
    _PLT = plt
    return _PLT

# 内存存储（不依赖磁盘，云端只读/易失文件系统也能跑）
SESSIONS = {}   # session_id -> DataFrame
RESULTS = {}    # token -> {"csv": bytes, "png": bytes|None}

# ---------- 使用次数统计 ----------
# 两个指标：
#   visits = 访问次数：有人打开这个网页就 +1
#   runs   = 使用次数：真正点「开始处理」跑完一次清洗/分析才 +1（更能代表"被用了几次"）
# 优先存到同目录的 usage_stats.json，服务重启也不会归零；
# 万一目录不让写（云端只读），自动退回内存计数，绝不会影响正常使用。
STATS_FILE = BASE / "usage_stats.json"
STATS = {"visits": 0, "runs": 0}
_STATS_LOCK = threading.Lock()


def _load_stats():
    """启动时把上次的计数读回来。"""
    try:
        if STATS_FILE.exists():
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            STATS["visits"] = int(data.get("visits", 0))
            STATS["runs"] = int(data.get("runs", 0))
    except Exception:
        pass   # 读不了就从 0 开始，不影响使用


def _save_stats():
    """把计数写回文件（写不了就算了，内存里的数字仍然有效）。"""
    try:
        STATS_FILE.write_text(json.dumps(STATS, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def bump_stat(key):
    """给某个计数 +1，并返回累加后的值。key = "visits" / "runs"。"""
    with _STATS_LOCK:
        STATS[key] = int(STATS.get(key, 0)) + 1
        _save_stats()
        return STATS[key]


_load_stats()


# ---------------------- 工具函数 ----------------------
def read_any(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """兼容 xlsx / csv，csv 自动尝试多种中文编码。"""
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(io.StringIO(file_bytes.decode(enc)))
        except (UnicodeDecodeError, LookupError) as e:
            last_err = e
            continue
    return pd.read_csv(io.StringIO(file_bytes.decode("gbk", errors="replace")))


# 列角色关键词表（按优先级判断）
_ID_KEYS = [
    "学号", "学籍号", "籍号", "考生号", "考号", "准考证", "考籍", "座号",
    "姓名", "名字", "性别", "身份证", "班级", "行政班", "教学班", "班号",
    "班", "学校", "年级", "考场", "name", "id",
]
# 聚合性成绩列（不是单题/单科得分）：与目标列高度相关，默认忽略以防数据泄漏
_AGG_KEYS = ["成绩", "总分", "综合分", "score", "total"]
# 排名列
_RANK_KEYS = ["排名", "位次", "rank"]

# 判定「整列都是空的」：全 NaN、或全是空字符串 / "nan" 文本。
# Excel 表格右侧经常拖着一排无名空列，这类列要直接忽略掉，
# 否则既会干扰列映射，又会因为列名里带 "name" 被误判成姓名类的标识列。
_BLANK_TEXTS = {"", "nan", "none", "null"}


def _blank_col_mask(df: pd.DataFrame):
    """返回布尔数组：True 表示这一列整列都是空的。"""
    mask = []
    for c in df.columns:
        s = df[c]
        blank = s.isna() | s.astype(str).str.strip().str.lower().isin(_BLANK_TEXTS)
        mask.append(bool(blank.all()))
    return pd.Series(mask, index=df.columns)


def suggest_columns(df: pd.DataFrame) -> dict:
    """根据列名/取值，自动建议各列角色。"""
    cols = list(df.columns)

    # 完全空白的列、以及 Excel 自动生成的"Unnamed"无名列，都不参与判断，一律「忽略」
    bm = _blank_col_mask(df)
    empty_cols = [c for c in cols
                  if bm[c] or str(c).startswith("Unnamed") or str(c).strip() == ""]

    # ---------- 目标列：按优先级挑（科目成绩 > 总成绩/总分 > 泛指成绩）----------
    target = None
    for group in (["科目成绩"], ["总成绩", "总分", "综合分", "score", "total"], ["成绩"]):
        for c in cols:
            if c in empty_cols:
                continue
            if any(k in str(c).lower() for k in group):
                target = c
                break
        if target is not None:
            break
    if target is None:
        num = [c for c in cols if c not in empty_cols and pd.api.types.is_numeric_dtype(df[c])]
        if num:
            target = num[-1]

    option_cols, id_cols, score_cols = [], [], []
    for c in cols:
        if c == target or c in empty_cols:
            continue
        n = str(c).lower()

        # 1) 选项列：取值绝大多数是单个字母 A~H（容忍少量混进的「缺扫/缺考」）
        vals = df[c].dropna().astype(str).str.strip().str.upper()
        non_null_txt = len(vals)
        if non_null_txt > 0:
            letters = vals[vals.str.match(r"^[A-H]$")]
            uniq = set(letters.unique())
            if len(uniq) >= 2 and len(letters) / non_null_txt >= 0.5:
                option_cols.append(c)
                continue

        # 2) 排名列（班级排名/学校排名/总排名）不是得分，默认忽略
        if any(k in n for k in _RANK_KEYS):
            continue

        # 3) 标识列（学号/考生号/姓名/行政班…）：保留在结果里，但不参与建模
        if any(k in n for k in _ID_KEYS):
            id_cols.append(c)
            continue

        # 4) 其他聚合成绩列（客观题成绩/主观题成绩…）：默认忽略，避免与目标列重复
        if any(k in n for k in _AGG_KEYS):
            continue

        # 5) 得分列：绝大多数取值可转成数值（容忍少量缺扫/缺考文本、空白单元格）
        blank_mask = df[c].isna() | df[c].astype(str).str.strip().str.lower().isin(_BLANK_TEXTS)
        non_null = int((~blank_mask).sum())
        if non_null > 0:
            coerced = pd.to_numeric(df[c].where(~blank_mask), errors="coerce")
            if coerced.notna().sum() / non_null >= 0.7:
                score_cols.append(c)

    return {
        "target": target,
        "score_cols": score_cols,
        "option_cols": option_cols,
        "id_cols": id_cols,
        "empty_cols": empty_cols,
    }


def clean_data(df: pd.DataFrame, target, invalid_text, drop_zero, drop_blank):
    """剔除无效学生行，返回 (cleaned_df, deleted_count)。"""
    if target not in df.columns:
        raise ValueError(f"目标列「{target}」不存在")
    markers = [m.strip() for m in (invalid_text or "").split(",") if m.strip()]
    keep_mask = pd.Series(True, index=df.index)

    t = df[target]
    # 文本标记（缺扫/缺考等）
    if markers:
        str_t = t.astype(str).str.strip()
        for m in markers:
            keep_mask &= (str_t != m)
    # 空值
    if drop_blank:
        keep_mask &= t.notna()
        # 空字符串
        str_t2 = t.astype(str).str.strip()
        keep_mask &= (str_t2 != "") & (str_t2.str.lower() != "nan")
    # 0 分
    if drop_zero:
        num_t = pd.to_numeric(t, errors="coerce")
        keep_mask &= ~((num_t == 0) & num_t.notna())

    deleted = int((~keep_mask).sum())
    return df[keep_mask].copy(), deleted


def _draw_beeswarm_bar(cols, X_test, shap_values, top_n, title=None, mean_abs=None):
    """对「一组」特征，画 柱状图(平均|SHAP|) + beeswarm 散点 的叠加图。

    - cols：本组要参与排名的特征名（得分列 或 选项 one-hot 列）
    - 组内按平均|SHAP| 独立排序，只取前 top_n 个
    - mean_abs：若提供（多轮平均后的「平均|SHAP|」数组，长度=全部特征数），
      则用它来排名和决定柱高，使结果更稳定；散点仍用本组 shap_values 的分布。
    - 返回 (base64_png, importance_rows)；本组没有特征时返回 (None, [])
    """
    if not cols:
        return None, []
    plt = init_plotting()

    all_cols = list(X_test.columns)
    idx_all = [all_cols.index(c) for c in cols]
    sv_g = shap_values[:, idx_all]                  # [n_samples, len(cols)]
    if mean_abs is not None:
        # 用多轮平均后的数值（更稳定），而不是单轮
        ma_g = np.asarray(mean_abs, dtype=float)[idx_all]
    else:
        ma_g = np.abs(sv_g).mean(axis=0)            # 每个特征的平均|SHAP|（单轮）

    # 组内排序：只保留前 top_n 个
    k = max(1, min(top_n, len(cols)))
    order = list(np.argsort(-ma_g)[:k])
    feats_top = [cols[i] for i in order]
    sv_top = sv_g[:, order]
    ma_top = ma_g[order]                    # 与排序对齐的平均|SHAP|（柱高用这个）

    # 倒序：最重要的画在最上面
    feats_rev = feats_top[::-1]
    sv_rev = sv_top[:, ::-1]
    ma_rev = ma_top[::-1]                    # 柱高=平均|SHAP|，保证与排名一致
    X_rev = X_test[feats_rev]

    fig, ax_bar = plt.subplots(figsize=(10, max(3.2, 0.42 * len(feats_rev) + 1.6)))
    y_pos = np.arange(len(feats_rev))
    ax_bar.barh(y_pos, ma_rev, height=0.65, color=BAR_COLOR, alpha=0.9)
    for i, v in enumerate(ma_rev):
        ax_bar.text(v + ma_rev.max() * 0.01, i, f"{v:.4f}", va="center", fontsize=9)
    ax_bar.set_yticks(y_pos)
    ax_bar.set_yticklabels(feats_rev, fontsize=10)
    ax_bar.set_xlabel("平均|SHAP|值", fontsize=12)
    if title:
        ax_bar.set_title(title, fontsize=13, pad=40)
    ax_bar.grid(axis="x", linestyle="--", alpha=0.3)

    ax_swarm = ax_bar.twiny()
    cmap = plt.cm.coolwarm
    rng = np.random.default_rng(42)
    sc = None
    for i, feat in enumerate(feats_rev):
        sv = sv_rev[:, i]
        fv = X_rev[feat].values.astype(float)
        if np.max(fv) == np.min(fv):
            cv = np.full_like(fv, 0.5)
        else:
            cv = (fv - np.min(fv)) / (np.max(fv) - np.min(fv))
        yj = rng.normal(loc=i, scale=0.10, size=len(sv))
        sc = ax_swarm.scatter(sv, yj, c=cv, cmap=cmap, s=18, alpha=0.75, edgecolors="none")
    ax_swarm.set_xlabel("SHAP值（beeswarm 分布）", fontsize=12)
    ax_swarm.grid(False)
    if sc is not None:
        plt.colorbar(sc, ax=ax_swarm, pad=0.02)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")

    importance = [{"feature": str(f), "shap": float(ma_g[i])}
                  for f, i in zip(feats_top, order)]
    return b64, importance


def run_shap(cleaned: pd.DataFrame, target, score_cols, option_cols,
             top_n_score=SHAP_TOP_N_SCORE, top_n_option=SHAP_TOP_N_OPTION,
             n_runs=SHAP_N_RUNS):
    """训练 LightGBM + 计算 SHAP 值，并**分成两张图**输出：

    - 图1（score）：各题 / 各科「得分」类特征（如 生物13题、18_得分）
    - 图2（option）：各题「选项」类特征（如 12_选项_C）

    返回 dict：{"score": {"image", "importance"}, "option": {"image", "importance"}}
    """
    # 重量级依赖：仅在真正做预测分析时才导入（见文件顶部说明）
    init_plotting()
    import lightgbm as lgb
    import shap
    from sklearn.model_selection import train_test_split

    work = cleaned.copy()
    # 目标转数值
    y = pd.to_numeric(work[target], errors="coerce")
    work = work[y.notna()].copy()
    y = y[y.notna()]

    # One-Hot 选项列
    onehot_cols = [c for c in option_cols if c in work.columns]
    if onehot_cols:
        work = pd.get_dummies(work, columns=onehot_cols, prefix=onehot_cols)

    # 特征：得分列（数值）+ 选项 one-hot
    # 注意：真实成绩表里科目列常常混进几条「缺扫 / 缺考」文本，pandas 会把整列
    # 判定成 object（文本）类型。所以这里不能要求“原生数值列”，只要多数取值能转成
    # 数值就当成得分特征，个别文本值在转换后会变成「空」，由后面 fillna(0) 兜住。
    feats = []
    for c in score_cols:
        if c not in work.columns:
            continue
        coerced = pd.to_numeric(work[c], errors="coerce")
        non_null = work[c].notna().sum()
        if non_null > 0 and coerced.notna().sum() / non_null >= 0.5:
            work[c] = coerced          # 文本值 → NaN
            feats.append(c)
    feat_candidates = feats + [c for c in work.columns if "_选项_" in c]
    feat_candidates = [c for c in feat_candidates if c in work.columns]
    if not feat_candidates:
        raise ValueError("没有可用特征列，无法进行预测分析。请在「列角色映射」里把至少一个科目/题目列指定为「得分列」或「选项列」。")

    X = work[feat_candidates].apply(pd.to_numeric, errors="coerce").fillna(0)
    if X.shape[1] == 0 or len(X) < 10:
        raise ValueError("样本量或特征不足，无法进行可靠的预测分析（至少需要约10条有效数据）。")

    # ---------- 多轮随机拆分建模，取平均 SHAP 值（让结果更稳定）----------
    # 单次只在「一组随机 80/20 拆分」的小测试集上算 SHAP，测试样本少时单个 SHAP
    # 值噪声大、排名容易抖。这里跑 n_runs 轮（每轮用不同随机种子做不同拆分），
    # 把每轮的「平均|SHAP|」累加起来再除以轮数，得到更稳健的特征重要性。
    all_cols = list(X.columns)
    mean_abs_sum = np.zeros(X.shape[1])   # 累积每个特征的「平均|SHAP|」
    last_shap = None
    last_X_test = None

    n_runs = max(1, int(n_runs))
    for ri in range(n_runs):
        rs = 42 + ri                   # 每轮不同种子 → 不同的随机拆分
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=rs
        )
        # 自适应参数：班级数据量通常不大（几十条），而 LightGBM 默认 min_child_samples=20，
        # 在小样本下会导致「一个叶子都分不出来」→ 模型退化成常数、SHAP 全为 0。
        # 这里按训练样本量放宽限制，保证小班数据也能得到有意义的分析结果。
        n_train = len(X_train)
        model = lgb.LGBMRegressor(
            random_state=rs,
            verbose=-1,
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=max(4, min(31, n_train // 4)),
            min_child_samples=max(2, min(20, n_train // 10)),
            subsample=0.9,
            colsample_bytree=0.9,
        )
        model.fit(X_train, y_train)

        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X_test)
        mean_abs_sum += np.abs(sv).mean(axis=0)
        last_shap = sv
        last_X_test = X_test

    # 多轮平均后的「平均|SHAP|」用于排名与柱高；散点分布用最后一轮的 SHAP
    mean_abs_avg = mean_abs_sum / n_runs
    shap_values = last_shap
    X_test = last_X_test

    # ---------- 分成两组特征，分别出图 ----------
    # 组1：得分列（数值型，各题/各科分数）
    score_feats = [c for c in feats if c in X_test.columns]
    # 组2：选项 One-Hot 列（各题选项，如 12_选项_C）
    option_feats = [c for c in X_test.columns if "_选项_" in c]

    img_s, imp_s = _draw_beeswarm_bar(
        score_feats, X_test, shap_values, top_n_score,
        title="图1  各题 / 各科得分 —— SHAP 特征重要性",
        mean_abs=mean_abs_avg,
    )
    img_o, imp_o = _draw_beeswarm_bar(
        option_feats, X_test, shap_values, top_n_option,
        title="图2  各题选项 —— SHAP 特征重要性",
        mean_abs=mean_abs_avg,
    )
    if img_s is None and img_o is None:
        raise ValueError("没有可用于出图的特征，请检查「得分列 / 选项列」是否选对。")

    return {
        "score": {"image": img_s, "importance": imp_s},
        "option": {"image": img_o, "importance": imp_o},
    }


# ---------------------- 路由 ----------------------
@app.route("/")
def index():
    return send_file(BASE / "templates" / "index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    try:
        if "file" not in request.files:
            return jsonify({"error": "未收到文件"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "文件名为空"}), 400
        file_bytes = f.read()

        df = read_any(file_bytes, f.filename)
        if df.empty:
            return jsonify({"error": "文件解析后为空，请检查内容。"}), 400

        # 丢掉没用的列：完全空白的列、以及 Excel 自动生成的 "Unnamed" 无名列
        # （这些列要么空着，要么名不对题，留着只会干扰列映射、混进清洗结果）
        bm = _blank_col_mask(df)
        keep = [c for c in df.columns
                if not bm[c] and not str(c).startswith("Unnamed") and str(c).strip() != ""]
        n_before = df.shape[1]
        df = df[keep]
        dropped_empty = n_before - df.shape[1]
        if df.shape[1] == 0:
            return jsonify({"error": "文件里没有任何有内容的列，请检查文件是否选错。"}), 400

        columns = []
        for c in df.columns:
            sample = df[c].dropna().head(3).tolist()
            sample = [str(x) for x in sample]
            columns.append({
                "name": str(c),
                "dtype": str(df[c].dtype),
                "sample": sample,
            })
        suggestions = suggest_columns(df)
        sid = uuid.uuid4().hex
        SESSIONS[sid] = df
        return jsonify({
            "session_id": sid,
            "row_count": int(len(df)),
            "columns": columns,
            "suggestions": suggestions,
            "dropped_empty": dropped_empty,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"解析失败：{e}"}), 500


@app.route("/api/process", methods=["POST"])
def process():
    try:
        data = request.get_json(force=True)
        sid = data.get("session_id")
        if not sid or sid not in SESSIONS:
            return jsonify({"error": "会话已失效，请重新上传文件。"}), 400

        target = data.get("target")
        score_cols = data.get("score_cols", [])
        option_cols = data.get("option_cols", [])
        invalid_text = data.get("invalid_text", DEFAULT_INVALID_TEXT)
        drop_zero = bool(data.get("drop_zero", DEFAULT_DROP_ZERO))
        drop_blank = bool(data.get("drop_blank", DEFAULT_DROP_BLANK))
        do_predict = bool(data.get("do_predict", False))

        df = SESSIONS[sid]
        original = len(df)
        cleaned, deleted = clean_data(df, target, invalid_text, drop_zero, drop_blank)

        token = uuid.uuid4().hex
        csv_bytes = cleaned.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        # 预览（前 50 行，仅保留常用列顺序）
        id_cols = data.get("id_cols", [])
        ordered = [c for c in id_cols if c in cleaned.columns]
        ordered += [c for c in score_cols if c in cleaned.columns]
        ordered += [c for c in option_cols if c in cleaned.columns]
        if target in cleaned.columns:
            ordered.append(target)
        remaining = [c for c in cleaned.columns if c not in ordered]
        ordered += remaining
        preview_df = cleaned[ordered].head(50)
        preview = {
            "columns": list(preview_df.columns),
            "rows": preview_df.astype(object).where(pd.notna(preview_df), None).values.tolist(),
        }

        result = {
            "token": token,
            "original_count": original,
            "cleaned_count": int(len(cleaned)),
            "deleted_count": deleted,
            "preview": preview,
        }

        png_bytes = None
        if do_predict:
            # 多轮取平均的轮数（前端可调，默认 SHAP_N_RUNS；这里限制 1~50 防止滥用）
            try:
                n_runs = int(data.get("n_runs", SHAP_N_RUNS))
            except (TypeError, ValueError):
                n_runs = SHAP_N_RUNS
            n_runs = max(1, min(50, n_runs))
            shap_res = run_shap(cleaned, target, score_cols, option_cols, n_runs=n_runs)
            # 两张图：score=得分类特征；option=选项类特征（各自独立排名）
            result["shap"] = shap_res
            main_img = shap_res["score"]["image"] or shap_res["option"]["image"]
            if main_img:
                png_bytes = base64.b64decode(main_img)

        RESULTS[token] = {"csv": csv_bytes, "png": png_bytes}
        runs = bump_stat("runs")          # 成功跑完一次 = 被使用一次
        result["runs"] = runs
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"处理失败：{e}"}), 500


@app.route("/api/download/<token>")
def download(token):
    r = RESULTS.get(token)
    if not r:
        return jsonify({"error": "文件不存在或已过期"}), 404
    return send_file(io.BytesIO(r["csv"]), as_attachment=True,
                     download_name="清洗后成绩.csv", mimetype="text/csv")


@app.route("/api/shap/<token>")
def shap_img(token):
    r = RESULTS.get(token)
    if not r or not r.get("png"):
        return jsonify({"error": "图片不存在"}), 404
    return send_file(io.BytesIO(r["png"]), mimetype="image/png")


@app.route("/api/template")
def template():
    """下载示例模板（题目格式）。"""
    p = BASE / "sample_成绩.xlsx"
    if not p.exists():
        return jsonify({"error": "模板不存在"}), 404
    return send_file(str(p), as_attachment=True, download_name="成绩数据示例模板.xlsx")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/stats")
def stats():
    """页面统计：每打开一次网页调一次，访问次数 +1。

    同时把「使用次数」和页脚要显示的反馈方式告诉前端。
    """
    n = bump_stat("visits")
    return jsonify({
        "visits": n,                                # 访问次数（打开网页）
        "runs": int(STATS.get("runs", 0)),          # 使用次数（跑完一次清洗/分析）
        "feedback_email": FEEDBACK_EMAIL,
        "feedback_qq": FEEDBACK_QQ,
        "feedback_wechat": FEEDBACK_WECHAT,
        "feedback_url": FEEDBACK_URL,
        "feedback_url_text": FEEDBACK_URL_TEXT,
        "feedback_tip": FEEDBACK_TIP,
    })


if __name__ == "__main__":
    # 云端发布时会通过环境变量 PORT 指定端口；本机运行时用 LOCAL_PORT
    port = int(os.environ.get("PORT", LOCAL_PORT))
    print(f"\n  ✅ 服务已启动，请在浏览器打开： http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, threaded=True)
