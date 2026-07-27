'use strict'

/*
 * One-shot compatibility host for LX Music custom-source scripts.
 *
 * The parent sends one JSON request over stdin. The source runs in a fresh VM
 * context with no `require` or `process` binding and the process exits after
 * initialization or one URL-resolution request.
 */

const crypto = require('crypto')
const vm = require('vm')
const zlib = require('zlib')

const MAX_RESPONSE_BYTES = 8 * 1024 * 1024
const EVENT_NAMES = Object.freeze({
  request: 'request',
  inited: 'inited',
  updateAlert: 'updateAlert',
})

const readInput = async() => {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

const withTimeout = (promise, milliseconds, message) => Promise.race([
  promise,
  new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), milliseconds)
    timer.unref()
  }),
])

const isBlockedHost = (hostname) => {
  const host = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '')
  if (['localhost', '0.0.0.0', '::1'].includes(host)) return true
  if (/^127\./.test(host) || /^169\.254\./.test(host)) return true
  if (/^10\./.test(host) || /^192\.168\./.test(host)) return true
  const match = host.match(/^172\.(\d+)\./)
  return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31)
}

const requestFromSource = (urlValue, options = {}, callback) => {
  const controller = new AbortController()
  let finished = false
  const finish = (...args) => {
    if (finished) return
    finished = true
    callback(...args)
  }
  ;(async() => {
    const url = new URL(String(urlValue))
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error('音源只能访问 HTTP 或 HTTPS 地址')
    }
    if (isBlockedHost(url.hostname)) {
      throw new Error('音源不能访问本机或局域网地址')
    }
    const method = String(options.method || 'get').toUpperCase()
    const headers = { ...(options.headers || {}) }
    let body = options.body
    if (options.form && typeof options.form === 'object') {
      body = new URLSearchParams(options.form).toString()
      if (!Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
      }
    }
    const timeout = Math.max(
      1000,
      Math.min(60000, Number(options.timeout) || 20000),
    )
    const timer = setTimeout(() => controller.abort(), timeout)
    let response
    try {
      response = await fetch(url, {
        method,
        headers,
        body: ['GET', 'HEAD'].includes(method) ? undefined : body,
        redirect: 'follow',
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timer)
    }
    if (isBlockedHost(new URL(response.url).hostname)) {
      throw new Error('音源请求被重定向到了受限地址')
    }
    const declaredSize = Number(response.headers.get('content-length') || 0)
    if (declaredSize > MAX_RESPONSE_BYTES) {
      throw new Error('音源接口返回的数据过大')
    }
    const raw = Buffer.from(await response.arrayBuffer())
    if (raw.length > MAX_RESPONSE_BYTES) {
      throw new Error('音源接口返回的数据过大')
    }
    const text = raw.toString('utf8')
    let parsedBody = text
    try {
      parsedBody = JSON.parse(text)
    } catch (_) {}
    const responseHeaders = {}
    response.headers.forEach((value, key) => {
      responseHeaders[key] = value
    })
    const result = {
      statusCode: response.status,
      statusMessage: response.statusText,
      headers: responseHeaders,
      bytes: raw.length,
      raw,
      body: parsedBody,
    }
    finish(null, result, parsedBody)
  })().catch(error => finish(error, null, null))
  return () => {
    controller.abort()
    finished = true
  }
}

const createHost = (request) => {
  const events = { request: null }
  let resolveInit
  let rejectInit
  const initialized = new Promise((resolve, reject) => {
    resolveInit = resolve
    rejectInit = reject
  })
  let didInit = false
  const lx = {
    version: '2.0.0',
    env: 'desktop',
    EVENT_NAMES,
    currentScriptInfo: {
      ...request.metadata,
      rawScript: request.script,
    },
    request: requestFromSource,
    on(eventName, handler) {
      if (eventName !== EVENT_NAMES.request || typeof handler !== 'function') {
        return Promise.reject(new Error(`不支持的音源事件：${eventName}`))
      }
      events.request = handler
      return Promise.resolve()
    },
    send(eventName, data) {
      if (eventName === EVENT_NAMES.inited) {
        if (didInit) return Promise.reject(new Error('音源已初始化'))
        didInit = true
        resolveInit(data)
        return Promise.resolve()
      }
      if (eventName === EVENT_NAMES.updateAlert) return Promise.resolve()
      return Promise.reject(new Error(`不支持的音源事件：${eventName}`))
    },
    utils: {
      crypto: {
        aesEncrypt(buffer, mode, key, iv) {
          const cipher = crypto.createCipheriv(mode, key, iv)
          return Buffer.concat([cipher.update(buffer), cipher.final()])
        },
        rsaEncrypt(buffer, key) {
          const padded = Buffer.concat([
            Buffer.alloc(Math.max(0, 128 - buffer.length)),
            buffer,
          ])
          return crypto.publicEncrypt({
            key,
            padding: crypto.constants.RSA_NO_PADDING,
          }, padded)
        },
        randomBytes(size) {
          return crypto.randomBytes(size)
        },
        md5(value) {
          return crypto.createHash('md5').update(String(value)).digest('hex')
        },
      },
      buffer: {
        from(...args) {
          return Buffer.from(...args)
        },
        bufToString(buffer, format) {
          return Buffer.from(buffer, 'binary').toString(format)
        },
      },
      zlib: {
        inflate(buffer) {
          return new Promise((resolve, reject) => {
            zlib.inflate(buffer, (error, value) => {
              if (error) reject(error)
              else resolve(value)
            })
          })
        },
        deflate(buffer) {
          return new Promise((resolve, reject) => {
            zlib.deflate(buffer, (error, value) => {
              if (error) reject(error)
              else resolve(value)
            })
          })
        },
      },
    },
  }
  return { lx, events, initialized, rejectInit }
}

