"""
智能选股系统 Web 界面（Streamlit 版）

- 仅做前端展示与操作入口：选股逻辑完全复用 main.run_all_strategies()，
  与命令行版（python main.py）行为一致，核心代码未改动。
- 启动方式：双击「启动选股界面.bat」，或手动运行：
      streamlit run app.py
"""

import io
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

import main as core

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "db" / "stock.db"

MODE_OPTIONS = {
    "仅个股": "stock",
    "仅ETF": "etf",
    "全部（个股 + ETF）": "all",
}
LIMIT_UP_OPTIONS = {
    "过滤涨停（默认）": "all",
    "不过滤涨停": None,
}

CUSTOM_STRATEGY_NAME = "自定义RSI超卖"
CUSTOM_STRATEGY_COLUMNS = ["ts_code", "rsi_14", "pct_chg", "close"]

# 策略名 -> 策略 key
NAME_TO_KEY = {cfg["name"]: key for key, cfg in core.STRATEGY_LIBRARY.items()}

# 数据更新（增量拉取）相关
FETCH_POOL_OPTIONS = {
    "个股": "stock",
    "ETF": "etf",
}
FETCH_LOG = BASE_DIR / "_fetch_update.log"
FETCH_ERR = BASE_DIR / "_fetch_update_err.log"


def query_db(sql: str) -> pd.DataFrame:
    """查询本地数据库（只读用途）"""
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


def get_data_status() -> dict:
    """数据概况（只读，不影响任何选股逻辑）"""
    status = {}
    try:
        df = query_db("SELECT MAX(cal_date) AS d FROM trading_calendar WHERE is_open = 1")
        status["calendar"] = str(df["d"].iloc[0]) if not df.empty and pd.notna(df["d"].iloc[0]) else "未知"
    except Exception:
        status["calendar"] = "未知"
    try:
        df = query_db("SELECT MAX(trade_date) AS d, COUNT(DISTINCT ts_code) AS n FROM daily_raw")
        status["stock_date"] = str(df["d"].iloc[0]) if not df.empty and pd.notna(df["d"].iloc[0]) else "无数据"
        status["stock_count"] = int(df["n"].iloc[0]) if not df.empty else 0
    except Exception:
        status["stock_date"], status["stock_count"] = "无数据", 0
    try:
        df = query_db("SELECT MAX(trade_date) AS d, COUNT(DISTINCT ts_code) AS n FROM etf_daily")
        status["etf_date"] = str(df["d"].iloc[0]) if not df.empty and pd.notna(df["d"].iloc[0]) else "无数据"
        status["etf_count"] = int(df["n"].iloc[0]) if not df.empty else 0
    except Exception:
        status["etf_date"], status["etf_count"] = "无数据", 0
    return status


