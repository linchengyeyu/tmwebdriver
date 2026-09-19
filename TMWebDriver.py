import json, threading, time, uuid, queue, socket, requests, traceback, os
from typing import Dict, Any, Optional, List  
from simple_websocket_server import WebSocketServer, WebSocket  
from bs4 import BeautifulSoup  
import bottle, random
from bottle import route, template, request, response

class Session:
    def __init__(self, session_id, info, client=None):
        self.id = session_id
        self.info = info
        self.connect_at = time.time()
        self.disconnect_at = None
        self.type = info.get('type', 'ws')
        self.ws_client = client if self.type in ('ws', 'ext_ws') else None
        self.http_queue = client if self.type == 'http' else None
    @property
    def url(self): return self.info.get('url', '')
    def is_active(self):
        if self.type == 'http' and time.time() - self.connect_at > 60: self.mark_disconnected()
        return self.disconnect_at is None
    def reconnect(self, client, info):
        self.info = info
        self.type = info.get('type', 'ws')
        if self.type in ('ws', 'ext_ws'):
            self.ws_client = client
            self.http_queue = None
        elif self.type == 'http':
            self.http_queue = client
        self.connect_at = time.time()
        self.disconnect_at = None
    def mark_disconnected(self):
        if self.is_active(): print(f"Tab disconnected: {self.url} (Session: {self.id})")
        self.disconnect_at = time.time()


