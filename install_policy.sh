#!/bin/bash
# 一次性安装：把 TMWD 扩展加入 Chrome 企业强制安装策略（需要 sudo）
# 注意：不用 defaults write —— 新版 macOS 上它写 /Library 会静默失败（cfprefsd 坑），
#       这里直接落 plist 文件，Chrome 启动时读取。
[ $EUID -eq 0 ] || exec sudo "$0" "$@"
set -e
ID=akajnmghgmcneahfaggpgaldfjcfnpjj
URL="http://127.0.0.1:18766/tmwd/update.xml"
DEST="/Library/Managed Preferences/com.google.Chrome.plist"

cat > /tmp/tmwd_chrome_policy.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>ExtensionInstallForcelist</key>
	<array>
		<string>$ID;$URL</string>
	</array>
</dict>
</plist>
EOF
plutil -lint /tmp/tmwd_chrome_policy.plist
mkdir -p "/Library/Managed Preferences"
cp /tmp/tmwd_chrome_policy.plist "$DEST"
chown root:wheel "$DEST"
chmod 644 "$DEST"
rm -f /tmp/tmwd_chrome_policy.plist
# 清掉上次 defaults write 误入的目录（若只有我们的残留）
if [ -d "/Library/Managed Preferences/makermz" ]; then
  CONTENTS=$(ls -A "/Library/Managed Preferences/makermz" 2>/dev/null)
  if [ -z "$CONTENTS" ] || [ "$CONTENTS" = "com.google.Chrome.plist" ]; then
    rm -rf "/Library/Managed Preferences/makermz"
    echo "已清理误入的 makermz/ 子目录"
  fi
fi
echo "✅ 策略文件已就位："
plutil -p "$DEST"
echo ""
echo "下一步：完全退出 Chrome（⌘Q）→ 重新打开 → chrome://extensions 查看 TMWD CDP Bridge"
