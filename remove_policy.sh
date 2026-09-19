#!/bin/bash
# 放弃策略路线时清理所有痕迹
[ $EUID -eq 0 ] || exec sudo "$0" "$@"
profiles remove -identifier local.makermz.tmwd 2>/dev/null && echo "✅ 描述文件已移除" || echo "(无描述文件)"
rm -f "/Library/Managed Preferences/com.google.Chrome.plist" && echo "✅ 策略 plist 已移除"
echo "完成 —— chrome://policy 重启后应清空"
