"""Minimal TMWebDriver smoke test.

Run:
    python examples/quickstart.py github.com

Before running, start Chrome with the extension loaded from ../assets.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from TMWebDriver import TMWebDriver


def wait_for_sessions(driver, seconds=15):
    for _ in range(seconds):
        sessions = driver.get_all_sessions()
        if sessions:
            return sessions
        time.sleep(1)
    return []


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else ""
    driver = TMWebDriver()
    sessions = wait_for_sessions(driver)

    if not sessions:
        raise SystemExit(
            "No Chrome tabs connected. Check that the extension is enabled, "
            "then reload a normal https:// tab."
        )

    print("Connected tabs:")
    for tab in sessions:
        print(f"- {tab['id']}: {tab.get('title', '')} | {tab.get('url', '')}")

    if pattern:
        session_id = driver.set_session(pattern)
        if not session_id:
            raise SystemExit(f"No tab URL contains: {pattern}")

    result = driver.execute_js("({ title: document.title, url: location.href })")
    print("\nCurrent tab:")
    print(result)


if __name__ == "__main__":
    main()
