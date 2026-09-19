// background.js - Cookie + CDP Bridge
importScripts('./config.js'); // TMWD_WS_URL / TMWD_TOKEN

// #5 收敛：不再全局剥 CSP 响应头（原 onInstalled 里对所有站点生效的 DNR 规则已移除）。
// 改为按需：execute_js 在 scripting+CDP 都被 CSP 挡住时，临时加上这条规则重试一次，
// 空闲 10 秒后自动撤掉，平时页面保持原生 CSP。
const CSP_RULE_ID = 9999;
let cspRuleArmedAt = 0;
async function ensureCspRule() {
  cspRuleArmedAt = Date.now();
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: [CSP_RULE_ID],
    addRules: [{
      id: CSP_RULE_ID, priority: 1,
      action: { type: 'modifyHeaders', responseHeaders: [
        { header: 'content-security-policy', operation: 'remove' },
        { header: 'content-security-policy-report-only', operation: 'remove' }
      ]},
      condition: { urlFilter: '*', resourceTypes: ['main_frame', 'sub_frame'] }
    }]
  });
  // 撤防：规则生效 10 秒后移除（页面重新加载后才受影响，所以给足窗口）
  setTimeout(async () => {
    if (Date.now() - cspRuleArmedAt >= 9900) {
      try { await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: [CSP_RULE_ID] }); } catch (_) {}
    }
  }, 10000);
}

chrome.runtime.onInstalled.addListener(() => {
  console.log('CDP Bridge installed');
  // 清掉旧版本遗留的全局 CSP 剥离规则（升级收敛）
  chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: [CSP_RULE_ID] }).catch(() => {});
});

async function handleExtMessage(msg, sender) {
  if (msg.cmd === 'cookies') return await handleCookies(msg, sender);
  if (msg.cmd === 'cdp') return await handleCDP(msg, sender);
  if (msg.cmd === 'batch') return await handleBatch(msg, sender);
  if (msg.cmd === 'tabs') {
    try {
      if (msg.method === 'switch') {
        const tab = await chrome.tabs.update(msg.tabId, { active: true });
        await chrome.windows.update(tab.windowId, { focused: true });
        return { ok: true };
      }
      if (msg.method === 'close') {
        await chrome.tabs.remove(msg.tabId);
        return { ok: true };
      } else {
        const tabs = (await chrome.tabs.query({})).filter(t => isScriptable(t.url));
        const data = tabs.map(t => ({ id: t.id, url: t.url, title: t.title, active: t.active, windowId: t.windowId }));
        return { ok: true, data };
      }
    } catch (e) { return { ok: false, error: e.message }; }
  }
  if (msg.cmd === 'management') {
    try {
      if (msg.method === 'list') {
        const all = await chrome.management.getAll();
        return { ok: true, data: all.map(e => ({ id: e.id, name: e.name, enabled: e.enabled, type: e.type, version: e.version })) };
      }
      if (msg.method === 'reload') {
        chrome.alarms.create('tmwd-self-reload', { when: Date.now() + 200 });
        return { ok: true };
      }
      if (msg.method === 'disable') {
        await chrome.management.setEnabled(msg.extId, false);
        return { ok: true };
      }
      if (msg.method === 'enable') {
        await chrome.management.setEnabled(msg.extId, true);
        return { ok: true };
      }
      return { ok: false, error: 'Unknown method: ' + msg.method };
    } catch (e) { return { ok: false, error: e.message }; }
  }
  return { ok: false, error: 'Unknown cmd: ' + msg.cmd };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handleExtMessage(msg, sender).then(sendResponse);
  return true;
});

