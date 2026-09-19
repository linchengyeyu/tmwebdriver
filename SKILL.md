---
name: tmwebdriver
description: "Control your real Chrome browser — DOM Outline with aria semantics, dual-channel CSP-proof JS exec, self-healing site skills, optional token auth. HTTP API + Python lib."
triggers:
  - tmwebdriver 安装
  - 安装 tmwebdriver
  - 装个浏览器自动化
  - install tmwebdriver
  - 浏览器插件
  - 控制浏览器
  - tmwd 是什么
  - TMWD 插件
---

# TMWebDriver (TMWD) — 控制你真正在用的 Chrome 浏览器

> 开源 MIT · GitHub: https://github.com/linchengyeyu/tmwebdriver · 当前版本 v2.2

## 一句话搞懂

Chrome 扩展（TMWD CDP Bridge）+ 本地 Python 服务，让你或你的 AI Agent **直接操控已在登录的日常 Chrome**：不开新实例、不用无头模式、不用重新登录。Cookie、会话、浏览器指纹全部保留 —— 反爬系统看到的是真实用户。

## 它是怎么工作的（三层）

```
Agent / 脚本 ──HTTP POST :18766 / WS :18765──▶ TMWebDriver.py（Python 服务）
                                                    │
                                                    ▼ WS（MV3 alarms 保活：5s 探针 + 24s 心跳）
                                    Chrome 扩展 background.js（Service Worker）
                                    ├─ 主通道：chrome.scripting（MAIN world 注入）
                                    ├─ 兜底①：chrome.debugger + CDP Runtime.evaluate（不受页面 CSP 约束）
                                    └─ 兜底②：按需剥 CSP 响应头（DNR 动态规则，10s 自动撤防）
```

每个 Chrome 标签页 = 一个 session（`get_all_sessions` 列出）。Python 库和 HTTP API 二选一驱动。

## 能做什么

| 能力 | 说明 |
|------|------|
| **执行任意 JS** | `execute_js`，支持 await；瞬态失败（导航竞态）自动重试；`channel='cdp'` 可强制走 DevTools 通道 |
| **DOM Outline** | 扫页面输出带编号的可交互元素清单，**带无障碍语义**（role/name/aria-label），按编号点击填字，不用写选择器 |
| **元素级操作** | `click_index` / `input_text_index`（React onChange 兼容 + contenteditable）/ `hover_index` |
| **CDP 真实事件** | `cdp_click_by_index` 等发 isTrusted:true 的真实鼠标/输入事件，React/Web Component 都认 |
| **任意 CDP 命令** | `_cdp_command` / `_cdp_batch` 直通 DevTools 协议（网络、截图、性能…） |
| **Site Skills 沉淀** | 操作成功自动提取稳定选择器存 `site_skills/<domain>.json`，下次免扫描零 token |
| **技能失效自愈** | 网站改版选择器失效时，自动重扫 outline 语义匹配（tag+文本+aria 打分），命中即改写技能并重试 |
| **确定性就绪等待** | `wait_ready`（readyState+双 rAF+可选选择器）、`wait_new_session`，取代 sleep 赌时间 |
| **超长结果保障** | 传输实测 ≥50KB 无截断；`execute_js_chunked` 表达式结果存 `window` 变量分段取回，任意大小 |
| **多平台发布** | `multipost.py`：B站/抖音/小红书 视频图文一键多发 |
| **Cookie 查看** | 扩展 popup 即 Cookie viewer（含 httpOnly/partition 标记，一键复制） |

## HTTP API（curl 即可驱动）

```bash
B=http://127.0.0.1:18766/link
curl -s --noproxy '*' -X POST $B -H "Content-Type: application/json" -d '<JSON>'
```

| cmd | 参数 | 说明 |
|-----|------|------|
| `get_all_sessions` | — | 列出所有已连接标签页 `[{id,url,title},...]` |
| `find_session` | `url_pattern` | 按 URL 子串找会话 |
| `execute_js` | `sessionId`,`code`,`timeout`,`channel`(auto/cdp/script) | 执行 JS，返回 `{r:{data,...}}` |
| `execute_js_chunked` | `sessionId`,`code`(表达式),`chunk` | 超长结果分段取回，返回完整字符串 |
| `wait_ready` | `sessionId`,`timeout`,`selector` | 等页面就绪，返回 `{r:{ready:bool}}` |
| `GET /health` | — | 服务健康 + 是否启用鉴权 |

