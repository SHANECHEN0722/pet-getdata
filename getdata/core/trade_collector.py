"""
逐笔成交采集器 - 订单级成交数据采集
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from py_clob_client.client import ClobClient

from getdata.config.settings import CLOB_API, trade_config
from getdata.core.market_selector import Market
from getdata.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TradeRecord:
    """单笔成交记录"""
    timestamp: int
    datetime: str
    trade_id: str
    market_id: str
    token_id: str
    side: Optional[str]
    price: Optional[float]
    size: Optional[float]
    amount: Optional[float]
    tx_hash: Optional[str]
    raw: str

    def to_dict(self) -> Dict:
        return asdict(self)


class TradeCollector:
    """逐笔成交采集器"""

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.client = ClobClient(CLOB_API)
        self.session = requests.Session()

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_cursor(payload: Dict) -> Optional[str]:
        return (
            payload.get("next_cursor")
            or payload.get("nextCursor")
            or payload.get("cursor")
            or payload.get("next")
        )

    @staticmethod
    def _extract_trades(payload: Dict) -> List[Dict]:
        if isinstance(payload, list):
            return payload

        for key in ("trades", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        return []

    def _normalize_trade(
        self,
        raw_trade: Dict,
        market_id: str,
        token_id: str
    ) -> Optional[TradeRecord]:
        trade_id = (
            raw_trade.get("id")
            or raw_trade.get("tradeID")
            or raw_trade.get("trade_id")
            or raw_trade.get("match_id")
        )

        trade_ts = (
            raw_trade.get("timestamp")
            or raw_trade.get("time")
            or raw_trade.get("created_at")
            or raw_trade.get("createdAt")
        )

        try:
            if isinstance(trade_ts, str):
                ts_int = int(float(trade_ts))
            elif isinstance(trade_ts, (int, float)):
                ts_int = int(trade_ts)
            else:
                ts_int = int(time.time())
        except Exception:
            ts_int = int(time.time())

        side = (
            raw_trade.get("side")
            or raw_trade.get("taker_side")
            or raw_trade.get("takerSide")
        )

        price = self._to_float(
            raw_trade.get("price") or raw_trade.get("match_price")
        )
        size = self._to_float(
            raw_trade.get("size") or raw_trade.get("amount") or raw_trade.get("quantity")
        )
        amount = self._to_float(raw_trade.get("amount"))

        if amount is None and price is not None and size is not None:
            amount = price * size

        tx_hash = (
            raw_trade.get("txHash")
            or raw_trade.get("tx_hash")
            or raw_trade.get("transactionHash")
        )

        if not trade_id:
            if tx_hash and ts_int:
                trade_id = f"{tx_hash}:{ts_int}"
            else:
                trade_id = f"{token_id}:{ts_int}:{price}:{size}"

        return TradeRecord(
            timestamp=ts_int,
            datetime=datetime.now().isoformat(),
            trade_id=str(trade_id),
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            amount=amount,
            tx_hash=tx_hash,
            raw=json.dumps(raw_trade, ensure_ascii=False)
        )

    def _fetch_by_clob_client(
        self,
        token_id: str,
        cursor: Optional[str],
        limit: int
    ) -> Tuple[List[Dict], Optional[str]]:
        if not hasattr(self.client, "get_trades"):
            return [], None

        params = {"token_id": token_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor

        try:
            payload = self.client.get_trades(**params)
        except TypeError as e:
            self.logger.debug(
                f"get_trades 签名不兼容，切换 HTTP 回退 (token={token_id[:12]}...): {e}"
            )
            return [], None
        except Exception:
            return [], None

        if isinstance(payload, list):
            return payload, None

        if isinstance(payload, dict):
            return self._extract_trades(payload), self._extract_cursor(payload)

        return [], None

    def _fetch_by_http_endpoint(
        self,
        endpoint: str,
        token_id: str,
        cursor: Optional[str],
        limit: int
    ) -> Tuple[List[Dict], Optional[str]]:
        params = {
            "token_id": token_id,
            "limit": limit
        }
        if cursor:
            params["cursor"] = cursor

        response = self.session.get(
            endpoint,
            params=params,
            timeout=trade_config.REQUEST_TIMEOUT
        )
        response.raise_for_status()

        payload = response.json()

        if isinstance(payload, list):
            return payload, None

        if isinstance(payload, dict):
            return self._extract_trades(payload), self._extract_cursor(payload)

        return [], None

    def fetch_trades_page(
        self,
        token_id: str,
        cursor: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Tuple[List[Dict], Optional[str]]:
        """抓取一页成交数据"""
        page_limit = limit or trade_config.PAGE_LIMIT

        try:
            trades, next_cursor = self._fetch_by_clob_client(token_id, cursor, page_limit)
            if trades:
                return trades, next_cursor
        except Exception as e:
            self.logger.debug(
                f"CLOB client 获取成交失败，切换 HTTP 回退 (token={token_id[:12]}...): {e}"
            )

        last_error = None
        for endpoint in trade_config.TRADE_ENDPOINTS:
            try:
                trades, next_cursor = self._fetch_by_http_endpoint(
                    endpoint=endpoint,
                    token_id=token_id,
                    cursor=cursor,
                    limit=page_limit
                )
                if trades:
                    return trades, next_cursor
            except Exception as e:
                last_error = e
                continue

        if last_error:
            self.logger.debug(
                f"获取成交页失败 (token={token_id[:12]}...): {last_error}"
            )

        return [], None

    def collect_market_trades(
        self,
        market: Market,
        cursor: Optional[str] = None,
        max_pages: Optional[int] = None
    ) -> Tuple[List[TradeRecord], Optional[str]]:
        """采集单个市场的逐笔成交"""
        if not market.yes_token_id:
            return [], cursor

        pages_limit = max_pages or trade_config.MAX_PAGES_PER_MARKET
        token_id = market.yes_token_id

        all_records: List[TradeRecord] = []
        current_cursor = cursor

        pages_fetched = 0
        while True:
            if pages_fetched >= pages_limit:
                self.logger.debug(
                    f"达到分页安全上限，停止本轮追平 (token={token_id[:12]}..., pages={pages_fetched})"
                )
                break

            raw_trades, next_cursor = self.fetch_trades_page(
                token_id=token_id,
                cursor=current_cursor,
                limit=trade_config.PAGE_LIMIT
            )
            pages_fetched += 1

            if not raw_trades:
                break

            for raw_trade in raw_trades:
                record = self._normalize_trade(raw_trade, market.market_id, token_id)
                if record:
                    all_records.append(record)

            if not next_cursor or next_cursor == current_cursor:
                break

            current_cursor = next_cursor

            if not trade_config.CATCH_UP_UNTIL_EXHAUSTED:
                break

        return all_records, current_cursor

    def collect_batch_with_cursors(
        self,
        markets: List[Market],
        cursors: Optional[Dict[str, str]] = None
    ) -> Tuple[List[TradeRecord], Dict[str, str]]:
        """批量采集并更新游标"""
        if not trade_config.ENABLED:
            return [], cursors or {}

        cursors = cursors or {}
        all_records: List[TradeRecord] = []

        for i, market in enumerate(markets, 1):
            if not market.yes_token_id:
                continue

            token_id = market.yes_token_id
            market_cursor = cursors.get(token_id)

            records, updated_cursor = self.collect_market_trades(
                market=market,
                cursor=market_cursor
            )

            all_records.extend(records)

            if updated_cursor:
                cursors[token_id] = updated_cursor

            self.logger.debug(
                f"[{i}/{len(markets)}] 成交采集 {market.market_id[:12]}...: {len(records)} 条"
            )

        return all_records, cursors
