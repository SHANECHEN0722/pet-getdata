"""
市场选择器 - 智能分层采样
参考：poly_data 与官方 SDK 的市场筛选逻辑
"""

import requests
import time
from typing import List, Dict, Optional
from dataclasses import dataclass

from getdata.config.settings import (
    GAMMA_API,
    market_config,
    collection_config
)
from getdata.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Market:
    """市场数据类"""
    market_id: str
    condition_id: str
    question: str
    description: str
    end_date: str
    volume_24hr: float
    liquidity: float
    yes_token_id: str
    no_token_id: str
    outcome_prices: List[str]
    tags: List[str]
    active: bool
    closed: bool
    
    @classmethod
    def from_api_response(cls, data: Dict) -> Optional['Market']:
        """从 API 响应创建 Market 对象"""
        try:
            import json
            
            # 解析 token IDs
            clob_token_ids = json.loads(data.get('clobTokenIds', '[]'))
            yes_token = clob_token_ids[0] if len(clob_token_ids) > 0 else None
            no_token = clob_token_ids[1] if len(clob_token_ids) > 1 else None
            
            # 解析 outcome prices
            outcome_prices_str = data.get('outcomePrices', '[]')
            if isinstance(outcome_prices_str, str):
                outcome_prices = json.loads(outcome_prices_str)
            else:
                outcome_prices = outcome_prices_str
            
            return cls(
                market_id=data.get('id', ''),
                condition_id=data.get('conditionId', ''),
                question=data.get('question', ''),
                description=data.get('description', ''),
                end_date=data.get('endDate', ''),
                volume_24hr=float(data.get('volume24hr', 0)),
                liquidity=float(data.get('liquidityNum', 0)),
                yes_token_id=yes_token or '',
                no_token_id=no_token or '',
                outcome_prices=outcome_prices,
                tags=data.get('tags', []),
                active=data.get('active', False),
                closed=data.get('closed', False)
            )
        except Exception as e:
            logger.error(f"解析市场数据失败: {e}, data={data.get('id', 'unknown')}")
            return None
    
    def meets_criteria(self) -> bool:
        """检查市场是否满足筛选条件"""
        # 活跃性检查
        if market_config.ONLY_ACTIVE and not self.active:
            return False
        
        if self.closed:
            return False
        
        # 流动性检查
        if self.liquidity < market_config.MIN_LIQUIDITY:
            return False
        
        # 成交量检查
        if self.volume_24hr < market_config.MIN_VOLUME_24H:
            return False
        
        # 二元市场检查
        if market_config.ONLY_BINARY:
            if not self.yes_token_id or not self.no_token_id:
                return False
        
        return True