**长值约定**：单次 `execute_js` 直传已支持 ≥50KB（实测）；要几十万字符（如整页 outerHTML）用 `execute_js_chunked`，它把结果存 `window.__tmwd_result` 后分段拉取拼接。

## Python API 快速上手

```python
from TMWebDriver import TMWebDriver
driver = TMWebDriver()                     # 端口已占用时自动变远程模式
driver.set_session('bilibili.com')         # 按 URL 子串锁定默认会话

outline = driver.get_page_outline(max_elements=30)   # 带编号+role+name 的元素清单
driver.input_text_index(3, "AI工具")        # 按编号填字
driver.click_index(5)                       # 按编号点击
driver.cdp_click_by_index(5)                # CDP 真实点击（顽固组件用这个）

driver.jump("https://example.com", selector=".result-item")  # 导航+等就绪（不用再 sleep）
r = driver.newtab("https://example.com")    # 返回 {'newSession': sid}

driver.save_outline_skill("search", steps=[{"type":"input","index":3,"param":"keyword"},
                                            {"type":"click","index":5}])
driver.execute_skill("search", keyword="AI工具")  # 失效会自动重扫语义自愈
```

## 安全（v2.2 新增，默认关闭）

两个端口只绑 127.0.0.1。要防本机其他进程借用你的登录态执行 JS，启用 token：

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(24))" > token.txt && chmod 600 token.txt
# 重启服务；然后把同一个值填进 assets/config.js 的 TMWD_TOKEN，chrome://extensions 里重载扩展
# 之后所有 HTTP 调用带 -H "X-TMWD-Token: <token>"；远程模式 TMWebDriver() 会自动从 TMWD_TOKEN 环境变量读取
```

不生成 token.txt = 行为与旧版完全一致（现有调用方零改动）。

## 行为收敛（v2.2）

- "已连接"徽章只在 URL 带 `?tmwd_debug` 时显示，平时不污染页面 DOM
- 不再全局剥除所有站点的 CSP 响应头；只在双通道都被 CSP 挡住时临时开启 DNR 规则（10 秒自动撤防）
- content script 不再无条件移除页面 meta CSP 标签

## 安装

> **Chrome 个人机须知（2026-09 实测结论）**：Google 已封死个人电脑上所有程序化安装非商店扩展的通道
> —— `--load-extension` 自 Chrome 136 起被正式版无视；`ExtensionInstallForcelist` 策略自 137 起
> 在"非 MDM 受管设备"上只认商店源（chrome://policy 会显示 [BLOCKED]）；CLI 装 mobileconfig
> 在 Sequoia 已不可用，且描述文件 ≠ MDM 注册，绕不过。**个人机唯一可行方式 = chrome://extensions
> 加载已解压**；扩展消失的根因是 Chrome 启动瞬间源目录不可用会被静默卸载（保持
> ~/.hermes/tmwebdriver/assets 目录稳定即不会再丢）。企业环境用 packed/tmwd.crx + 策略（pack_crx.sh）。

```bash
git clone https://github.com/linchengyeyu/tmwebdriver.git ~/.hermes/tmwebdriver
cd ~/.hermes/tmwebdriver && python3 -m venv venv
./venv/bin/pip install simple-websocket-server requests beautifulsoup4 bottle
# Chrome: chrome://extensions → 开发者模式 → 加载已解压 → 选 assets/ 目录
#   （若扩展连不上：chrome://flags 里把 local-network-access-check 两个 flag 设为 Disabled）
nohup ./venv/bin/python3 TMWebDriver.py >> server.log 2>&1 &
curl -s --noproxy '*' http://127.0.0.1:18766/health   # {"ok":true,...}
```

改动 `assets/*.js` 后需在 chrome://extensions 里点一次"重新加载"（`TMWebDriver.py` 重启即生效）。
回归测试：`./venv/bin/python3 tests/test_v2_2.py`

## 不能做什么

- 不支持 chrome:// 和 chrome-extension:// 页面
- 浏览器原生弹窗（"确定离开"）由 `disable_dialogs.js` 尽力拦截，但操作期间别手动刷新页面
- 不能替代"人确认复杂决策"——它是执行器，不是决策者

## 致谢

- [alibaba/page-agent](https://github.com/alibaba/page-agent) (MIT) — DOM 文本化核心思路
- [browser-use](https://github.com/browser-use) (MIT) — 原始 DOM 扁平化算法；自愈选择器思路
- Playwright aria snapshot — 无障碍语义（role/name）参考
- [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) (MIT) — 多平台发布参考