const normalizeInit = (value) => {
  if (!value || typeof value !== 'object' || !value.sources) {
    throw new Error('脚本没有返回有效的 LX 音源信息')
  }
  const sources = {}
  const allowedSources = new Set(['kw', 'kg', 'tx', 'wy', 'mg', 'local'])
  const allowedQualities = new Set(['128k', '320k', 'flac', 'flac24bit'])
  for (const [key, source] of Object.entries(value.sources)) {
    if (!allowedSources.has(key) || !source || source.type !== 'music') continue
    sources[key] = {
      name: String(source.name || key).slice(0, 40),
      actions: Array.isArray(source.actions)
        ? source.actions.filter(action => ['musicUrl', 'lyric', 'pic'].includes(action))
        : [],
      qualitys: Array.isArray(source.qualitys)
        ? source.qualitys.filter(quality => allowedQualities.has(quality))
        : [],
    }
  }
  if (!Object.keys(sources).length) {
    throw new Error('脚本没有提供可用的音乐平台')
  }
  return { sources }
}

const main = async() => {
  const request = await readInput()
  if (typeof request.script !== 'string' || request.script.length > 4 * 1024 * 1024) {
    throw new Error('JS 音源文件无效或超过 4 MB')
  }
  const host = createHost(request)
  const silentConsole = Object.freeze({
    log() {},
    info() {},
    warn() {},
    error() {},
    debug() {},
  })
  const sandbox = {
    lx: host.lx,
    console: silentConsole,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    AbortController,
    atob: value => Buffer.from(String(value), 'base64').toString('binary'),
    btoa: value => Buffer.from(String(value), 'binary').toString('base64'),
    navigator: { userAgent: 'Mozilla/5.0 Echovault LXSourceHost/1.0' },
    location: { href: 'https://localhost/' },
  }
  sandbox.globalThis = sandbox
  sandbox.window = sandbox
  sandbox.document = {
    getElementsByTagName(name) {
      return name === 'script'
        ? [Object.freeze({ innerText: request.script })]
        : []
    },
  }
  const context = vm.createContext(sandbox, {
    codeGeneration: { strings: true, wasm: false },
  })
  try {
    new vm.Script(request.script, {
      filename: 'lx-custom-source.js',
    }).runInContext(context, { timeout: 5000 })
  } catch (error) {
    host.rejectInit(error)
    throw error
  }
  const initialized = normalizeInit(
    await withTimeout(host.initialized, 20000, '等待音源初始化超时'),
  )
  if (request.action === 'inspect') return initialized
  if (request.action !== 'resolve') throw new Error('未知的音源操作')
  if (typeof host.events.request !== 'function') {
    throw new Error('脚本没有注册 URL 解析事件')
  }
  const sourceKey = String(request.source_key || '')
  const source = initialized.sources[sourceKey]
  if (!source || !source.actions.includes('musicUrl')) {
    throw new Error('该脚本不支持此平台的歌曲解析')
  }
  const value = host.events.request.call(context, {
    source: sourceKey,
    action: 'musicUrl',
    info: {
      type: request.quality,
      musicInfo: request.music_info,
    },
  })
  const url = await withTimeout(
    Promise.resolve(value),
    25000,
    '等待音源解析歌曲地址超时',
  )
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url) || url.length > 4096) {
    throw new Error('脚本没有返回有效的歌曲地址')
  }
  return { url }
}

main().then(
  value => {
    process.stdout.write(JSON.stringify({ ok: true, value }))
    process.exit(0)
  },
  error => {
    process.stdout.write(JSON.stringify({
      ok: false,
      error: String(error && error.message ? error.message : error),
    }))
    process.exit(1)
  },
)