class MarketSelector:
    """市场选择器 - 负责获取和筛选市场"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    def fetch_markets(
        self,
        limit: int = None,
        order: str = "volume24hr",
        ascending: bool = False
    ) -> List[Market]:
        """
        从 Gamma API 获取市场列表（带重试机制）
        
        Args:
            limit: 返回的市场数量上限
            order: 排序字段（volume24hr, liquidity, endDate 等）
            ascending: 是否升序
        
        Returns:
            Market 对象列表
        """
        limit = limit or market_config.INITIAL_POOL_SIZE
        
        # 带重试的请求逻辑
        for attempt in range(1, collection_config.MAX_RETRIES + 1):
            try:
                self.logger.info(
                    f"正在从 API 获取市场列表（limit={limit}, order={order}）..."
                    f" [尝试 {attempt}/{collection_config.MAX_RETRIES}]"
                )
                
                response = requests.get(
                    f"{GAMMA_API}/markets",
                    params={
                        "limit": limit,
                        "active": market_config.ONLY_ACTIVE,
                        "closed": False,
                        "order": order,
                        "ascending": ascending
                    },
                    timeout=collection_config.REQUEST_TIMEOUT
                )
                response.raise_for_status()
                
                data = response.json()
                self.logger.info(f"✓ API 返回 {len(data)} 个市场")
                
                # 解析为 Market 对象
                markets = []
                for item in data:
                    market = Market.from_api_response(item)
                    if market:
                        markets.append(market)
                
                self.logger.info(f"✓ 成功解析 {len(markets)} 个市场")
                return markets
                
            except requests.exceptions.Timeout:
                self.logger.warning(
                    f"✗ 请求超时（{collection_config.REQUEST_TIMEOUT}秒）"
                )
                if attempt < collection_config.MAX_RETRIES:
                    self.logger.info(f"等待 {collection_config.RETRY_DELAY} 秒后重试...")
                    time.sleep(collection_config.RETRY_DELAY)
                else:
                    self.logger.error("所有重试均失败，尝试分批获取...")
                    return self._fetch_markets_in_batches(limit, order, ascending)
                    
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"✗ 请求失败: {e}")
                if attempt < collection_config.MAX_RETRIES:
                    self.logger.info(f"等待 {collection_config.RETRY_DELAY} 秒后重试...")
                    time.sleep(collection_config.RETRY_DELAY)
                else:
                    self.logger.error("所有重试均失败，尝试分批获取...")
                    return self._fetch_markets_in_batches(limit, order, ascending)
                    
            except Exception as e:
                self.logger.error(f"✗ 处理市场数据时出错: {e}", exc_info=True)
                return []
        
        return []
    
    def _fetch_markets_in_batches(
        self,
        total_limit: int,
        order: str,
        ascending: bool,
        batch_size: int = 50
    ) -> List[Market]:
        """
        分批获取市场数据（备选方案）
        
        Args:
            total_limit: 总共需要获取的市场数量
            order: 排序字段
            ascending: 是否升序
            batch_size: 每批获取的数量
        
        Returns:
            Market 对象列表
        """
        self.logger.info(f"开始分批获取市场（每批 {batch_size} 个）...")
        all_markets = []
        offset = 0
        
        while len(all_markets) < total_limit:
            try:
                current_batch_size = min(batch_size, total_limit - len(all_markets))
                self.logger.info(
                    f"获取第 {offset//batch_size + 1} 批（offset={offset}, limit={current_batch_size}）..."
                )
                
                response = requests.get(
                    f"{GAMMA_API}/markets",
                    params={
                        "limit": current_batch_size,
                        "offset": offset,
                        "active": market_config.ONLY_ACTIVE,
                        "closed": False,
                        "order": order,
                        "ascending": ascending
                    },
                    timeout=collection_config.REQUEST_TIMEOUT
                )
                response.raise_for_status()
                
                data = response.json()
                if not data:
                    self.logger.info("没有更多市场数据，停止分批获取")
                    break
                
                # 解析本批数据
                for item in data:
                    market = Market.from_api_response(item)
                    if market:
                        all_markets.append(market)
                
                self.logger.info(f"✓ 本批获取 {len(data)} 个市场，累计 {len(all_markets)} 个")
                
                offset += current_batch_size
                
                # 批次间延迟，避免速率限制
                if len(all_markets) < total_limit:
                    time.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"✗ 分批获取失败: {e}")
                break
        
        self.logger.info(f"✓ 分批获取完成，共 {len(all_markets)} 个市场")
        return all_markets
    
    def filter_markets(self, markets: List[Market]) -> List[Market]:
        """
        根据配置过滤市场
        
        Args:
            markets: 待过滤的市场列表
        
        Returns:
            满足条件的市场列表
        """
        filtered = [m for m in markets if m.meets_criteria()]
        
        self.logger.info(
            f"过滤后保留 {len(filtered)}/{len(markets)} 个市场 "
            f"(min_liq=${market_config.MIN_LIQUIDITY}, "
            f"min_vol=${market_config.MIN_VOLUME_24H})"
        )
        
        return filtered
    
    def stratified_sample(self, markets: List[Market]) -> List[Market]:
        """
        分层采样：高/中/低流动性市场
        
        策略：
        - 高流动性：前 20% 中选 N 个
        - 中等流动性：30%-50% 区间选 M 个
        - 低流动性：80% 后选 K 个
        
        Args:
            markets: 已排序的市场列表（按 volume_24hr 降序）
        
        Returns:
            采样后的市场列表
        """
        if len(markets) < market_config.TOTAL_MARKETS:
            self.logger.warning(
                f"可用市场数 ({len(markets)}) 少于目标数 ({market_config.TOTAL_MARKETS})，"
                f"使用全部"
            )
            return markets[:market_config.TOTAL_MARKETS]
        
        selected = []
        
        # 高流动性层（前 20%）
        high_end = max(
            market_config.HIGH_LIQUIDITY_COUNT,
            int(len(markets) * 0.2)
        )
        high_tier = markets[:high_end]
        selected.extend(high_tier[:market_config.HIGH_LIQUIDITY_COUNT])
        
        # 中等流动性层（30%-50%）
        mid_start = int(len(markets) * 0.3)
        mid_end = int(len(markets) * 0.5)
        mid_tier = markets[mid_start:mid_end]
        selected.extend(mid_tier[:market_config.MID_LIQUIDITY_COUNT])
        
        # 低流动性层（80% 后）
        low_start = int(len(markets) * 0.8)
        low_tier = markets[low_start:]
        selected.extend(low_tier[:market_config.LOW_LIQUIDITY_COUNT])
        
        self.logger.info(
            f"✓ 分层采样完成：\n"
            f"  - 高流动性: {len(selected[:market_config.HIGH_LIQUIDITY_COUNT])} 个\n"
            f"  - 中等流动性: {len(selected[market_config.HIGH_LIQUIDITY_COUNT:market_config.HIGH_LIQUIDITY_COUNT+market_config.MID_LIQUIDITY_COUNT])} 个\n"
            f"  - 低流动性: {len(selected[market_config.HIGH_LIQUIDITY_COUNT+market_config.MID_LIQUIDITY_COUNT:])} 个"
        )
        
        return selected
    
    def select_markets(self) -> List[Market]:
        """
        主流程：获取、过滤、采样市场
        
        Returns:
            最终选中的市场列表
        """
        self.logger.info("=" * 60)
        self.logger.info("开始市场选择流程")
        self.logger.info("=" * 60)
        
        # 1. 获取市场池
        all_markets = self.fetch_markets()
        if not all_markets:
            self.logger.error("无法获取市场数据，退出")
            return []
        
        # 2. 过滤
        filtered_markets = self.filter_markets(all_markets)
        if not filtered_markets:
            self.logger.error("过滤后无可用市场，放宽条件或检查 API")
            return []
        
        # 3. 分层采样
        selected_markets = self.stratified_sample(filtered_markets)
        
        # 4. 日志输出选中的市场
        self.logger.info("\n选中的市场详情：")
        for i, m in enumerate(selected_markets, 1):
            tier = (
                "高流动性" if i <= market_config.HIGH_LIQUIDITY_COUNT
                else "中等流动性" if i <= market_config.HIGH_LIQUIDITY_COUNT + market_config.MID_LIQUIDITY_COUNT
                else "低流动性"
            )
            self.logger.info(
                f"[{i}] {tier} | {m.question[:60]}...\n"
                f"    Volume: ${m.volume_24hr:,.0f} | Liquidity: ${m.liquidity:,.0f} | "
                f"ID: {m.market_id[:12]}..."
            )
        
        self.logger.info("=" * 60)
        return selected_markets
