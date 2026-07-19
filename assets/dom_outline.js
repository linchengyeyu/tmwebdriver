/**
 * dom_outline.js — 精简版 DOM 文本化（给 LLM 看的页面大纲）
 *
 * Derived from alibaba/page-agent (MIT) → browser-use (MIT)
 *   https://github.com/alibaba/page-agent/blob/main/packages/page-controller/src/dom/dom_tree/index.js
 *   https://github.com/browser-use/browser-use
 *
 * 作用：扫描当前页面 DOM，输出带编号的"可交互元素清单"文本。
 *   [1]<input placeholder=搜索 />
 *   [2]<button>搜索</button>
 *   [3]<a>首页</a>
 *
 * 编号即索引，后续可 tmwebdriver.click_index(1) 直接操作。
 * 纯 JS，无 LLM 依赖，无网络请求，可作 content script 注入。
 *
 * 用法：
 *   const outline = getDOMOutline({ maxElements: 50 })
 *   // outline.text  →  带编号的文本清单
 *   // outline.selectorMap  →  { 1: element, 2: element, ... } 元素引用
 *   // outline.pageInfo  →  { url, scrollY, pageHeight, viewportHeight, ... }
 */

(function (global) {
  'use strict'

  // 语义标签，即使不可交互也保留作为上下文
  const SEMANTIC_TAGS = new Set(['nav', 'menu', 'header', 'footer', 'aside', 'dialog', 'main', 'article', 'form'])

  // 缓存：避免重复读 layout 属性（性能优化）
  const cache = {
    boundingRects: new WeakMap(),
    computedStyles: new WeakMap()
  }

  function getRect(el) {
    if (!el) return null
    if (cache.boundingRects.has(el)) return cache.boundingRects.get(el)
    const r = el.getBoundingClientRect()
    cache.boundingRects.set(el, r)
    return r
  }

  function getStyle(el) {
    if (!el) return null
    if (cache.computedStyles.has(el)) return cache.computedStyles.get(el)
    const s = window.getComputedStyle(el)
    cache.computedStyles.set(el, s)
    return s
  }

  // ===== 可见性判断 =====
  function isElementVisible(el) {
    const style = getStyle(el)
    if (!style) return false
    if (style.display === 'none' || style.visibility === 'hidden') return false
    if (parseFloat(style.opacity) === 0) return false
    const rect = getRect(el)
    if (!rect) return false
    if (rect.width === 0 || rect.height === 0) return false
    // content-visibility: hidden（Chrome 85+）
    if (style.contentVisibility === 'hidden') return false
    return true
  }

  function isTextNodeVisible(textNode) {
    if (!textNode.textContent || !textNode.textContent.trim()) return false
    const parent = textNode.parentElement
    if (!parent) return false
    return isElementVisible(parent)
  }

  // 判断元素是否在视口最上层（不被其他元素遮挡）—— 用 elementFromPoint 检测
  function isTopElement(el) {
    const rect = getRect(el)
    if (!rect) return false
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    // 元素完全在视口外时不检查（elementFromPoint 返回 null）
    if (y < 0 || y > window.innerHeight || x < 0 || x > window.innerWidth) {
      return true // 视口外的不遮挡
    }
    try {
      const top = document.elementFromPoint(x, y)
      if (!top) return true
      // 检查 top 是 el 或 el 的后代/祖先
      return top === el || el.contains(top) || top.contains(el)
    } catch {
      return true
    }
  }

  // ===== 可交互性判断 =====
  // 标签名 → 是否可交互（快速路径，不用读 style）
  const INTERACTIVE_TAGS = new Set([
    'a', 'button', 'input', 'select', 'textarea', 'summary', 'label',
    'option', 'optgroup', 'details'
  ])

  // 可交互 cursor 集合
  const INTERACTIVE_CURSORS = new Set([
    'pointer', 'text', 'move', 'grab', 'grabbing', 'cell', 'copy',
    'alias', 'all-scroll', 'col-resize', 'context-menu', 'crosshair',
    'help', 'n-resize', 'ne-resize', 'nesw-resize', 'ns-resize',
    'nw-resize', 'nwse-resize', 'row-resize', 's-resize', 'se-resize',
    'sw-resize', 'e-resize', 'w-resize', 'ew-resize', 'vertical-text',
    'zoom-in', 'zoom-out'
  ])

  function isInteractiveElement(el, blacklist, whitelist) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false
    if (blacklist && blacklist.includes(el)) return false
    if (whitelist && whitelist.includes(el)) return true

    const tag = el.tagName.toLowerCase()

    // 快速路径：常见交互标签
    if (INTERACTIVE_TAGS.has(tag)) return true

    // ARIA role
    const role = el.getAttribute('role')
    if (role && ['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'combobox', 'option', 'searchbox', 'textbox'].includes(role)) {
      return true
    }

    // contenteditable
    if (el.isContentEditable) return true

    // tabindex >= 0
    const tabindex = el.getAttribute('tabindex')
    if (tabindex !== null && parseInt(tabindex, 10) >= 0) return true

    // JS 事件绑定（onclick, onmousedown 等）
    if (el.onclick || el.onmousedown || el.onmouseup || el.onmouseover) return true

    // cursor 判断（慢路径）
    const style = getStyle(el)
    if (style && style.cursor && INTERACTIVE_CURSORS.has(style.cursor)) return true

    return false
  }

  // ===== 主扫描函数：构建带编号的扁平 DOM 树 =====
  function buildFlatTree(options) {
    const blacklist = options.blacklist || []
    const whitelist = options.whitelist || []
    const viewportOnly = options.viewportOnly !== false // 默认只看视口内

    const nodes = [] // 线性数组
    const selectorMap = {} // {index: element}
    let highlightIndex = 0

    // 全局引用映射 —— 让后续 click_index 能找到元素
    if (!global._tmw_outline_map) global._tmw_outline_map = {}
    const refMap = global._tmw_outline_map

    function walk(el, depth, parentIndex) {
      if (!el || el.nodeType !== Node.ELEMENT_NODE) return

      // 跳过 script/style/noscript/meta/link 等
      const tag = el.tagName.toLowerCase()
      if (['script', 'style', 'noscript', 'meta', 'link', 'head', 'title'].includes(tag)) return
      // 跳过装饰性 SVG/PATH（不具交互意义，纯噪声）
      if (['svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'defs', 'use', 'g'].includes(tag)) {
        // 但 SVG 内的 <a>/<button> 仍处理（通过递归子节点完成）
        for (const child of el.children) walk(child, depth + 1, parentIndex)
        return
      }
      // 跳过纯空 div（无文字、无子元素、不可交互）
      if (tag === 'div' && el.children.length === 0 && !getDirectText(el) && !isInteractiveElement(el, blacklist, whitelist)) return

      const visible = isElementVisible(el)
      if (!visible) return

      // 视口过滤
      if (viewportOnly) {
        const rect = getRect(el)
        if (rect && (rect.bottom < 0 || rect.top > window.innerHeight ||
                     rect.right < 0 || rect.left > window.innerWidth)) {
          return
        }
      }

      const interactive = isInteractiveElement(el, blacklist, whitelist)
      let myIndex = null

      if (interactive) {
        // 只对交互元素编号（避免输出爆炸）
        myIndex = ++highlightIndex
        refMap[myIndex] = el
        selectorMap[myIndex] = {
          tag,
          text: getDirectText(el).substring(0, 60),
          attrs: pickAttrs(el),
          xpath: getXPath(el)
        }
      }

      // 递归子节点
      for (const child of el.children) {
        walk(child, depth + 1, myIndex)
      }
    }

    walk(document.body, 0, null)

    return { selectorMap, totalIndexed: highlightIndex }
  }

  function getDirectText(el) {
    // 只取直接子文本节点（不递归，避免抓到后代按钮的文字）
    let text = ''
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent
      }
    }
    return text.trim()
  }

  function pickAttrs(el) {
    // 选取对 LLM 有用的属性
    const attrs = {}
    const interesting = ['href', 'placeholder', 'aria-label', 'title', 'type',
                         'name', 'value', 'role', 'alt', 'src', 'for', 'id']
    for (const attr of interesting) {
      const v = el.getAttribute(attr)
      if (v) attrs[attr] = v.substring(0, 80)
    }
    return attrs
  }

  function getXPath(el) {
    if (el.id) return `//*[@id="${el.id}"]`
    const parts = []
    while (el && el.nodeType === Node.ELEMENT_NODE && el !== document.body) {
      let index = 1
      let sibling = el.previousElementSibling
      while (sibling) {
        if (sibling.tagName === el.tagName) index++
        sibling = sibling.previousElementSibling
      }
      parts.unshift(`${el.tagName.toLowerCase()}[${index}]`)
      el = el.parentElement
    }
    return '/html/body/' + parts.join('/')
  }

  // ===== 序列化为文本（给 LLM 看的格式）=====
  function serializeOutline(selectorMap, options) {
    const lines = []
    const maxLen = options.maxTextLen || 8000

    const indices = Object.keys(selectorMap).map(Number).sort((a, b) => a - b)

    for (const idx of indices) {
      const info = selectorMap[idx]
      const attrsStr = formatAttrs(info.attrs)
      const textStr = info.text ? ` ${info.text}` : ''
      lines.push(`[${idx}]<${info.tag}${attrsStr}>${textStr}`)

      if (lines.join('\n').length > maxLen) {
        lines.push(`... (truncated, ${indices.length - lines.length} more elements)`)
        break
      }
    }

    return lines.join('\n')
  }

  function formatAttrs(attrs) {
    const entries = Object.entries(attrs)
    if (!entries.length) return ''
    return ' ' + entries.map(([k, v]) => `${k}="${v}"`).join(' ')
  }

  // ===== 页面信息（滚动状态、尺寸）=====
  function getPageInfo() {
    const vh = window.innerHeight
    const ph = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
    const sy = window.scrollY
    return {
      url: location.href,
      title: document.title,
      viewport: { width: window.innerWidth, height: vh },
      page: { width: document.documentElement.scrollWidth, height: ph },
      scroll: {
        y: sy,
        pixelsBelow: Math.max(0, ph - (vh + sy)),
        pagesBelow: vh > 0 ? Math.max(0, ph - (vh + sy)) / vh : 0,
        total: vh > 0 ? ph / vh : 0
      }
    }
  }

  // ===== 主入口 =====
  /**
   * 获取页面 DOM 大纲
   * @param {Object} options
   *   - maxElements: int    最大编号元素数（默认 80）
   *   - viewportOnly: bool  只扫视口内（默认 true，避免大页面爆炸）
   *   - maxTextLen: int     文本输出最大长度（默认 8000）
   * @returns {Object} { text, selectorMap, pageInfo, totalIndexed }
   */
  function getDOMOutline(options = {}) {
    cache.boundingRects = new WeakMap()
    cache.computedStyles = new WeakMap()

    const opts = {
      maxElements: options.maxElements || 80,
      viewportOnly: options.viewportOnly !== false,
      maxTextLen: options.maxTextLen || 8000,
      blacklist: options.blacklist || [],
      whitelist: options.whitelist || []
    }

    // 临时 monkey-patch 检查器：超过 maxElements 停止编号
    const original = buildFlatTree
    const result = (function () {
      // 我们在 buildFlatTree 里没法提前停，改在这里做：先 build，再 trim
      const r = original(opts)
      // 保留前 maxElements 个
      const trimmedMap = {}
      let count = 0
      for (const k of Object.keys(r.selectorMap).map(Number).sort((a, b) => a - b)) {
        if (count >= opts.maxElements) {
          // 清理超出部分的 refMap
          delete global._tmw_outline_map[k]
          continue
        }
        trimmedMap[k] = r.selectorMap[k]
        count++
      }
      r.selectorMap = trimmedMap
      return r
    })()

    const text = serializeOutline(result.selectorMap, opts)
    const pageInfo = getPageInfo()

    return {
      text,
      selectorMap: result.selectorMap,
      pageInfo,
      totalIndexed: Object.keys(result.selectorMap).length
    }
  }

  // 暴露到全局
  global.getDOMOutline = getDOMOutline
  global._tmw_outline_map = global._tmw_outline_map || {}

  // 工具函数：通过索引获取元素（供 tmwebdriver 调用）
  global._tmw_get_element_by_index = function (idx) {
    return global._tmw_outline_map[idx] || null
  }

  /**
   * 提取元素的稳定选择器信息（多 fallback）
   * 用于沉淀成 site_skill，下次免扫描
   * @returns {Object} {
   *   tag, id, text, role, ariaLabel, placeholder, name, type, href,
   *   dataTestId, xpath, selectors: [...], bestSelector: 'xxx'
   * }
   */
  global._tmw_get_element_selector = function (idx) {
    const el = global._tmw_outline_map[idx]
    if (!el) return null

    const tag = el.tagName.toLowerCase()
    const id = el.id || ''
    const text = (getDirectText(el) || '').substring(0, 40)
    const role = el.getAttribute('role') || ''
    const ariaLabel = el.getAttribute('aria-label') || ''
    const placeholder = el.getAttribute('placeholder') || ''
    const name = el.getAttribute('name') || ''
    const type = el.getAttribute('type') || ''
    const href = (el.getAttribute('href') || '').substring(0, 120)
    const dataTestId = el.getAttribute('data-testid') || el.getAttribute('data-test') || ''
    const className = el.className && typeof el.className === 'string'
      ? el.className.split(/\s+/).filter(Boolean).slice(0, 3) : []
    const xpath = getXPath(el)

    // 生成候选选择器（按稳定性从高到低）
    const selectors = []
    if (id && /^[a-zA-Z][\w-]*$/.test(id)) selectors.push(`#${id}`)
    if (dataTestId) selectors.push(`[data-testid="${dataTestId}"]`)
    if (tag === 'input' || tag === 'textarea') {
      if (placeholder) selectors.push(`${tag}[placeholder="${placeholder}"]`)
      if (name) selectors.push(`${tag}[name="${name}"]`)
      if (type) selectors.push(`${tag}[type="${type}"]`)
    }
    if (ariaLabel) selectors.push(`[aria-label="${ariaLabel}"]`)
    if (role) selectors.push(`[role="${role}"]`)
    // 对 <a>，href 最稳
    if (tag === 'a' && href) {
      // 用 href 的 pathname（去掉 query 参数）
      try {
        const hrefPath = new URL(href, location.href).pathname
        if (hrefPath && hrefPath.length > 1) selectors.push(`a[href*="${hrefPath}"]`)
      } catch {}
    }
    // 自己的文字（短文字才稳）
    if (text && text.length <= 20) selectors.push(`${tag}="${text}"`)
    // 父级元素的文字（对 a>span 结构很有用）
    if (!text && el.parentElement) {
      const parentText = (getDirectText(el.parentElement) || '').substring(0, 20)
      if (parentText && parentText.length <= 20) selectors.push(`${tag}:has(> *:contains("${parentText}"))`)
    }
    selectors.push(`xpath:${xpath}`)

    return {
      tag, id, text, role, ariaLabel, placeholder, name, type, href,
      dataTestId, className, xpath,
      selectors,
      bestSelector: selectors[0]
    }
  }

})(typeof window !== 'undefined' ? window : this)
