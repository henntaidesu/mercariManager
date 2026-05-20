/**
 * 管理番号 5 进制暗号：-=~<> 对应 0–4（低位在前）。
 * 与 backend/src/operation_mercari/mgmt_id_cipher.py 保持一致。
 */

export const MGMT_CIPHER_ALPHABET = '-=~<>'

const CIPHER_CHAR_SET = new Set(MGMT_CIPHER_ALPHABET.split(''))
const CIPHER_TOKEN_RE = /^([-=~<>]+)(?:\s*[*xX×]\s*(\d+))?$/u

export function encodeMgmtId(value) {
  let n = Number(value)
  if (!Number.isFinite(n) || n < 0) {
    throw new Error('invalid management id')
  }
  n = Math.floor(n)
  if (n === 0) return MGMT_CIPHER_ALPHABET[0]
  const chars = []
  while (n > 0) {
    chars.push(MGMT_CIPHER_ALPHABET[n % 5])
    n = Math.floor(n / 5)
  }
  return chars.join('')
}

export function decodeMgmtIdCipher(token) {
  const s = String(token || '').trim()
  if (!s || [...s].some((c) => !CIPHER_CHAR_SET.has(c))) return null
  let n = 0
  let mult = 1
  for (const c of s) {
    n += MGMT_CIPHER_ALPHABET.indexOf(c) * mult
    mult *= 5
  }
  return n > 0 ? n : null
}

export function encodeMgmtIds(ids, sep = '、') {
  const parts = []
  for (const raw of ids || []) {
    const n = Number(raw)
    if (Number.isFinite(n) && n > 0) parts.push(encodeMgmtId(n))
  }
  return parts.join(sep)
}

function splitCipherChunks(segment) {
  return String(segment || '')
    .split(/[,，、\s]+/)
    .map((p) => p.trim())
    .filter(Boolean)
}

function cipherTokenBaseAndQty(token) {
  const t = String(token || '').trim()
  if (!t) return { base: '', qty: 1 }
  const m = t.match(CIPHER_TOKEN_RE)
  if (!m) return { base: '', qty: 1 }
  const base = (m[1] || '').trim()
  const qraw = (m[2] || '').trim()
  if (!qraw) return { base, qty: 1 }
  const q = parseInt(qraw, 10)
  return { base, qty: Number.isFinite(q) && q > 0 ? q : 1 }
}

export function isCipherMgmtLine(line) {
  const s = String(line || '').trim()
  if (!s) return false
  if (/管理\s*(?:ID|番号)\s*[:：]/iu.test(s)) return false
  if (/バーコード\s*[:：]/u.test(s)) return false
  let hasToken = false
  for (const part of splitCipherChunks(s)) {
    const { base } = cipherTokenBaseAndQty(part)
    if (!base || [...base].some((c) => !CIPHER_CHAR_SET.has(c))) return false
    hasToken = true
  }
  return hasToken
}

/** 从说明最末非空行解析暗号管理番号，返回 [{ id, quantity }] */
export function parseTrailingCipherMgmtIds(text) {
  const s = String(text ?? '').trim()
  if (!s) return []
  const lines = s.split(/\r?\n/)
  let lastLine = ''
  for (let i = lines.length - 1; i >= 0; i--) {
    const t = String(lines[i] || '').trim()
    if (t) {
      lastLine = t
      break
    }
  }
  if (!lastLine || !isCipherMgmtLine(lastLine)) return []
  const out = []
  for (const part of splitCipherChunks(lastLine)) {
    const { base, qty } = cipherTokenBaseAndQty(part)
    if (!base) continue
    const id = decodeMgmtIdCipher(base)
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
