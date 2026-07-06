# TMWebDriver

Control the real Chrome browser you already use from Python.

No headless browser. No separate automation profile. No re-login. TMWebDriver connects Python scripts to your live Chrome tabs through a local server and a Manifest V3 extension, then executes JavaScript in the page you are already logged into.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](pyproject.toml)
[![Chrome Extension](https://img.shields.io/badge/Chrome-Extension-green.svg)](assets/manifest.json)

## Why It Exists

Modern browser automation often starts a clean browser profile. That is painful when the useful state lives in your daily browser: cookies, logged-in creator accounts, internal tools, AI chats, dashboards, and tabs you already opened.

TMWebDriver keeps that state where it is.

| You want to | TMWebDriver gives you |
| --- | --- |
| Automate websites where you are already logged in | Commands run in your existing Chrome tabs |
| Avoid bot-like headless sessions | A normal user browser with your normal profile |
| Build repeatable site actions | Site Skills stored as editable JSON |
| Let an AI agent operate a page cheaply | Direct JavaScript execution, no LLM call per click |

## How It Works

```text
Python script -> Local server (WS :18765 / HTTP :18766)
              -> Chrome extension
              -> Your existing Chrome tab
              -> Result back to Python
```

The extension reports open tabs to the local Python server. Your script picks a tab and sends JavaScript to execute inside that page. Successful snippets can be saved as Site Skills and reused later.

## Quick Start

### 1. Install

Clone the repo, then install it in editable mode:

```bash
git clone https://github.com/linchengyeyu/tmwebdriver.git
cd tmwebdriver
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Or install only the dependencies:

```bash
python -m pip install -r requirements.txt
```

### 2. Load the Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select this repo's `assets/` folder

### 3. Start Python and list tabs

```python
from TMWebDriver import TMWebDriver

driver = TMWebDriver()

for tab in driver.get_all_sessions():
    print(tab["id"], tab["title"], tab["url"])
```

If the list is empty, wait a few seconds and reload the extension or the target tab.

### 4. Run JavaScript in a real tab

```python
driver.set_session("github.com")

title = driver.execute_js("document.title")
text = driver.execute_js("document.body.innerText.slice(0, 500)")

print(title)
print(text)
```

You can also run the included example:

```bash
python examples/quickstart.py github.com
```

## Site Skills

Site Skills are reusable JavaScript snippets stored by domain in `site_skills/*.json`. They are useful for turning a proven page action into a one-line command.

Save a skill:

```python
driver.set_session("bilibili.com")

driver.execute_and_save(
    "search",
    "window.location.href='https://search.bilibili.com/all?keyword={{keyword}}'",
    description="Search Bilibili by keyword",
    keyword="AI tools",
)
```

Use it later:

```python
driver.set_session("bilibili.com")
driver.execute_skill("search", keyword="browser automation")
```

List saved skills:

```python
print(driver.list_skills())
```

## Common Use Cases

- Scrape text from pages that require your existing login.
- Fill internal dashboards or admin panels from Python.
- Trigger repetitive creator-platform tasks from scripts.
- Give an AI agent a low-cost browser control layer.
- Save site-specific workflows as editable JSON skills.

## API Overview

| Method | Description |
| --- | --- |
| `get_all_sessions()` | List connected Chrome tabs |
| `find_session(pattern)` | Find tabs whose URL contains `pattern` |
| `set_session(pattern)` | Set the default tab by URL keyword |
| `execute_js(code, timeout=15)` | Execute JavaScript in the selected tab |
| `jump(url)` | Navigate the selected tab to a URL |
| `newtab(url=None)` | Open a new tab |
| `save_skill(name, js, description="", domain=None)` | Save a reusable site skill |
| `get_skill(name, domain=None)` | Load a saved site skill |
| `list_skills(domain=None)` | List saved skills |
| `execute_skill(name, **variables)` | Run a saved skill with variable substitution |
| `execute_and_save(name, js, **variables)` | Execute JavaScript and save it as a skill |

## Project Structure

```text
tmwebdriver/
├── TMWebDriver.py        # Python server and public API
├── simphtml.py           # HTML simplification helpers
├── multipost.py          # Experimental multi-platform publishing helper
├── assets/               # Chrome extension
├── examples/             # Runnable examples
└── site_skills/          # Saved domain skills
```

## Troubleshooting

### Chrome blocks WebSocket to localhost

Some Chrome versions enforce Local Network Access restrictions. If the extension cannot connect, open these flags and disable them:

- `chrome://flags/#local-network-access-check`
- `chrome://flags/#local-network-access-check-websockets`

Relaunch Chrome, reload the extension, and restart your Python process.

### `get_all_sessions()` returns an empty list

Try this checklist:

1. Confirm the extension is enabled in `chrome://extensions`
2. Start Python with `driver = TMWebDriver()`
3. Reload the target Chrome tab
4. Wait up to 15 seconds

```python
import time

for _ in range(15):
    sessions = driver.get_all_sessions()
    if sessions:
        break
    time.sleep(1)
```

### JavaScript times out

The script may have been delivered but not returned a serializable value. Start with a small expression:

```python
driver.execute_js("document.title")
```

Then move to longer async snippets once the connection is confirmed.

## Security Notes

TMWebDriver can execute JavaScript in pages where you are logged in. Treat it like a local developer tool:

- Run it only on your own machine.
- Keep the server bound to `127.0.0.1`.
- Do not paste untrusted JavaScript into `execute_js`.
- Review Site Skills before sharing them.

## Roadmap

- Package a signed extension release.
- Add screenshots and a short demo video.
- Add more examples for scraping, form filling, and AI-agent use.
- Publish stable version tags.

## License

MIT

## Acknowledgments

- [Browser Harness](https://github.com/browser-use/browser-harness) for the Site Skills idea.
- [Playwright](https://playwright.dev/) for browser automation inspiration.
