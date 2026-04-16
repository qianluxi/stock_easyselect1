"""
数据库表结构定义
与 data 模块保持一致，统一使用 ts_code 作为股票代码标识
"""

# =========================
# 基础信息表
# =========================

STOCK_BASIC_SQL = """
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code     TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL,
    area        TEXT,
    industry    TEXT,
    list_date   TEXT NOT NULL
);
"""

# =========================
# 日线行情原始数据表（与 data/cache.py 中的 daily_raw 对应）
# 字段完全匹配 Tushare daily 接口实际返回字段（含扩展字段预留）
# =========================

DAILY_RAW_SQL = """
CREATE TABLE IF NOT EXISTS daily_raw (
    ts_code       TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL,
    pre_close     REAL,
    change        REAL,
    pct_chg       REAL,
    vol           REAL,          -- 成交量（手）
    amount        REAL,          -- 成交额（千元）
    total_mv      REAL,          -- 总市值（万元，需权限）
    turnover_rate REAL,          -- 换手率（%，需权限）
    PRIMARY KEY (ts_code, trade_date)
);
"""

# =========================
# 每日指标表（可选，用于扩展财务数据）
# =========================

DAILY_BASIC_SQL = """
CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code         TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    total_mv        REAL,        -- 总市值（万元）
    circ_mv         REAL,        -- 流通市值（万元）
    turnover_rate   REAL,        -- 换手率（%）
    turnover_rate_f REAL,        -- 换手率（自由流通股）
    volume_ratio    REAL,        -- 量比
    pe              REAL,        -- 市盈率
    pe_ttm          REAL,        -- 市盈率TTM
    pb              REAL,        -- 市净率
    PRIMARY KEY (ts_code, trade_date)
);
"""

# =========================
# 数据同步元数据表（替代原 sync_log，与 data/cache.py 的 data_meta 保持一致）
# =========================

DATA_META_SQL = """
CREATE TABLE IF NOT EXISTS data_meta (
    ts_code           TEXT PRIMARY KEY,
    last_update_date  TEXT,
    row_count         INTEGER,
    updated_at        TEXT
);
"""

# 保留旧版 sync_log 表定义，以便兼容旧代码（可择期废弃）
SYNC_LOG_SQL = """
CREATE TABLE IF NOT EXISTS sync_log (
    symbol          TEXT PRIMARY KEY,
    last_sync_date  TEXT NOT NULL,
    row_count       INTEGER,
    updated_at      TEXT NOT NULL
);
"""

# =========================
# 交易日历表（由 data/calendar.py 自动创建）
# =========================

TRADING_CALENDAR_SQL = """
CREATE TABLE IF NOT EXISTS trading_calendar (
    cal_date        TEXT PRIMARY KEY,
    is_open         INTEGER,
    pretrade_date   TEXT
);
"""

# =========================
# 因子值表（待后续开发）
# =========================

FACTOR_VALUES_SQL = """
CREATE TABLE IF NOT EXISTS factor_values (
    ts_code     TEXT NOT NULL,
    trade_date  TEXT NOT NULL,

    ret_1       REAL,
    ret_5       REAL,
    ret_20      REAL,

    ma5         REAL,
    ma10        REAL,
    ma20        REAL,
    ma60        REAL,

    rsi14       REAL,

    macd        REAL,
    macd_signal REAL,
    macd_hist   REAL,

    atr14       REAL,

    bb_mid      REAL,
    bb_upper    REAL,
    bb_lower    REAL,
    bb_width    REAL,

    vol_ratio   REAL,

    volatility20 REAL,

    roc12       REAL,
    momentum10  REAL,
    cci20       REAL,
    williams_r  REAL,

    skew20      REAL,
    kurt20      REAL,

    PRIMARY KEY(ts_code, trade_date)
);
"""

# =========================
# 特征值表（待后续开发）
# =========================

FEATURE_VALUES_SQL = """
CREATE TABLE IF NOT EXISTS feature_values (
    ts_code     TEXT NOT NULL,
    trade_date  TEXT NOT NULL,

    -- 基础特征
    ret_1       REAL,
    ret_5       REAL,
    ret_20      REAL,
    volatility20 REAL,
    vol_ratio   REAL,
    roc12       REAL,
    momentum10  REAL,
    rsi14       REAL,
    macd        REAL,
    macd_signal REAL,
    macd_hist   REAL,
    cci20       REAL,
    williams_r  REAL,
    skew20      REAL,
    kurt20      REAL,
    atr14       REAL,

    -- 截面排名特征
    ret_1_rank  REAL,
    ret_5_rank  REAL,
    ret_20_rank REAL,

    PRIMARY KEY(ts_code, trade_date)
);
"""

# 复权因子表
ADJUST_FACTOR_SQL = """
CREATE TABLE IF NOT EXISTS adjust_factor (
    ts_code       TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    adj_factor    REAL NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);
"""

# =========================
# 所有表定义列表（供 database.py 调用）
# =========================

ALL_SCHEMA_SQL = [
    STOCK_BASIC_SQL,
    DAILY_RAW_SQL,
    DAILY_BASIC_SQL,
    DATA_META_SQL,
    SYNC_LOG_SQL,               # 保留兼容
    TRADING_CALENDAR_SQL,
    ADJUST_FACTOR_SQL,          # 新增
    FACTOR_VALUES_SQL,
    FEATURE_VALUES_SQL
]