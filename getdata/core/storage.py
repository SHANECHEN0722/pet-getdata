"""
存储模块 - CSV 数据持久化
参考：poly_data 的数据结构设计
"""

import csv
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from getdata.config.settings import (
    storage_config,
    data_fields_config
)
from getdata.core.market_selector import Market
from getdata.core.data_collector import MarketSnapshot
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
    
    def get_collection_stats(self) -> Dict:
        """
        获取采集统计信息
        
        Returns:
            包含文件数、总记录数等的字典
        """
        stats = {
            'timeseries_files': 0,
            'total_records': 0,
            'markets': []
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
        
        if stats['markets']:
            self.logger.info("\n各市场记录数：")
            for m in sorted(stats['markets'], key=lambda x: x['records'], reverse=True):
                self.logger.info(f"  - {m['file']}: {m['records']} 条")
        
        self.logger.info("=" * 60)
