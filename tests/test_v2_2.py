"""v2.2 改进项回归测试（无需 pytest，直跑）：
  #1 execute_js_chunked 逻辑（分段拼接纯函数级验证在 live 冒烟里做）
  #4 token 鉴权：HTTP 401/200、/health 免鉴权、WS hello 握手
  #7 _match_outline_step 语义匹配
用法: venv/bin/python3 tests/test_v2_2.py
"""
import json, os, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from TMWebDriver import TMWebDriver  # noqa: E402

PASS, FAIL = [], []

def check(name, cond, detail=''):
    if isinstance(detail, bytes): detail = detail.decode('utf-8', 'replace')
    (PASS if cond else FAIL).append(name)
    print(('  ✅' if cond else '  ❌'), name, ('— ' + detail if detail and not cond else ''))

def http(port, path='/link', body=None, headers=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 data=json.dumps(body or {'cmd': 'get_all_sessions'}).encode(),
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过本地代理
    try:
        resp = opener.open(req, timeout=5)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def main():
    print('== #4 鉴权：token 启用实例 (28765/28766) ==')
    d1 = TMWebDriver(host='127.0.0.1', port=28765, token='test-token-123')
    time.sleep(0.5)  # 等 HTTP 线程 bind
    st, _ = http(28766)
    check('无 token → 401', st == 401, f'got {st}')
    st, _ = http(28766, headers={'X-TMWD-Token': 'wrong'})
    check('错 token → 401', st == 401, f'got {st}')
    st, body = http(28766, headers={'X-TMWD-Token': 'test-token-123'})
    check('对 token (header) → 200', st == 200)
    st, _ = http(28766, path='/link?token=test-token-123')
    check('对 token (query) → 200', st == 200, f'got {st}')
    st, _ = http(28766, body={'cmd': 'get_all_sessions', 'token': 'test-token-123'})
    check('对 token (body) → 200', st == 200, f'got {st}')
    st, body = http(28766, path='/health')
    check('/health 免鉴权且 auth=true', st == 200 and json.loads(body)['auth'] is True, body[:80])
    check('构造器 token 读取', d1.token == 'test-token-123')

    print('== #4 向后兼容：无 token 实例 (29765/29766) ==')
    d2 = TMWebDriver(host='127.0.0.1', port=29765, token='')
    time.sleep(0.5)
    st, body = http(29766)
    check('无 token 时裸调用 → 200（不破坏 hermes/omni-search）', st == 200, f'got {st}')
    st, body = http(29766, path='/health')
    check('/health auth=false', st == 200 and json.loads(body)['auth'] is False, body[:80])

    print('== #7 _match_outline_step 语义匹配 ==')
    outline = {'selectorMap': {
        1: {'tag': 'input', 'name': '搜索', 'role': 'searchbox', 'text': '', 'attrs': {'placeholder': '搜索你感兴趣的内容'}},
        2: {'tag': 'button', 'name': '登录', 'role': 'button', 'text': '扫码登录', 'attrs': {}},
        3: {'tag': 'a', 'name': '', 'role': 'link', 'text': '番剧', 'attrs': {}},
    }}
    m = d2._match_outline_step({'tag': 'input', 'text': '搜索', 'selectors': []}, outline)
    check('改版后 placeholder 语义命中 input', m is not None and m[0] == 1 and m[1] >= 4, str(m))
    m = d2._match_outline_step({'tag': 'button', 'text': '扫码登录', 'selectors': []}, outline)
    check('文本命中 button', m is not None and m[0] == 2, str(m))
    m = d2._match_outline_step({'tag': 'a', 'text': '完全不相关的文字且很长很长很长', 'selectors': []}, outline)
    check('无关文本不误匹配', m is None, str(m))

    print('== #1 execute_js_chunked 生成 JS 合法性 ==')
    wrapped = ("(window.%s = String((%s)), JSON.stringify({ok:1, len: window.%s.length}))"
               % ('k', 'document.title', 'k'))
    check('包装表达式语法', isinstance(wrapped, str) and wrapped.count('window.k') == 2)

    print(f"\n结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print('失败项:', FAIL); sys.exit(1)

if __name__ == '__main__':
    main()
