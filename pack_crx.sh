#!/bin/bash
# TMWD 扩展重打包（改了 assets/ 之后跑这个；然后重启 TMWebDriver 服务）
# 用法: ./pack_crx.sh [新版本号]   如 ./pack_crx.sh 2.3
set -e
cd "$(dirname "$0")"
if [ -n "$1" ]; then
  python3 -c "import json;p='assets/manifest.json';m=json.load(open(p));m['version']='$1';json.dump(m,open(p,'w'),indent=2)"
fi
VER=$(python3 -c "import json;print(json.load(open('assets/manifest.json'))['version'])")
npx -y crx3 -p extension_key.pem -o packed/tmwd.crx assets/
echo "✅ 已打包 v$VER → packed/tmwd.crx（Chrome 重启后会自动检查更新）"
