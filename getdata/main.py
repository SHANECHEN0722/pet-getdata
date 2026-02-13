"""
Polymarket 数据采集工具 - 主入口
用途：异常赔率运动检测项目的数据采集

作者：基于 awesome-polymarket 开源项目设计
许可：MIT
"""

import time
import signal
import sys
from typing import Optional

from getdata.config.settings import (
    collection_config,
    runtime_config,
    trade_config,
    storage_config
)
from getdata.core.market_selector import MarketSelector, Market
from getdata.core.data_collector import DataCollector
from getdata.core.trade_collector import TradeCollector
from getdata.core.storage import StorageManager
from getdata.utils.logger import get_logger

logger = get_logger("main")


class CollectionOrchestrator:
    """数据采集协调器"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.running = True
        self.iteration = 0
        
        # 初始化组件
        self.market_selector = MarketSelector()
        self.data_collector = DataCollector()
        self.trade_collector = TradeCollector()
        self.storage_manager = StorageManager()
        self.trade_cursors = self.storage_manager.load_trade_cursors()
        
        # 注册信号处理（优雅退出）
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        self.logger.info("\n收到退出信号，正在优雅关闭...")
        self.running = False
    
    def verify_api_connection(self) -> bool:
        """验证 API 连接"""
        if not runtime_config.VERIFY_API_ON_START:
            return True
        
        self.logger.info("验证 API 连接...")
        
        try:
            # 尝试获取 1 个市场
            test_markets = self.market_selector.fetch_markets(limit=1)
            if test_markets:
                self.logger.info("✓ API 连接正常")
                return True
            else:
                self.logger.error("✗ API 返回空数据")
                return False
        except Exception as e:
            self.logger.error(f"✗ API 连接失败: {e}")
            return False
    
    def setup(self) -> Optional[list]:
        """
        初始化设置：选择市场并保存元数据
        
        Returns:
            选中的市场列表，失败返回 None
        """
        self.logger.info("=" * 70)
        self.logger.info("Polymarket 数据采集工具")
        self.logger.info("用途：异常赔率运动检测 - 时序数据采集")
        self.logger.info("=" * 70)
        
        # 验证 API
        if not self.verify_api_connection():
            self.logger.error("API 连接失败，退出")
            return None
        
        # 选择市场
        markets = self.market_selector.select_markets()
        if not markets:
            self.logger.error("未能选择到任何市场，退出")
            return None
        
        # 验证市场（过滤掉没有订单簿的市场）
        self.logger.info(f"\n验证 {len(markets)} 个市场的订单簿可用性...")
        valid_markets = []
        for i, market in enumerate(markets, 1):
            self.logger.info(f"  [{i}/{len(markets)}] 验证: {market.question[:50]}...")
            if self.data_collector.validate_market(market):
                valid_markets.append(market)
                self.logger.info(f"    ✓ 有效")
            else:
                self.logger.warning(f"    ✗ 无订单簿，已跳过")
        
        if not valid_markets:
            self.logger.error("所有市场均无有效订单簿，退出")
            self.logger.error("提示：可能需要调整过滤条件（MIN_LIQUIDITY, MIN_VOLUME_24H）")
            return None
        
        self.logger.info(
            f"\n✓ {len(valid_markets)}/{len(markets)} 个市场验证通过，将开始采集"
        )
        
        # 保存元数据（只保存有效市场）
        self.storage_manager.save_market_metadata(valid_markets)
        
        # 启动延迟（给用户检查配置的时间）
        if runtime_config.STARTUP_DELAY > 0:
            self.logger.info(
                f"\n{runtime_config.STARTUP_DELAY} 秒后开始采集，"
                f"按 Ctrl+C 可随时停止..."
            )
            time.sleep(runtime_config.STARTUP_DELAY)
        
        return valid_markets
    
    def collection_loop(
        self,
        markets: list,
        duration_hours: Optional[int] = None
    ):
        """
        主采集循环
        
        Args:
            markets: 要采集的市场列表
            duration_hours: 运行时长（小时），None 表示无限运行
        """
        duration_hours = duration_hours or runtime_config.DEFAULT_DURATION_HOURS
        
        self.logger.info("=" * 70)
        self.logger.info("开始数据采集")
        self.logger.info(f"市场数: {len(markets)}")
        self.logger.info(f"采集间隔: {collection_config.INTERVAL_SECONDS} 秒")
        if trade_config.ENABLED:
            self.logger.info("逐笔成交采集: 已启用")
            if trade_config.USE_L2_HISTORY_IF_AVAILABLE:
                missing_l2 = []
                if not (trade_config.L2_PRIVATE_KEY or "").strip():
                    missing_l2.append("POLY_L2_PRIVATE_KEY")
                if not (trade_config.L2_API_KEY or "").strip():
                    missing_l2.append("POLY_L2_API_KEY")
                if not (trade_config.L2_API_SECRET or "").strip():
                    missing_l2.append("POLY_L2_API_SECRET")
                if not (trade_config.L2_API_PASSPHRASE or "").strip():
                    missing_l2.append("POLY_L2_API_PASSPHRASE")

                if missing_l2 and not trade_config.L2_AUTO_DERIVE_CREDS:
                    self.logger.info(
                        "逐笔模式: L2 自动全量未就绪（缺少: "
                        + ", ".join(missing_l2)
                        + "），将使用公开接口"
                    )
                elif missing_l2 and trade_config.L2_AUTO_DERIVE_CREDS:
                    self.logger.info(
                        "逐笔模式: 将尝试私钥自动 derive L2 凭证（若失败则回退公开接口）"
                    )
                else:
                    self.logger.info("逐笔模式: 检测到完整 L2 凭证，优先使用 CLOB 全量历史")
        if duration_hours:
            self.logger.info(f"计划运行时长: {duration_hours} 小时")
        else:
            self.logger.info("持续运行直到手动停止")
        self.logger.info("=" * 70)
        
        start_time = time.time()
        
        try:
            while self.running:
                self.iteration += 1
                cycle_start = time.time()
                
                self.logger.info(f"\n--- 第 {self.iteration} 轮采集 ---")
                
                # 采集数据
                snapshots = self.data_collector.collect_with_retry(markets)
                
                # 保存数据
                if snapshots:
                    self.storage_manager.save_snapshots_batch(snapshots)
                    self.logger.info(
                        f"✓ 成功采集并保存 {len(snapshots)}/{len(markets)} 个市场"
                    )
                else:
                    self.logger.warning("✗ 本轮采集失败")

                # 采集逐笔成交（订单级）
                if trade_config.ENABLED:
                    try:
                        self.logger.info("开始逐笔成交采集...")
                        yes_trades, updated_cursors = self.trade_collector.collect_batch_with_cursors(
                            markets=markets,
                            cursors=self.trade_cursors,
                            outcome="YES"
                        )
                        no_trades, updated_cursors = self.trade_collector.collect_batch_with_cursors(
                            markets=markets,
                            cursors=updated_cursors,
                            outcome="NO"
                        )

                        inserted_yes = self.storage_manager.save_trades_batch(yes_trades, outcome="YES")
                        inserted_no = self.storage_manager.save_trades_batch(no_trades, outcome="NO")
                        self.logger.info(
                            f"✓ 逐笔成交 YES 抓取 {len(yes_trades)} 条，实际新增 {inserted_yes} 条"
                        )
                        self.logger.info(
                            f"✓ 逐笔成交 NO 抓取 {len(no_trades)} 条，实际新增 {inserted_no} 条"
                        )

                        self.trade_cursors = updated_cursors
                        self.storage_manager.save_trade_cursors(self.trade_cursors)
                    except Exception as e:
                        self.logger.warning(f"逐笔成交采集异常（已跳过本轮，不影响快照）: {e}")
                
                # 检查运行时长
                if duration_hours:
                    elapsed_hours = (time.time() - start_time) / 3600
                    if elapsed_hours >= duration_hours:
                        self.logger.info(
                            f"已达到运行时长 {duration_hours} 小时，停止采集"
                        )
                        break
                
                # 等待下一轮
                cycle_elapsed = time.time() - cycle_start
                sleep_time = max(0, collection_config.INTERVAL_SECONDS - cycle_elapsed)
                
                if sleep_time > 0 and self.running:
                    next_time = time.strftime(
                        "%H:%M:%S",
                        time.localtime(time.time() + sleep_time)
                    )
                    self.logger.info(
                        f"等待 {sleep_time:.1f} 秒... (下次采集: {next_time})"
                    )
                    
                    # 分段 sleep，便于响应中断信号
                    for _ in range(int(sleep_time)):
                        if not self.running:
                            break
                        time.sleep(1)
                    
                    # 剩余小数部分
                    if self.running:
                        time.sleep(sleep_time - int(sleep_time))
                
        except KeyboardInterrupt:
            self.logger.info("\n收到键盘中断 (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"采集循环异常: {e}", exc_info=True)
        finally:
            self.cleanup(start_time)
    
    def cleanup(self, start_time: float):
        """清理与总结"""
        total_hours = (time.time() - start_time) / 3600
        
        self.logger.info("\n" + "=" * 70)
        self.logger.info("数据采集已停止")
        self.logger.info(f"总运行时间: {total_hours:.2f} 小时")
        self.logger.info(f"完成轮次: {self.iteration}")
        self.logger.info("=" * 70)
        
        # 打印统计
        self.storage_manager.print_stats()
        
        self.logger.info("\n数据文件位置:")
        self.logger.info(f"  元数据: {storage_config.METADATA_FILE}")
        self.logger.info(f"  时序数据: {storage_config.TIMESERIES_DIR}")
        self.logger.info(f"  逐笔成交: {storage_config.TRADES_DIR}")
        self.logger.info(f"  日志: {storage_config.LOG_FILE}")
    
    def run(self, duration_hours: Optional[int] = None):
        """
        运行主流程
        
        Args:
            duration_hours: 运行时长（小时），None 表示无限运行
        """
        # 初始化
        markets = self.setup()
        if not markets:
            sys.exit(1)
        
        # 开始采集
        self.collection_loop(markets, duration_hours)


def main():
    """程序入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Polymarket 数据采集工具 - 异常赔率运动检测项目"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="运行时长（小时），不指定则持续运行直到 Ctrl+C"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=collection_config.INTERVAL_SECONDS,
        help=f"采集间隔（秒），默认 {collection_config.INTERVAL_SECONDS}"
    )
    parser.add_argument(
        "--log-level",
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help="日志级别"
    )
    
    args = parser.parse_args()
    
    # 动态修改配置
    if args.interval:
        collection_config.INTERVAL_SECONDS = args.interval
    
    # 更新日志级别
    from getdata.config.settings import log_config
    log_config.LEVEL = args.log_level
    
    # 运行
    orchestrator = CollectionOrchestrator()
    orchestrator.run(duration_hours=args.duration)


if __name__ == "__main__":
    main()