async function handleCookies(msg, sender) {
  try {
    let url = msg.url || sender.tab?.url;
    if (!url && msg.tabId) {
      const tab = await chrome.tabs.get(msg.tabId);
      url = tab.url;
    }
    const origin = url.match(/^https?:\/\/[^\/]+/)[0];
    const all = await chrome.cookies.getAll({ url });
    const part = await chrome.cookies.getAll({ url, partitionKey: { topLevelSite: origin } }).catch(() => []);
    const merged = [...all];
    for (const c of part) {
      if (!merged.some(x => x.name === c.name && x.domain === c.domain)) merged.push(c);
    }
    return { ok: true, data: merged };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function handleBatch(msg, sender) {
  const R = [];
  let attached = null;
  const resolve$N = (params) => JSON.parse(JSON.stringify(params || {}).replace(/"\$(\d+)\.([^"]+)"/g,
    (_, i, path) => { let v = R[+i]; for (const k of path.split('.')) v = v[k]; return JSON.stringify(v); }));
  try {
    for (const c of msg.commands) {
      if (c.tabId === undefined && msg.tabId !== undefined) c.tabId = msg.tabId;
      if (c.cmd === 'cookies') {
        R.push(await handleCookies(c, sender));
      } else if (c.cmd === 'tabs') {
        const tabs = (await chrome.tabs.query({})).filter(t => isScriptable(t.url));
        R.push({ ok: true, data: tabs.map(t => ({ id: t.id, url: t.url, title: t.title, active: t.active, windowId: t.windowId })) });
      } else if (c.cmd === 'cdp') {
        const tabId = c.tabId || msg.tabId || sender.tab?.id;
        if (attached !== tabId) {
          if (attached) { await chrome.debugger.detach({ tabId: attached }); attached = null; }
          await chrome.debugger.attach({ tabId }, '1.3');
          attached = tabId;
        }
        R.push(await chrome.debugger.sendCommand({ tabId }, c.method, resolve$N(c.params)));
      } else {
        R.push({ ok: false, error: 'unknown cmd: ' + c.cmd });
      }
    }
    if (attached) await chrome.debugger.detach({ tabId: attached });
    return { ok: true, results: R };
  } catch (e) {
    if (attached) try { await chrome.debugger.detach({ tabId: attached }); } catch (_) {}
    return { ok: false, error: e.message, results: R };
  }
}

async function handleCDP(msg, sender) {
  const tabId = msg.tabId || sender.tab?.id;
  if (!tabId) return { ok: false, error: 'no tabId' };
  try {
    await chrome.debugger.attach({ tabId }, '1.3');
    const result = await chrome.debugger.sendCommand({ tabId }, msg.method, msg.params || {});
    await chrome.debugger.detach({ tabId });
    return { ok: true, data: result };
  } catch (e) {
    try { await chrome.debugger.detach({ tabId }); } catch (_) {}
    return { ok: false, error: e.message };
  }
}
// Filter out chrome:// and other internal tabs that can't be scripted
const isScriptable = url => url && /^https?:/.test(url);

// --- Shared page/CDP script builder core ---
function buildExecScript(code, errorHandler) {
  return `(async () => {
    function smartProcessResult(result) {
      if (result === null || result === undefined || typeof result !== 'object') return result;
      try { if (result.window === result && result.document) return '[Window: ' + (result.location?.href || 'about:blank') + ']'; } catch(_){}
      if (typeof jQuery !== 'undefined' && result instanceof jQuery) {
        const elements = []; for (let i = 0; i < result.length; i++) { if (result[i] && result[i].nodeType === 1) elements.push(result[i].outerHTML); } return elements;
      }
      if (result instanceof NodeList || result instanceof HTMLCollection) {
        const elements = []; for (let i = 0; i < result.length; i++) { if (result[i] && result[i].nodeType === 1) elements.push(result[i].outerHTML); } return elements;
      }
      if (result.nodeType === 1) return result.outerHTML;
      if (!Array.isArray(result) && typeof result === 'object' && result !== null && 'length' in result && typeof result.length === 'number') {
        const firstElement = result[0];
        if (firstElement && firstElement.nodeType === 1) {
          const elements = []; const length = Math.min(result.length, 100);
          for (let i = 0; i < length; i++) { const elem = result[i]; if (elem && elem.nodeType === 1) elements.push(elem.outerHTML); } return elements;
        }
      }
      try { return JSON.parse(JSON.stringify(result, function(key, value) { if (typeof value === 'object' && value !== null) { if (value.nodeType === 1) return value.outerHTML; if (value === window || value === document) return '[Object]'; try { if (value.window === value && value.document) return '[Window]'; } catch(_){} } return value; })); } catch (e) { return '[无法序列化: ' + e.message + ']'; }
    }
    try {
      const jsCode = ${JSON.stringify(code)}.trim();
      const lines = jsCode.split(/\\r?\\n/).filter(l => l.trim());
      const lastLine = lines.length > 0 ? lines[lines.length - 1].trim() : '';
      const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
      let r;
      function _air(c) { const ls = c.split(/\\r?\\n/); let i = ls.length - 1; while (i >= 0 && !ls[i].trim()) i--; if (i < 0) return c; const t = ls[i].trim(); if (/^(return |return;|return$|let |const |var |if |if\\(|for |for\\(|while |while\\(|switch|try |throw |class |function |async |import |export |\\/\\/|})/.test(t)) return c; ls[i] = ls[i].match(/^(\\s*)/)[1] + 'return ' + t; return ls.join('\\n'); }
      if (lastLine.startsWith('return')) {
        r = await (new AsyncFunction(jsCode))();
      } else {
        try { r = eval(jsCode); if (r instanceof Promise) r = await r; } catch (e) {
          if (e instanceof SyntaxError && (/return/i.test(e.message) || /await/i.test(e.message))) { r = await (new AsyncFunction(_air(jsCode)))(); } else throw e;
        }
      }
      return { ok: true, data: smartProcessResult(r) };
    } catch (e) {
      ${errorHandler}
    }
  })()`;
}

