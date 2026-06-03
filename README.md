```markdown
# 📈 Stock EasySelect — A股量化选股与ETF轮动系统

基于 Tushare 数据，支持**股票多因子筛选**、**ETF行业均衡轮动**以及**历史回测**的量化研究平台。通过配置化策略，无需修改代码即可快速验证交易思路。

## 📦 项目结构

```
tushare_select2/
├── data/                    # 数据模块（拉取、缓存、加载）
├── strategies/              # 策略配置与运行器
│   ├── configs.py           # ★ 所有策略定义（股票/ETF）
│   └── runner.py
├── core/                    # 因子引擎、过滤引擎、回测器
├── tools/
│   └── generate_etf_pool.py # 生成行业均衡的 ETF 池
├── main.py                  # 盘后多策略筛选 + 共振分析 + Excel导出
├── main_backtest.py         # 单策略回测入口
├── stock_pool.py            # 股票池
├── etf_pool.py              # ETF 池（由工具自动生成）
├── config.py                # Tushare Token 配置
└── db/
    └── stock.db             # SQLite 本地数据库
```

## 🚀 快速开始

### 1. 环境要求
- Python 3.10+
- 安装依赖：`pip install pandas numpy tushare openpyxl`
- 在 [Tushare Pro](https://tushare.pro) 注册并获取 Token（需要 120 积分以上）
- 将 Token 填写至项目根目录的 `config.py` 中：
  ```python
  TS_TOKEN = "你的token"
  ```

### 2. 数据准备（必做）

#### 生成 ETF 池（自动筛选流动性好的各行业 ETF）
```bash
cd tools
python generate_etf_pool.py
```
执行后会在项目根目录生成 `etf_pool.py`，包含约 100 只行业均衡的 ETF。

#### 拉取股票日线数据（近5年）
```bash
# 全量拉取，从 5 年前开始（例如今天是 2026-06-03，则用 20210603）
python -m data.fetcher --mode full --start 20210603
```

#### 拉取 ETF 日线数据（近5年）
```bash
# ETF 全量拉取（最近5年）
python -m data.fetcher --mode full --pool_type etf --start 20220101
```

#### 后续增量更新
```bash
# 股票增量更新（只拉取本地缺失的最新交易日）
python -m data.fetcher --mode incremental

# ETF 增量更新
python -m data.fetcher --mode incremental --pool_type etf
```

> 可自定义日期区间：  
> `python -m data.fetcher --mode full --start 20230101 --end 20250429`

---

## 📊 运行策略筛选

### 盘后多策略扫描（输出 Excel 报告）
```bash
python main.py
```
- 会遍历所有已启用的策略，输出各策略选中的股票/ETF
- 自动进行**策略共振分析**，找出被多个策略同时选中的标的
- 结果导出为 `选股结果_YYYY-MM-DD.xlsx`

### 历史回测（检验策略绩效）
```bash
python main_backtest.py
```
在 `main_backtest.py` 中可选择要回测的策略，查看净值曲线、胜率、盈亏比等。

---

## ⚙️ 常用配置开关（手动修改代码）

所有开关均位于 `main.py` 顶部或策略配置中，修改后直接运行即可。

| 开关 | 位置 | 说明 |
|------|------|------|
| **涨停过滤** | `main.py` 头部 `LIMIT_UP_FILTER` | `"all"` 过滤所有涨停；`"strict"` 仅过滤一字板/T字板；`None` 不过滤 |
| **股票/ETF 运行模式** | `main.py` 头部 `RUN_MODE` | `"all"` 全部策略；`"stock"` 仅股票策略；`"etf"` 仅 ETF 策略 |
| **股票池** | `stock_pool.py` | 手动编辑，放入需要筛选的股票代码（默认约 600 只） |
| **ETF 池** | `etf_pool.py` | 由 `tools/generate_etf_pool.py` 自动生成，也可手动增删 |
| **策略阈值调整** | `strategies/configs.py` | 每个策略的 `filters` 均可修改（如涨幅、量比、波动率阈值） |
| **Top N 数量** | `strategies/configs.py` | 修改对应策略的 `top_n` 值 |
| **ETF 池生成参数** | `tools/generate_etf_pool.py` | 修改 `MIN_AMOUNT_THRESHOLD`（流动性阈值）、`TOP_N` 等 |

---

## 🧠 策略体系

### 股票策略（举例）
- 健康放量上涨（量价配合）
- 均线金叉（MA5上穿MA20）
- MACD 多头
- RSI 超跌反弹
- 低波高换手
- 慢牛低换手（斜率+低波动）

### ETF 轮动策略（举例）
- **横截面动量**：多周期加权评分，选最强 ETF
- **风险调整动量**：收益/波动率比值最高
- **双动量**：绝对收益过滤 + 动量排序（防御性强）
- **ETF均线金叉**：趋势跟随
- **ETF低波动**：稳健配置
- **ETF RSI 超跌反弹**：逆向交易

> 所有策略均可在 `strategies/configs.py` 中按模板自由增删。

---

## 📝 开源与反馈

- 代码仓库：`https://github.com/qianluxi/stock_easyselect1/tree/v2.0ETF版`
- 欢迎提交 Issue 或 PR，一同完善量化选股工具。

⚠️ 本系统仅供研究学习，不构成任何投资建议。股市有风险，投资需谨慎。
```