class TMWebDriver:
    @staticmethod
    def _load_token():
        """读取访问令牌：TMWD_TOKEN 环境变量优先，其次 token.txt（chmod 600）。
        都没有 → 空 = 不启用鉴权（向后兼容既有调用方）。"""
        tok = os.environ.get('TMWD_TOKEN')
        if tok is not None: return tok.strip()
        tf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'token.txt')
        if os.path.exists(tf):
            try:
                with open(tf) as f: return f.read().strip()
            except Exception: pass
        return ''

    def __init__(self, host: str = '127.0.0.1', port: int = 18765, token=None):
        self.host, self.port = host, port
        self.sessions, self.results, self.acks = {}, {}, {}
        self.default_session_id = None
        self.latest_session_id = None
        # 鉴权（#4）：token 显式传 '' 可强制关闭；None = 从 env/token.txt 读
        self.token = self._load_token() if token is None else (token or '')
        self.is_remote = socket.socket().connect_ex((host, port+1)) == 0
        if not self.is_remote:
            self.start_ws_server()
            self.start_http_server()
        else:
            self.remote = f'http://{self.host}:{self.port+1}/link'

    def start_http_server(self):
        self.app = app = bottle.Bottle()

        # ---- 鉴权（#4）：token 启用时所有 /api、/link 路由要求凭证 ----
        if self.token:
            @app.hook('before_request')
            def _require_token():
                if request.path == '/health' or request.path.startswith('/tmwd/'): return  # 健康检查与 CRX 自托管（Chrome 更新器不带凭证）免鉴权
                supplied = request.get_header('X-TMWD-Token') or ''
                if not supplied:
                    ah = request.get_header('Authorization') or ''
                    if ah.startswith('Bearer '): supplied = ah[7:].strip()
                if not supplied: supplied = (request.query.token or '').strip()
                if not supplied:
                    try:
                        body = request.json
                        if isinstance(body, dict): supplied = str(body.get('token', '') or '').strip()
                    except Exception: pass
                if supplied != self.token:
                    raise bottle.HTTPError(401, json.dumps({'error': 'unauthorized', 'hint': 'send X-TMWD-Token header / ?token= / body token'}))

        @app.route('/health')
        def health():
            return json.dumps({'ok': True, 'auth': bool(self.token), 'version': '2.2'}, ensure_ascii=False)

        @app.route('/health', method=['GET', 'POST'])
        def health():
            return json.dumps({'ok': True, 'auth': bool(self.token), 'version': '2.2'}, ensure_ascii=False)

        # ---- CRX 自托管（Chrome 正式版 136+ 忽略 --load-extension，走企业策略强制安装）----
        _base = os.path.dirname(os.path.abspath(__file__))

        @app.route('/tmwd/update.xml')
        def tmwd_update_xml():
            try:
                with open(os.path.join(_base, 'assets', 'manifest.json')) as f:
                    ver = json.load(f).get('version', '2.0')
            except Exception:
                ver = '2.0'
            host = request.headers.get('Host') or f'127.0.0.1:{self.port+1}'
            response.content_type = 'application/xml'
            return ('<?xml version="1.0" encoding="UTF-8"?>'
                    '<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">'
                    '<app appid="akajnmghgmcneahfaggpgaldfjcfnpjj">'
                    f'<updatecheck codebase="http://{host}/tmwd/tmwd.crx" version="{ver}" />'
                    '</app></gupdate>')

        @app.route('/tmwd/tmwd.crx')
        def tmwd_crx():
            crx = os.path.join(_base, 'packed', 'tmwd.crx')
            if not os.path.exists(crx):
                raise bottle.HTTPError(404, 'tmwd.crx 未打包：先跑 pack_crx.sh')
            with open(crx, 'rb') as f:
                data = f.read()
            response.content_type = 'application/x-chrome-extension'
            return data

        @app.route('/api/longpoll', method=['GET', 'POST'])
        def long_poll():
            data = request.json
            session_id = data.get('sessionId')  
            session_info = {'url': data.get('url'), 'title': data.get('title', ''), 'type': 'http'}  
            if session_id not in self.sessions: 
                session = Session(session_id, session_info, queue.Queue())
                print(f"Browser http connected: {session.url} (Session: {session_id})")  
                self.sessions[session_id] = session
            session = self.sessions[session_id]
            if session.disconnect_at is not None and session.type != 'http': session.reconnect(queue.Queue(), session_info)
            session.disconnect_at = None
            if session.type == 'http': msgQ = session.http_queue
            else: return json.dumps({"id": "", "ret": "use ws"})
            session.connect_at = start_time = time.time()
            while time.time() - start_time < 5:
                try:
                    msg = msgQ.get(timeout=0.2)
                    try: self.acks[json.loads(msg).get('id','')] = True
                    except: traceback.print_exc()
                    return msg
                except queue.Empty: continue
            return json.dumps({"id": "", "ret": "next long-poll"})

        @app.route('/api/result', method=['GET','POST'])
        def result():
            data = request.json
            if data.get('type') == 'result':  
                self.results[data.get('id')] = {'success': True, 'data': data.get('result'), 'newTabs': data.get('newTabs', [])}  
            elif data.get('type') == 'error':  
                self.results[data.get('id')] = {'success': False, 'data': data.get('error'), 'newTabs': data.get('newTabs', [])}  
            return 'ok'

        @app.route('/link', method=['GET','POST'])
        def link():
            data = request.json
            if data.get('cmd') == 'get_all_sessions': return json.dumps({'r': self.get_all_sessions()}, ensure_ascii=False)  
            if data.get('cmd') == 'find_session': 
                url_pattern = data.get('url_pattern', '')
                return json.dumps({'r': self.find_session(url_pattern)}, ensure_ascii=False)
            if data.get('cmd') == 'execute_js':
                session_id = data.get('sessionId')
                code = data.get('code')
                timeout = float(data.get('timeout', 10.0))
                channel = data.get('channel', 'auto')
                try:
                    result = self.execute_js(code, timeout=timeout, session_id=session_id, channel=channel)
                    print('[remote result]', (str(code)[:50] + ' RESULT:' +str(result)[:50]).replace('\n', ' '))
                    return json.dumps({'r': result}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({'r': {'error': str(e)}}, ensure_ascii=False)
            if data.get('cmd') == 'execute_js_chunked':
                try:
                    full = self.execute_js_chunked(data.get('code'), session_id=data.get('sessionId'),
                                                   key=data.get('key', '__tmwd_result'),
                                                   chunk=int(data.get('chunk', 4000)),
                                                   timeout=float(data.get('timeout', 15.0)))
                    return json.dumps({'r': {'data': full}}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({'r': {'error': str(e)}}, ensure_ascii=False)
            if data.get('cmd') == 'wait_ready':
                ok = self.wait_ready(session_id=data.get('sessionId'),
                                     timeout=float(data.get('timeout', 15.0)),
                                     selector=data.get('selector'))
                return json.dumps({'r': {'ready': bool(ok)}}, ensure_ascii=False)
            return 'ok'
        def run():
            from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
            from socketserver import ThreadingMixIn
            class _T(ThreadingMixIn, WSGIServer): pass
            class _H(WSGIRequestHandler):
                def log_request(self, *a): pass
            make_server(self.host, self.port+1, app, server_class=_T, handler_class=_H).serve_forever()
        http_thread = threading.Thread(target=run, daemon=True)
        http_thread.start()  

    def clean_sessions(self):
        sids = list(self.sessions.keys())
        for sid in sids:
            session = self.sessions[sid]
            if not session.is_active() and time.time() - session.disconnect_at > 600:
                del self.sessions[sid]
    
    def start_ws_server(self) -> None:  
        driver = self  
        class JSExecutor(WebSocket):
            def handle(self) -> None:
                try:
                    data = json.loads(self.data)
                    # ---- WS 鉴权（#4）：token 启用时，首条消息必须是 hello+token ----
                    if driver.token and not getattr(self, 'authed', False):
                        if data.get('type') == 'hello' and data.get('token') == driver.token:
                            self.authed = True
                            self.send_message(json.dumps({'type': 'auth_ok'}))
                            return
                        try:
                            self.send_message(json.dumps({'type': 'auth_error', 'error': 'token required/mismatched'}))
                        except Exception: pass
                        self.close(1008, 'unauthorized')
                        return
                    if data.get('type') == 'ready':  
                        session_id = data.get('sessionId')  
                        session_info = {'url': data.get('url'), 'title': data.get('title', ''),
                            'connected_at': time.time(), 'type': 'ws'}  
                        driver._register_client(session_id, self, session_info)  
                    elif data.get('type') in ['ext_ready', 'tabs_update']:
                        tabs = data.get('tabs', [])
                        current_tab_ids = {str(tab['id']) for tab in tabs}
                        print(f"Received tabs update: {current_tab_ids}")
                        # 2026-08-21 修复：多扩展并存时（日常 Chrome + ego-browser 同时
                        # 连 WS:18765），空 tab 列表的一方会把另一方注册的会话全部误清。
                        # 规则：tab 列表为空的连接只跳过，不触发全局清理——扩展重连初期
                        # 或纯工具型浏览器（无普通网页 tab）上报空集是合法状态。
                        if current_tab_ids:
                            for sid in list(driver.sessions.keys()):
                                sess = driver.sessions[sid]
                                if sess.type == 'ext_ws' and sid not in current_tab_ids:
                                    sess.mark_disconnected()
                        for tab in tabs:
                            session_id = str(tab['id'])
                            session_info = {'url': tab.get('url'), 'title': tab.get('title', ''), 'connected_at': time.time(), 'type': 'ext_ws'}
                            sess = driver.sessions.get(session_id)
                            if sess and sess.is_active(): sess.info = session_info
                            else: driver._register_client(session_id, self, session_info)
                    elif data.get('type') == 'ack': driver.acks[data.get('id','')] = True
                    elif data.get('type') == 'result':  
                        driver.results[data.get('id')] = {'success': True, 'data': data.get('result'), 'newTabs': data.get('newTabs', [])}  
                    elif data.get('type') == 'error':  
                        driver.results[data.get('id')] = {'success': False, 'data': data.get('error'), 'newTabs': data.get('newTabs', [])}  
                except Exception as e:  
                    print(f"Error handling message: {e}")  
                    if hasattr(self, 'data'): print(self.data)  
            def connected(self): (f"New connection from {self.address}")  
            def handle_close(self): 
                print(f"WS Connection closed: {self.address}")
                driver._unregister_client(self)  
        
        self.server = WebSocketServer(self.host, self.port, JSExecutor)  
        server_thread = threading.Thread(target=self.server.serve_forever)  
        server_thread.daemon = True  
        server_thread.start()  
        print(f"WebSocket server running on ws://{self.host}:{self.port}")  
    
    def _register_client(self, session_id: str, client: WebSocket, session_info) -> None:  
        is_new_session = session_id not in self.sessions

        if is_new_session:
            session = Session(session_id, session_info, client)
            self.sessions[session_id] = session            
            print(f"New tab connected: {session.url} (Session: {session_id})")  
        else:
            session = self.sessions[session_id]
            session.reconnect(client, session_info)
            print(f"Tab reconnected: {session.url} (Session: {session_id})")  

        self.latest_session_id = session_id
        if self.default_session_id is None: self.default_session_id = session_id 
    
    def _unregister_client(self, client: WebSocket) -> None:  
        for session in self.sessions.values():
            if session.ws_client == client: session.mark_disconnected()
    
    def execute_js(self, code, timeout=15, session_id=None, channel='auto') -> Any:
        """channel（#3）:
        - 'auto'  默认：scripting 注入为主 → 瞬态错误重试 → CDP 兜底 → 按需剥 CSP 再试
        - 'cdp'   CDP 优先（不依赖页面注入环境），失败回退 scripting
        - 'script' 仅 scripting
        旧版扩展忽略 channel 字段，等价 'auto'。"""
        if session_id is None: session_id = self.default_session_id
        if self.is_remote:
            print('remote_execute_js')
            response = self._remote_cmd({"cmd": "execute_js", "sessionId": session_id,
                                         "code": code, "timeout": str(timeout), "channel": channel}).get('r', {})
            if response.get('error'): raise Exception(response['error'])
            return response
 
        session = self.sessions.get(session_id)
        if not session or not session.is_active(): 
            time.sleep(3)
            session = self.sessions.get(session_id)
            if not session or not session.is_active(): 
                alive_sessions = [s for s in self.sessions.values() if s.is_active()]
                if alive_sessions:
                    session = alive_sessions[0]  
                    print(f"会话 {session_id} 未连接，自动切换到最新活动会话: {session.id}")
                    session_id = self.default_session_id = session.id
                if not session or not session.is_active(): 
                    raise ValueError(f"会话ID {session_id} 未连接")  

        tp = session.type
        assert tp in ['ws', 'http', 'ext_ws'], f"Unsupported session type: {tp}"
        exec_id = str(uuid.uuid4())
        payload_dict = {'id': exec_id, 'code': code, 'channel': channel}
        if tp == 'ext_ws': payload_dict['tabId'] = int(session.id)
        payload = json.dumps(payload_dict)

        if tp in ['ws', 'ext_ws']: session.ws_client.send_message(payload)  
        elif tp == 'http': session.http_queue.put(payload)

        start_time = time.time()  
        self.clean_sessions() 
        hasjump = acked = False

        while exec_id not in self.results:  
            time.sleep(0.2)  
            if not acked and exec_id in self.acks:
                acked = True; start_time = time.time()
            if tp in ['ws', 'ext_ws']:
                if not session.is_active(): hasjump = True
                if hasjump and session.is_active():
                    return {'result': f"Session {session_id} reloaded.", "closed":1}
            if time.time() - start_time > timeout:  
                if tp in ['ws', 'ext_ws']:
                    if hasjump: return {'result': f"Session {session_id} reloaded and new page is loading...", 'closed':1}
                    if acked: return {"result": f"No response data in {timeout}s (ACK received, script may still be running)"}
                    return {"result": f"No response data in {timeout}s (no ACK, script may not have been delivered)"}
                elif tp == 'http':
                    if acked: return {"result": f"Session {session_id} no response in {timeout}s (delivered but no result)"}
                    return {"result": f"Session {session_id} no response in {timeout}s (script not polled)"}
        
        result = self.results.pop(exec_id)  
        if exec_id in self.acks: self.acks.pop(exec_id)
        if not result['success']: raise Exception(result['data'])  
        rr = {'data': result['data']}
        newtabs = result.get('newTabs', []); [x.pop('ts', None) for x in newtabs]
        if newtabs: rr['newTabs'] = newtabs
        return rr

    # ===== DOM Outline API =====
    # 借鉴 alibaba/page-agent 的 DOM 文本化思路
    # 详见 assets/dom_outline.js

    _DOM_OUTLINE_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'dom_outline.js')
    _DOM_OUTLINE_JS_CACHE = None

    def _load_dom_outline_js(self):
        """加载并缓存 dom_outline.js 内容"""
        if self._DOM_OUTLINE_JS_CACHE is None:
            with open(self._DOM_OUTLINE_JS_PATH) as f:
                self._DOM_OUTLINE_JS_CACHE = f.read()
        return self._DOM_OUTLINE_JS_CACHE

    def get_page_outline(self, max_elements=80, viewport_only=True, session_id=None, include_text=True):
        """
        获取页面 DOM 大纲（带编号的元素清单）

        借鉴 alibaba/page-agent 的 DOM 文本化方案：
        把页面所有"可交互元素"（a/button/input/select 等）打上数字编号，
        输出像这样的文本：
            [1]<a href="//www.bilibili.com"> 首页
            [2]<input placeholder="搜索" type="text">
            [3]<button> 搜索
        后续可通过 click_index(index) 操作对应元素。

        比手动写 CSS 选择器的优势：
        - 陌生网站零适配，直接用
        - 网站改版不失效（基于 DOM 结构而非固定选择器）
        - LLM 看文本大纲就能决策，不用截图

        :param max_elements: 最大编号元素数（默认 80，避免输出过长）
        :param viewport_only: 只扫视口内可见元素（默认 True，大页面防爆）
        :param session_id: 指定 tab，None 用默认
        :param include_text: 返回值是否包含 text 字段（LLM 决策用）
        :return: dict {
            'text': '带编号的文本清单',
            'pageInfo': {url, title, viewport, scroll...},
            'totalIndexed': int,
            'selectorMap': {1: {tag, text, attrs, xpath}, ...}
        }
        """
        import base64
        js_code = self._load_dom_outline_js()
        b64 = base64.b64encode(js_code.encode()).decode()

        call_js = f"""(function() {{
    var b64 = "{b64}";
    eval(atob(b64));
    var r = window.getDOMOutline({{maxElements: {max_elements}, viewportOnly: {str(viewport_only).lower()}}});
    return JSON.stringify(r);
}})()"""

        result = self.execute_js(call_js, session_id=session_id)
        data_str = result.get('data', '{}')
        try:
            data = json.loads(data_str)
        except:
            return {'error': 'Failed to parse outline', 'raw': data_str[:500]}

        if not include_text:
            data.pop('text', None)
        # selectorMap 太大时只返回 text
        if 'selectorMap' in data and len(str(data['selectorMap'])) > 20000:
            data.pop('selectorMap', None)
        return data

    def click_index(self, index, session_id=None):
        """
        通过 get_page_outline() 返回的编号点击元素

        :param index: get_page_outline() 返回的编号（如 3）
        :return: dict {success: bool, message: str}
        """
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element index {index} not found. Run get_page_outline() first.'}});
    try {{
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        el.click();
        return JSON.stringify({{success: true, message: 'Clicked [{index}]: <' + el.tagName.toLowerCase() + '>', tag: el.tagName.toLowerCase()}});
    }} catch(e) {{
        return JSON.stringify({{success: false, message: e.message}});
    }}
}})()"""
        result = self.execute_js(js, session_id=session_id)
        try:
            return json.loads(result.get('data', '{}'))
        except:
            return {'success': False, 'raw': result.get('data', '')[:200]}

    def hover_index(self, index, session_id=None):
        """
        通过编号悬停元素（触发 hover/mouseenter 下拉菜单）

        微信后台上「添加回复内容」这类 hover 触发式菜单需要这个。

        :param index: get_page_outline() 返回的编号
        :return: dict {success: bool, message: str}
        """
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element index {index} not found. Run get_page_outline() first.'}});
    try {{
        el.scrollIntoView({{block: 'center', behavior: 'instant'}});
        // 触发 mouseenter + mouseover 模拟鼠标悬停
        el.dispatchEvent(new MouseEvent('mouseenter', {{bubbles: true, cancelable: true, view: window}}));
        el.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true, cancelable: true, view: window}}));
        return JSON.stringify({{success: true, message: 'Hovered [{index}]: <' + el.tagName.toLowerCase() + '>', tag: el.tagName.toLowerCase()}});
    }} catch(e) {{
        return JSON.stringify({{success: false, message: e.message}});
    }}
}})()"""
        result = self.execute_js(js, session_id=session_id)
        try:
            return json.loads(result.get('data', '{}'))
        except:
            return {'success': False, 'raw': result.get('data', '')[:200]}

    def input_text_index(self, index, text, session_id=None, submit=False):
        """
        通过编号往输入框填文字（可选回车提交）

        :param index: get_page_outline() 返回的编号
        :param text: 要输入的文字
        :param submit: 是否按回车提交
        """
        import base64 as _b64
        import json as _json
        # base64 编码文字避免引号转义地狱
        # 注意：atob() 返回的是字节字符串（每个字符 charCode 0-255），
        # 不是 Unicode 字符。中文 UTF-8 字节会被当 Latin-1 解读 → 乱码。
        # 修复：用 TextDecoder 从字节字符串解 UTF-8。
        b64_text = _b64.b64encode(text.encode()).decode()
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element not found'}});
    try {{
        // atob → 字节字符串 → TextDecoder 解 UTF-8 → 正确的 Unicode 字符串
        var byteStr = atob('{b64_text}');
        var bytes = new Uint8Array(byteStr.length);
        for (var i = 0; i < byteStr.length; i++) bytes[i] = byteStr.charCodeAt(i);
        var text = new TextDecoder('utf-8').decode(bytes);
        el.scrollIntoView({{block: 'center'}});
        el.focus();

        if (el.isContentEditable) {{
            // Contenteditable 策略（参考 Page Agent）：
            // beforeinput -> innerText -> input 事件序列
            // React contenteditable 靠 InputEvent('beforeinput') 同步状态

            // 清除已有内容
            el.dispatchEvent(new InputEvent('beforeinput', {{
                bubbles: true, cancelable: true, inputType: 'deleteContent'
            }}));
            el.innerText = '';
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true, inputType: 'deleteContent'
            }}));

            // 插入新内容
            el.dispatchEvent(new InputEvent('beforeinput', {{
                bubbles: true, cancelable: true, inputType: 'insertText', data: text
            }}));
            el.innerText = text;
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true, inputType: 'insertText', data: text
            }}));

            // 验证，失败则 execCommand fallback
            if (el.innerText.trim() !== text.trim()) {{
                el.focus();
                var sel = window.getSelection();
                var rng = document.createRange();
                rng.selectNodeContents(el);
                sel.removeAllRanges();
                sel.addRange(rng);
                document.execCommand('delete', false);
                document.execCommand('insertText', false, text);
            }}

            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.blur();
        }} else {{
            // 普通 input/textarea：用 native setter 触发 React onChange
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                      || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (setter) setter.call(el, text);
            else el.value = text;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}

        if ({str(submit).lower()}) {{
            el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}}));
            if (el.form) el.form.submit();
        }}
        return JSON.stringify({{success: true, message: 'Filled [{index}] with: ' + text.substring(0, 30)}});
    }} catch(e) {{
        return JSON.stringify({{success: false, message: e.message}});
    }}
}})()"""
        result = self.execute_js(js, session_id=session_id)
        try:
            return json.loads(result.get('data', '{}'))
        except:
            return {'success': False, 'raw': result.get('data', '')[:200]}

    # ===== CDP 增强操作 =====
    # 利用 background.js 已有的 chrome.debugger 桥接
    # 发真实 CDP 命令（isTrusted: true），解决 React contenteditable 等框架不认合成事件的问题

    def _cdp_command(self, method, params=None, session_id=None):
        """
        发送 CDP 命令到浏览器 tab（内部方法）
        利用 background.js 已有的 handleCDP -> chrome.debugger.sendCommand 桥接

        :param method: CDP 方法名，如 'Input.dispatchMouseEvent'
        :param params: CDP 参数 dict
        :return: CDP 返回结果 dict
        """
        code = {'cmd': 'cdp', 'method': method, 'params': params or {}}
        result = self.execute_js(code, session_id=session_id)
        return result.get('data')

    def _cdp_batch(self, commands, session_id=None):
        """
        批量发送 CDP 命令（一次 attach，多个命令，最后 detach）
        避免连续多次 attach/detach 导致的竞争条件和 tab 僵死

        :param commands: [(method, params), ...] CDP 命令列表
        :return: [result1, result2, ...]
        """
        cmd_list = [{'cmd': 'cdp', 'method': m, 'params': p or {}} for m, p in commands]
        code = {'cmd': 'batch', 'commands': cmd_list}
        result = self.execute_js(code, session_id=session_id)
        return result.get('data', [])

    def cdp_click_by_index(self, index, session_id=None):
        """
        通过 CDP Input.dispatchMouseEvent 实现真实鼠标点击
        产生 isTrusted: true 的事件，React / Web Component 等框架认

        比 click_index() 更强：不用 el.click() 发合成事件，
        而是让 Chrome 用 DevTools Protocol 真的"移动鼠标并点击"。

        :param index: get_page_outline() 返回的编号
        :return: dict {success, message, x, y, tag}
        """
        # 获取元素坐标
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element not found. Run get_page_outline() first.'}});
    el.scrollIntoView({{block: 'center', behavior: 'instant'}});
    var r = el.getBoundingClientRect();
    return JSON.stringify({{success: true, x: r.left + r.width/2, y: r.top + r.height/2, tag: el.tagName.toLowerCase()}});
}})()"""
        result = self.execute_js(js, session_id=session_id)
        try:
            rect = json.loads(result.get('data', '{}'))
        except:
            return {'success': False, 'message': 'Failed to parse element position'}
        if not rect.get('success'):
            return {'success': False, 'message': rect.get('message', 'Unknown error')}

        x, y = rect['x'], rect['y']

        # CDP 鼠标事件序列：用 batch 一次 attach 避免竞争
        self._cdp_batch([
            ('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y, 'button': 'left', 'pointerType': 'mouse'}),
            ('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1, 'pointerType': 'mouse'}),
            ('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1, 'pointerType': 'mouse'})
        ], session_id=session_id)

        return {
            'success': True,
            'message': f'CDP real click [{index}]: <{rect["tag"]}> at ({x:.0f},{y:.0f})',
            'x': x, 'y': y, 'tag': rect['tag']
        }

    def cdp_input_text_by_index(self, index, text, session_id=None, submit=False):
        """
        CDP 真实点击 + beforeinput 填充 contenteditable
        最强方案：先用 CDP 真实点击激活 React 焦点（isTrusted: true），
        再用 beforeinput 事件序列填内容。

        适用于 input_text_index 搞不定的顽固 contenteditable。

        :param index: get_page_outline() 返回的编号
        :param text: 要输入的文字
        :param submit: 是否按回车提交
        :return: dict {success, message}
        """
        # Step 1: CDP 真实点击激活元素
        click_result = self.cdp_click_by_index(index, session_id=session_id)
        if not click_result.get('success'):
            return click_result

        # Step 2: 等待 React 处理焦点
        import time
        time.sleep(0.15)

        # Step 3: 填充内容（beforeinput + innerText + input）
        import base64 as _b64
        b64_text = _b64.b64encode(text.encode()).decode()
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element not found'}});
    try {{
        if(!window._tmw_b64d)window._tmw_b64d=function(s){{var b=atob(s);var a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new TextDecoder('utf-8').decode(a);}};
        var t = window._tmw_b64d('{b64_text}');
        el.scrollIntoView({{block: 'center'}});
        el.focus();

        if (el.isContentEditable) {{
            // 清除
            el.dispatchEvent(new InputEvent('beforeinput', {{
                bubbles: true, cancelable: true, inputType: 'deleteContent'
            }}));
            el.innerText = '';
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true, inputType: 'deleteContent'
            }}));
            // 插入
            el.dispatchEvent(new InputEvent('beforeinput', {{
                bubbles: true, cancelable: true, inputType: 'insertText', data: t
            }}));
            el.innerText = t;
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true, inputType: 'insertText', data: t
            }}));
            // fallback
            if (el.innerText.trim() !== t.trim()) {{
                el.focus();
                var sel = window.getSelection();
                var rng = document.createRange();
                rng.selectNodeContents(el);
                sel.removeAllRanges();
                sel.addRange(rng);
                document.execCommand('delete', false);
                document.execCommand('insertText', false, t);
            }}
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.blur();
        }} else {{
            var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                      || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            if (setter) setter.call(el, t);
            else el.value = t;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}

        if ({str(submit).lower()}) {{
            el.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}}));
            if (el.form) el.form.submit();
        }}
        return JSON.stringify({{success: true, message: 'CDP filled [{index}]: ' + t.substring(0, 30)}});
    }} catch(e) {{
        return JSON.stringify({{success: false, message: e.message}});
    }}
}})()"""
        result = self.execute_js(js, session_id=session_id)
        try:
            return json.loads(result.get('data', '{}'))
        except:
            return {'success': False, 'raw': result.get('data', '')[:200]}


    # ===== Phase 2: Skill 沉淀 API =====

    def get_element_selector(self, index, session_id=None):
        """
        提取编号元素的稳定选择器信息（需先调过 get_page_outline）

        :return: dict {tag, id, text, selectors:[...], bestSelector}
        """
        js = f"""(function() {{
    var s = window._tmw_get_element_selector ? window._tmw_get_element_selector({index}) : null;
    return s ? JSON.stringify(s) : 'null';
}})()"""
        r = self.execute_js(js, session_id=session_id)
        try:
            return json.loads(r.get('data', 'null'))
        except:
            return None

    @staticmethod
    def _gen_skill_js(steps, description=""):
        """
        根据步骤生成可复用的 site_skill JS 代码

        :param steps: [{type:'input', selectors:[...], param:'keyword'},
                       {type:'click', selectors:[...]}]
        :return: str JS 代码，含 {{param}} 占位符
        """
        # 选择器查找函数（多 fallback）
        lines = ['(function(){',
                 '  function findBy(selectors) {',
                 '    for (var i = 0; i < selectors.length; i++) {',
                 '      var s = selectors[i];',
                 '      try {',
                 '        if (s.indexOf("xpath:") === 0) {',
                 '          // xpath 方式',
                 '          var r = document.evaluate(s.substring(6), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);',
                 '          if (r.singleNodeValue) return r.singleNodeValue;',
                 '        } else if (s.indexOf(":has(") > 0) {',
                 '          // jQuery-style :has() 不被原生支持，退化到文字匹配',
                 '          var m = s.match(/^[a-z]+:has\\(> \\*:contains\\("([^"]+)"\\)\\)/);',
                 '          if (m) {',
                 '            var els = document.querySelectorAll(s.split(":has")[0]);',
                 '            for (var j=0; j<els.length; j++) { if (els[j].textContent.indexOf(m[1]) >= 0) return els[j]; }',
                 '          }',
                 '        } else if (s.indexOf("=") > 0) {',
                 '          // tag="text" 形式',
                 '          var p = s.split("="); var tag = p[0]; var txt = p[1].replace(/"/g, "");',
                 '          var all = document.querySelectorAll(tag);',
                 '          for (var j=0; j<all.length; j++) { if (all[j].textContent.trim() === txt) return all[j]; }',
                 '        } else {',
                 '          var el = document.querySelector(s);',
                 '          if (el) return el;',
                 '        }',
                 '      } catch(e) {}',
                 '    }',
                 '    return null;',
                 '  }',
                 '  function doClick(el) {',
                 '    el.scrollIntoView({block:"center", behavior:"instant"});',
                 '    el.click();',
                 '    return "ok";',
                 '  }',
                 '  function doInput(el, text) {',
                 '    el.scrollIntoView({block:"center"});',
                 '    el.focus();',
                 '    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set',
                 '              || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;',
                 '    if (setter) setter.call(el, text); else el.value = text;',
                 '    el.dispatchEvent(new Event("input", {bubbles:true}));',
                 '    el.dispatchEvent(new Event("change", {bubbles:true}));',
                 '  }',
                 '']

        for i, step in enumerate(steps):
            selectors_js = json.dumps(step.get('selectors', []))
            stype = step.get('type', 'click')
            if stype == 'input':
                param = step.get('param', 'text')
                lines.append(f'  // Step {i+1}: input into <{step.get("tag","?")}>')
                lines.append(f'  var el{i} = findBy({selectors_js});')
                lines.append(f'  if (!el{i}) return JSON.stringify({{success:false, step:{i+1}, message:"element not found"}});')
                lines.append(f'  doInput(el{i}, "{{{{{param}}}}}");')
            else:  # click
                lines.append(f'  // Step {i+1}: click <{step.get("tag","?")}>')
                lines.append(f'  var el{i} = findBy({selectors_js});')
                lines.append(f'  if (!el{i}) return JSON.stringify({{success:false, step:{i+1}, message:"element not found"}});')
                lines.append(f'  doClick(el{i});')

        lines.append('  return JSON.stringify({success:true, message:"all steps done"});')
        lines.append('})()')
        return '\n'.join(lines)

    def save_outline_skill(self, action_name, steps, description="", session_id=None,
                           domain=None, wait_steps=None):
        """
        把 outline 操作序列沉淀成 site_skill（下次免扫描）

        :param action_name: 技能名（如 "search"）
        :param steps: [{"type":"input","index":5,"param":"keyword"},
                       {"type":"click","index":8}]
                       （index 会被换成真实 selectors）
        :param description: 技能描述
        :param session_id: 当前 tab（提取 selectors 用）
        :param domain: 指定域名（None=自动从当前 URL 提取）
        :param wait_steps: [(after_step_idx, ms)] 每步后等待毫秒
        :return: dict {skill_name, domain, file, js_preview}
        """
        from urllib.parse import urlparse
        import os, json as _json

        # 1. 提取每步的 selectors
        resolved_steps = []
        for step in steps:
            idx = step.get('index')
            if idx is None:
                resolved_steps.append(step)
                continue
            sel = self.get_element_selector(idx, session_id=session_id)
            if not sel:
                return {'error': f'Cannot extract selector for index {idx}. Run get_page_outline first.'}
            resolved_steps.append({
                'type': step.get('type', 'click'),
                'tag': sel.get('tag'),
                'text': sel.get('text', ''),
                'selectors': sel.get('selectors', []),
                **({'param': step['param']} if 'param' in step else {})
            })

        # 2. 生成 JS
        js_code = self._gen_skill_js(resolved_steps, description)

        # 3. 定位域名
        if domain is None:
            url = self.execute_js('window.location.href', session_id=session_id).get('data', '')
            parsed = urlparse(url)
            domain = parsed.netloc or 'unknown.com'

        # 4. 存进 site_skills/<domain>.json
        skill_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site_skills')
        os.makedirs(skill_dir, exist_ok=True)
        skill_file = os.path.join(skill_dir, f'{domain}.json')

        existing = {}
        if os.path.exists(skill_file):
            try:
                with open(skill_file) as f:
                    existing = _json.load(f)
            except:
                existing = {}

        existing[action_name] = {
            'js': js_code,
            'description': description or f'{action_name} on {domain}',
            'tags': ['outline-derived'],
            'source': 'dom_outline',
            'resolved_steps': resolved_steps,
            'updated_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d'),
            'use_count': 0
        }

        with open(skill_file, 'w') as f:
            _json.dump(existing, f, ensure_ascii=False, indent=2)

        return {
            'skill_name': action_name,
            'domain': domain,
            'file': skill_file,
            'steps_count': len(resolved_steps),
            'js_preview': js_code[:300] + '...' if len(js_code) > 300 else js_code
        }

    def _remote_cmd(self, cmd):
        headers = {"Content-Type": "application/json"}
        if self.token: headers['X-TMWD-Token'] = self.token  # #4 远程模式自动带凭证
        return requests.post(self.remote, headers=headers, json=cmd).json()

    def get_all_sessions(self):  
        if self.is_remote:
            return self._remote_cmd({"cmd": "get_all_sessions"}).get('r', [])
        return [{'id': session.id, **session.info} for session in self.sessions.values()
                if session.is_active()]  

    def get_session_dict(self):
        return {session['id']: session['url'] for session in self.get_all_sessions()}
        
    def find_session(self, url_pattern: str):
        if url_pattern == '': 
            session = self.sessions.get(self.latest_session_id)
            return [(session.id, session.info)] if session else []
        matching_sessions = []  
        for session in self.sessions.values():
            if not session.is_active(): continue
            if 'url' in session.info and url_pattern in session.info['url']:  
                matching_sessions.append((session.id, session.info))  
        return matching_sessions

    def set_session(self, url_pattern: str) -> bool:  
        if self.is_remote:
            matched = self._remote_cmd({"cmd": "find_session", "url_pattern": url_pattern}).get('r', [])
        else:
            matched = self.find_session(url_pattern)
        if not matched: return print(f"警告: 未找到URL包含 '{url_pattern}' 的会话")  
        if len(matched) > 1: print(f"警告: 找到多个URL包含 '{url_pattern}' 的会话，选择第一个")  
        self.default_session_id, info = matched[0]
        print(f"成功设置默认会话: {self.default_session_id}: {info['url']}")  
        return self.default_session_id  
    
    # ---- #2 就绪信号：确定性等待取代 reload+sleep+重试 ----

    def wait_ready(self, session_id=None, timeout=15, selector=None, settle=0.4):
        """等页面就绪：document.readyState === 'complete'（可选再等 selector 出现）。
        settle 秒是给 SPA 渲染留的微稳定期。返回 bool，不抛异常。"""
        sel_js = ''
        if selector:
            sel_js = 'if(ok){var el=document.querySelector(%s);ok=!!el;}' % json.dumps(selector)
        # ok 时用双 requestAnimationFrame 等 SPA 渲染两帧再报就绪（execute_js 会 await Promise）
        js = ("(function(){var ok=(document.readyState==='complete');" + sel_js +
              "if(!ok)return '0';"
              "return new Promise(function(res){requestAnimationFrame(function(){requestAnimationFrame(function(){res('1')})})})})()")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.execute_js(js, timeout=5, session_id=session_id)
                if str(r.get('data', '')).strip() == '1':
                    time.sleep(settle)
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def wait_new_session(self, url_pattern='', timeout=15, exclude=None):
        """等一个新会话出现（新建标签页冷启动慢的问题）。返回新 session id 或 None。"""
        exclude = set(exclude or [])
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.is_remote:
                    matched = self._remote_cmd({"cmd": "find_session", "url_pattern": url_pattern}).get('r', [])
                    pairs = [(m[0], m[1]) for m in matched] if matched and isinstance(matched[0], (list, tuple)) else []
                else:
                    pairs = self.find_session(url_pattern)
                for sid, info in pairs:
                    if sid not in exclude:
                        return sid
            except Exception:
                pass
            time.sleep(0.3)
        return None

    def jump(self, url, timeout=10, wait=True, selector=None, ready_timeout=15):
        """导航并（默认）等就绪。wait=True 返回 bool（页面是否就绪）。"""
        self.execute_js(f"window.location.href={json.dumps(url)}", timeout=timeout)
        if wait:
            return self.wait_ready(timeout=ready_timeout, selector=selector)
        return None

    def newtab(self, url=None, wait=True, ready_timeout=15):
        """新开标签页。wait=True 时等新会话注册 + 页面就绪，返回 {'newSession': sid, ...}。"""
        if url is None: url = "http://www.baidu.com/robots.txt"
        try:
            if self.is_remote:
                before = {m[0] for m in (self._remote_cmd({"cmd": "find_session", "url_pattern": ''}).get('r', []) or []) if isinstance(m, (list, tuple))}
            else:
                before = {s['id'] for s in self.get_all_sessions()}
        except Exception:
            before = set()
        r = self.execute_js(f'GM_openInTab({json.dumps(url)});')
        if not wait: return r
        new_sid = self.wait_new_session(url_pattern=url.split('?')[0][:60], timeout=ready_timeout, exclude=before)
        if new_sid:
            self.wait_ready(session_id=new_sid, timeout=ready_timeout)
            out = {'newSession': new_sid}
            if isinstance(r, dict):
                out.update({k: v for k, v in r.items() if k != 'data'} or {})
            return out
        return {'newSession': None}

    # ---- #1 超长结果保障：存 window 变量 + 分段取回（协议级，防任何环节截断） ----

    def execute_js_chunked(self, code, session_id=None, key='__tmwd_result', chunk=4000, timeout=15):
        """code 必须是【表达式】（如 document.documentElement.outerHTML）。
        结果存 window.<key>，只回长度，再分段 substring 取回拼接。
        任何单段异常已取部分照常返回，不抛。"""
        wrapped = ("(window.%s = String((%s)), JSON.stringify({ok:1, len: window.%s.length}))"
                   % (key, code, key))
        r = self.execute_js(wrapped, session_id=session_id, timeout=timeout)
        try:
            total = int(json.loads(r.get('data', '{}')).get('len', 0))
        except Exception:
            total = 0
        parts, off = [], 0
        while off < total:
            n = min(chunk, total - off)
            j = "String(window.%s).substring(%d, %d)" % (key, off, off + n)
            try:
                r2 = self.execute_js(j, session_id=session_id, timeout=timeout)
                seg = r2.get('data', '')
                if not isinstance(seg, str) or seg == '': break
                parts.append(seg)
            except Exception:
                break
            off += n
        return ''.join(parts)

    # ================================================================
    # Site Skills — 灵感来自 Browser Harness 的 domain-skills
    # 每次成功的操作自动保存，下次访问同域名直接复用
    # ================================================================

    def _skills_dir(self):
        """获取 site_skills 目录路径"""
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site_skills')
        os.makedirs(d, exist_ok=True)
        return d

    def _extract_domain(self, session_id=None):
        """从当前会话URL提取域名"""
        if session_id is None: session_id = self.default_session_id
        session = self.sessions.get(session_id)
        if not session or not session.url: return None
        url = session.url
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            # 去掉 www. 前缀
            if domain.startswith('www.'): domain = domain[4:]
            return domain
        except:
            return None

    def save_skill(self, name, js_code, description="", domain=None, tags=None):
        """
        保存一个网站操作技能（成功的JS代码）
        - name: 技能名称，如 "search_videos"
        - js_code: 可执行的JS代码（支持 {{var}} 占位符）
        - description: 这个操作做什么
        - domain: 域名（不传则自动从当前tab检测）
        - tags: 标签列表，如 ["scrape", "navigate"]
        """
        if domain is None: domain = self._extract_domain()
        if not domain:
            print("⚠️ 无法保存技能：未指定域名且当前tab无有效URL")
            return False

        skill_file = os.path.join(self._skills_dir(), f"{domain}.json")
        skills = {}
        if os.path.exists(skill_file):
            try:
                with open(skill_file, 'r') as f: skills = json.load(f)
            except: skills = {}

        skills[name] = {
            'js': js_code,
            'description': description,
            'tags': tags or [],
            'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'use_count': skills.get(name, {}).get('use_count', 0)
        }

        with open(skill_file, 'w') as f:
            json.dump(skills, f, ensure_ascii=False, indent=2)

        print(f"✅ 技能已保存: {domain}/{name}")
        return True

    def get_skill(self, name, domain=None):
        """
        获取一个已保存的网站操作技能
        返回 {js, description, tags, updated_at, use_count} 或 None
        """
        if domain is None: domain = self._extract_domain()
        if not domain: return None

        skill_file = os.path.join(self._skills_dir(), f"{domain}.json")
        if not os.path.exists(skill_file): return None
        try:
            with open(skill_file, 'r') as f: skills = json.load(f)
            return skills.get(name)
        except:
            return None

    def list_skills(self, domain=None):
        """
        列出已保存的技能
        - domain=None: 列出所有域名的所有技能
        - domain="bilibili.com": 只列该域名的技能
        返回 {domain: {skill_name: description, ...}, ...}
        """
        import glob
        result = {}
        pattern = f"{domain}.json" if domain else "*.json"
        for f in glob.glob(os.path.join(self._skills_dir(), pattern)):
            d = os.path.basename(f).replace('.json', '')
            try:
                with open(f, 'r') as fh: skills = json.load(fh)
                result[d] = {k: v.get('description', '') for k, v in skills.items()}
            except: pass
        return result

    def _match_outline_step(self, step, outline):
        """#7 语义匹配：在 outline 的 selectorMap 里找回 step 对应的元素。
        打分：tag 命中 +2；文本/name/aria/placeholder 精确 +3 / 包含 +2。
        返回 (index, score) 或 None。"""
        best_idx, best_score = None, 0
        target_text = (step.get('text') or '').strip()
        old_sel = step.get('selectors') or []
        # 从旧选择器里捞语义线索（tag="text" 形式、placeholder 等）
        for s in old_sel:
            if isinstance(s, str) and '=' in s and not s.startswith(('#', '[', 'xpath:', 'a[')):
                frag = s.split('=', 1)[1].strip('"')
                if frag and len(frag) <= 30 and frag not in (target_text,): target_text = target_text or frag
        smap = outline.get('selectorMap') or {}
        for idx, info in smap.items():
            score = 0
            if info.get('tag') == step.get('tag'): score += 2
            attrs = info.get('attrs') or {}
            cands = [info.get('text', ''), info.get('name', ''), info.get('role', ''),
                     attrs.get('aria-label', ''), attrs.get('placeholder', ''), attrs.get('name', ''), attrs.get('title', '')]
            for c in cands:
                c = (c or '').strip()
                if not c or not target_text: continue
                if c == target_text: score += 3
                elif target_text in c or c in target_text: score += 2
            if score > best_score: best_idx, best_score = idx, score
        return (best_idx, best_score) if best_score >= 4 else None

    def _heal_skill(self, skill, name, domain, failed_step, session_id=None):
        """#7 自愈：重扫 outline → 语义匹配失败步 → 更新 selectors → 重新生成 JS 写回。"""
        steps = skill.get('resolved_steps')
        if not steps or not (1 <= failed_step <= len(steps)): return None
        try:
            outline = self.get_page_outline(session_id=session_id)
        except Exception:
            return None
        hit = self._match_outline_step(steps[failed_step - 1], outline)
        if not hit: return None
        idx, score = hit
        new_sel = self.get_element_selector(idx, session_id=session_id)
        if not new_sel or not new_sel.get('selectors'): return None
        step = steps[failed_step - 1]
        step['selectors'] = new_sel['selectors']
        step['tag'] = new_sel.get('tag', step.get('tag'))
        if new_sel.get('text'): step['text'] = new_sel['text']
        skill['js'] = self._gen_skill_js(steps, skill.get('description', ''))
        skill.setdefault('healed', []).append(
            {'step': failed_step, 'score': score, 'at': time.strftime('%Y-%m-%d %H:%M:%S')})
        skill['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        try:
            skill_file = os.path.join(self._skills_dir(), f"{domain}.json")
            with open(skill_file) as f: all_skills = json.load(f)
            all_skills[name] = skill
            with open(skill_file, 'w') as f: json.dump(all_skills, f, ensure_ascii=False, indent=2)
        except Exception:
            return None
        return True

    def execute_skill(self, name, domain=None, timeout=15, session_id=None, heal=True, **variables):
        """
        执行一个已保存的技能（带变量替换）
        - {{keyword}} 占位符会被替换为 variables 中对应的值
        - 自动更新 use_count
        - #7 自愈：元素找不到时重扫 outline 语义匹配，命中则更新技能并重试一次

        示例:
            driver.execute_skill("search", keyword="AI工具")
        """
        skill = self.get_skill(name, domain=domain)
        if not skill:
            domain_str = domain or self._extract_domain() or "未知域名"
            print(f"⚠️ 未找到技能: {domain_str}/{name}")
            return None

        js_code = skill['js']
        # 变量替换
        for key, val in variables.items():
            js_code = js_code.replace(f"{{{{{key}}}}}", str(val))

        # 更新使用计数
        if domain is None: domain = self._extract_domain()
        if domain:
            skill_file = os.path.join(self._skills_dir(), f"{domain}.json")
            try:
                with open(skill_file) as f: all_skills = json.load(f)
                all_skills[name]['use_count'] = all_skills[name].get('use_count', 0) + 1
                with open(skill_file, 'w') as f: json.dump(all_skills, f, ensure_ascii=False, indent=2)
            except: pass

        result = self.execute_js(js_code, timeout=timeout, session_id=session_id)

        # ---- #7 失效自愈：element not found → 重扫匹配 → 写回 → 重试一次 ----
        if heal and isinstance(result, dict):
            try:
                parsed = json.loads(result.get('data') or '')
                if (isinstance(parsed, dict) and not parsed.get('success')
                        and 'element not found' in str(parsed.get('message', ''))
                        and parsed.get('step') and domain):
                    healed = self._heal_skill(skill, name, domain, parsed['step'], session_id=session_id)
                    if healed:
                        r2 = self.execute_js(skill['js'], timeout=timeout, session_id=session_id)
                        try: r2['healed'] = {'step': parsed['step']}
                        except Exception: pass
                        print(f"🔁 技能自愈成功: {domain}/{name} step {parsed['step']}")
                        return r2
                    print(f"⚠️ 技能自愈未命中: {domain}/{name} step {parsed['step']}")
            except (ValueError, TypeError):
                pass
        return result

    def execute_and_save(self, name, js_code, description="", domain=None, timeout=15, session_id=None, **variables):
        """
        执行JS代码，成功后自动保存为技能（一站式）
        如果 variables 提供了，会先做变量替换再执行
        保存的是带占位符的原始模板（方便复用）
        """
        # 变量替换（用于执行）
        exec_js = js_code
        for key, val in variables.items():
            exec_js = exec_js.replace(f"{{{{{key}}}}}", str(val))

        result = self.execute_js(exec_js, timeout=timeout, session_id=session_id)

        # 不管成功失败都保存（失败的后续可以修改）
        self.save_skill(name, js_code, description=description, domain=domain)

        return result


if __name__ == "__main__":
    driver = TMWebDriver(host='127.0.0.1', port=18765)
    import signal, time, sys as _sys
    signal.signal(signal.SIGINT, lambda s,f: _sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s,f: _sys.exit(0))
    print("TMWebDriver running. Press Ctrl+C to stop.")
    while True:
        time.sleep(3600)