function buildPageScript(code) {
  return buildExecScript(code, `
      const errMsg = e.message || String(e);
      return { ok: false, error: { name: e.name || 'Error', message: errMsg, stack: e.stack || '' },
        csp: errMsg.includes('Refused to evaluate') || errMsg.includes('unsafe-eval') || errMsg.includes('Content Security Policy') };
  `);
}

function buildCdpScript(code) {
  return buildExecScript(code, `
      return { ok: false, error: { name: e.name || 'Error', message: e.message || String(e), stack: e.stack || '' } };
  `);
}

// --- WebSocket Client for TMWebDriver ---
let ws = null;
const WS_URL = (typeof TMWD_WS_URL !== 'undefined' && TMWD_WS_URL) ? TMWD_WS_URL : 'ws://127.0.0.1:18765';
const WS_TOKEN = (typeof TMWD_TOKEN !== 'undefined') ? (TMWD_TOKEN || '') : '';

function scheduleProbe() {
  // Use chrome.alarms to survive MV3 service worker suspension
  chrome.alarms.create('tmwd-ws-probe', { delayInMinutes: 0.083 }); // ~5s
}

function scheduleKeepalive() {
  // Keep SW alive while WS is connected (~25s, under 30s SW timeout)
  chrome.alarms.create('tmwd-ws-keepalive', { delayInMinutes: 0.4 }); // ~24s
}

async function isServerAlive() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 2000);
    await fetch('http://127.0.0.1:18765', { signal: ctrl.signal });
    return true; // Got HTTP response → port is listening
  } catch (e) {
    return false; // Network error (connection refused) or timeout → server not alive
  }
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'tmwd-self-reload') {
    chrome.runtime.reload();
    return;
  }
  if (alarm.name === 'tmwd-ws-keepalive') {
    // Keepalive: ping to keep SW alive + detect dead connections
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send('{"type":"ping"}'); } catch (_) {}
      scheduleKeepalive();
    } else {
      // Connection lost, switch to probe mode
      ws = null;
      scheduleProbe();
    }
  }
  if (alarm.name === 'tmwd-ws-probe') {
    if (ws && ws.readyState <= 1) return; // Already connected/connecting
    if (await isServerAlive()) {
      console.log('[TMWD-WS] Server detected, connecting...');
      connectWS();
    } else {
      scheduleProbe(); // Server not up, keep probing
    }
  }
});

// --- #3 执行通道重构：scripting / CDP 双通道 + 瞬态重试 + 按需 CSP ---
// 瞬态错误：导航竞态导致的注入失败，重试一次通常就好（取代旧版"reload+sleep 5s"）
const TRANSIENT_RE = /Frame with ID .* was removed|The frame was removed|cannot access contents of the page|Extension context invalidated|No frame .* found|Target closed|Frame was navigated/i;

