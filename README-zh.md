# TMWebDriver — 控制你真正在用的 Chrome，零反爬，零重登录

控制你**已经在用的** Chrome 浏览器。不开新实例、无头模式，不需要重新登录。你的 Cookie、会话、浏览器指纹全部保留——反爬系统看到的是真实用户，不是机器人。

**v2 新增 (2026-07):** DOM Outline API + Skill 自动蜕变——借鉴了 [alibaba/page-agent](https://github.com/alibaba/page-agent)（27k★）和 [browser-use](https://github.com/browser-use/browser-use)（105k★）的核心思路，但**每步零 LLM 成本**。

---

## ✨ 五大亮点

### 🎯 1. 复用你真实在用的 Chrome — 零反爬，零重登录

Selenium/Playwright 的最大痛点：永远开新浏览器。登录全部丢失，反爬系统秒识别。

TMWebDriver 通过 Manifest V3 扩展连接你**已经在用的** Chrome。指纹不变，登录态不变。B站、知乎、小红书、微信公众号后台——所有已登录站点一个 API 就搞定。

### 📋 2. DOM Outline — 操作任何网站不需要写选择器（新增）

借鉴 page-agent 的 DOM 文本化方案。扫描页面，输出带编号的可交互元素清单：

```python
outline = driver.get_page_outline(session_id=sid)
print(outline['text'])
```

输出：
```
[1]<a href="//www.bilibili.com"> 首页
[2]<a href="//www.bilibili.com/anime/"> 番剧
[3]<input placeholder="搜索" type="text">
[4]<button> 搜索
[5]<a href="//space.bilibili.com/252071912/favlist"> 收藏
```

直接按编号操作——**不用写、不用猜 CSS 选择器**：

```python
driver.input_text_index(3, "AI工具", session_id=sid)  # 填搜索框
driver.click_index(4, session_id=sid)                  # 点搜索按钮
```

**为什么重要**：新网站首次访问，你不再需要猜选择器 → 试错 → 重试。扫一次（400ms），看清单，直接操作。网站改版也不怕——outline 基于 DOM 结构，不依赖固定选择器。

### 🧠 3. Skill 蜕变 — 一次操作，永久复用（新增）

Outline 操作之后，**自动提取稳定选择器，保存为可复用的技能**：

```python
# 第一次：扫描 + 操作 + 蜕变
outline = driver.get_page_outline(session_id=sid)
driver.save_outline_skill(
    action_name="search",
    steps=[
        {"type": "input", "index": 3, "param": "keyword"},
        {"type": "click", "index": 4}
    ],
    session_id=sid
)

# 以后：直接调用，零扫描
import json
with open('site_skills/example.com.json') as f:
    skill = json.load(f)['search']
js = skill['js'].replace('{{keyword}}', '新搜索词')
driver.execute_js(js, session_id=sid)
```

**8 层选择器降级**（从最稳到兜底）：

| 优先级 | 选择器类型 | 稳定性 |
|----------|-----------|--------|
| 1 | `#id` | ⭐⭐⭐⭐⭐ |
| 2 | `[data-testid="..."]` | ⭐⭐⭐⭐⭐ |
| 3 | `input[placeholder="..."]` | ⭐⭐⭐⭐ |
| 4 | `[aria-label="..."]` | ⭐⭐⭐⭐ |
| 5 | `a[href*="/path"]` | ⭐⭐⭐⭐ |
| 6 | `[role="..."]` | ⭐⭐⭐ |
| 7 | `tag="text"` | ⭐⭐⭐ |
| 8 | `xpath:...`（兜底） | ⭐⭐ |

网站改了 placeholder？第 3 层失效 → 第 4 层自动接上。改了全站 DOM？xpath 兜底。**写一次，永久生效。**

### 🚀 4. 多平台一键发布 — 一个 API，多个平台

内置 `multipost.py` 模块。一个调用把视频/图文发到多个平台：

```python
from multipost import MultiPublisher
pub = MultiPublisher(driver)

# 视频 → B站 + 抖音
pub.publish_video(
    title="AI工具测评",
    video_path="/path/to/video.mp4",
    platforms=["bilibili", "douyin"],
    auto_publish=False
)

# 图片 → 小红书
pub.publish_dynamic(
    title="AI日报",
    image_paths=["/img/1.jpg", "/img/2.jpg"],
    platforms=["xiaohongshu"]
)
```

借鉴自 [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension)（2.4k★），但用 Python 编排——更容易扩展和调试。

### 📚 5. 持续增长的 Site Skills 库

每次成功操作都可以保存。技能越用越多：

```
site_skills/
├── bilibili.com.json     # 3 skills: search, get_video_list, get_page_text
├── google.com.json       # 2 skills: search, get_search_results
├── chatgpt.com.json      # 2 skills: send_message, click_send
├── mp.weixin.qq.com.json # 1 skill: get_article_list
└── ...                   # 用得越多，积累越多
```

---

## 🆚 竞品对比

| 功能 | **TMWebDriver** | page-agent | browser-use | Playwright | Selenium | DrissionPage | Skyvern |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **GitHub 星数** | 新建 | 27k | 105k | 93k | 34k | 12k | 22k |
| **协议** | MIT | MIT | MIT | Apache-2.0 | Apache-2.0 | Custom | AGPL-3.0 |
| **复用真实 Chrome** | ✅ | ❌ 仅扩展 | ❌ 开新 | ⚠️ 配置复杂 | ⚠️ 配置复杂 | ✅ | ❌ 开新 |
| **抗反爬** | ✅ 真实指纹 | ⚠️ 被检测 | ❌ 被检测 | ❌ 被检测 | ❌ 被检测 | ✅ | ❌ 被检测 |
| **零选择器操作** | ✅ **免费** | ✅ 每步调LLM | ✅ 每步调LLM | ❌ | ❌ | ❌ | ✅ 每步调LLM |
| **Skill 蜕变** | ✅ **8层降级** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **每步 LLM 成本** | **$0** | ~$0.001/步 | ~$0.01/步 | $0 | $0 | $0 | ~$0.02/步 |
| **操作速度** | ~400ms | ~800ms | 2-5s | ~10ms | ~50ms | ~50ms | 3-8s |
| **多平台发布** | ✅ 内置 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **语言** | Python | TS | Python | TS/Python | 多语言 | Python | Python |
| **部署难度** | 低（装个扩展） | 低（装个扩展） | 中 | 高 | 高 | 低 | 高 |

### 核心差异

**page-agent / browser-use / Skyvern** 很好，但每步都要调 LLM。搜 10 次百度花费的 token 钱比电费还贵。

**Selenium / Playwright** 免费、快速，但每个选择器要手写，而且开新浏览器（反爬秒识别）。

**TMWebDriver 坐在中间最舒服的位置**：
- **快且免费** 像 Selenium/Playwright（不调 LLM）
- **抗反爬** 像 DrissionPage（真实 Chrome，真实指纹）
- **零选择器操作** 像 page-agent（DOM Outline）
- **越用越聪明** 像没人能做到的（8层降级的 Skill 蜕变）

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install simple-websocket-server requests beautifulsoup4 bottle
```

### 2. 加载 Chrome 扩展

1. 打开 `chrome://extensions`
2. 开启**开发者模式**
3. 点击**加载已解压的扩展程序**
4. 选择 `assets/` 目录

### 3. 开始操作

```python
from TMWebDriver import TMWebDriver

driver = TMWebDriver()

# 列出已连接标签页
sessions = driver.get_all_sessions()
print(sessions)

# 在标签页执行 JavaScript
result = driver.execute_js("document.body.innerText")

# 或用 DOM Outline 零选择器操作
outline = driver.get_page_outline()
print(outline['text'])
```

---

## 📖 API 参考

### 基础

| 方法 | 说明 |
|------|------|
| `get_all_sessions()` | 列出所有已连接标签页 |
| `find_session(pattern)` | 按 URL 关键词查找标签页 |
| `set_session(pattern)` | 设置默认标签页 |
| `execute_js(code, timeout=15)` | 在标签页执行 JS |
| `jump(url)` | 导航当前标签页 |

### DOM Outline（新增）

| 方法 | 说明 |
|------|------|
| `get_page_outline(max_elements=80)` | 扫描页面，返回带编号的元素清单 |
| `click_index(index)` | 按 outline 编号点击元素 |
| `input_text_index(index, text)` | 按编号向输入框填文字 |
| `get_element_selector(index)` | 提取编号元素的稳定选择器 |

### Skill 蜕变（新增）

| 方法 | 说明 |
|------|------|
| `save_outline_skill(name, steps)` | 把 outline 操作序列蜕变为可复用 skill |
| `save_skill(name, js, domain)` | 手动保存 skill |
| `get_skill(name, domain)` | 获取已保存的 skill |
| `list_skills(domain)` | 列出所有 skill |
| `execute_skill(name, **vars)` | 执行已保存的 skill（变量替换） |
| `execute_and_save(name, js)` | 执行 JS 并自动保存为 skill |

### 多平台发布

```python
from multipost import MultiPublisher
pub = MultiPublisher(driver)
pub.publish_video(title, video_path, platforms=["bilibili", "douyin"])
pub.publish_dynamic(title, image_paths, platforms=["xiaohongshu"])
```

---

## 🏗️ 工作原理

```
你的脚本 → Python Server (WS :18765 / HTTP :18766) → Chrome 扩展 → 网页
                                                                     ↓
                   你的脚本 ← 结果 ←━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```

1. **Chrome 扩展** (Manifest V3) — 在浏览器标签页和本地服务器之间搭桥
2. **Python Server** — 接收 JS 代码，发给扩展，返回结果
3. **DOM Outline** — 注入 JS 扫描页面，返回编号元素清单
4. **Site Skills** — 成功操作保存为 JSON 技能文件，永久复用

---

## 📁 项目结构

```
tmwebdriver/
├── TMWebDriver.py           # 核心：WS/HTTP 服务 + 全部 API（740行）
├── multipost.py             # 多平台发布模块（542行）
├── simphtml.py              # HTML 简化工具（871行）
├── assets/                  # Chrome 扩展 (Manifest V3)
│   ├── manifest.json
│   ├── background.js        # 扩展服务工作线程 / CDP 桥（395行）
│   ├── content.js           # 注入页面的内容脚本
│   ├── dom_outline.js       # DOM 扫描引擎（420行，从 page-agent 衍生）
│   ├── config.js / popup.*  # 界面
│   └── disable_dialogs.js   # 屏蔽烦人的弹窗
├── site_skills/             # 自动保存的网站操作技能
│   ├── bilibili.com.json
│   ├── google.com.json
│   └── ...
├── fix.sh                   # 一键恢复脚本
└── requirements.txt
```

**总计: ~3,400 行代码，18 个文件。无编译二进制，原生依赖仅 Python + Chrome。**

---

## 🛠️ 排错指南

### Chrome 阻止 WebSocket 连接本地端口

Chrome 147+ 新增本地网络访问限制。需禁用两个 flag：
- `chrome://flags/#local-network-access-check` → **Disabled**
- `chrome://flags/#local-network-access-check-websockets` → **Disabled**

然后重启 Chrome 并刷新扩展。

### `execute_js` 返回 `remote_execute_js`

Content script 未注入。刷新标签页：
```python
driver.execute_js('window.location.reload()', session_id=sid)
import time; time.sleep(5)
```

### 连接后 Sessions 为空

等待最多 15 秒让扩展建立 WebSocket 连接：
```python
import time
for i in range(15):
    sessions = driver.get_all_sessions()
    if sessions: break
    time.sleep(1)
```

### Chrome 更新后扩展被删除

Chrome 大版本更新后会清除开发者模式扩展。重新从 `assets/` 目录加载，或运行 `bash fix.sh`。

---

## 📊 性能

| 操作 | 耗时 |
|------|------|
| `execute_js`（简单） | ~10ms |
| `get_page_outline`（30 个元素） | ~400ms |
| `click_index` / `input_text_index` | ~50ms |
| `save_outline_skill` | ~100ms |
| 已蜕变 skill 执行（零扫描） | ~10ms |

---

## 📝 协议

MIT

## 🙏 致谢

- [alibaba/page-agent](https://github.com/alibaba/page-agent) (MIT) — DOM 文本化概念灵感，`dom_outline.js` 源自其源码
- [browser-use](https://github.com/browser-use/browser-use) (MIT) — page-agent 移植的原始 DOM 扁平化算法
- [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) (MIT) — 多平台发布参考
- [Browser Harness](https://github.com/browser-use/browser-harness) — Site Skills 设计灵感
- [Playwright](https://playwright.dev/) — CDP 协议参考
