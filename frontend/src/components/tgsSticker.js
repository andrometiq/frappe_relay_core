// Telegram TGS is bounded gzip-compressed Lottie vector data. Rendering uses the
// expression-free light canvas player; no assets, scripts or fonts are loaded.
// https://core.telegram.org/stickers#animated-stickers-and-emoji
export const MAX_TGS_BYTES = 2 * 1024 * 1024
const MAX_NODES = 50000, MAX_LAYERS = 100, MAX_DEPTH = 32
const fail = () => { throw new Error('Animated sticker is invalid or exceeds supported limits') }

export function validateTgs(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.v !== 'string' || !/^\d+\.\d+\.\d+$/u.test(data.v) || data.w !== 512 || data.h !== 512 ||
      !Number.isFinite(data.fr) || data.fr < 1 || data.fr > 60 || !Number.isFinite(data.ip) ||
      !Number.isFinite(data.op) || data.ip < 0 || data.op <= data.ip || data.op - data.ip > 180 ||
      (data.op - data.ip) / data.fr > 3 || !Array.isArray(data.layers)) fail()
  const pending = [[data, 0]], assets = new Map(), layerSets = [data.layers], layerCosts = new WeakMap()
  let nodes = 0, layers = 0
  if (data.assets !== undefined && !Array.isArray(data.assets)) fail()
  for (const asset of data.assets || []) {
    if (!asset || typeof asset.id !== 'string' || !asset.id || assets.has(asset.id) || !Array.isArray(asset.layers) ||
        ['p', 'u', 'e', 't'].some(key => key in asset)) fail()
    assets.set(asset.id, asset.layers); layerSets.push(asset.layers)
  }
  const sourceCost = layer => {
    let count = 0
    const stack = [layer]
    while (stack.length) {
      const value = stack.pop()
      if (++count > MAX_NODES) fail()
      if (value && typeof value === 'object') for (const child of Object.values(value)) stack.push(child)
    }
    return count
  }
  const checkLayers = list => {
    for (const layer of list) {
      if (!layer || ![0, 3, 4].includes(layer.ty) || ++layers > MAX_LAYERS || layer.ddd ||
          (layer.refId !== undefined && !assets.has(layer.refId))) fail()
      layerCosts.set(layer, sourceCost(layer))
    }
  }
  layerSets.forEach(checkLayers)
  // Cyclic/nested precompositions can blow up a renderer despite a small JSON.
  let precompVisits = 0, expandedCost = 0
  const visit = (list, ancestors = new Set(), depth = 0) => {
    if (depth > 8 || ++precompVisits > 1000) fail()
    for (const layer of list) {
      expandedCost += layerCosts.get(layer)
      if (expandedCost > MAX_NODES) fail()
      if (!layer.refId) continue
      if (ancestors.has(layer.refId)) fail()
      visit(assets.get(layer.refId), new Set([...ancestors, layer.refId]), depth + 1)
    }
  }
  visit(data.layers)
  while (pending.length) {
    const [value, depth] = pending.pop()
    if (++nodes > MAX_NODES || depth > MAX_DEPTH) fail()
    if (typeof value === 'number' && (!Number.isFinite(value) || Math.abs(value) > 1000000)) fail()
    if (typeof value === 'string' && (value.length > 2048 || /[<>\x00]/u.test(value))) fail()
    if (Array.isArray(value)) {
      if (value.length > 4096) fail()
      for (const child of value) pending.push([child, depth + 1])
    } else if (value && typeof value === 'object') {
      if (['rp', 'mm', 'sr', 'gs'].includes(value.ty)) fail()
      for (const [key, child] of Object.entries(value)) {
        if (['__proto__', 'prototype', 'constructor', 'fonts', 'chars', 'ef', 'masksProperties', 'tm'].includes(key) ||
            (key === 'x' && typeof child === 'string') || (['p', 'u'].includes(key) && typeof child === 'string')) fail()
        pending.push([child, depth + 1])
      }
    }
  }
  return data
}

export async function boundedBytes(stream, limit = MAX_TGS_BYTES, signal) {
  if (!stream?.getReader) throw new Error('Streaming sticker download is unavailable')
  const reader = stream.getReader(), chunks = []
  let size = 0
  const abort = () => { void reader.cancel().catch(() => {}) }
  signal?.addEventListener('abort', abort, { once: true })
  try {
    while (true) {
      signal?.throwIfAborted()
      const { done, value } = await reader.read()
      signal?.throwIfAborted()
      if (done) break
      size += value.byteLength
      if (size > limit) { await reader.cancel(); fail() }
      chunks.push(value)
    }
  } finally { signal?.removeEventListener('abort', abort); reader.releaseLock() }
  const result = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength }
  return result
}

export async function decodeTgs(bytes, signal) {
  if (!(bytes instanceof Uint8Array) || bytes.length > MAX_TGS_BYTES || bytes[0] !== 0x1f || bytes[1] !== 0x8b) fail()
  if (typeof DecompressionStream !== 'function') throw new Error('Animated stickers are unavailable in this browser')
  const expanded = await boundedBytes(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')), MAX_TGS_BYTES, signal)
  const text = new TextDecoder('utf-8', { fatal: true }).decode(expanded)
  return validateTgs(JSON.parse(text))
}

export function stickerSource(source, origin) {
  const target = new URL(source, origin)
  if (target.origin !== origin || target.pathname !== '/api/method/relay_core.messaging.sticker' || target.username || target.password || target.hash ||
      [...target.searchParams.keys()].some(key => key !== 'message') || target.searchParams.getAll('message').length !== 1 ||
      !target.searchParams.get('message') || target.searchParams.get('message').length > 255) fail()
  return target.href
}

export async function fetchTgs(source, signal, { fetcher = fetch, origin = window.location.origin } = {}) {
  const response = await fetcher(stickerSource(source, origin), { credentials: 'same-origin', redirect: 'error', signal })
  if (!response.ok) throw new Error('Animated sticker unavailable')
  const declared = Number(response.headers.get('Content-Length') || 0)
  if (declared > MAX_TGS_BYTES) { await response.body?.cancel(); fail() }
  const bytes = await boundedBytes(response.body, MAX_TGS_BYTES, signal)
  return decodeTgs(bytes, signal)
}
