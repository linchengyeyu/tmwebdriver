"""
MultiPost — One-click multi-platform content publisher for TMWebDriver.

Inspired by leaperone/MultiPost-Extension, rebuilt natively for TMWebDriver.
Uses TMWebDriver's execute_js to inject page automation — same principle as
MultiPost's chrome.scripting.executeScript, but with Python orchestration.

Usage:
    from TMWebDriver import TMWebDriver
    from multipost import MultiPublisher

    driver = TMWebDriver()
    publisher = MultiPublisher(driver)

    # Publish a video to multiple platforms
    publisher.publish_video(
        title="My Awesome Video",
        description="Check this out!",
        video_path="/path/to/video.mp4",
        tags=["AI", "tech"],
        platforms=["bilibili", "douyin"],
        auto_publish=False,
    )

    # Publish images + text (Xiaohongshu style)
    publisher.publish_dynamic(
        title="My Post",
        content="Some text content",
        image_paths=["/path/to/img1.jpg", "/path/to/img2.jpg"],
        platforms=["xiaohongshu"],
        auto_publish=False,
    )
"""

import os
import time
import base64
from typing import List, Optional


class MultiPublisher:
    """Multi-platform content publisher using TMWebDriver browser automation."""

    # Platform upload URLs
    UPLOAD_URLS = {
        "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
        "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
        "douyin": "https://creator.douyin.com/creator-micro/content/upload",
        "kuaishou": "https://cp.kuaishou.com/article/publish/video",
        "weibo": "https://weibo.com/upload",
        "zhihu": "https://zhuanlan.zhihu.com/write",
    }

    def __init__(self, driver, file_server_port=18766):
        """
        Args:
            driver: TMWebDriver instance
            file_server_port: TMWebDriver's HTTP port (default 18766) for local file serving
        """
        self.driver = driver
        self.file_base = f"http://127.0.0.1:{file_server_port}/file"

    def publish_video(
        self,
        title: str,
        description: str,
        video_path: str,
        tags: Optional[List[str]] = None,
        cover_path: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        auto_publish: bool = False,
    ) -> dict:
        """
        Publish a video to multiple platforms.

        Args:
            title: Video title
            description: Video description
            video_path: Absolute path to video file
            tags: List of tags (platform-dependent)
            cover_path: Optional cover image path
            platforms: List of platform names (default: all supported)
            auto_publish: If True, auto-click publish button

        Returns:
            dict of {platform: {"success": bool, "message": str}}
        """
        if platforms is None:
            platforms = ["bilibili", "douyin"]

        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        results = {}
        for platform in platforms:
            print(f"\n{'='*50}")
            print(f"Publishing to {platform}...")
            print(f"{'='*50}")

            try:
                handler = getattr(self, f"_video_{platform}", None)
                if handler is None:
                    results[platform] = {"success": False, "message": f"Platform '{platform}' not supported for video"}
                    continue

                handler(
                    title=title,
                    description=description,
                    video_path=video_path,
                    tags=tags or [],
                    cover_path=cover_path,
                    auto_publish=auto_publish,
                )
                results[platform] = {"success": True, "message": "Upload completed"}
            except Exception as e:
                results[platform] = {"success": False, "message": str(e)}
                print(f"❌ {platform} failed: {e}")

        return results

    def publish_dynamic(
        self,
        title: str,
        content: str,
        image_paths: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None,
        auto_publish: bool = False,
    ) -> dict:
        """
        Publish a text+images post (dynamic/note) to multiple platforms.

        Args:
            title: Post title
            content: Post body text
            image_paths: List of absolute paths to images
            platforms: List of platform names
            auto_publish: If True, auto-click publish button

        Returns:
            dict of {platform: {"success": bool, "message": str}}
        """
        if platforms is None:
            platforms = ["xiaohongshu"]

        results = {}
        for platform in platforms:
            print(f"\n{'='*50}")
            print(f"Publishing dynamic to {platform}...")
            print(f"{'='*50}")

            try:
                handler = getattr(self, f"_dynamic_{platform}", None)
                if handler is None:
                    results[platform] = {"success": False, "message": f"Platform '{platform}' not supported for dynamic"}
                    continue

                handler(
                    title=title,
                    content=content,
                    image_paths=image_paths or [],
                    auto_publish=auto_publish,
                )
                results[platform] = {"success": True, "message": "Post completed"}
            except Exception as e:
                results[platform] = {"success": False, "message": str(e)}
                print(f"❌ {platform} failed: {e}")

        return results

    # ==================== Internal helpers ====================

    def _navigate_and_wait(self, url: str, wait_seconds=5):
        """Navigate current tab to URL and wait for page load."""
        self.driver.execute_js(f"window.location.href = '{url}'")
        time.sleep(wait_seconds)
        # Reload to ensure content script is injected
        self.driver.execute_js("window.location.reload()")
        time.sleep(wait_seconds)

    def _open_new_tab(self, url: str, wait_seconds=5):
        """Open URL in a new tab by finding an existing tab to clone."""
        # Use JS to open new tab
        self.driver.execute_js(f"window.open('{url}', '_blank')")
        time.sleep(wait_seconds)
        # Switch to the new tab
        sessions = self.driver.get_all_sessions()
        if sessions:
            # Find the new tab (most recent)
            for s in reversed(sessions):
                if url in s.get("url", ""):
                    self.driver.default_session_id = s["id"]
                    break

    def _file_url(self, abs_path: str) -> str:
        """Convert local file path to TMWebDriver file server URL."""
        return f"{self.file_base}/{abs_path}"

    def _encode_js_string(self, s: str) -> str:
        """Safely embed a string into JS code via base64."""
        b64 = base64.b64encode(s.encode("utf-8")).decode("ascii")
        return f"atob('{b64}')"

    # ==================== Bilibili Video ====================

    def _video_bilibili(self, title, description, video_path, tags, cover_path, auto_publish):
        """Publish video to Bilibili (哔哩哔哩)."""
        upload_url = self.UPLOAD_URLS["bilibili"]
        self._navigate_and_wait(upload_url, wait_seconds=6)

        video_url = self._file_url(os.path.abspath(video_path))
        title_b64 = base64.b64encode(title.encode()).decode()
        desc_b64 = base64.b64encode(description.encode()).decode()

        # Step 1: Upload video file
        print("  → Uploading video file...")
        upload_js = f"""
        (async () => {{
            const input = document.querySelector('input[type="file"]');
            if (!input) return 'ERROR: file input not found';
            const resp = await fetch('{video_url}');
            const blob = await resp.blob();
            const ext = '{os.path.splitext(video_path)[1]}'.replace('.', '') || 'mp4';
            const file = new File([blob], 'video.' + ext, {{ type: blob.type || 'video/mp4' }});
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return 'OK: upload triggered, size=' + file.size;
        }})()
        """
        result = self.driver.execute_js(upload_js, timeout=30)
        print(f"  ← {result}")
        if "ERROR" in str(result):
            raise Exception(f"Bilibili upload failed: {result}")

        # Step 2: Wait for upload to complete (check for "上传完成" text)
        print("  → Waiting for upload to finish (this may take a while for large files)...")
        self._wait_for_text("上传完成", timeout=600)

        # Step 3: Fill title and description
        print("  → Filling title and description...")
        fill_js = f"""
        (async () => {{
            // Title
            const titleInput = document.querySelector('input.input-val[type="text"][maxlength="80"]')
                || document.querySelector('input[type="text"]');
            if (titleInput) {{
                titleInput.focus();
                titleInput.value = atob('{title_b64}');
                titleInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                titleInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            // Description (Quill editor)
            const editor = document.querySelector('div.ql-editor[contenteditable="true"]');
            if (editor) {{
                editor.innerHTML = atob('{desc_b64}');
            }}
            return 'OK: title and description filled';
        }})()
        """
        result = self.driver.execute_js(fill_js, timeout=10)
        print(f"  ← {result}")

        # Step 4: Add tags
        if tags:
            print(f"  → Adding tags: {tags}...")
            for tag in tags[:10]:
                tag_b64 = base64.b64encode(tag.encode()).decode()
                tag_js = f"""
                (async () => {{
                    const tagInput = document.querySelector('input[placeholder*="Enter"]')
                        || document.querySelector('input[placeholder*="标签"]');
                    if (tagInput) {{
                        tagInput.value = atob('{tag_b64}');
                        tagInput.dispatchEvent(new KeyboardEvent('keydown', {{
                            bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13
                        }}));
                    }}
                    return 'OK';
                }})()
                """
                self.driver.execute_js(tag_js, timeout=5)
                time.sleep(1)

        # Step 5: Auto publish
        if auto_publish:
            print("  → Clicking publish...")
            publish_js = """
            (() => {
                const btn = document.querySelector('span.submit-add')
                    || document.querySelector('.submit-btn')
                    || document.querySelector('button.submit');
                if (btn) { btn.click(); return 'OK: publish clicked'; }
                return 'WARN: publish button not found';
            })()
            """
            result = self.driver.execute_js(publish_js, timeout=10)
            print(f"  ← {result}")

        print("  ✅ Bilibili video upload done!")

    # ==================== Xiaohongshu Dynamic ====================

    def _dynamic_xiaohongshu(self, title, content, image_paths, auto_publish):
        """Publish images+text to Xiaohongshu (小红书)."""
        upload_url = self.UPLOAD_URLS["xiaohongshu"]
        self._navigate_and_wait(upload_url, wait_seconds=6)

        # Step 1: Click "上传图文" button
        print("  → Clicking upload button...")
        click_js = """
        (() => {
            const spans = document.querySelectorAll('span[class="title"]');
            const btn = Array.from(spans).find(s => s.textContent.includes('上传图文'));
            if (btn) { btn.click(); return 'OK'; }
            // Fallback: try any upload-related button
            const tabs = document.querySelectorAll('[class*="tab"], [class*="upload"]');
            if (tabs.length > 1) { tabs[1].click(); return 'OK: fallback tab'; }
            return 'WARN: upload button not found';
        })()
        """
        result = self.driver.execute_js(click_js, timeout=10)
        print(f"  ← {result}")
        time.sleep(2)

        # Step 2: Upload images
        if image_paths:
            print(f"  → Uploading {len(image_paths)} images...")
            img_urls = [self._file_url(os.path.abspath(p)) for p in image_paths]
            img_url_json = str(img_urls).replace("'", '"')

            upload_js = f"""
            (async () => {{
                const input = document.querySelector('input[type="file"]');
                if (!input) return 'ERROR: file input not found';
                const dt = new DataTransfer();
                const urls = {img_url_json};
                for (const url of urls) {{
                    try {{
                        const resp = await fetch(url);
                        const blob = await resp.blob();
                        const name = url.split('/').pop() || 'image.jpg';
                        const file = new File([blob], name, {{ type: blob.type || 'image/jpeg' }});
                        dt.items.add(file);
                    }} catch(e) {{
                        return 'ERROR: fetch failed for ' + url + ': ' + e.message;
                    }}
                }}
                input.files = dt.files;
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return 'OK: ' + dt.files.length + ' images uploaded';
            }})()
            """
            result = self.driver.execute_js(upload_js, timeout=60)
            print(f"  ← {result}")
            if "ERROR" in str(result):
                raise Exception(f"Xiaohongshu image upload failed: {result}")
            time.sleep(3)

        # Step 3: Fill title and content
        print("  → Filling title and content...")
        title_b64 = base64.b64encode(title.encode()).decode()
        content_b64 = base64.b64encode(content.encode()).decode()

        fill_js = f"""
        (async () => {{
            // Title
            const titleInput = document.querySelector('input[type="text"]');
            if (titleInput) {{
                titleInput.value = atob('{title_b64}');
                titleInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
            // Content (contenteditable div — use paste event for React compatibility)
            const editor = document.querySelector('div[contenteditable="true"]');
            if (editor) {{
                editor.focus();
                const dt = new DataTransfer();
                dt.setData('text/plain', atob('{content_b64}'));
                editor.dispatchEvent(new ClipboardEvent('paste', {{
                    bubbles: true, cancelable: true, clipboardData: dt
                }}));
            }}
            return 'OK: title and content filled';
        }})()
        """
        result = self.driver.execute_js(fill_js, timeout=10)
        print(f"  ← {result}")

        # Step 4: Auto publish
        if auto_publish:
            print("  → Clicking publish...")
            publish_js = """
            (async () => {
                const buttons = document.querySelectorAll('button');
                const publishBtn = Array.from(buttons).find(b => b.textContent.includes('发布'));
                if (publishBtn) {
                    while (publishBtn.getAttribute('aria-disabled') === 'true') {
                        await new Promise(r => setTimeout(r, 1000));
                    }
                    publishBtn.click();
                    return 'OK: publish clicked';
                }
                return 'WARN: publish button not found';
            })()
            """
            result = self.driver.execute_js(publish_js, timeout=30)
            print(f"  ← {result}")

        print("  ✅ Xiaohongshu dynamic done!")

    # ==================== Douyin Video ====================

    def _video_douyin(self, title, description, video_path, tags, cover_path, auto_publish):
        """Publish video to Douyin (抖音)."""
        upload_url = self.UPLOAD_URLS["douyin"]
        self._navigate_and_wait(upload_url, wait_seconds=6)

        video_url = self._file_url(os.path.abspath(video_path))
        title_b64 = base64.b64encode(title.encode()).decode()
        desc_b64 = base64.b64encode(description.encode()).decode()

        # Step 1: Upload video
        print("  → Uploading video file...")
        upload_js = f"""
        (async () => {{
            const input = document.querySelector('input[type="file"][accept*="video"]')
                || document.querySelector('input[type="file"]');
            if (!input) return 'ERROR: file input not found';
            const resp = await fetch('{video_url}');
            const blob = await resp.blob();
            const ext = '{os.path.splitext(video_path)[1]}'.replace('.', '') || 'mp4';
            const file = new File([blob], 'video.' + ext, {{ type: blob.type || 'video/mp4' }});
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return 'OK: upload triggered, size=' + file.size;
        }})()
        """
        result = self.driver.execute_js(upload_js, timeout=30)
        print(f"  ← {result}")
        if "ERROR" in str(result):
            raise Exception(f"Douyin upload failed: {result}")

        # Step 2: Wait for upload
        print("  → Waiting for upload to finish...")
        self._wait_for_text("上传完成", timeout=600)

        # Step 3: Fill title/description
        print("  → Filling title and description...")
        fill_js = f"""
        (async () => {{
            // Douyin uses a contenteditable editor for title+description combined
            const editor = document.querySelector('.ql-editor[contenteditable="true"]')
                || document.querySelector('div[contenteditable="true"]');
            if (editor) {{
                editor.focus();
                const text = atob('{title_b64}') + '\\n' + atob('{desc_b64}');
                const dt = new DataTransfer();
                dt.setData('text/plain', text);
                editor.dispatchEvent(new ClipboardEvent('paste', {{
                    bubbles: true, cancelable: true, clipboardData: dt
                }}));
            }}
            return 'OK: content filled';
        }})()
        """
        result = self.driver.execute_js(fill_js, timeout=10)
        print(f"  ← {result}")

        # Step 4: Auto publish
        if auto_publish:
            print("  → Clicking publish...")
            publish_js = """
            (() => {
                const buttons = document.querySelectorAll('button');
                const btn = Array.from(buttons).find(b =>
                    b.textContent.includes('发布') && !b.disabled);
                if (btn) { btn.click(); return 'OK: publish clicked'; }
                return 'WARN: publish button not found';
            })()
            """
            result = self.driver.execute_js(publish_js, timeout=10)
            print(f"  ← {result}")

        print("  ✅ Douyin video upload done!")

    # ==================== Utility ====================

    def _wait_for_text(self, text: str, timeout: int = 300, interval: float = 2.0):
        """Wait until the page contains the specified text."""
        start = time.time()
        while time.time() - start < timeout:
            check_js = f"""
            (() => {{
                const text = document.body.innerText;
                return text.includes('{text}') ? 'YES' : 'NO';
            }})()
            """
            result = self.driver.execute_js(check_js, timeout=5)
            if "YES" in str(result):
                return True
            time.sleep(interval)
        raise TimeoutError(f"Timed out waiting for '{text}' on page ({timeout}s)")


if __name__ == "__main__":
    # Quick test / demo
    print("""
    MultiPost for TMWebDriver
    =========================
    Import this module to use:

        from TMWebDriver import TMWebDriver
        from multipost import MultiPublisher

        driver = TMWebDriver()
        publisher = MultiPublisher(driver)

        # Publish video to Bilibili + Douyin
        publisher.publish_video(
            title="My Video",
            description="Description here",
            video_path="/path/to/video.mp4",
            platforms=["bilibili", "douyin"],
        )

        # Publish images to Xiaohongshu
        publisher.publish_dynamic(
            title="My Post",
            content="Check this out!",
            image_paths=["/path/to/image.jpg"],
            platforms=["xiaohongshu"],
        )

    Supported platforms:
      Video: bilibili, douyin
      Dynamic: xiaohongshu

    More platforms can be added — see _video_<platform> and _dynamic_<platform> methods.
    """)
