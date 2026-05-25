"""
策略配置库（修正版）
所有策略以字典形式定义，供 StrategyRunner 解析执行
"""

STRATEGY_LIBRARY = {
    # ---------- 单日策略 ----------
    "healthy_volume_rise": {
        "name": "健康放量上涨",
        "type": "single_day",
        "factors": ["vol_ratio_5"],   # 原先缺失，现已补充
        "filters": [
            ("pct_chg", ">", 3.0),
            ("vol_ratio_5", ">", 1.5),
            ("turnover_rate", ">", 5.0),    # 原名 turnover，改为 turnover_rate
            ("turnover_rate", "<", 15.0),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "description": "当日涨幅>3%，量比>1.5，换手率5%~15%",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": True,
    },

    # ---------- 多日窗口策略 ----------
    "momentum_breakout": {
        "name": "动量突破",
        "type": "window",
        "window": 10,
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
        "prefer_healthy": False,
    },

    "ma_golden_cross": {
        "name": "均线金叉",
        "type": "window",
        "window": 20,
        "factors": ["ma_5", "ma_20", "vol_ratio_5"],  # 补充量比因子
        "filters": [
            ("ma_5", ">", "ma_20"),          # 列间比较，runner 已支持
            ("vol_ratio_5", ">", 1.0),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "5日均线上穿20日均线，且当日量比>1",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False,
    },

    "low_vol_high_turnover": {
        "name": "低波高换手",
        "type": "window",
        "window": 20,
        "factors": ["volatility_20", "vol_ratio_5"],
        "filters": [
            ("volatility_20", "<", 0.40),
            ("turnover_rate", ">", 3.5),    # turnover → turnover_rate
            ("pct_chg", ">", 2.0),
        ],
        "sort_by": "turnover_rate",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "波动率低但换手率较高，温和上涨",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False,
    },

    "atr_breakout": {
        "name": "ATR 突破",
        "type": "window",
        "window": 30,
        "factors": ["atr_14", "atr_2x_pct"],
        "filters": [
            ("pct_chg", ">", "atr_2x_pct"),   # 列间比较
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "当日涨幅超过2倍ATR波动幅度，强势突破",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False,
    },

    "rsi_oversold_rebound": {
        "name": "RSI 超跌反弹",
        "type": "window",
        "window": 30,
        "factors": ["rsi_14", "ret_5"],
        "filters": [
            ("rsi_14", "<", 40),
            ("pct_chg", ">", 2.0),
        ],
        "sort_by": "rsi_14",
        "ascending": True,
        "top_n": 20,
        "keep_last_only": True,
        "description": "RSI<30超卖后出现反弹，当日涨幅>2%",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False,
    },

    "macd_bullish": {
        "name": "MACD 多头",
        "type": "window",
        "window": 30,
        "factors": ["macd"],
        "filters": [
            ("dif", ">", "dea"),   # 列间比较
            ("macd", ">", 0),
        ],
        "sort_by": "macd",
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,
        "description": "MACD 金叉且柱状图为正",
        "apply_quality_filter": True,
        "remove_risky": True,
        "prefer_healthy": False,
    },

    "value_momentum": {
        "name": "估值动量",
        "type": "window",
        "window": 60,
        "factors": ["ret_20"],
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
        "remove_risky": True,
        "prefer_healthy": False,
    },

    # ---------- 实时专用策略：非涨停健康放量 ----------
    "live_non_limit_up_healthy": {
        "name": "非涨停健康放量(实时)",
        "type": "single_day",
        "factors": ["vol_ratio_5"],    # 声明需要的因子
        "filters": [
            ("pct_chg", ">", 2.0),
            ("vol_ratio_5", ">", 1.2),
            ("turnover_rate", ">", 3.0),       # 原 between 改为两条独立条件
            ("turnover_rate", "<", 20.0),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "description": "实时版(非涨停)：涨幅>2%，量比>1.2，换手率3%~20%",
        "apply_quality_filter": False,
        "exclude_limit_up": "strict",
    },

    "live_safe_healthy": {
        "name": "安全健康放量(实时，全过滤涨停)",
        "type": "single_day",
        "factors": ["vol_ratio_5"],
        "filters": [
            ("pct_chg", ">", 1.0),
            ("vol_ratio_5", ">", 1.0),
            ("turnover_rate", ">", 2.0),
            ("turnover_rate", "<", 30.0),
        ],
        "sort_by": "pct_chg",
        "ascending": False,
        "top_n": 20,
        "apply_quality_filter": False,
        "exclude_limit_up": "all",
    },

    # ---------- 新增策略：慢牛低换手 ----------
    # "slow_bull": {
    #     "name": "慢牛低换手",
    #     "description": "半年内小步上涨，成交量稳定，换手率低，无异常放量",
    #     "type": "window",
    #     "window": 120,
    #     "factors": ["slope_120", "volatility_120", "volume_ratio_max120"],
    #     "filters": [
    #         ("slope_120", ">", 0),
    #         ("slope_120", "<", 0.005),
    #         ("volatility_120", "<", 0.30),
    #         ("turnover_rate", "<", 3.0),
    #         ("volume_ratio_max120", "<", 3.0),
    #     ],
    #     "sort_by": "slope_120",
    #     "ascending": False,
    #     "top_n": 20,
    #     "keep_last_only": True,
    # },
    "slow_bull": {
        "name": "慢牛低换手",                          # 策略名称
        "description": "半年内小步上涨，成交量稳定，换手率低，无异常放量",
        "type": "window",                             # 窗口策略，需回看历史数据
        "window": 120,                                # 回看 120 个交易日（约半年）
        "factors": [
            "slope_120",                              # 120日收盘价线性回归斜率（趋势强度）
            "volatility_120",                         # 120日年化波动率（价格稳定性）
            "volume_ratio_max120"                     # 120日内单日量比的最大值（防爆量）
        ],
        "filters": [
            ("slope_120", ">", 0),                    # 斜率必须为正（上涨趋势）
            ("slope_120", "<", 0.005),                # 斜率小于0.005（缓慢上涨，约年化60%） # 斜率上限放大4倍
            ("volatility_120", "<", 0.30),            # 年化波动率 < 30%（要求走势平稳） # 波动率放宽到50%
            ("turnover_rate", "<", 3.0),              # 最新换手率 < 3%（不放量） # 换手率放宽到6%
            ("volume_ratio_max120", "<", 3.0),        # 半年内任何一天成交量不超过平均的3倍（无异常放量） # 最大量比放宽到5倍
        ],
        "sort_by": "slope_120",                       # 按斜率从大到小排序（更强势的慢牛靠前）
        "ascending": False,
        "top_n": 20,
        "keep_last_only": True,                       # 仅输出最新一天的符合条件的股票
    }
}