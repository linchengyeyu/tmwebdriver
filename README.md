# TMWebDriver — Control Your Real Chrome, Zero Anti-Crawl, Zero Re-Login

Control the Chrome browser you're **already logged into**. No new browser instance, no headless mode, no re-login. Your cookies, sessions, and fingerprints are preserved — anti-crawl systems see a real user, not a bot.

**New in v2 (2026-07):** DOM Outline API + Skill auto-sedimentation — borrowed ideas from [alibaba/page-agent](https://github.com/alibaba/page-agent) (27k★) and [browser-use](https://github.com/browser-use/browser-use) (105k★), but **without the per-step LLM cost**.

**v2.2 (2026-09):** chunked long-result guarantee / deterministic readiness wait / execution channel refactor (channel=auto·cdp·script) / optional token auth / behavior convergence / outline aria semantics / self-healing skills. See SKILL.md.

---

## ⚠️ REQUIRED FOR AGENTS: install SKILL.md first — otherwise your agent won't know how to use this

**This extension is driven by AI agents, not clicked by humans.** Without SKILL.md your agent has no idea
which APIs exist, how indices work, or what the responses look like. **After setting up the server, you MUST
install SKILL.md into your agent's skill directory:**

```bash
# Hermes / generic agents (skill-dir convention):
mkdir -p ~/.hermes/skills/browser/tmwebdriver
cp SKILL.md ~/.hermes/skills/browser/tmwebdriver/SKILL.md
```

Then just tell your agent "use tmwebdriver to open / operate ...". SKILL.md contains the full HTTP/Python API,
long-value conventions, pitfalls and install steps — agents that read it can drive the extension.

---

---

## ✨ Highlights

### 🎯 1. Reuse Your Real Chrome — No Anti-Crawl, No Re-Login

The #1 pain with Selenium/Playwright: they launch a fresh browser. You lose all logins. Anti-crawl systems flag you instantly.

TMWebDriver connects to the Chrome **you're already using** via a Manifest V3 extension. Zero fingerprint change. Zero re-login. Bilibili, Zhihu, Xiaohongshu, WeChat — all your logged-in sites are one API call away.

### 📋 2. DOM Outline — Operate Any Website Without Writing Selectors (New)

Inspired by page-agent's DOM text flattening. Scan any page and get a numbered list of interactive elements:

```python
outline = driver.get_page_outline(session_id=sid)
print(outline['text'])
```

Output:
```
[1]<a href="//www.bilibili.com"> 首页
[2]<a href="//www.bilibili.com/anime/"> 番剧
[3]<input placeholder="搜索" type="text">
[4]<button> 搜索
[5]<a href="//space.bilibili.com/252071912/favlist"> 收藏
```

Then operate by index — **no need to write or guess CSS selectors**:

```python
driver.input_text_index(3, "AI tools", session_id=sid)  # fill search box
driver.click_index(4, session_id=sid)                    # click search button
```

**Why this matters**: On a new website, you used to guess selectors, fail, retry. Now you scan once (400ms), read the outline, and act. Website redesigns don't break you — the outline is based on DOM structure, not hardcoded selectors.

### 🧠 3. Skill Sedimentation — One-Time Scan, Forever Reusable (New)

After you operate a site via Outline, **automatically extract stable selectors and save as a reusable skill**:

```python
# First time: scan + operate + sediment
outline = driver.get_page_outline(session_id=sid)
driver.save_outline_skill(
    action_name="search",
    steps=[
        {"type": "input", "index": 3, "param": "keyword"},
        {"type": "click", "index": 4}
    ],
    session_id=sid
)

# Every time after: direct call, zero scanning
import json
with open('site_skills/example.com.json') as f:
    skill = json.load(f)['search']
js = skill['js'].replace('{{keyword}}', 'new query')
driver.execute_js(js, session_id=sid)
```

**8-layer selector fallback** (most stable first):

| Priority | Selector | Stability |
|----------|----------|-----------|
| 1 | `#id` | ⭐⭐⭐⭐⭐ |
| 2 | `[data-testid="..."]` | ⭐⭐⭐⭐⭐ |
| 3 | `input[placeholder="..."]` | ⭐⭐⭐⭐ |
| 4 | `[aria-label="..."]` | ⭐⭐⭐⭐ |
| 5 | `a[href*="/path"]` | ⭐⭐⭐⭐ |
| 6 | `[role="..."]` | ⭐⭐⭐ |
| 7 | `tag="text"` | ⭐⭐⭐ |
| 8 | `xpath:...` (fallback) | ⭐⭐ |

Website changed the placeholder? Layer 3 fails → layer 4 kicks in. Changed the whole DOM? XPath still works. **You write it once, it keeps working.**

### 🚀 4. Multi-Platform Publishing — One API, Multiple Platforms

Built-in `multipost.py` module — publish videos/images to multiple platforms with one call:

```python
from multipost import MultiPublisher
pub = MultiPublisher(driver)

# Video → Bilibili + Douyin
pub.publish_video(
    title="AI Tool Review",
    video_path="/path/to/video.mp4",
    platforms=["bilibili", "douyin"],
    auto_publish=False
)

# Images → Xiaohongshu
pub.publish_dynamic(
    title="Daily AI Picks",
    image_paths=["/img/1.jpg", "/img/2.jpg"],
    platforms=["xiaohongshu"]
)
```

Inspired by [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) (2.4k★), but orchestrated in Python — easier to extend and debug.

### 📚 5. Growing Site Skills Library

Every successful operation can be saved. Skills accumulate over time:

```
site_skills/
├── bilibili.com.json     # 3 skills: search, get_video_list, get_page_text
├── google.com.json       # 2 skills: search, get_search_results
├── chatgpt.com.json      # 2 skills: send_message, click_send
├── mp.weixin.qq.com.json # 1 skill: get_article_list
└── ...                   # Add more as you use it
```

---

## 🆚 Comparison with Other Tools

| Feature | **TMWebDriver** | page-agent | browser-use | Playwright | Selenium | DrissionPage | Skyvern |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **GitHub Stars** | New | 27k | 105k | 93k | 34k | 12k | 22k |
| **License** | MIT | MIT | MIT | Apache-2.0 | Apache-2.0 | Custom | AGPL-3.0 |
| **Reuse real Chrome login** | ✅ | ❌ Extension only | ❌ Fresh browser | ⚠️ Complex setup | ⚠️ Complex setup | ✅ | ❌ Fresh browser |
| **Anti-crawl evasion** | ✅ Real fingerprint | ⚠️ Detected | ❌ Detected | ❌ Detected | ❌ Detected | ✅ | ❌ Detected |
| **DOM Outline (no selectors)** | ✅ **Free** | ✅ LLM-driven | ✅ LLM-driven | ❌ | ❌ | ❌ | ✅ LLM-driven |
| **Skill auto-sedimentation** | ✅ **8-layer fallback** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Per-step LLM cost** | **$0** | ~$0.001/step | ~$0.01/step | $0 | $0 | $0 | ~$0.02/step |
| **Speed per action** | ~400ms | ~800ms | 2-5s | ~10ms | ~50ms | ~50ms | 3-8s |
| **Multi-platform publish** | ✅ Built-in | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Language** | Python | TS | Python | TS/Python | Multi | Python | Python |
| **Setup complexity** | Low (1 extension) | Low (1 extension) | Medium | High | High | Low | High |

### The Key Difference

**page-agent / browser-use / Skyvern** are great, but every step calls an LLM. Searching Baidu 10 times costs more in tokens than your electricity bill.

**Selenium / Playwright** are fast and free, but you hand-write every selector, and they launch fresh browsers (anti-crawl flags them).

**TMWebDriver** sits in the sweet spot:
- **Fast & free** like Selenium/Playwright (no per-step LLM)
- **Anti-crawl safe** like DrissionPage (real Chrome, real fingerprint)
- **Zero-selector operation** like page-agent (DOM Outline)
- **Learns over time** like nothing else (Skill sedimentation with 8-layer fallback)

---

## 🚀 Quick Start

### 1. Install

```bash
pip install simple-websocket-server requests beautifulsoup4 bottle
```

### 2. Load the Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `assets/` folder

### 3. Start Operating

```python
from TMWebDriver import TMWebDriver

driver = TMWebDriver()

# List connected tabs
sessions = driver.get_all_sessions()
print(sessions)

# Execute JS on any tab
result = driver.execute_js("document.body.innerText")

# Or use DOM Outline for zero-selector operation
outline = driver.get_page_outline()
print(outline['text'])
```

---

## 📖 API Reference

### Core

| Method | Description |
|--------|-------------|
| `get_all_sessions()` | List all connected browser tabs |
| `find_session(pattern)` | Find tab by URL keyword |
| `set_session(pattern)` | Set default tab by URL keyword |
| `execute_js(code, timeout=15)` | Run JavaScript on a tab |
| `jump(url)` | Navigate current tab to URL |

### DOM Outline (New)

| Method | Description |
|--------|-------------|
| `get_page_outline(max_elements=80, viewport_only=True)` | Scan page, return numbered element list |
| `click_index(index)` | Click element by outline index |
| `input_text_index(index, text, submit=False)` | Fill input by outline index |
| `get_element_selector(index)` | Extract stable selectors for an element |

### Skill Sedimentation (New)

| Method | Description |
|--------|-------------|
| `save_outline_skill(action_name, steps, session_id)` | Save outline operations as reusable skill |
| `save_skill(name, js, description, domain)` | Manually save a skill |
| `get_skill(name, domain)` | Get a saved skill |
| `list_skills(domain)` | List all skills |
| `execute_skill(name, **variables)` | Execute saved skill with variable substitution |
| `execute_and_save(name, js, **variables)` | Execute JS and auto-save as skill |

### Multi-Platform Publishing

```python
from multipost import MultiPublisher
pub = MultiPublisher(driver)
pub.publish_video(title, video_path, platforms=["bilibili", "douyin"])
pub.publish_dynamic(title, image_paths, platforms=["xiaohongshu"])
```

---

## 🏗️ How It Works

```
Your Script → Python Server (WS :18765 / HTTP :18766) → Chrome Extension → Web Page
                                                                     ↓
                    Your Script ← Result ←━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```

1. **Chrome Extension** (Manifest V3) — bridges between browser tabs and a local server
2. **Python Server** — receives JS code, sends to extension, returns result
3. **DOM Outline** — injected JS scans the page and returns a numbered element list
4. **Site Skills** — successful operations are saved as JSON, reused forever

---

## 📁 Project Structure

```
tmwebdriver/
├── TMWebDriver.py           # Core: WS/HTTP server + all APIs (740 lines)
├── multipost.py             # Multi-platform publishing module (542 lines)
├── simphtml.py              # HTML simplification utilities (871 lines)
├── assets/                  # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js        # Extension service worker / CDP bridge (395 lines)
│   ├── content.js           # Content script injected into pages
│   ├── dom_outline.js       # DOM scanning engine (420 lines, from page-agent)
│   ├── config.js / popup.*  # UI
│   └── disable_dialogs.js   # Suppress annoying dialogs
├── site_skills/             # Auto-saved website operation skills
│   ├── bilibili.com.json
│   ├── google.com.json
│   └── ...
├── fix.sh                   # Recovery script
└── requirements.txt
```

**Total: ~3,400 lines of code across 18 files. No compiled binaries. No native dependencies beyond Python + Chrome.**

---

## 🔧 Troubleshooting

### Chrome blocks WebSocket to localhost

Chrome 147+ added Local Network Access restrictions. Disable both flags:
- `chrome://flags/#local-network-access-check` → **Disabled**
- `chrome://flags/#local-network-access-check-websockets` → **Disabled**

Then relaunch Chrome and reload the extension.

### `execute_js` returns `remote_execute_js`

Content script not injected. Reload the tab:
```python
driver.execute_js('window.location.reload()', session_id=sid)
import time; time.sleep(5)
```

### Sessions empty after connecting

Wait up to 15 seconds for the extension to establish the WebSocket connection.

### Chrome removes the extension after update

Chrome deletes unpacked extensions on major version updates. Re-load from `assets/` folder, or run `bash fix.sh`.

---

## 📊 Performance

| Operation | Time |
|-----------|------|
| `execute_js` (simple) | ~10ms |
| `get_page_outline` (30 elements) | ~400ms |
| `click_index` / `input_text_index` | ~50ms |
| `save_outline_skill` | ~100ms |
| Saved skill execution (no scan) | ~10ms |

---

## 📝 License

MIT

## 🙏 Acknowledgments

- [alibaba/page-agent](https://github.com/alibaba/page-agent) (MIT) — DOM text flattening concept, `dom_outline.js` derived from their source
- [browser-use](https://github.com/browser-use/browser-use) (MIT) — Original DOM flattening implementation that page-agent ported from
- [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) (MIT) — Multi-platform publishing reference
- [Browser Harness](https://github.com/browser-use/browser-harness) — Site Skills design inspiration
- [Playwright](https://playwright.dev/) — CDP protocol reference