async function runScripting(tabId, code) {
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: async (s) => await eval(s),
      args: [buildPageScript(code)]
    });
    let res = (result && result.length > 0) ? result[0].result : undefined;
    if (res === null || res === undefined) {
      res = { ok: false, error: { name: 'Error', message: 'executeScript returned null (possible CSP or context issue)', stack: '' }, csp: true };
    }
    return res;
  } catch (e) {
    return { ok: false, error: { name: e.name || 'Error', message: e.message || String(e), stack: e.stack || '' },
      csp: /cannot access contents|Frame with ID|Content Security Policy|Refused to evaluate/i.test(e.message || '') };
  }
}

async function runCdp(tabId, code) {
  try {
    await chrome.debugger.attach({ tabId }, '1.3');
    const cdpRes = await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
      expression: buildCdpScript(code), awaitPromise: true, returnByValue: true
    });
    await chrome.debugger.detach({ tabId });
    if (cdpRes.exceptionDetails) {
      const desc = cdpRes.exceptionDetails.exception?.description || 'CDP Error';
      return { ok: false, error: { name: 'Error', message: desc, stack: desc } };
    }
    return cdpRes.result.value;
  } catch (cdpErr) {
    try { await chrome.debugger.detach({ tabId }); } catch (_) {}
    return { ok: false, error: { name: 'Error', message: 'CDP failed: ' + cdpErr.message, stack: '' } };
  }
}

async function handleWsExec(data) {
  const tabId = data.tabId;
  console.log('[TMWD-WS] Exec request', data.id, 'on tab', tabId, 'channel', data.channel || 'auto');
  ws.send(JSON.stringify({ type: 'ack', id: data.id }));
  if (!tabId) {
    ws.send(JSON.stringify({ type: 'error', id: data.id, error: 'No tabId provided' }));
    return;
  }
  // Use onCreated listener to reliably capture new tabs (avoids race condition with query-diff)
  const newTabIds = new Set();
  const onCreated = (tab) => { newTabIds.add(tab.id); };
  chrome.tabs.onCreated.addListener(onCreated);
  try {
    const channel = data.channel || 'auto';
    let res;
    if (channel === 'cdp') {
      // CDP 优先（不依赖页面注入环境），失败回退 scripting
      res = await runCdp(tabId, data.code);
      if (!res?.ok) {
        console.log('[TMWD-WS] CDP-first failed, falling back to scripting:', res?.error?.message);
        res = await runScripting(tabId, data.code);
      }
    } else {
      // auto / script：注入为主
      res = await runScripting(tabId, data.code);
      const errMsg = res?.error?.message || '';
      if (!res?.ok && TRANSIENT_RE.test(errMsg)) {
        // 瞬态错误（导航竞态）：等 300ms 重试一次
        await new Promise(r => setTimeout(r, 300));
        res = await runScripting(tabId, data.code);
      }
      if (channel !== 'script' && !res?.ok && (res.csp || TRANSIENT_RE.test(res?.error?.message || ''))) {
        // CSP / 仍瞬态失败 → CDP 兜底（Runtime.evaluate 属 DevTools 通道，不受页面 CSP 约束）
        console.log('[TMWD-WS] CDP fallback for tab', tabId);
        const wasCsp = !!res.csp;
        res = await runCdp(tabId, data.code);
        if (!res?.ok && wasCsp) {
          // 双通道都被 CSP 挡住（如 debugger 被占用）：按需剥 CSP 响应头，
          // 下次导航/重载后 scripting 通道即可用；10 秒后自动撤防
          await ensureCspRule();
        }
      }
    }
    // Grace period for async tab creation (e.g. link click with target=_blank)
    if (newTabIds.size === 0) await new Promise(r => setTimeout(r, 200));
    chrome.tabs.onCreated.removeListener(onCreated);
    // Get full info for captured new tabs
    const newTabs = [];
    for (const id of newTabIds) {
      try { const t = await chrome.tabs.get(id); newTabs.push({id: t.id, url: t.url, title: t.title}); } catch (_) {}
    }
    if (res?.ok) {
      ws.send(JSON.stringify({ type: 'result', id: data.id, result: res.data, newTabs }));
    } else {
      console.log(res);
      ws.send(JSON.stringify({ type: 'error', id: data.id, error: res?.error || 'Unknown error', newTabs }));
    }
  } catch (e) {
    ws.send(JSON.stringify({ type: 'error', id: data.id, error: { name: e.name || 'Error', message: e.message || String(e), stack: e.stack || '' } }));
  } finally {
    chrome.tabs.onCreated.removeListener(onCreated);
  }
}

