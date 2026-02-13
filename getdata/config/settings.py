"""
配置文件 - 所有可调参数集中管理
参考：Polymarket 官方 SDK 与社区最佳实践
"""

import os
from pathlib import Path
from typing import List

# ==================== API 端点 ====================
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# ==================== 采集配置 ====================
class CollectionConfig:
    """数据采集配置"""
    
    # 采集间隔（秒）
    INTERVAL_SECONDS: int = 180  # 3 分钟
    
    # 请求超时（秒）- 增加到 30 秒以应对大量数据请求
    REQUEST_TIMEOUT: int = 300
    
    # 单次采集失败后的重试次数
    MAX_RETRIES: int = 3
    
    # 重试间隔（秒）
    RETRY_DELAY: int = 5
    
    # 速率限制：市场间的延迟（秒）
    RATE_LIMIT_DELAY: float = 0.3
    
    # 是否采集订单簿深度
    COLLECT_ORDERBOOK_DEPTH: bool = True
    
    # 订单簿深度档位数
    ORDERBOOK_TOP_N: int = 5

# ==================== 逐笔成交采集配置 ====================
class TradeCollectionConfig:
    """逐笔成交（订单级）采集配置"""

    # 是否启用逐笔成交采集
    ENABLED: bool = True

    # 每次请求的成交数量上限
    PAGE_LIMIT: int = 200

    # 追平模式：每轮持续翻页直到没有新数据
    CATCH_UP_UNTIL_EXHAUSTED: bool = True

    # 单轮翻页安全上限（防止异常接口导致死循环）
    # 说明：首次历史回溯会按该上限分轮推进（支持断点续传），避免单轮耗时过长
    MAX_PAGES_PER_MARKET: int = 20

    # 交易请求超时（秒）
    REQUEST_TIMEOUT: int = 300

    # 检测到 L2 凭证时，自动启用 CLOB 全量历史模式
    USE_L2_HISTORY_IF_AVAILABLE: bool = False

    # 仅提供私钥时，是否自动 create_or_derive_api_creds
    L2_AUTO_DERIVE_CREDS: bool = True

    # L2 请求重试配置
    L2_MAX_RETRIES: int = 3
    L2_RETRY_DELAY: float = 2.0

    # L2 鉴权配置（建议通过环境变量注入）
    L2_CHAIN_ID: int = int(os.getenv("POLY_L2_CHAIN_ID", "137"))
    L2_PRIVATE_KEY: str = os.getenv("POLY_L2_PRIVATE_KEY", "")
    L2_API_KEY: str = os.getenv("POLY_L2_API_KEY", "")
    L2_API_SECRET: str = os.getenv("POLY_L2_API_SECRET", "")
    L2_API_PASSPHRASE: str = os.getenv("POLY_L2_API_PASSPHRASE", "")

    # 候选交易接口（按顺序尝试）
    TRADE_ENDPOINTS: List[str] = [
        f"{CLOB_API}/trades",
        f"{DATA_API}/trades"
    ]

# ==================== 市场选择配置 ====================
class MarketSelectionConfig:
    """市场分层采样配置"""
    
    # 高流动性市场数量（volume_24hr 前 20%）
    HIGH_LIQUIDITY_COUNT: int = 3
    
    # 中等流动性市场数量（30%-50%）
    MID_LIQUIDITY_COUNT: int = 2
    
    # 低流动性市场数量（80% 后）
    LOW_LIQUIDITY_COUNT: int = 1
    
    # 总市场数量
    @property
    def TOTAL_MARKETS(self) -> int:
        return (self.HIGH_LIQUIDITY_COUNT + 
                self.MID_LIQUIDITY_COUNT + 
                self.LOW_LIQUIDITY_COUNT)
    
    # 从 API 获取的初始市场池大小
    INITIAL_POOL_SIZE: int = 100  # 改成 100 或 80
    
    # 市场过滤条件
    MIN_LIQUIDITY: float = 100.0  # 最小流动性（美元）
    MIN_VOLUME_24H: float = 0.0   # 最小 24h 成交量
    ONLY_ACTIVE: bool = True      # 只选择活跃市场
    ONLY_BINARY: bool = True      # 只选择二元市场（YES/NO）

