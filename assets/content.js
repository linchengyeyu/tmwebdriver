;(function(){ if (/streamlit/i.test(document.title)) return;

// #5 收敛激进行为：
// - 不再无条件移除 meta CSP（对已加载页面本就无效，且属于可被站点检测的改动；
//   CSP 页面由 background 的 CDP 兜底通道处理）
// - "已连接"徽章仅在 URL 带 ?tmwd_debug / #tmwd_debug 时显示（平时不污染页面、不留指纹）

if (/[?&#]tmwd_debug/.test(location.search + location.hash)) {
  (function(){
    if (window.self !== window.top) return;
    const d = document.createElement('div');
    d.id = 'ljq-ind';
    d.innerText = 'ljq_driver: 已连接';
    d.style.cssText = 'position:fixed;bottom:8px;right:8px;background:#4CAF50;color:white;padding:4px 7px;border-radius:4px;font-size:11px;font-weight:bold;z-index:99999;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.2);opacity:0.5;';
    d.addEventListener('click', () => alert('会话活跃\nURL: ' + location.href));
    (document.body || document.documentElement).appendChild(d);
  })();
}

new MutationObserver(muts => {
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.id === TID || (n.querySelector && n.querySelector('#' + TID))) {
      const el = n.id === TID ? n : n.querySelector('#' + TID);
      handle(el);
    }
  }
}).observe(document.documentElement, { childList: true, subtree: true });

async function handle(el) {
  try {
    const req = el.textContent.trim() ? JSON.parse(el.textContent) : { cmd: 'cookies' };
    const cmd = req.cmd || 'cookies';
    let resp;
    if (cmd === 'cookies') {
      resp = await chrome.runtime.sendMessage({ cmd: 'cookies', url: req.url || location.href });
    } else if (cmd === 'cdp') {
      resp = await chrome.runtime.sendMessage({ cmd: 'cdp', method: req.method, params: req.params || {}, tabId: req.tabId });
    } else if (cmd === 'batch') {
      resp = await chrome.runtime.sendMessage({ cmd: 'batch', commands: req.commands, tabId: req.tabId });
    } else if (cmd === 'tabs') {
      resp = await chrome.runtime.sendMessage({ cmd: 'tabs', method: req.method, tabId: req.tabId });
    } else {
      resp = { ok: false, error: 'unknown cmd: ' + cmd };
    }
    el.textContent = JSON.stringify(resp);
  } catch (e) {
    el.textContent = JSON.stringify({ ok: false, error: e.message });
  }
}
})();
