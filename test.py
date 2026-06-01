from data.loader import DataLoader
from core.factor_engine import FactorEngine
from etf_pool import ETF_POOL

loader = DataLoader()
df = loader.load_unified(pool_type='etf', include_basic=False, fill_missing=False)
df = df.reset_index()
df.rename(columns={'symbol': 'ts_code'}, inplace=True)
df = FactorEngine.compute_factors(df, ['ret_20'])
df_recent = df.groupby('ts_code').tail(1)
print(df_recent[['ts_code', 'ret_20', 'pct_chg']])