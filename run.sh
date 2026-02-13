#!/bin/bash
# 快速启动脚本

echo "=========================================="
echo "Polymarket 数据采集工具"
echo "=========================================="
echo ""

# 加载本地环境变量（私钥/API 凭证）
if [ -f .env.local ]; then
    # shellcheck disable=SC1091
    source .env.local
    echo "✓ 已加载 .env.local"
else
    echo "ℹ 未找到 .env.local，将使用系统环境变量"
fi

# 检查依赖
echo "检查依赖..."
if ! python3 -c "import py_clob_client" 2>/dev/null; then
    echo "✗ 缺少依赖，正在安装..."
    pip3 install -r getdata/requirements.txt
else
    echo "✓ 依赖已安装"
fi

echo ""
echo "选择运行模式："
echo "  1) 快速测试 (约 2 分钟)"
echo "  2) 持续采集 (按 Ctrl+C 停止)"
echo "  3) 定时采集 (7 天)"
echo ""
read -p "请选择 [1-3]: " choice

case $choice in
    1)
        echo ""
        echo "开始快速测试..."
        python3 -m getdata.test
        ;;
    2)
        echo ""
        echo "开始持续采集（按 Ctrl+C 停止）..."
        python3 -m getdata.main
        ;;
    3)
        echo ""
        echo "开始 7 天采集..."
        python3 -m getdata.main --duration 168
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac
