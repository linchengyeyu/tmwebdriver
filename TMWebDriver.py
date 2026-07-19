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
    def __init__(self, host: str = '127.0.0.1', port: int = 18765):  
        self.host, self.port = host, port
        self.sessions, self.results, self.acks = {}, {}, {}
        self.default_session_id = None  
        self.latest_session_id = None  
        self.is_remote = socket.socket().connect_ex((host, port+1)) == 0
        if not self.is_remote:  
            self.start_ws_server()  
            self.start_http_server()
        else:
            self.remote = f'http://{self.host}:{self.port+1}/link'

    def start_http_server(self):
        self.app = app = bottle.Bottle()

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
                try:
                    result = self.execute_js(code, timeout=timeout, session_id=session_id)
                    print('[remote result]', (str(code)[:50] + ' RESULT:' +str(result)[:50]).replace('\n', ' '))
                    return json.dumps({'r': result}, ensure_ascii=False)
                except Exception as e:
                    return json.dumps({'r': {'error': str(e)}}, ensure_ascii=False)
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
                    if data.get('type') == 'ready':  
                        session_id = data.get('sessionId')  
                        session_info = {'url': data.get('url'), 'title': data.get('title', ''),
                            'connected_at': time.time(), 'type': 'ws'}  
                        driver._register_client(session_id, self, session_info)  
                    elif data.get('type') in ['ext_ready', 'tabs_update']:
                        tabs = data.get('tabs', [])
                        current_tab_ids = {str(tab['id']) for tab in tabs}
                        print(f"Received tabs update: {current_tab_ids}")
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
    
    def execute_js(self, code, timeout=15, session_id=None) -> Any:  
        if session_id is None: session_id = self.default_session_id  
        if self.is_remote:
            print('remote_execute_js')
            response = self._remote_cmd({"cmd": "execute_js", "sessionId": session_id, 
                                         "code": code, "timeout": str(timeout)}).get('r', {})
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
        payload_dict = {'id': exec_id, 'code': code}
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
        b64_text = _b64.b64encode(text.encode()).decode()
        js = f"""(function() {{
    var el = window._tmw_get_element_by_index ? window._tmw_get_element_by_index({index}) : null;
    if (!el) return JSON.stringify({{success: false, message: 'Element not found'}});
    try {{
        var text = atob('{b64_text}');
        el.scrollIntoView({{block: 'center'}});
        el.focus();
        // 用 native setter 触发 React 等框架的 onChange
        var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
                  || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        if (setter) setter.call(el, text);
        else el.value = text;
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
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
        return requests.post(self.remote, headers={"Content-Type": "application/json"}, json=cmd).json()

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
    
    def jump(self, url, timeout=10): self.execute_js(f"window.location.href='{url}'", timeout=timeout)
    def newtab(self, url=None):
        if url is None: url = "http://www.baidu.com/robots.txt"
        return self.execute_js(f'GM_openInTab("{url}");')

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

    def execute_skill(self, name, domain=None, timeout=15, session_id=None, **variables):
        """
        执行一个已保存的技能（带变量替换）
        - {{keyword}} 占位符会被替换为 variables 中对应的值
        - 自动更新 use_count

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
                with open(skill_file, 'r') as f: all_skills = json.load(f)
                all_skills[name]['use_count'] = all_skills[name].get('use_count', 0) + 1
                with open(skill_file, 'w') as f: json.dump(all_skills, f, ensure_ascii=False, indent=2)
            except: pass

        return self.execute_js(js_code, timeout=timeout, session_id=session_id)

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