def build_excel_bytes(all_results: dict, resonance_df: pd.DataFrame) -> bytes:
    """生成与命令行版相同结构的 Excel（内存版，供页面下载）"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in all_results.items():
            df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=False)
        if resonance_df is not None and not resonance_df.empty:
            resonance_df.to_excel(writer, sheet_name="共振分析", index=False)
    return buf.getvalue()


def read_tail(path: Path, max_chars: int = 1200) -> str:
    """读取文件末尾内容（容错处理编码问题）"""
    try:
        if not path.exists():
            return ""
        text = path.read_bytes().decode("utf-8", errors="replace")
        return text[-max_chars:]
    except Exception:
        return ""


def start_fetch(pool_type: str) -> subprocess.Popen:
    """后台启动增量数据更新（与命令行 python -m data.fetcher 完全一致）"""
    cmd = [sys.executable, "-m", "data.fetcher", "--mode", "incremental"]
    if pool_type == "etf":
        cmd += ["--pool_type", "etf"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    with open(FETCH_LOG, "w", encoding="utf-8") as fout, open(FETCH_ERR, "w", encoding="utf-8") as ferr:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=fout,
            stderr=ferr,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return proc


def render_results(run_output: dict):
    """展示一次运行结果"""
    latest_date = run_output["latest_date"]
    all_results = run_output["all_results"]
    resonance_df = run_output["resonance_df"]

    st.success(f"选股完成！最新交易日：{latest_date}，结果已同时导出到：{run_output['excel_path'].name}")

    # 总览
    overview_rows = []
    for key, cfg in core.STRATEGY_LIBRARY.items():
        if not core.strategy_belongs_to_mode(cfg, run_output["mode"]):
            continue
        df = all_results.get(cfg["name"], pd.DataFrame())
        overview_rows.append({"策略": cfg["name"], "说明": cfg.get("description", ""), "命中数量": len(df)})
    if run_output["mode"] in ("all", "stock"):
        df = all_results.get(CUSTOM_STRATEGY_NAME, pd.DataFrame())
        overview_rows.append({"策略": CUSTOM_STRATEGY_NAME, "说明": "RSI<30 且当日涨幅>2%（固定取前10）", "命中数量": len(df)})
    st.subheader("📋 结果总览")
    st.dataframe(pd.DataFrame(overview_rows), width="stretch", hide_index=True)

    # 各策略明细
    tab_names = [row["策略"] for row in overview_rows] + ["共振分析"]
    tabs = st.tabs(tab_names)
    for tab, row in zip(tabs, overview_rows):
        with tab:
            name = row["策略"]
            df = all_results.get(name, pd.DataFrame())
            if df.empty:
                st.info("该策略当天没有选出标的。")
                continue
            if name == CUSTOM_STRATEGY_NAME:
                columns = CUSTOM_STRATEGY_COLUMNS
            else:
                columns = core.DISPLAY_COLUMNS_MAP.get(NAME_TO_KEY.get(name, ""))
            if columns:
                columns = [c for c in columns if c in df.columns]
                st.dataframe(df[columns], width="stretch", hide_index=True)
            else:
                st.dataframe(df, width="stretch", hide_index=True)
            st.caption(f"共 {len(df)} 条")

    with tabs[-1]:
        if resonance_df.empty:
            st.info("没有标的被多个策略同时选中。")
        else:
            st.dataframe(resonance_df, width="stretch", hide_index=True)
            st.caption("各标的被选中的策略数量分布：")
            st.bar_chart(resonance_df.set_index("ts_code")["共振次数"])


@st.fragment(run_every=2)
def render_fetch_section():
    """数据更新区域：启动/停止按钮 + 实时进度 + 最近一次结果（每 2 秒自动刷新）"""
    fetch = st.session_state.get("fetch")
    result = st.session_state.get("fetch_result")

    st.subheader("🔄 数据更新")
    st.caption("增量拉取缺失的最新交易日，与命令行 python -m data.fetcher --mode incremental 完全一致")

    if fetch is not None and fetch["proc"].poll() is None:
        # ---------- 运行中 ----------
        label = fetch["label"]
        elapsed = int(time.time() - fetch["started"])
        st.button("⏳ 正在更新数据…", disabled=True, key="fetch_btn_running")
        if st.button("🛑 停止更新", key="fetch_btn_stop"):
            st.session_state["fetch"]["stopped"] = True
            st.session_state["fetch"]["proc"].terminate()
        st.warning(f"⏳ 数据更新进行中（{label}），已运行 {elapsed // 60} 分 {elapsed % 60} 秒… 请保持页面打开")
        tail = read_tail(FETCH_LOG)
        if tail:
            st.code(tail[-1000:])
        st.caption("进度每 2 秒自动刷新；即使关闭页面，更新也会在后台继续完成。")
        return

    if fetch is not None:
        # ---------- 刚结束：转存结果并整页刷新（顺带刷新侧边栏的数据状态） ----------
        st.session_state.pop("fetch", None)
        st.session_state["fetch_result"] = {
            "label": fetch["label"],
            "rc": fetch["proc"].returncode,
            "stopped": fetch.get("stopped", False),
            "elapsed": int(time.time() - fetch["started"]),
            "tail": read_tail(FETCH_LOG),
            "err": read_tail(FETCH_ERR),
        }
        st.rerun(scope="app")
        return

    # ---------- 空闲：显示最近一次结果 + 启动按钮 ----------
    if result is not None:
        if result["stopped"]:
            st.info(f"⏹ 数据更新已手动停止（{result['label']}），已下载的数据已保存，可随时再次更新。")
        elif result["rc"] == 0:
            st.success(f"✅ 数据更新完成（{result['label']}），用时 {result['elapsed'] // 60} 分 {result['elapsed'] % 60} 秒")
        else:
            st.error(f"❌ 数据更新失败（{result['label']}，返回码 {result['rc']}），请查看下方日志")
        if result["tail"].strip():
            st.code(result["tail"][-1500:])
        if result["err"].strip():
            st.code("错误输出：\n" + result["err"][-800:])
        if st.button("清除提示", key="fetch_dismiss"):
            st.session_state.pop("fetch_result", None)
            st.rerun(scope="app")

    pool_label = st.radio("更新范围", list(FETCH_POOL_OPTIONS.keys()), index=0, key="fetch_pool")
    if st.button("🚀 开始更新数据", type="primary", width="stretch", key="fetch_btn_start"):
        proc = start_fetch(FETCH_POOL_OPTIONS[pool_label])
        st.session_state["fetch"] = {
            "proc": proc,
            "started": time.time(),
            "label": pool_label,
            "pool": FETCH_POOL_OPTIONS[pool_label],
        }
        st.rerun(scope="app")  # 立即刷新为“运行中”状态


st.set_page_config(page_title="智能选股系统", page_icon="📈", layout="wide")

st.title("📈 智能选股系统")
st.caption("在浏览器里用鼠标操作：选择范围 → 点击开始 → 查看结果 → 下载 Excel。选股逻辑与命令行版完全一致。")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("⚙️ 运行设置")
    mode_label = st.radio("运行范围", list(MODE_OPTIONS.keys()), index=0)
    mode = MODE_OPTIONS[mode_label]
    limit_label = st.radio("涨停过滤", list(LIMIT_UP_OPTIONS.keys()), index=0)
    limit_up_filter = LIMIT_UP_OPTIONS[limit_label]
    top_n = st.slider("每个策略最多选出几只", min_value=5, max_value=100, value=50, step=5,
                      help="自定义RSI超卖策略固定取前10，与原逻辑一致")
    run_clicked = st.button("🚀 开始选股", type="primary", width="stretch")

    st.divider()
    st.header("📊 数据状态")
    status = get_data_status()
    st.metric("最新交易日", status["calendar"])
    st.metric("个股行情截止", status["stock_date"], help=f"{status['stock_count']} 只个股")
    st.metric("ETF行情截止", status["etf_date"], help=f"{status['etf_count']} 只ETF")
    st.caption("数据来自本地 db/stock.db；如需更新请先运行 data.fetcher")

# ================= 主区域 =================
render_fetch_section()

run_output = st.session_state.get("run_output")

if run_clicked:
    total = sum(1 for cfg in core.STRATEGY_LIBRARY.values() if core.strategy_belongs_to_mode(cfg, mode))
    if mode in ("all", "stock"):
        total += 1
    progress_bar = st.progress(0.0, text="准备运行…")
    counter = {"n": 0}

    def _progress(name, result):
        counter["n"] += 1
        progress_bar.progress(counter["n"] / total, text=f"正在运行：{name}（命中 {len(result)} 条）")

    try:
        result = core.run_all_strategies(
            mode=mode,
            limit_up_filter=limit_up_filter,
            top_n=top_n,
            progress_callback=_progress,
        )
    except Exception as e:
        st.error(f"运行失败：{e}")
        st.stop()
    progress_bar.empty()

    result["mode"] = mode
    result["limit_up_filter"] = limit_up_filter
    result["top_n"] = top_n
    st.session_state["run_output"] = result
    run_output = result

if run_output is None:
    st.info("👈 在左侧选择运行范围与参数，然后点击「开始选股」。")
    st.markdown(
        "**使用步骤**\n\n"
        "1. 双击 `启动选股界面.bat` 打开本页面；\n"
        "2. 如需更新行情数据，在页面顶部「数据更新」区域选个股或ETF，点 **开始更新数据**；\n"
        "3. 左侧选择：仅个股 / 仅ETF / 全部，以及是否过滤涨停；\n"
        "4. 点击 **开始选股**，等待各策略运行完成；\n"
        "5. 在每个策略页签查看命中标的，在「共振分析」看多策略共识；\n"
        "6. 点击 **下载 Excel** 保存结果（同时也会自动导出到项目目录）。"
    )
    st.stop()

params_changed = (
    run_output.get("mode") != mode
    or run_output.get("limit_up_filter") != limit_up_filter
    or run_output.get("top_n") != top_n
)
if params_changed:
    st.warning("当前显示的是上一次运行结果；参数已调整，点击左侧「开始选股」可刷新。")
    st.caption(f"上次运行：{run_output.get('mode')}，{run_output.get('limit_up_filter')}，TopN={run_output.get('top_n')}")
else:
    render_results(run_output)

    # 页面底部提供下载（与导出文件内容一致）
    with st.expander("💾 导出 Excel", expanded=False):
        excel_bytes = build_excel_bytes(run_output["all_results"], run_output["resonance_df"])
        st.download_button(
            "⬇️ 下载 Excel 结果",
            data=excel_bytes,
            file_name=f"选股结果_{run_output['latest_date']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
