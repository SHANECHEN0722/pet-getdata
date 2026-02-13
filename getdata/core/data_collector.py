"""
数据采集器 - 核心采集逻辑
参考：官方 py-clob-client 与 poly_data 项目
"""

import time
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

from py_clob_client.client import ClobClient

from getdata.config.settings import (
    CLOB_API,
    collection_config
)
from getdata.core.market_selector import Market
from getdata.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketSnapshot:
    """单次市场快照数据"""
    timestamp: int
    datetime: str
    market_id: str
    token_id: str
    midpoint: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    bid_depth_top5: Optional[float]
    ask_depth_top5: Optional[float]
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class DataCollector:
    """数据采集器"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.client = ClobClient(CLOB_API)
        self.logger.info("✓ CLOB 客户端初始化完成")
    
    def validate_market(self, market: Market) -> bool:
        """
        验证市场是否有有效的订单簿
        
        Args:
            market: Market 对象
        
        Returns:
            True 如果市场有效，False 否则
        """
        if not market.yes_token_id:
            self.logger.debug(f"市场无 YES token: {market.question[:40]}")
            return False
        
        try:
            # 尝试获取 midpoint 来验证订单簿是否存在
            self.client.get_midpoint(market.yes_token_id)
            return True
        except Exception as e:
            error_msg = str(e)
            if '404' in error_msg or 'No orderbook' in error_msg:
                self.logger.debug(
                    f"市场无订单簿 (跳过): {market.question[:40]}..."
                )
            else:
                self.logger.debug(
                    f"市场验证失败 (跳过): {market.question[:40]}... - {e}"
                )
            return False
    
    def get_orderbook_depth(
        self,
        token_id: str,
        top_n: int = None
    ) -> tuple:
        """
        获取订单簿深度（前 N 档买卖单总量）
        
        Args:
            token_id: Token ID
            top_n: 前 N 档，默认使用配置值
        
        Returns:
            (bid_depth, ask_depth) 或 (None, None)
        """
        if not collection_config.COLLECT_ORDERBOOK_DEPTH:
            return None, None
        
        top_n = top_n or collection_config.ORDERBOOK_TOP_N
        
        try:
            book = self.client.get_order_book(token_id)
            
            # 买盘深度（按价格降序排列，取前 N 档）
            sorted_bids = sorted(
                book.bids,
                key=lambda x: float(x.price),
                reverse=True
            )
            bid_depth = sum(
                float(bid.size) for bid in sorted_bids[:top_n]
            )
            
            # 卖盘深度（按价格升序排列，取前 N 档）
            sorted_asks = sorted(
                book.asks,
                key=lambda x: float(x.price)
            )
            ask_depth = sum(
                float(ask.size) for ask in sorted_asks[:top_n]
            )
            
            return bid_depth, ask_depth
            
        except Exception as e:
            self.logger.debug(
                f"获取订单簿深度失败 (token={token_id[:12]}...): {e}"
            )
            return None, None
    
    def collect_snapshot(
        self,
        market: Market,
        token_id: str
    ) -> Optional[MarketSnapshot]:
        """
        采集单个市场的快照数据
        
        Args:
            market: Market 对象
            token_id: 要采集的 token ID（通常是 yes_token_id）
        
        Returns:
            MarketSnapshot 对象或 None
        """
        try:
            # 基础价格数据
            mid_data = self.client.get_midpoint(token_id)
            midpoint = float(mid_data.get('mid', 0))
            
            # 价差
            spread_data = self.client.get_spread(token_id)
            spread = float(spread_data.get('spread', 0))
            
            # Best bid/ask
            best_bid, best_ask = None, None
            try:
                buy_price_data = self.client.get_price(token_id, side="BUY")
                sell_price_data = self.client.get_price(token_id, side="SELL")
                best_ask = float(buy_price_data.get('price', 0))
                best_bid = float(sell_price_data.get('price', 0))
            except Exception as e:
                self.logger.debug(f"获取 bid/ask 失败: {e}")
            
            # 订单簿深度
            bid_depth, ask_depth = self.get_orderbook_depth(token_id)
            
            # 构建快照
            snapshot = MarketSnapshot(
                timestamp=int(time.time()),
                datetime=datetime.now().isoformat(),
                market_id=market.market_id,
                token_id=token_id,
                midpoint=midpoint,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                bid_depth_top5=bid_depth,
                ask_depth_top5=ask_depth
            )
            
            return snapshot
            
        except Exception as e:
            error_msg = str(e)
            # 区分404错误（订单簿不存在）和其他错误
            if '404' in error_msg or 'No orderbook' in error_msg:
                self.logger.debug(
                    f"订单簿不存在 (market={market.question[:30]}...): 可能已关闭或未开始交易"
                )
            else:
                self.logger.warning(
                    f"采集快照失败 (market={market.question[:30]}...): {e}"
                )
            return None
    
    def collect_batch(
        self,
        markets: List[Market]
    ) -> List[MarketSnapshot]:
        """
        批量采集多个市场的快照
        
        Args:
            markets: Market 列表
        
        Returns:
            成功采集的快照列表
        """
        snapshots = []
        
        for i, market in enumerate(markets, 1):
            # 使用 YES token
            if not market.yes_token_id:
                self.logger.warning(
                    f"市场无 YES token，跳过: {market.question[:40]}"
                )
                continue
            
            snapshot = self.collect_snapshot(market, market.yes_token_id)
            
            if snapshot:
                snapshots.append(snapshot)
                self.logger.debug(
                    f"[{i}/{len(markets)}] ✓ {market.question[:40]}... | "
                    f"Midpoint={snapshot.midpoint:.4f}"
                )
            else:
                self.logger.debug(
                    f"[{i}/{len(markets)}] ✗ 失败"
                )
            
            # 速率限制
            if i < len(markets):
                time.sleep(collection_config.RATE_LIMIT_DELAY)
        
        return snapshots
    
    def collect_with_retry(
        self,
        markets: List[Market],
        max_retries: int = None
    ) -> List[MarketSnapshot]:
        """
        带重试机制的批量采集
        
        Args:
            markets: Market 列表
            max_retries: 最大重试次数
        
        Returns:
            成功采集的快照列表
        """
        max_retries = max_retries or collection_config.MAX_RETRIES
        
        for attempt in range(1, max_retries + 1):
            try:
                snapshots = self.collect_batch(markets)
                
                if snapshots:
                    return snapshots
                elif attempt < max_retries:
                    self.logger.warning(
                        f"采集失败，{collection_config.RETRY_DELAY} 秒后重试 "
                        f"({attempt}/{max_retries})..."
                    )
                    time.sleep(collection_config.RETRY_DELAY)
                    
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.logger.error(f"采集异常: {e}", exc_info=True)
                if attempt < max_retries:
                    time.sleep(collection_config.RETRY_DELAY)
        
        return []
