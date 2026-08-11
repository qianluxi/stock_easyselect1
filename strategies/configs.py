"""
策略配置库（修正版）
所有策略以字典形式定义，供 StrategyRunner 解析执行
"""

STRATEGY_LIBRARY = {
# ---------- 单日策略 ----------
    "healthy_volume_rise": {
        "name": "健康放量上涨",
        "type": "single_day",
        "factors": ["vol_ratio_5", "ret_40"],   # 添加 ret_40
        "filters": [
            ("pct_chg", ">", 3.0),
            ("vol_ratio_5", ">", 1.5),
            ("turnover_rate", ">", 5.0),
            ("turnover_rate", "<", 15.0),
            ("ret_40", "<", 0.15),          # 过滤40日涨幅超过15%的个股
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "description": "当日涨幅>3%，量比>1.5，换手率5%~15%",
    },

    # ---------- 多日窗口策略 ----------
    "momentum_breakout": {
        "name": "动量突破",
        "type": "window",
        "window": 10,
        "factors": ["ret_5", "vol_ratio_5", "ret_40"],
        "filters": [
            ("ret_5", ">", 0.05),
            ("vol_ratio_5", ">", 1.5),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "ret_5",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "5日涨幅>5%，且5日量比>1.5",
    },

    "ma_golden_cross": {
        "name": "均线金叉",
        "type": "window",
        "window": 20,
        "factors": ["ma_5", "ma_20", "vol_ratio_5", "ret_40"],
        "filters": [
            ("ma_5", ">", "ma_20"),
            ("vol_ratio_5", ">", 1.0),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "5日均线上穿20日均线，且当日量比>1",
    },

    "low_vol_high_turnover": {
        "name": "低波高换手",
        "type": "window",
        "window": 20,
        "factors": ["volatility_20", "vol_ratio_5", "ret_40"],
        "filters": [
            ("volatility_20", "<", 0.40),
            ("turnover_rate", ">", 3.5),
            ("pct_chg", ">", 2.0),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "turnover_rate",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "波动率低但换手率较高，温和上涨",
    },

    "atr_breakout": {
        "name": "ATR 突破",
        "type": "window",
        "window": 30,
        "factors": ["atr_14", "atr_2x_pct", "ret_40"],
        "filters": [
            ("pct_chg", ">", "atr_2x_pct"),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "当日涨幅超过2倍ATR波动幅度，强势突破",
    },

    "rsi_oversold_rebound": {
        "name": "RSI 超跌反弹",
        "type": "window",
        "window": 30,
        "factors": ["rsi_14", "ret_5", "ret_40"],
        "filters": [
            ("rsi_14", "<", 40),
            ("pct_chg", ">", 2.0),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 20,
        "keep_last_only": True,
        "description": "RSI<30超卖后出现反弹，当日涨幅>2%",
    },

    "macd_bullish": {
        "name": "MACD 多头",
        "type": "window",
        "window": 30,
        "factors": ["macd", "ret_40"],
        "filters": [
            ("dif", ">", "dea"),
            ("macd", ">", 0),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "macd",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "MACD 金叉且柱状图为正",
    },

    "value_momentum": {
        "name": "估值动量",
        "type": "window",
        "window": 60,
        "factors": ["ret_20", "ret_40"],
        "filters": [
            ("ret_20", ">", 0.10),
            ("pe_ttm", ">", 0),
            ("pe_ttm", "<", 40),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "ret_20",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "20日涨幅>10%，且PE在0~40之间",
    },

    # ---------- 慢牛低换手 ----------
    "slow_bull": {
        "name": "慢牛低换手",
        "description": "半年内小步上涨，成交量稳定，换手率低，无异常放量",
        "type": "window",
        "window": 120,
        "factors": [
            "slope_120",
            "volatility_120",
            "volume_ratio_max120",
            "ret_40",                          # 新增
        ],
        "filters": [
            ("slope_120", ">", 0),
            ("slope_120", "<", 0.005),
            ("volatility_120", "<", 0.30),
            ("turnover_rate", "<", 3.0),
            ("volume_ratio_max120", "<", 3.0),
            ("ret_40", "<", 0.15),          # 即使慢牛也过滤短期过热
        ],
        "sort_by": "slope_120",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
    },

    #-----------------以下是ETF的策略------------------------
    "etf_momentum": {
        "name": "ETF动量",
        "type": "window",
        "window": max(20, 40),          # 保证足够计算 ret_40
        "pool_type": "etf",
        "factors": ["ret_20", "ret_40"],
        "filters": [
            ("ret_20", ">", 0.05),      # 20日涨幅 > 5%
            ("ret_40", "<", 0.15),      # 近40日涨幅不能过大（<15%）
        ],
        "sort_by": "ret_20",
        "ascending": False,
        "top_n": 5,
        "keep_last_only": True,
    },

    "etf_ma_cross": {
        "name": "ETF均线金叉",
        "description": "5日均线上穿20日均线，量比>1.2",
        "type": "window",
        "window": max(30, 40),
        "pool_type": "etf",
        "factors": ["ma_5", "ma_20", "vol_ratio_5", "ret_40"],
        "filters": [
            ("ma_5", ">", "ma_20"),
            ("vol_ratio_5", ">", 1.2),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "vol_ratio_5",
        "ascending": False,
        "top_n": 5,
        "keep_last_only": True,
    },

    "etf_low_volatility": {
        "name": "ETF低波动",
        "description": "20日年化波动率低于30%，且价格在20日均线上方",
        "type": "window",
        "window": max(30, 40),
        "pool_type": "etf",
        "factors": ["volatility_20", "ma_20", "ret_40"],
        "filters": [
            ("volatility_20", "<", 0.30),
            ("close", ">", "ma_20"),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "volatility_20",
        "ascending": True,
        "top_n": 5,
        "keep_last_only": True,
    },

    "etf_rsi_rebound": {
        "name": "ETF RSI超跌反弹",
        "description": "14日RSI<40且当日涨幅>2%，博取反弹",
        "type": "window",
        "window": max(30, 40),
        "pool_type": "etf",
        "factors": ["rsi_14", "ret_40"],
        "filters": [
            ("rsi_14", "<", 40),
            ("pct_chg", ">", 2.0),
            ("ret_40", "<", 0.15),   # 避免前期涨幅过大的“假超跌”
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 5,
        "keep_last_only": True,
    },

    "etf_breakout": {
        "name": "ETF突破",
        "description": "当日涨幅超过2倍ATR波动幅度，强势突破",
        "type": "window",
        "window": max(30, 40),
        "pool_type": "etf",
        "factors": ["atr_14", "atr_2x_pct", "ret_40"],
        "filters": [
            ("pct_chg", ">", "atr_2x_pct"),
            ("ret_40", "<", 0.15),   # 防止追高前期已大幅上涨的 ETF
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 5,
        "keep_last_only": True,
    },

    # ---------- ETF 动量轮动策略（已升级） ----------
    "etf_cross_momentum": {
        "name": "ETF横截面动量",
        "description": "多周期收益率加权评分，选综合动量最强的 ETF",
        "type": "window",
        "window": 120,                  # 已足够计算 ret_40
        "pool_type": "etf",
        "factors": ["momentum_score", "ret_40"],
        "filters": [
            ("momentum_score", ">", 0.0),
            ("ret_40", "<", 0.15),   # 综合动量也得避免短期过热
        ],
        "sort_by": "momentum_score",
        "ascending": False,
        "top_n": 3,
        "keep_last_only": True,
    },

    "etf_risk_adjusted_momentum": {
        "name": "ETF风险调整动量",
        "description": "收益/波动率比值越高越好（动量效率）",
        "type": "window",
        "window": 120,
        "pool_type": "etf",
        "factors": ["momentum_ratio", "ret_20", "ret_40"],
        "filters": [
            ("ret_20", ">", 0.02),
            ("ret_40", "<", 0.15),
        ],
        "sort_by": "momentum_ratio",
        "ascending": False,
        "top_n": 3,
        "keep_last_only": True,
    },

    "etf_dual_momentum": {
        "name": "ETF双动量",
        "description": "绝对收益过滤 + 综合动量排序，防御性强",
        "type": "window",
        "window": 120,
        "pool_type": "etf",
        "factors": ["ret_60", "momentum_score", "ret_40"],
        "filters": [
            ("ret_60", ">", 0.05),
            ("ret_40", "<", 0.15),   # 即使长周期好，也不能短期过热
        ],
        "sort_by": "momentum_score",
        "ascending": False,
        "top_n": 1,
        "keep_last_only": True,
    }
}

# ========== 全局开关 ==========
# 是否启用 ret_40 过滤（近40日涨幅限制），True 表示启用，False 表示禁用
# 阈值统一为 0.15（即 40 日涨幅超过 15% 的标的会被过滤）
USE_RET40_FILTER = True
