"""
数据库完整性检查脚本（结果保存到文件）
功能：
1. 查看每只股票的交易日数量
2. 对比交易日历，找出缺失的交易日
3. 将完整报告保存到 check_report.txt
"""

import pandas as pd
from data.cache import DataCache
from data.calendar import TradingCalendar
from stock_pool import STOCK_POOL
import sys

def main():
    # 输出文件路径
    report_file = "check_report.txt"
    
    cache = DataCache("db/stock.db")
    calendar = TradingCalendar("db/stock.db")
    
    # 检查的日期范围（根据实际情况调整）
    end_date = "2026-06-08"
    start_date = "2026-03-01"
    
    # 将输出重定向到文件和控制台
    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, text):
            for f in self.files:
                f.write(text)
        def flush(self):
            for f in self.files:
                f.flush()
    
    with open(report_file, 'w', encoding='utf-8') as f:
        # 同时输出到控制台和文件
        tee = Tee(sys.stdout, f)
        
        tee.write(f"数据库完整性检查报告\n")
        tee.write(f"检查日期范围: {start_date} ~ {end_date}\n")
        
        trade_days = calendar.get_trading_days(start_date, end_date)
        trade_days_str = [d.strftime("%Y-%m-%d") for d in trade_days]
        tee.write(f"交易日总数: {len(trade_days_str)}\n\n")
        
        df = cache.load_raw_data(symbols=STOCK_POOL, start_date=start_date, end_date=end_date)
        if df.empty:
            tee.write("数据库中无该区间数据！\n")
            return
        
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime("%Y-%m-%d")
        
        stock_data = {}
        for code, group in df.groupby('ts_code'):
            stock_data[code] = set(group['trade_date'].tolist())
        
        tee.write("=== 每只股票交易日数量 ===\n")
        for code in sorted(stock_data.keys()):
            count = len(stock_data[code])
            tee.write(f"{code}: {count} 个交易日")
            missing = [d for d in trade_days_str if d not in stock_data[code]]
            if missing:
                tee.write(f"  (缺失 {len(missing)} 天)")
                if len(missing) <= 10:
                    tee.write(f" {missing}")
                tee.write("\n")
            else:
                tee.write("  ✓ 完整\n")
        
        # 汇总缺失
        total_missing = 0
        for code in sorted(stock_data.keys()):
            missing = [d for d in trade_days_str if d not in stock_data[code]]
            total_missing += len(missing)
        
        tee.write(f"\n总缺失交易日次数: {total_missing} (所有股票合计)\n")
        tee.write(f"应覆盖股票数量: {len(STOCK_POOL)}\n")
        
        no_data_codes = [code for code in STOCK_POOL if code not in stock_data]
        if no_data_codes:
            tee.write(f"\n以下 {len(no_data_codes)} 只股票在指定区间内没有任何数据:\n")
            for code in no_data_codes:
                tee.write(f"{code}\n")
        
        tee.write(f"\n报告已保存至 {report_file}\n")

if __name__ == "__main__":
    main()