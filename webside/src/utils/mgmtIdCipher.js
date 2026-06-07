/**
 * 管理番号暗号（低位在前），两种编码：
 * - 五进制（默认）：-=~<> 对应 0–4
 * - 二进制：菱形 ◇◆ 对应 0–1（◇=0，◆=1）
 *
 * 当前编码模式记录在后端 config 表（隐藏页 /x9 切换），启动时拉取并 setCipherMode()。
 * 编码与解析都**严格按当前模式**：选了五进制就只按五进制解析（非兼容解析）。
 * 与 backend/src/use_mercari/mgmt_id_cipher.py 保持一致。
 */

export const MGMT_CIPHER_ALPHABET = '-=~<>' // 五进制 0–4
export const MGMT_BINARY_ALPHABET = '◇◆' // 二进制 0–1（◇=0，◆=1）

const BASE5_SET = new Set(MGMT_CIPHER_ALPHABET.split(''))
const BINARY_SET = new Set(MGMT_BINARY_ALPHABET.split(''))
const BASE5_TOKEN_RE = /^([-=~<>]+)(?:\s*[*xX×]\s*(\d+))?$/u
const BINARY_TOKEN_RE = /^([◇◆]+)(?:\s*[*xX×]\s*(\d+))?$/u

// 当前编码模式：'binary' | 'base5'（默认 base5）。由 setCipherMode 在启动/切换时更新。
let currentMode = 'base5'

export function setCipherMode(mode) {
  currentMode = String(mode || '').toLowerCase() === 'binary' ? 'binary' : 'base5'
  return currentMode
}

export function getCipherMode() {
  return currentMode
}

function modeSpec(mode) {
  const m = (mode || currentMode) === 'binary' ? 'binary' : 'base5'
  return m === 'binary'
    ? { alphabet: MGMT_BINARY_ALPHABET, base: 2, charset: BINARY_SET, tokenRe: BINARY_TOKEN_RE }
    : { alphabet: MGMT_CIPHER_ALPHABET, base: 5, charset: BASE5_SET, tokenRe: BASE5_TOKEN_RE }
}

export function encodeMgmtId(value, mode = currentMode) {
  let n = Number(value)
  if (!Number.isFinite(n) || n < 0) {
    throw new Error('invalid management id')
  }
  n = Math.floor(n)
  const { alphabet, base } = modeSpec(mode)
  if (n === 0) return alphabet[0]
  const chars = []
  while (n > 0) {
    chars.push(alphabet[n % base])
    n = Math.floor(n / base)
  }
  return chars.join('')
}

export function decodeMgmtIdCipher(token, mode = currentMode) {
  const s = String(token || '').trim()
  if (!s) return null
  const { alphabet, base, charset } = modeSpec(mode)
  if ([...s].some((c) => !charset.has(c))) return null
  let n = 0
  let mult = 1
  for (const c of s) {
    n += alphabet.indexOf(c) * mult
    mult *= base
  }
  return n > 0 ? n : null
}

export function encodeMgmtIds(ids, sep = '、') {
  const mode = currentMode
  const parts = []
  for (const raw of ids || []) {
    const n = Number(raw)
    if (Number.isFinite(n) && n > 0) parts.push(encodeMgmtId(n, mode))
  }
  return parts.join(sep)
}

function splitCipherChunks(segment) {
  return String(segment || '')
    .split(/[,，、\s]+/)
    .map((p) => p.trim())
    .filter(Boolean)
}

function cipherTokenBaseAndQty(token, mode) {
  const t = String(token || '').trim()
  if (!t) return { base: '', qty: 1 }
  const { tokenRe } = modeSpec(mode)
  const m = t.match(tokenRe)
  if (!m) return { base: '', qty: 1 }
  const base = (m[1] || '').trim()
  const qraw = (m[2] || '').trim()
  if (!qraw) return { base, qty: 1 }
  const q = parseInt(qraw, 10)
  return { base, qty: Number.isFinite(q) && q > 0 ? q : 1 }
}

export function isCipherMgmtLine(line, mode = currentMode) {
  const s = String(line || '').trim()
  if (!s) return false
  if (/管理\s*(?:ID|番号)\s*[:：]/iu.test(s)) return false
  if (/バーコード\s*[:：]/u.test(s)) return false
  const { charset } = modeSpec(mode)
  let hasToken = false
  for (const part of splitCipherChunks(s)) {
    const { base } = cipherTokenBaseAndQty(part, mode)
    if (!base || [...base].some((c) => !charset.has(c))) return false
    hasToken = true
  }
  return hasToken
}

/** 从说明最末非空行解析暗号管理番号（严格按当前模式），返回 [{ id, quantity }] */
export function parseTrailingCipherMgmtIds(text) {
  const s = String(text ?? '').trim()
  if (!s) return []
  const mode = currentMode
  const lines = s.split(/\r?\n/)
  let lastLine = ''
  for (let i = lines.length - 1; i >= 0; i--) {
    const t = String(lines[i] || '').trim()
    if (t) {
      lastLine = t
      break
    }
  }
  if (!lastLine || !isCipherMgmtLine(lastLine, mode)) return []
  const out = []
  for (const part of splitCipherChunks(lastLine)) {
    const { base, qty } = cipherTokenBaseAndQty(part, mode)
    if (!base) continue
    const id = decodeMgmtIdCipher(base, mode)
    if (id != null) out.push({ id, quantity: qty })
  }
  return out
}

/** 合并去重后的管理番号 id 列表（仅 id，不含数量） */
export function parseMgmtIdsFromDescription(text) {
  const ids = []
  const seen = new Set()
  for (const { id } of parseTrailingCipherMgmtIds(text)) {
    if (!seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }
  return ids
}

export function stripTrailingMgmtBlock(text) {
  let s = String(text || '')
  let prev = null
  while (prev !== s) {
    prev = s
    s = s.replace(/(?:\n{1,2})?管理番号[:：][\d、,，\s]+$/u, '').trimEnd()
  }
  const lines = s.split(/\r?\n/)
  while (lines.length) {
    const last = String(lines[lines.length - 1] || '').trim()
    if (!last) {
      lines.pop()
      continue
    }
    if (isCipherMgmtLine(last)) {
      lines.pop()
      continue
    }
    break
  }
  return lines.join('\n').trimEnd()
}
