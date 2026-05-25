"""
数据拉取调度器（优化版：按交易日批量拉取）
将逐只股票循环改为按日批量拉取，大幅减少 API 调用次数并提升性能。
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.sources import TushareSource
from data.cache import DataCache
from data.calendar import TradingCalendar
from config import TS_TOKEN


def get_stock_pool():
    """动态导入 stock_pool.py 中的 STOCK_POOL 列表"""
    try:
        from stock_pool import STOCK_POOL
        return STOCK_POOL
    except ImportError:
        print("警告：未找到 stock_pool.py 文件，请先生成股票池。")
        return []


class DataFetcher:
    """数据拉取器（批量优化版）"""

    def __init__(self, db_path: str = "db/stock.db"):
        self.cache = DataCache(db_path)
        self.source = TushareSource(TS_TOKEN)
        self.calendar = TradingCalendar(db_path)

    def fetch_incremental(self, symbols: list = None):
        """
        增量拉取：找出全局数据最新日期，拉取从该日期后到最新交易日之间
        所有交易日的数据，每次拉取全部股票池的日线、复权因子和 daily_basic。
        """
        if symbols is None:
            symbols = get_stock_pool()

        if not symbols:
            print("股票池为空，退出。")
            return

        # 1. 确定需要拉取的交易日区间
        latest_trade_day = self.calendar.latest_trading_day()
        end_date_str = latest_trade_day.strftime("%Y%m%d")

        # 获取 daily_raw 表中所有股票的最新日期（全局最大）
        last_date_global = self.cache.get_global_last_date()
        if last_date_global is None:
            # 无任何数据，从 20100101 开始全量拉取（也可调用 fetch_full）
            print("本地无数据，将执行全量拉取...")
            self.fetch_full(symbols)
            return

        # 计算开始日期（下一个交易日）
        try:
            start_date = self.calendar.next_trading_day(last_date_global).strftime("%Y%m%d")
        except ValueError:
            print("已是最新数据，无需拉取。")
            return

        if start_date > end_date_str:
            print("已是最新数据，无需拉取。")
            return

        # 2. 生成待拉取的交易日列表
        trade_dates = self.calendar.get_trading_days(start_date, end_date_str)  # 修改方法名
        if not trade_dates:
            print("无交易日需要拉取。")
            return

        print(f"增量拉取开始：从 {start_date} 到 {end_date_str}，共 {len(trade_dates)} 个交易日，"
            f"股票池 {len(symbols)} 只")

        # 3. 按日循环拉取
        total_added = 0
        for date_obj in trade_dates:            # 变量改为 date_obj
            date_str = date_obj.strftime("%Y%m%d")   # 转成 YYYYMMDD 字符串
            date_date = date_obj.strftime("%Y-%m-%d") # 转成 YYYY-MM-DD 字符串
            print(f"拉取交易日 {date_str} ...")

            # 3.1 日线行情（一次拉取全部股票）
            df_daily = self.source.fetch_daily(symbols, date_str, date_str)
            if not df_daily.empty:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  日线: {len(df_daily)} 条")

            # 3.2 复权因子（按日期批量拉取，需配合 source 新接口）
            df_factor = self.source.fetch_adjust_factor_by_date(date_str)
            if not df_factor.empty:
                self.cache.save_adjust_factor_batch(df_factor)
                print(f"  复权因子: {len(df_factor)} 条")

            # 3.3 daily_basic（总市值、换手率等，按日期批量拉取）
            df_basic = self.source.fetch_daily_basic(symbols, date_str, date_str)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")

            # 3.4 更新 meta 表中各股票的最新日期（批量）
            self._batch_update_meta(df_daily)

        # 4. 最后，将全局最新拉取日期写入 meta 或全局配置
        self.cache.set_global_last_date(latest_trade_day)
        print(f"增量拉取完成，共新增日线记录 {total_added} 条。")

    def fetch_full(self, symbols: list = None, start_date: str = "20100101", end_date: str = None):
        """
        全量拉取（按年批量模式）：将时间范围按年切分，每年一次拉取全部股票池，
        大幅减少请求次数。
        """
        if symbols is None:
            symbols = get_stock_pool()
        
        if end_date is None:
            end_date = datetime.today().strftime("%Y%m%d")
        
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        
        print(f"全量拉取: {start_date} ~ {end_date}，按年分批，股票池 {len(symbols)} 只")
        total_added = 0
        
        # 按年循环
        for year in range(start_year, end_year + 1):
            # 确定年份起止边界，避免超出原始 range
            year_start = max(start_date, f"{year}0101")
            year_end = min(end_date, f"{year}1231")
            
            print(f"拉取 {year} 年 ({year_start}-{year_end}) ...")
            
            # 一次拉取全年所有股票
            df_daily = self.source.fetch_daily(symbols, year_start, year_end)
            if df_daily.empty:
                print(f"  {year} 年日线无数据")
            else:
                self.cache.save_daily_batch(df_daily)
                total_added += len(df_daily)
                print(f"  日线: {len(df_daily)} 条")
                self._batch_update_meta(df_daily)
            
            # 复权因子也按年拉（但 adj_factor 接口只支持 trade_date，不支持范围，仍按天拉性价比低，
            # 可改为只拉有除权发生日的高度变化日，但这里保持简单，沿用 fetch_adjust_factor_by_date 逐日策略太慢，
            # 因此采用全部拉取再过滤，或者干脆全量时一次性拉全量区间再过滤）
            # 实际上 Tushare adj_factor 支持 ts_code 和 trade_date，但不支持范围。
            # 为了速度，建议改为：根据区间一次性拉取全部股票的复权因子（不传 trade_date，然后按区间筛选）
            # 但之前 fetch_adjust_factor 已支持不传 trade_date 拉取所有，我们加一个全量加载方法。
            df_factor = self.source.fetch_adjust_factor(symbols=symbols)  # 拉全部，然后再过滤
            if not df_factor.empty:
                df_factor = df_factor[(df_factor["trade_date"] >= year_start) & (df_factor["trade_date"] <= year_end)]
                if not df_factor.empty:
                    self.cache.save_adjust_factor_batch(df_factor)
                    print(f"  复权因子: {len(df_factor)} 条")
            
            # daily_basic 支持范围批量，直接按年拉
            df_basic = self.source.fetch_daily_basic(symbols, year_start, year_end)
            if not df_basic.empty:
                self.cache.save_daily_basic_batch(df_basic)
                print(f"  daily_basic: {len(df_basic)} 条")
        
        # 记录全局最后日期
        last_day = pd.to_datetime(end_date)
        self.cache.set_global_last_date(last_day)
        print(f"全量拉取完成，共新增日线记录 {total_added} 条。")

    def _batch_update_meta(self, df_daily: pd.DataFrame):
        """从日线数据中提取每只股票的最新交易日期，批量更新 meta 表。"""
        if df_daily.empty:
            return
        # 按 ts_code 分组，取最大 trade_date
        meta_update = df_daily.groupby("ts_code")["trade_date"].max().reset_index()
        for _, row in meta_update.iterrows():
            # 将日期转为字符串 'YYYY-MM-DD'（与 cache 表内格式一致）
            last_date_str = pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d")
            self.cache.update_meta(row["ts_code"], last_date_str, None)

    # ---- 以下辅助拉取方法已废弃，不再需要 ----
    # 原 _fetch_and_save_adjust_factor / _fetch_and_save_daily_basic 直接删除


def main():
    parser = argparse.ArgumentParser(description="A股数据拉取工具（批量优化版）")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental",
                        help="拉取模式：incremental(增量) 或 full(全量)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="指定股票代码，逗号分隔，例如 000001.SZ,600000.SH")
    parser.add_argument("--start", type=str, default="20100101",
                        help="全量模式下的开始日期 (YYYYMMDD)")
    parser.add_argument("--end", type=str, default=None,
                        help="全量模式下的结束日期 (YYYYMMDD)")

    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = get_stock_pool()

    if not symbols:
        print("未指定股票池，且 stock_pool.py 为空，退出。")
        return

    fetcher = DataFetcher()

    if args.mode == "incremental":
        fetcher.fetch_incremental(symbols)
    else:
        fetcher.fetch_full(symbols, start_date=args.start, end_date=args.end)


if __name__ == "__main__":
    main()