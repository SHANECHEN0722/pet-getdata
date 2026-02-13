"""
快速测试脚本 - 验证采集工具是否正常工作
运行时间：约 2 分钟
"""

import sys
import time

from getdata.core.market_selector import MarketSelector
from getdata.core.data_collector import DataCollector
from getdata.core.storage import StorageManager
from getdata.utils.logger import get_logger, setup_logger

# 测试专用 logger
logger = setup_logger("test", level="INFO")


def test_api_connection():
    """测试 1：API 连接"""
    logger.info("=" * 60)
    logger.info("测试 1/4：API 连接")
    logger.info("=" * 60)
    
    try:
        selector = MarketSelector()
        markets = selector.fetch_markets(limit=5)
        
        if markets:
            logger.info(f"✓ API 连接成功，获取到 {len(markets)} 个市场")
            logger.info(f"  示例市场: {markets[0].question[:50]}...")
            return True, markets
        else:
            logger.error("✗ API 返回空数据")
            return False, []
    except Exception as e:
        logger.error(f"✗ API 连接失败: {e}")
        return False, []


def test_market_selection():
    """测试 2：市场选择"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 2/4：分层采样")
    logger.info("=" * 60)
    
    try:
        selector = MarketSelector()
        
        # 临时调整配置（只选少数市场）
        from getdata.config.settings import market_config
        original_counts = (
            market_config.HIGH_LIQUIDITY_COUNT,
            market_config.MID_LIQUIDITY_COUNT,
            market_config.LOW_LIQUIDITY_COUNT
        )
        
        market_config.HIGH_LIQUIDITY_COUNT = 1
        market_config.MID_LIQUIDITY_COUNT = 1
        market_config.LOW_LIQUIDITY_COUNT = 0
        
        markets = selector.select_markets()
        
        # 恢复配置
        (market_config.HIGH_LIQUIDITY_COUNT,
         market_config.MID_LIQUIDITY_COUNT,
         market_config.LOW_LIQUIDITY_COUNT) = original_counts
        
        if markets:
            logger.info(f"✓ 成功选择 {len(markets)} 个市场")
            return True, markets
        else:
            logger.error("✗ 未能选择到市场")
            return False, []
    except Exception as e:
        logger.error(f"✗ 市场选择失败: {e}")
        return False, []


def test_data_collection(markets):
    """测试 3：数据采集"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 3/4：数据采集（2 轮，间隔 30 秒）")
    logger.info("=" * 60)
    
    if not markets:
        logger.warning("无可用市场，跳过采集测试")
        return False, []
    
    try:
        collector = DataCollector()
        all_snapshots = []
        
        for round_num in range(1, 3):
            logger.info(f"\n--- 第 {round_num}/2 轮 ---")
            
            snapshots = collector.collect_batch(markets[:2])  # 只采集前 2 个
            
            if snapshots:
                all_snapshots.extend(snapshots)
                for s in snapshots:
                    logger.info(
                        f"  ✓ Market {s.market_id[:12]}... | "
                        f"Midpoint={s.midpoint:.4f} | "
                        f"Spread={s.spread:.4f}"
                    )
            else:
                logger.warning("  ✗ 本轮采集失败")
            
            if round_num < 2:
                logger.info("等待 30 秒...")
                time.sleep(30)
        
        if all_snapshots:
            logger.info(f"\n✓ 共采集 {len(all_snapshots)} 个快照")
            return True, all_snapshots
        else:
            logger.error("✗ 采集失败")
            return False, []
            
    except Exception as e:
        logger.error(f"✗ 采集异常: {e}", exc_info=True)
        return False, []


def test_storage(markets, snapshots):
    """测试 4：数据存储"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 4/4：数据存储")
    logger.info("=" * 60)
    
    try:
        storage = StorageManager()
        
        # 保存元数据
        storage.save_market_metadata(markets, overwrite=True)
        logger.info("✓ 元数据已保存")
        
        # 保存快照
        storage.save_snapshots_batch(snapshots)
        logger.info(f"✓ 已保存 {len(snapshots)} 个快照")
        
        # 统计
        stats = storage.get_collection_stats()
        logger.info(f"✓ 时序文件数: {stats['timeseries_files']}")
        logger.info(f"✓ 总记录数: {stats['total_records']}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ 存储失败: {e}", exc_info=True)
        return False


def main():
    """主测试流程"""
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + " " * 12 + "Polymarket 数据采集工具 - 快速测试" + " " * 12 + "║")
    logger.info("╚" + "═" * 58 + "╝")
    
    # 测试 1: API 连接
    success, markets = test_api_connection()
    if not success:
        logger.error("\n测试失败：无法连接 API")
        return False
    
    # 测试 2: 市场选择
    success, selected_markets = test_market_selection()
    if not success:
        logger.error("\n测试失败：市场选择异常")
        return False
    
    # 测试 3: 数据采集
    success, snapshots = test_data_collection(selected_markets)
    if not success:
        logger.error("\n测试失败：数据采集异常")
        return False
    
    # 测试 4: 数据存储
    success = test_storage(selected_markets, snapshots)
    if not success:
        logger.error("\n测试失败：数据存储异常")
        return False
    
    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("✓ 所有测试通过！")
    logger.info("=" * 60)
    logger.info("\n数据文件位置:")
    from getdata.config.settings import storage_config
    logger.info(f"  元数据: {storage_config.METADATA_FILE}")
    logger.info(f"  时序数据: {storage_config.TIMESERIES_DIR}")
    logger.info(f"  日志: {storage_config.LOG_FILE}")
    
    logger.info("\n现在可以运行完整采集:")
    logger.info("  python -m getdata.main")
    logger.info("  或")
    logger.info("  python -m getdata.main --duration 168  # 运行 7 天")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
