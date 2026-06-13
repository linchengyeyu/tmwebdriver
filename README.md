# TMWebDriver — Control Your Real Chrome Browser

Control the Chrome browser you're already logged into. No new browser instance, no headless mode, no re-login. Your cookies and sessions are preserved.

## How It Works

1. **Chrome Extension** — A Manifest V3 extension that bridges between your browser tabs and a local WebSocket/HTTP server
2. **Python Server** — Receives JS code from your script, sends it to the extension, returns the result
3. **Site Skills** — Successful operations are saved as reusable skills. Next time you visit the same domain, one command does it all

```
Your Script → Python Server (WS :18765 / HTTP :18766) → Chrome Extension → Web Page
                                                                     ↓
                    Your Script ← Result ←━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```

## Why Not browser-use / Selenium / Playwright?

| Tool | Problem |
|------|---------|
| **browser-use** (98k★) | Every step calls an LLM. Searching Baidu costs more in tokens than your electricity bill |
| **Selenium** | Bot fingerprint detected by anti-crawl. Can't connect to your logged-in browser |
| **Playwright** | Great API, but defaults to launching a fresh browser. You lose all your logins |

TMWebDriver connects to the Chrome you already use. Zero LLM calls. Zero re-login. Just direct JS execution on real pages.

## Quick Start

### 1. Install dependencies

```bash
pip install simple-websocket-server requests beautifulsoup4 bottle
```

### 2. Load the Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the `assets/` folder from this repo

### 3. Start the server

```python
from TMWebDriver import TMWebDriver

driver = TMWebDriver(host='127.0.0.1', port=18765)

# List connected tabs
sessions = driver.get_all_sessions()
print(sessions)
# [{'id': '123', 'url': 'https://www.bilibili.com', 'title': 'B站'}]
```

### 4. Execute JavaScript on any tab

```python
# Get page text
result = driver.execute_js("document.body.innerText")

# Find a tab by URL
driver.set_session("bilibili")

# Run JS on that tab
result = driver.execute_js("document.title", session_id="bilibili_tab_id")
```

## Site Skills — It Learns

Inspired by [Browser Harness](https://github.com/browser-use/browser-harness) domain skills, but simpler: save verified JS code, reuse forever.

### Save a skill (first time)

```python
driver.execute_and_save(
    "search",
    "window.location.href='https://search.bilibili.com/all?keyword={{keyword}}'",
    description="Search on Bilibili"
)
```

### Use it (every time after)

```python
driver.execute_skill("search", keyword="AI tools")
# That's it. One line.
```

### Browse learned skills

```python
driver.list_skills()
# {'bilibili.com': {'search': 'Search on Bilibili', ...}, ...}
```

Skills are stored as JSON in `site_skills/{domain}.json`. Edit them manually anytime.

## API Reference

| Method | Description |
|--------|-------------|
| `get_all_sessions()` | List all connected browser tabs |
| `find_session(pattern)` | Find tab by URL keyword |
| `set_session(pattern)` | Set default tab by URL keyword |
| `execute_js(code, timeout=15)` | Run JavaScript on a tab |
| `jump(url)` | Navigate current tab to URL |
| `save_skill(name, js, description, domain)` | Save a reusable skill |
| `get_skill(name, domain)` | Get a saved skill |
| `list_skills(domain)` | List all skills |
| `execute_skill(name, **variables)` | Execute a saved skill with variable substitution |
| `execute_and_save(name, js, **variables)` | Execute JS and auto-save as skill |

## Project Structure

```
tmwebdriver/
├── TMWebDriver.py        # Core: WebSocket/HTTP server + API
├── simphtml.py           # HTML simplification utilities
├── assets/               # Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js     # Extension service worker (CDP bridge)
│   ├── content.js        # Content script injected into pages
│   ├── config.js
│   ├── popup.html / popup.js
│   └── disable_dialogs.js
└── site_skills/          # Auto-saved website operation skills
    ├── bilibili.com.json
    └── google.com.json
```

## Troubleshooting

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

Wait up to 15 seconds for the extension to establish the WebSocket connection:
```python
import time
for i in range(15):
    sessions = driver.get_all_sessions()
    if sessions: break
    time.sleep(1)
```

## License

MIT

## Acknowledgments

- [Browser Harness](https://github.com/browser-use/browser-harness) — Site Skills design inspiration
- [Playwright](https://playwright.dev/) — CDP protocol reference
