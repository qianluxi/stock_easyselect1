"""
策略配置库
所有策略以字典形式定义，供 StrategyRunner 解析执行
"""

STRATEGY_LIBRARY = {
    # ---------- 单日策略 ----------
    "healthy_volume_rise": {
        "name": "健康放量上涨",
        "type": "single_day",
        "filters": [
            ("pct_chg", ">", 3.0),
            ("volume_ratio", ">", 1.5),
            ("turnover", "between", (5.0, 15.0)),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "description": "当日涨幅>3%，量比>1.5，换手率5%~15%",
        # 启用二次质量过滤
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": True        
    },

    # ---------- 多日窗口策略 ----------
    "momentum_breakout": {
        "name": "动量突破",
        "type": "window",
        "window": 10,  # 默认回看10个交易日
        "factors": ["ret_5", "vol_ratio_5"],
        "filters": [
            ("ret_5", ">", 0.05),
            ("vol_ratio_5", ">", 1.5),
        ],
        "sort_by": "ret_5",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "5日涨幅>5%，且5日量比>1.5",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False   # 允许高换手、高估值，符合动量特征        
    },

    "ma_golden_cross": {
        "name": "均线金叉",
        "type": "window",
        "window": 20,
        "factors": ["ma_5", "ma_20"],
        "filters": [
            ("ma_5", ">", "ma_20"),  # 支持列间比较（需在 runner 中处理）
            ("volume_ratio", ">", 1.0),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "5日均线上穿20日均线，且当日量比>1",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False   # 趋势策略，不额外限制量价区间        
    },

    "low_vol_high_turnover": {
        "name": "低波高换手",
        "type": "window",
        "window": 20,
        "factors": ["volatility_20", "vol_ratio_5"],
        "filters": [
            ("volatility_20", "<", 0.4),   # 年化波动率 < 40%
            ("turnover", ">", 3.5),    # 换手率
            ("pct_chg", ">", 2.0),
        ],
        "sort_by": "turnover",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "波动率低但换手率较高，温和上涨",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False   # 已有波动率、换手率条件，避免过度过滤
    },

    "atr_breakout": {
        "name": "ATR 突破",
        "type": "window",
        "window": 30,
        "factors": ["atr_14"],
        "filters": [
            ("pct_chg", ">", "2 * atr_14 / close"),  # 涨幅超过 2倍 ATR%
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "当日涨幅超过2倍ATR波动幅度，强势突破",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False
    },

    "rsi_oversold_rebound": {
        "name": "RSI 超跌反弹",
        "type": "window",
        "window": 30,
        "factors": ["rsi_14", "ret_5"],
        "filters": [
            ("rsi_14", "<", 30),
            ("pct_chg", ">", 2.0),
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 20,
        "keep_last_only": True,
        "description": "RSI<30超卖后出现反弹，当日涨幅>2%",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False  # 超跌股本身可能量价不健康
    },

    "macd_bullish": {
        "name": "MACD 多头",
        "type": "window",
        "window": 30,
        "factors": ["macd"],
        "filters": [
            ("dif", ">", "dea"),  # DIF 上穿 DEA
            ("macd", ">", 0),
        ],
        "sort_by": "macd",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "MACD 金叉且柱状图为正",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False
    },

    "value_momentum": {
        "name": "估值动量",
        "type": "window",
        "window": 60,
        "factors": ["ret_20", "pe_ttm"],
        "filters": [
            ("ret_20", ">", 0.10),
            ("pe_ttm", ">", 0),
            ("pe_ttm", "<", 40),
        ],
        "sort_by": "ret_20",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "20日涨幅>10%，且PE在0~40之间",
        "apply_quality_filter": True,
        "remove_risky": True,     # 进一步剔除 ST、市值过小
        "prefer_healthy": False   # 已有 PE<40 条件
    }
}