function connectWS() {
  if (ws && ws.readyState <= 1) return; // CONNECTING or OPEN
  ws = null;
  console.log('[TMWD-WS] Connecting to', WS_URL);
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.error('[TMWD-WS] Constructor error:', e);
    ws = null;
    scheduleProbe();
    return;
  }
  ws.onopen = async () => {
    console.log('[TMWD-WS] Connected!');
    scheduleKeepalive(); // Keep SW alive while connected
    // #4 鉴权握手：token 启用时首条消息必须是 hello+token，通过后服务端才受理后续消息
    if (WS_TOKEN) {
      ws.send(JSON.stringify({ type: 'hello', token: WS_TOKEN }));
    }
    const tabs = (await chrome.tabs.query({})).filter(t => isScriptable(t.url));
    ws.send(JSON.stringify({
      type: 'ext_ready',
      tabs: tabs.map(t => ({ id: t.id, url: t.url, title: t.title }))
    }));
    console.log('[TMWD-WS] Sent ext_ready with', tabs.length, 'tabs');
  };
  ws.onmessage = async (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'auth_ok') { console.log('[TMWD-WS] Auth ok'); return; }
      if (data.type === 'auth_error') {
        console.error('[TMWD-WS] Auth failed:', data.error, '→ 检查 config.js TMWD_TOKEN 与服务端 token.txt 是否一致');
        try { ws.close(); } catch (_) {}
        ws = null;
        return; // 保持 probe 循环，修正配置后会自动重连
      }
      if (data.id && data.code) {
        let code = data.code;
        // If code is a JSON string representing an object, parse it
        if (typeof code === 'string') {
          try { const p = JSON.parse(code); if (p && typeof p === 'object') code = p; } catch (_) {}
        }
        if (typeof code === 'object' && code !== null && code.cmd) {
          // Custom protocol message → route to handleExtMessage
          if (code.tabId === undefined && data.tabId !== undefined) code.tabId = data.tabId;
          const res = await handleExtMessage(code, {});
          ws.send(JSON.stringify({ type: res.ok ? 'result' : 'error', id: data.id, result: res.data ?? res.results ?? res, error: res.error }));
        } else if (typeof code === 'string') {
          // Plain JS code
          await handleWsExec(data);
        } else if (typeof code === 'object' && code !== null) {
          // Object without cmd → legacy extension message
          const msg = code.tabId === undefined && data.tabId !== undefined ? { ...code, tabId: data.tabId } : code;
          const res = await handleExtMessage(msg, {});
          ws.send(JSON.stringify({ type: res.ok ? 'result' : 'error', id: data.id, result: res.data ?? res.results ?? res, error: res.error }));
        }
      }
    } catch (e) {
      console.error('[TMWD-WS] message parse error', e);
    }
  };
  ws.onclose = () => {
    console.log('[TMWD-WS] Disconnected');
    ws = null;
    scheduleProbe();
  };
  ws.onerror = (e) => {
    console.error('[TMWD-WS] Error:', e);
    // onclose will fire after this, which triggers reconnect
  };
}

// Initial connect + wake-up hooks
connectWS();
chrome.runtime.onStartup.addListener(() => connectWS());
chrome.runtime.onInstalled.addListener(() => connectWS());

// Sync tab list on changes
async function sendTabsUpdate() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const tabs = (await chrome.tabs.query({})).filter(t => isScriptable(t.url) && !/streamlit/i.test(t.title));
  ws.send(JSON.stringify({
    type: 'tabs_update',
    tabs: tabs.map(t => ({ id: t.id, url: t.url, title: t.title }))
  }));
}
chrome.tabs.onUpdated.addListener((_, changeInfo) => {
  if (changeInfo.status === 'complete') sendTabsUpdate();
});
chrome.tabs.onRemoved.addListener(() => sendTabsUpdate());
chrome.tabs.onCreated.addListener(() => sendTabsUpdate());
