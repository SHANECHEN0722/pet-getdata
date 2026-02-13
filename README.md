## 数据字段说明

### 元数据字段（`METADATA_FIELDS`）

| 字段 | 含义 |
|---|---|
| `market_id` | 市场唯一 ID（主关联键） |
| `condition_id` | 条件 ID（链上结算条件标识） |
| `question` | 市场问题标题 |
| `description` | 市场规则/结算说明 |
| `end_date` | 市场截止时间（通常 UTC） |
| `volume_24hr` | 近 24 小时成交量 |
| `liquidity` | 流动性深度（盘口厚度） |
| `yes_token_id` | YES outcome 对应 token ID |
| `no_token_id` | NO outcome 对应 token ID |
| `tags` | 标签分类 |
| `created_at` | 本地写入该元数据的时间 |

---

### 时序数据字段（`TIMESERIES_FIELDS`）

> 这是“快照模式”：每隔固定秒数记录一次市场状态。

| 字段 | 含义 |
|---|---|
| `timestamp` | 采集时刻 Unix 时间戳（秒） |
| `datetime` | 采集时刻可读时间 |
| `midpoint` | 中间价 |
| `best_bid` | 最优买价 |
| `best_ask` | 最优卖价 |
| `spread` | 价差（通常约等于 `best_ask - best_bid`） |
| `bid_depth_top5` | 买盘前 5 档累计深度 |
| `ask_depth_top5` | 卖盘前 5 档累计深度 |

---

### 逐笔成交字段（`TRADE_FIELDS`）

> 这是“逐笔模式”：每一笔成交记录一行，并按游标持续增量采集。

| 字段 | 含义 |
|---|---|
| `timestamp` | 成交时间戳（秒） |
| `datetime` | 本地标准化记录时间 |
| `trade_id` | 成交唯一标识（用于去重） |
| `market_id` | 所属市场 ID |
| `token_id` | 对应 outcome token ID |
| `side` | 成交方向（以数据源定义为准） |
| `price` | 成交价格 |
| `size` | 成交数量 |
| `amount` | 成交金额（通常近似 `price * size`） |
| `tx_hash` | 链上交易哈希（若数据源提供） |
| `raw` | 原始 JSON 字段（保真留档） |

---

## 采集模式说明

- **快照模式**：固定间隔采 `midpoint / spread / depth` 等市场状态。  
- **逐笔模式**：持续抓取新增成交，基于游标断点续采。  
- 当前逐笔默认开启“追平模式”：单轮会翻页直到无新数据（同时受安全上限保护）。

---