# ==================== 存储配置 ====================
class StorageConfig:
    """数据存储配置"""
    
    # 数据根目录
    DATA_DIR: Path = Path("./polymarket_data")
    
    # 元数据文件
    METADATA_FILE: Path = DATA_DIR / "market_metadata.csv"
    
    # 时序数据目录
    TIMESERIES_DIR: Path = DATA_DIR / "timeseries"
    
    # 日志目录
    LOG_DIR: Path = DATA_DIR / "logs"

    # 逐笔成交目录
    TRADES_DIR: Path = DATA_DIR / "trades"

    # 逐笔成交断点游标
    TRADE_CURSOR_FILE: Path = DATA_DIR / "trade_cursors.json"
    
    # 日志文件
    LOG_FILE: Path = LOG_DIR / "collection.log"
    
    # CSV 分隔符
    CSV_DELIMITER: str = ","
    
    # 是否追加模式（False 会覆盖已有文件）
    APPEND_MODE: bool = True
    
    # 时序文件命名格式
    @staticmethod
    def get_timeseries_filename(market_id: str, outcome: str = "YES") -> Path:
        """生成时序数据文件名"""
        return StorageConfig.TIMESERIES_DIR / f"{market_id}_{outcome}.csv"

    @staticmethod
    def get_trades_filename(market_id: str, outcome: str = "YES") -> Path:
        """生成逐笔成交文件名"""
        return StorageConfig.TRADES_DIR / f"{market_id}_{outcome}.csv"

# ==================== 日志配置 ====================
class LogConfig:
    """日志配置"""
    
    # 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL
    LEVEL: str = "INFO"
    
    # 日志格式
    FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    # 时间格式
    DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    
    # 控制台输出
    CONSOLE_OUTPUT: bool = True
    
    # 文件输出
    FILE_OUTPUT: bool = True
    
    # 日志文件最大大小（MB）
    MAX_FILE_SIZE_MB: int = 50
    
    # 日志文件备份数量
    BACKUP_COUNT: int = 5

# ==================== 运行配置 ====================
class RuntimeConfig:
    """运行时配置"""
    
    # 默认运行时长（小时），None 表示无限运行
    DEFAULT_DURATION_HOURS: int = None
    
    # 是否在启动时验证 API 连接
    VERIFY_API_ON_START: bool = True
    
    # 启动延迟（秒，给予时间检查配置）
    STARTUP_DELAY: int = 2
    
    # 优雅退出超时（秒）
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 10

# ==================== 数据字段配置 ====================
class DataFieldsConfig:
    """定义采集的数据字段"""
    
    # 元数据字段
    METADATA_FIELDS: List[str] = [
        'market_id',
        'condition_id',
        'question',
        'description',
        'end_date',
        'volume_24hr',
        'liquidity',
        'yes_token_id',
        'no_token_id',
        'tags',
        'created_at'
    ]
    
    # 时序数据字段
    TIMESERIES_FIELDS: List[str] = [
        'timestamp',
        'datetime',
        'midpoint',
        'best_bid',
        'best_ask',
        'spread',
        'bid_depth_top5',
        'ask_depth_top5'
    ]

    # 逐笔成交字段
    TRADE_FIELDS: List[str] = [
        'timestamp',
        'datetime',
        'trade_id',
        'market_id',
        'token_id',
        'side',
        'price',
        'size',
        'amount',
        'tx_hash',
        'raw'
    ]

# ==================== 实例化配置 ====================
collection_config = CollectionConfig()
trade_config = TradeCollectionConfig()
market_config = MarketSelectionConfig()
storage_config = StorageConfig()
log_config = LogConfig()
runtime_config = RuntimeConfig()
data_fields_config = DataFieldsConfig()

# ==================== 初始化目录 ====================
def init_directories():
    """创建必要的目录"""
    storage_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage_config.TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
    storage_config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    storage_config.TRADES_DIR.mkdir(parents=True, exist_ok=True)

# 自动初始化
init_directories()
