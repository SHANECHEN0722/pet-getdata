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
from py_clob_client.clob_types import ApiCreds, TradeParams

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
        self.l2_enabled = False
        self._l2_market_scope_warned = False

        private_key = (trade_config.L2_PRIVATE_KEY or "").strip()
        api_key = (trade_config.L2_API_KEY or "").strip()
        api_secret = (trade_config.L2_API_SECRET or "").strip()
        api_passphrase = (trade_config.L2_API_PASSPHRASE or "").strip()

        self.client = ClobClient(CLOB_API)

        if trade_config.USE_L2_HISTORY_IF_AVAILABLE:
            self._init_l2_client(
                private_key=private_key,
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase
            )
        else:
            self.logger.info("ℹ 已禁用 L2 历史模式，逐笔成交使用公开接口模式")

        self.session = requests.Session()

    def _init_l2_client(
        self,
        private_key: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str
    ):
        if not private_key:
            self.logger.info("ℹ 未提供 POLY_L2_PRIVATE_KEY，逐笔成交使用公开接口模式")
            return

        try:
            l1_client = ClobClient(
                CLOB_API,
                chain_id=trade_config.L2_CHAIN_ID,
                key=private_key
            )

            creds = None
            if api_key and api_secret and api_passphrase:
                creds = ApiCreds(
                    api_key=api_key,
                    api_secret=api_secret,
                    api_passphrase=api_passphrase
                )
                self.logger.info("✓ 检测到显式 L2 API 凭证，尝试启用 CLOB 全量历史模式")
            elif trade_config.L2_AUTO_DERIVE_CREDS:
                self.logger.info("ℹ 未提供完整 L2 API 凭证，尝试 create_or_derive_api_creds")
                creds = l1_client.create_or_derive_api_creds()

            if not creds:
                self.logger.warning("⚠ L2 API 凭证不可用，回退公开接口模式")
                return

            l1_client.set_api_creds(creds)
            self.client = l1_client
            self.l2_enabled = True
            self.logger.info("✓ L2 已启用：逐笔成交将使用 CLOB 全量历史模式")
        except Exception as e:
            self.client = ClobClient(CLOB_API)
            self.l2_enabled = False
            self.logger.warning(f"⚠ L2 初始化失败，回退公开接口模式: {e}")

    def _collect_market_trades_by_l2(
        self,
        market: Market,
        outcome: str = "YES",
        last_seen_ts: Optional[int] = None
    ) -> Tuple[List[TradeRecord], Optional[str]]:
        token_id = self._get_market_token_id(market, outcome)
        if not token_id:
            return [], None

        params = TradeParams(asset_id=str(token_id))
        if last_seen_ts is not None and last_seen_ts > 0:
            params.after = int(last_seen_ts)

        raw_trades = []
        last_error = None
        for attempt in range(1, trade_config.L2_MAX_RETRIES + 1):
            try:
                raw_trades = self.client.get_trades(params=params, next_cursor="MA==")
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < trade_config.L2_MAX_RETRIES:
                    self.logger.warning(
                        f"L2 get_trades 失败，{trade_config.L2_RETRY_DELAY}s 后重试 "
                        f"({attempt}/{trade_config.L2_MAX_RETRIES}) market={market.market_id}: {e}"
                    )
                    time.sleep(trade_config.L2_RETRY_DELAY)

        if last_error is not None:
            raise last_error

        if not isinstance(raw_trades, list):
            return [], f"ts:{last_seen_ts}" if last_seen_ts else None

        records: List[TradeRecord] = []
        latest_ts = last_seen_ts or 0

        for raw_trade in raw_trades:
            if not self._trade_matches_token(raw_trade, token_id, market.condition_id):
                continue

            record = self._normalize_trade(raw_trade, market.market_id, token_id)
            if not record:
                continue

            if record.timestamp > latest_ts:
                latest_ts = record.timestamp

            if last_seen_ts is not None and record.timestamp <= last_seen_ts:
                continue

            records.append(record)

        next_cursor = f"ts:{latest_ts}" if latest_ts > 0 else None
        return records, next_cursor

    @staticmethod
    def _get_market_token_id(market: Market, outcome: str) -> str:
        if str(outcome).upper() == "NO":
            return market.no_token_id or ""
        return market.yes_token_id or ""

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

    @staticmethod
    def _extract_trade_asset_id(raw_trade: Dict) -> Optional[str]:
        direct_keys = (
            "asset",
            "asset_id",
            "assetId",
            "token_id",
            "tokenId",
            "tokenID",
            "maker_asset_id",
            "makerAssetId",
            "taker_asset_id",
            "takerAssetId"
        )

        for key in direct_keys:
            value = raw_trade.get(key)
            if value not in (None, ""):
                return str(value)

        nested_keys = ("maker_orders", "makerOrders", "orders")
        for key in nested_keys:
            value = raw_trade.get(key)
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    nested_value = (
                        item.get("asset_id")
                        or item.get("assetId")
                        or item.get("token_id")
                        or item.get("tokenId")
                    )
                    if nested_value not in (None, ""):
                        return str(nested_value)

        return None

    @staticmethod
    def _extract_trade_condition_id(raw_trade: Dict) -> Optional[str]:
        value = (
            raw_trade.get("condition_id")
            or raw_trade.get("conditionId")
            or raw_trade.get("market")
            or raw_trade.get("market_id")
            or raw_trade.get("marketId")
        )
        if value in (None, ""):
            return None
        return str(value)

    def _trade_matches_token(
        self,
        raw_trade: Dict,
        token_id: str,
        condition_id: Optional[str] = None
    ) -> bool:
        asset_id = self._extract_trade_asset_id(raw_trade)
        if asset_id is not None:
            return asset_id == str(token_id)

        if condition_id:
            trade_condition_id = self._extract_trade_condition_id(raw_trade)
            if trade_condition_id and trade_condition_id == str(condition_id):
                return True

        return False

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
        if self.l2_enabled:
            return [], None

        if not hasattr(self.client, "get_trades"):
            return [], None

        params = TradeParams(asset_id=str(token_id))
        next_cursor = cursor or "MA=="

        try:
            payload = self.client.get_trades(params=params, next_cursor=next_cursor)
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
        limit: int,
        offset: Optional[int] = None,
        condition_id: Optional[str] = None
    ) -> Tuple[List[Dict], Optional[str]]:
        param_candidates = []

        if condition_id:
            param_candidates.append({"market": str(condition_id), "limit": limit})

        param_candidates.extend([
            {"asset_id": str(token_id), "limit": limit},
            {"token_id": str(token_id), "limit": limit}
        ])

        if cursor:
            for params in param_candidates:
                params["cursor"] = cursor
                params["next_cursor"] = cursor

        if offset is not None:
            for params in param_candidates:
                params["offset"] = offset

        last_error = None
        for params in param_candidates:
            try:
                response = self.session.get(
                    endpoint,
                    params=params,
                    timeout=trade_config.REQUEST_TIMEOUT
                )

                if response.status_code == 400:
                    try:
                        payload = response.json()
                    except Exception:
                        payload = {}

                    error_message = str(payload.get("error", "")).lower()
                    if (
                        "offset" in params
                        and "max historical activity offset" in error_message
                    ):
                        return [], None

                response.raise_for_status()

                payload = response.json()

                if isinstance(payload, list):
                    return payload, None

                if isinstance(payload, dict):
                    return self._extract_trades(payload), self._extract_cursor(payload)
            except Exception as e:
                last_error = e
                continue

        if last_error:
            raise last_error

        return [], None

    def fetch_trades_page(
        self,
        token_id: str,
        condition_id: Optional[str] = None,
        cursor: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None
    ) -> Tuple[List[Dict], Optional[str]]:
        """抓取一页成交数据"""
        page_limit = limit or trade_config.PAGE_LIMIT

        try:
            if offset is None and not self.l2_enabled:
                trades, next_cursor = self._fetch_by_clob_client(token_id, cursor, page_limit)
            else:
                trades, next_cursor = [], None
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
                    limit=page_limit,
                    offset=offset,
                    condition_id=condition_id
                )
                if trades and condition_id:
                    matched = [
                        trade for trade in trades
                        if self._trade_matches_token(trade, token_id, condition_id)
                    ]
                    if not matched:
                        self.logger.debug(
                            f"端点返回数据与目标市场不匹配，尝试下一个端点: {endpoint}"
                        )
                        continue

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
        max_pages: Optional[int] = None,
        outcome: str = "YES"
    ) -> Tuple[List[TradeRecord], Optional[str]]:
        """采集单个市场的逐笔成交"""
        token_id = self._get_market_token_id(market, outcome)
        if not token_id:
            return [], cursor

        pages_limit = max_pages or trade_config.MAX_PAGES_PER_MARKET
        outcome = str(outcome).upper()

        all_records: List[TradeRecord] = []

        current_cursor = None
        fetch_offset = 0
        last_seen_ts: Optional[int] = None

        if cursor:
            if cursor.startswith("ts:"):
                try:
                    last_seen_ts = int(cursor[3:])
                except ValueError:
                    last_seen_ts = None
            elif cursor.startswith("offset:"):
                offset_payload = cursor[7:]
                offset_parts = offset_payload.split(":")

                try:
                    fetch_offset = max(0, int(offset_parts[0]))
                except ValueError:
                    fetch_offset = 0

                if len(offset_parts) > 1:
                    try:
                        last_seen_ts = int(offset_parts[1])
                    except ValueError:
                        last_seen_ts = None
            else:
                current_cursor = cursor

        latest_ts = last_seen_ts or 0
        stop_by_timestamp = False
        backfill_exhausted = False
        total_raw_rows = 0
        total_matched_rows = 0

        if self.l2_enabled and trade_config.USE_L2_HISTORY_IF_AVAILABLE:
            if not self._l2_market_scope_warned:
                self.logger.warning(
                    "检测到 L2 已启用，但 py_clob_client.get_trades 为用户维度接口；"
                    "市场逐笔采集将继续使用 market 公共端点，避免出现全 0 结果"
                )
                self._l2_market_scope_warned = True

        pages_fetched = 0
        while True:
            if pages_fetched >= pages_limit:
                self.logger.debug(
                    f"达到分页安全上限，停止本轮追平 (token={token_id[:12]}..., pages={pages_fetched})"
                )
                break

            raw_trades, next_cursor = self.fetch_trades_page(
                token_id=token_id,
                condition_id=market.condition_id,
                cursor=current_cursor,
                offset=fetch_offset,
                limit=trade_config.PAGE_LIMIT
            )
            pages_fetched += 1

            if not raw_trades:
                backfill_exhausted = True
                break

            total_raw_rows += len(raw_trades)

            filtered_count = 0

            for raw_trade in raw_trades:
                if not self._trade_matches_token(
                    raw_trade,
                    token_id,
                    market.condition_id
                ):
                    filtered_count += 1
                    continue

                record = self._normalize_trade(raw_trade, market.market_id, token_id)
                if record:
                    total_matched_rows += 1
                    if record.timestamp > latest_ts:
                        latest_ts = record.timestamp

                    if last_seen_ts is not None and record.timestamp <= last_seen_ts:
                        stop_by_timestamp = True
                        continue

                    all_records.append(record)

            if filtered_count:
                self.logger.debug(
                    f"过滤非目标 token 成交 {filtered_count} 条 (token={token_id[:12]}...)"
                )

            if stop_by_timestamp:
                backfill_exhausted = True
                break

            if not next_cursor or next_cursor == current_cursor:
                if len(raw_trades) < trade_config.PAGE_LIMIT:
                    backfill_exhausted = True
                    break

                if current_cursor:
                    backfill_exhausted = True
                    break

                fetch_offset += trade_config.PAGE_LIMIT

                if not trade_config.CATCH_UP_UNTIL_EXHAUSTED:
                    break

                continue

            current_cursor = next_cursor

            if not trade_config.CATCH_UP_UNTIL_EXHAUSTED:
                break

        if latest_ts > 0:
            hit_rate = (total_matched_rows / total_raw_rows) if total_raw_rows else 0.0
            self.logger.info(
                f"market={market.market_id} 逐笔质量: 原始={total_raw_rows}, "
                f"{outcome}匹配={total_matched_rows}, 命中率={hit_rate:.1%}"
            )
            if not backfill_exhausted and current_cursor is None and last_seen_ts is None:
                return all_records, f"offset:{fetch_offset}:{latest_ts}"
            return all_records, f"ts:{latest_ts}"

        if current_cursor:
            return all_records, current_cursor

        if fetch_offset > 0:
            return all_records, f"offset:{fetch_offset}"

        return all_records, None

    def collect_batch_with_cursors(
        self,
        markets: List[Market],
        cursors: Optional[Dict[str, str]] = None,
        outcome: str = "YES"
    ) -> Tuple[List[TradeRecord], Dict[str, str]]:
        """批量采集并更新游标"""
        if not trade_config.ENABLED:
            return [], cursors or {}

        outcome = str(outcome).upper()
        cursors = cursors or {}
        all_records: List[TradeRecord] = []

        for i, market in enumerate(markets, 1):
            token_id = self._get_market_token_id(market, outcome)
            if not token_id:
                continue
            market_cursor = cursors.get(token_id)

            started_at = time.time()
            self.logger.info(
                f"[{i}/{len(markets)}] 采集逐笔成交({outcome}): market={market.market_id}"
            )

            records, updated_cursor = self.collect_market_trades(
                market=market,
                cursor=market_cursor,
                outcome=outcome
            )

            all_records.extend(records)

            if updated_cursor:
                cursors[token_id] = updated_cursor

            self.logger.info(
                f"[{i}/{len(markets)}] 完成({outcome}): market={market.market_id}, "
                f"本轮抓取={len(records)} 条, 耗时={time.time() - started_at:.1f}s"
            )

        return all_records, cursors
