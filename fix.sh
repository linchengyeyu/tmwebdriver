#!/bin/bash
# TMWebDriver 一键修复：重注 Chrome 扩展 + 重启后台服务
# 用法：bash ~/.hermes/tmwebdriver/fix.sh

EXT_PATH="$HOME/.hermes/tmwebdriver/assets"
EXT_ID=$(echo -n "$EXT_PATH" | shasum -a 256 | cut -c1-32)

echo "== 1. 注入 Chrome 扩展 =="
python3 -c "
import json
path = '$EXT_PATH'
ext_id = '$EXT_ID'
prefs_path = '$HOME/Library/Application Support/Google/Chrome/Default/Preferences'
with open(prefs_path) as f:
    prefs = json.load(f)
prefs.setdefault('extensions', {}).setdefault('settings', {})[ext_id] = {
    'active_permissions': {'api': []}, 'commands': {}, 'content_settings': [],
    'creation_flags': 1, 'from_bookmark': False, 'granted_incognito': True,
    'granted_permissions': {'api': []}, 'incognito_content_settings': [],
    'incognito_preferences': {}, 'install_time': '13000000000000000',
    'installation_policy': 1, 'lastpingday': '13000000000000000',
    'location': 4, 'manifest_version': 3, 'path': path,
    'preferences': {}, 'regular_only_preferences': {}, 'state': 1,
    'was_installed_by_enterprise': False
}
with open(prefs_path, 'w') as f:
    json.dump(prefs, f, indent=2)
print('  ✅ Extension registered')
"

echo ""
echo "== 2. 重启后台服务 =="
launchctl kickstart gui/$(id -u)/com.tmwebdriver.server 2>/dev/null || \
launchctl load ~/Library/LaunchAgents/com.tmwebdriver.server.plist 2>/dev/null
sleep 3

echo ""
echo "== 3. 验证 =="
if lsof -ti :18766 >/dev/null 2>&1; then
    SESSIONS=$(curl -s -X POST http://localhost:18766/link \
      -H "Content-Type: application/json" \
      -d '{"cmd":"get_all_sessions"}' 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('r',[])))")
    echo "  ✅ TMWebDriver OK | $SESSIONS tabs 在线"
else
    echo "  ❌ 服务未启动"
fi
