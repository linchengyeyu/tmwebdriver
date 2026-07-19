---
name: tmwebdriver
description: "Control your real Chrome browser — DOM Outline, CDP real click, skill sedimentation. Install: just tell your Agent."
triggers:
  - tmwebdriver 安装
  - 安装 tmwebdriver
  - 装个浏览器自动化
  - install tmwebdriver
  - 浏览器插件
  - 控制浏览器
---

# TMWebDriver — 控制你真正在用的 Chrome 浏览器

> 开源 MIT，GitHub: https://github.com/linchengyeyu/tmwebdriver

## 一句话搞懂

TMWebDriver 是一个 Chrome 扩展 + Python 服务，让你（或你的 AI Agent）操控你已在登录的 Chrome 浏览器。不用开新浏览器，不用重新登录，不触发反爬。

---

## 能做什么

- 自动填表、点按钮、查数据 —— 用编号操作，**不用写 CSS 选择器**
- 操作 React/Vue 等框架的页面组件 —— **CDP 真实鼠标点击**，框架认
- 自动沉淀操作技能 —— 第一次陌生网站操作后存成 skill，下次免扫描
- 多平台内容发布 —— B站/抖音/小红书视频图文一键发
- 抓取 XHR API 参数 —— 装拦截器，UI 操作一次，抓到真实请求，以后绕过 UI 直接调 API

---

## 不能做什么

- 不能"一句话全自动"（需要人确认复杂决策）
- 浏览器原生弹窗（"确定离开"）关不掉，操作期间不要手动刷新页面
- 不支持 chrome:// 和 chrome-extension:// 页面

---

## 安装（Agent 可执行）

以下步骤装到 Hermes 上。如果你用的是其他 Agent 平台，原理一样。

### 零、确认前置条件

```bash
node --version   # 需要 >= 20
python3 --version  # 需要 >= 3.10
google-chrome --version  # 需要 Chrome
```

### 一、克隆仓库到技能目录

```bash
git clone https://github.com/linchengyeyu/tmwebdriver.git ~/.hermes/tmwebdriver
```

### 二、安装 Python 依赖

```bash
cd ~/.hermes/tmwebdriver
python3 -m venv venv
./venv/bin/pip install simple-websocket-server requests beautifulsoup4 bottle
```

### 三、加载 Chrome 扩展

1. 打开 Chrome，地址栏输入 `chrome://extensions`
2. 开启右上角"开发者模式"
3. 点击"加载已解压的扩展程序"
4. **禁止** Chrome 两个本地网络访问限制 flag：`chrome://flags/#local-network-access-check` → **Disabled**，`chrome://flags/#local-network-access-check-websockets` → **Disabled**。点 "Relaunch" 后回来选 `~/.hermes/tmwebdriver/assets/` 文件夹

### 四、启动后台服务

```bash
cd ~/.hermes/tmwebdriver
PYTHONPATH="" ./venv/bin/python3 -c "
from TMWebDriver import TMWebDriver
import time
driver = TMWebDriver()
print('TMWebDriver 服务已启动 (Port 18765 WS / 18766 HTTP)')
print('打开 Chrome 任意网页，扩展会自动连接')
while True: time.sleep(3600)
" &
```

**验证：**

```bash
curl -s -X POST http://localhost:18766/link \
  -H "Content-Type: application/json" \
  -d '{"cmd":"get_all_sessions"}'
# 应返回你的 Chrome 标签页列表
```

### 五、告诉 Agent

装好之后，跟你 AI 助手说：

> "用 tmwebdriver 扫描一下当前 B站首页，输出有哪些可交互元素"

或者在聊天里直接给 Agent 这个命令即可，Agent 会自己调用 TMWebDriver 的 API。

---

## 快速上手

```python
from TMWebDriver import TMWebDriver

driver = TMWebDriver()

# 看看有哪些标签页连着
sessions = driver.get_all_sessions()
print(sessions)

# 扫描某个页面
sid = sessions[0]['id']
outline = driver.get_page_outline(max_elements=30, session_id=sid)
print(outline['text'])
# 输出: [1]<a href="//www.bilibili.com"> 首页
#       [3]<input placeholder="搜索" type="text">
#       [5]<button> 搜索

# 按编号操作
driver.click_index(5, session_id=sid)       # 点搜索按钮
driver.input_text_index(3, "AI工具", session_id=sid)  # 填搜索框
```

---

## 许可证

MIT

## 致谢

- [alibaba/page-agent](https://github.com/alibaba/page-agent) (MIT) — DOM 文本化核心思路
- [browser-use](https://github.com/browser-use/browser-use) (MIT) — 原始 DOM 扁平化算法
- [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) (MIT) — 多平台发布参考
