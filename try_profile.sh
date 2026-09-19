#!/bin/bash
# 实验：用描述文件交付 Chrome 策略（可能让 Chrome 判定设备"受管理"从而解锁自托管源）
# 失败可撤销：sudo profiles remove -identifier local.makermz.tmwd
[ $EUID -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$0")"
profiles install -type configuration -path tmwd.mobileconfig && echo "✅ 描述文件已安装"
echo "--- 验证 ---"
profiles show -type configuration 2>/dev/null | grep -A2 "local.makermz" | head -5
profiles status -type enrollment
