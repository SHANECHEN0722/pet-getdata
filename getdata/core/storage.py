"""
存储模块 - CSV 数据持久化
参考：poly_data 的数据结构设计
"""

import csv
import json
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from getdata.config.settings import (
    storage_config,
    data_fields_config
)
from getdata.core.market_selector import Market
from getdata.core.data_collector import MarketSnapshot
from getdata.core.trade_collector import TradeRecord
from getdata.utils.logger import get_logger

logger = get_logger(__name__)


class StorageManager:
    """存储管理器"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.ensure_directories()
    
    def ensure_directories(self):
        """确保所有必要目录存在"""
        storage_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        storage_config.TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)
        storage_config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        storage_config.TRADES_DIR.mkdir(parents=True, exist_ok=True)
    
    def save_market_metadata(
        self,
        markets: List[Market],
        overwrite: bool = False
    ):
        """
        保存市场元数据到 CSV
        
        Args:
            markets: Market 列表
            overwrite: 是否覆盖已有文件
        """
        metadata_file = storage_config.METADATA_FILE
        
        # 检查文件是否存在
        if metadata_file.exists() and not overwrite:
            self.logger.info(f"元数据文件已存在，跳过写入: {metadata_file}")
            return
        
        try:
            with open(metadata_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=data_fields_config.METADATA_FIELDS,
                    delimiter=storage_config.CSV_DELIMITER
                )
                writer.writeheader()
                
                for m in markets:
                    writer.writerow({
                        'market_id': m.market_id,
                        'condition_id': m.condition_id,
                        'question': m.question,
                        'description': m.description,
                        'end_date': m.end_date,
                        'volume_24hr': m.volume_24hr,
                        'liquidity': m.liquidity,
                        'yes_token_id': m.yes_token_id,
                        'no_token_id': m.no_token_id,
                        'tags': '|'.join(m.tags) if m.tags else '',
                        'created_at': datetime.now().isoformat()
                    })
            
            self.logger.info(f"✓ 元数据已保存: {metadata_file} ({len(markets)} 个市场)")
            
        except Exception as e:
            self.logger.error(f"✗ 保存元数据失败: {e}", exc_info=True)
    
    def save_snapshot(self, snapshot: MarketSnapshot):
        """
        保存单个快照到对应市场的时序 CSV 文件
        
        Args:
            snapshot: MarketSnapshot 对象
        """
        csv_file = storage_config.get_timeseries_filename(
            snapshot.market_id,
            "YES"
        )
        
        # 检查文件是否存在，决定是否写表头
        write_header = not csv_file.exists()
        
        try:
            with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=data_fields_config.TIMESERIES_FIELDS,
                    delimiter=storage_config.CSV_DELIMITER
                )
                
                if write_header:
                    writer.writeheader()
                
                writer.writerow({
                    'timestamp': snapshot.timestamp,
                    'datetime': snapshot.datetime,
                    'midpoint': snapshot.midpoint,
                    'best_bid': snapshot.best_bid,
                    'best_ask': snapshot.best_ask,
                    'spread': snapshot.spread,
                    'bid_depth_top5': snapshot.bid_depth_top5,
                    'ask_depth_top5': snapshot.ask_depth_top5
                })
                
        except Exception as e:
            self.logger.error(
                f"✗ 保存快照失败 (market={snapshot.market_id[:12]}...): {e}"
            )
    
    def save_snapshots_batch(self, snapshots: List[MarketSnapshot]):
        """
        批量保存快照
        
        Args:
            snapshots: MarketSnapshot 列表
        """
        for snapshot in snapshots:
            self.save_snapshot(snapshot)
        
        if snapshots:
            self.logger.debug(f"✓ 已保存 {len(snapshots)} 个快照")

    def _load_existing_trade_ids(self, csv_file: Path) -> set:
        """读取已有 trade_id，用于去重"""
        if not csv_file.exists():
            return set()

        existing = set()
        try:
            with open(csv_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=storage_config.CSV_DELIMITER)
                for row in reader:
                    trade_id = row.get('trade_id')
                    if trade_id:
                        existing.add(trade_id)
        except Exception as e:
            self.logger.warning(f"读取已有 trade_id 失败 {csv_file.name}: {e}")

        return existing

    def save_trades_batch(self, trades: List[TradeRecord], outcome: str = "YES"):
        """按市场分组保存逐笔成交"""
        if not trades:
            return

        grouped: Dict[str, List[TradeRecord]] = {}
        for trade in trades:
            grouped.setdefault(trade.market_id, []).append(trade)

        total_new = 0

        for market_id, market_trades in grouped.items():
            csv_file = storage_config.get_trades_filename(market_id, outcome)
            write_header = not csv_file.exists()
            existing_ids = self._load_existing_trade_ids(csv_file)

            new_rows = [
                t for t in market_trades
                if t.trade_id and t.trade_id not in existing_ids
            ]

            if not new_rows:
                continue

            try:
                with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=data_fields_config.TRADE_FIELDS,
                        delimiter=storage_config.CSV_DELIMITER
                    )

                    if write_header:
                        writer.writeheader()

                    for row in new_rows:
                        writer.writerow(row.to_dict())

                total_new += len(new_rows)
            except Exception as e:
                self.logger.error(f"✗ 保存逐笔成交失败 ({csv_file.name}): {e}")

        if total_new:
            self.logger.debug(f"✓ 已保存 {total_new} 条逐笔成交")

    def load_trade_cursors(self) -> Dict[str, str]:
        """加载逐笔成交游标"""
        cursor_file = storage_config.TRADE_CURSOR_FILE
        if not cursor_file.exists():
            return {}

        try:
            with open(cursor_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            self.logger.warning(f"读取游标文件失败，已忽略: {e}")

        return {}

    def save_trade_cursors(self, cursors: Dict[str, str]):
        """保存逐笔成交游标"""
        try:
            with open(storage_config.TRADE_CURSOR_FILE, 'w', encoding='utf-8') as f:
                json.dump(cursors or {}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"保存游标文件失败: {e}")
    
    def get_collection_stats(self) -> Dict:
        """
        获取采集统计信息
        
        Returns:
            包含文件数、总记录数等的字典
        """
        stats = {
            'timeseries_files': 0,
            'total_records': 0,
            'markets': [],
            'trade_files': 0,
            'total_trade_records': 0
        }
        
        if not storage_config.TIMESERIES_DIR.exists():
            return stats
        
        csv_files = list(storage_config.TIMESERIES_DIR.glob("*.csv"))
        stats['timeseries_files'] = len(csv_files)
        
        for csv_file in csv_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    record_count = sum(1 for _ in f) - 1  # 减去表头
                    stats['total_records'] += record_count
                    
                    stats['markets'].append({
                        'file': csv_file.name,
                        'records': record_count
                    })
            except Exception as e:
                self.logger.warning(f"读取文件失败 {csv_file.name}: {e}")

        trade_files = list(storage_config.TRADES_DIR.glob("*.csv"))
        stats['trade_files'] = len(trade_files)

        for csv_file in trade_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    record_count = max(sum(1 for _ in f) - 1, 0)
                    stats['total_trade_records'] += record_count
            except Exception as e:
                self.logger.warning(f"读取交易文件失败 {csv_file.name}: {e}")
        
        return stats
    
    def print_stats(self):
        """打印采集统计信息到日志"""
        stats = self.get_collection_stats()
        
        self.logger.info("=" * 60)
        self.logger.info("数据采集统计")
        self.logger.info("=" * 60)
        self.logger.info(f"元数据文件: {storage_config.METADATA_FILE}")
        self.logger.info(f"时序文件数: {stats['timeseries_files']}")
        self.logger.info(f"总记录数: {stats['total_records']}")
        self.logger.info(f"逐笔成交文件数: {stats['trade_files']}")
        self.logger.info(f"逐笔成交总记录数: {stats['total_trade_records']}")
        
        if stats['markets']:
            self.logger.info("\n各市场记录数：")
            for m in sorted(stats['markets'], key=lambda x: x['records'], reverse=True):
                self.logger.info(f"  - {m['file']}: {m['records']} 条")
        
        self.logger.info("=" * 60)
