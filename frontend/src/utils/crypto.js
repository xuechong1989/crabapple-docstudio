// xuechong 2026-06-26 前端加密工具函数
// 解决 crypto.subtle 在 HTTP 非安全上下文中不可用的问题（localhost 可用，IP 地址不可用）

/**
 * 纯 JavaScript SHA-256 实现（降级方案）
 * 仅在 crypto.subtle 不可用时使用（HTTP 非安全上下文）
 */
// xuechong 2026-06-26 SHA-256 常量表
const K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]

// xuechong 2026-06-26 纯 JS SHA-256 实现
function sha256Pure(message) {
  const rotr = (n, x) => (x >>> n) | (x << (32 - n))
  const ch = (x, y, z) => (x & y) ^ (~x & z)
  const maj = (x, y, z) => (x & y) ^ (x & z) ^ (y & z)
  const sigma0 = (x) => rotr(2, x) ^ rotr(13, x) ^ rotr(22, x)
  const sigma1 = (x) => rotr(6, x) ^ rotr(11, x) ^ rotr(25, x)
  const gamma0 = (x) => rotr(7, x) ^ rotr(18, x) ^ (x >>> 3)
  const gamma1 = (x) => rotr(17, x) ^ rotr(19, x) ^ (x >>> 10)

  // xuechong 2026-06-26 消息填充（SHA-256 要求对齐到 64 字节块）
  // xuechong 2026-06-26 修复填充公式：原公式对小消息（32B）计算 padLen=56，导致 DataView 越界
  const msgLen = message.length
  const bitLen = msgLen * 8
  const padLen = ((msgLen + 72) >>> 6 << 6)
  const padded = new Uint8Array(padLen)
  padded.set(message)
  padded[msgLen] = 0x80
  const view = new DataView(padded.buffer)
  view.setUint32(padLen - 4, bitLen & 0xffffffff, false)
  view.setUint32(padLen - 8, Math.floor(bitLen / 0x100000000), false)

  // xuechong 2026-06-26 初始哈希值
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19

  // xuechong 2026-06-26 处理每个 512 位块
  for (let offset = 0; offset < padLen; offset += 64) {
    const w = new Uint32Array(64)
    for (let i = 0; i < 16; i++) {
      w[i] = view.getUint32(offset + i * 4, false)
    }
    for (let i = 16; i < 64; i++) {
      w[i] = (gamma1(w[i - 2]) + w[i - 7] + gamma0(w[i - 15]) + w[i - 16]) | 0
    }

    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let i = 0; i < 64; i++) {
      const t1 = (h + sigma1(e) + ch(e, f, g) + K[i] + w[i]) | 0
      const t2 = (sigma0(a) + maj(a, b, c)) | 0
      h = g; g = f; f = e; e = (d + t1) | 0
      d = c; c = b; b = a; a = (t1 + t2) | 0
    }

    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0
    h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0
  }

  // xuechong 2026-06-26 输出 32 字节哈希
  const result = new Uint8Array(32)
  const resultView = new DataView(result.buffer)
  resultView.setUint32(0, h0, false); resultView.setUint32(4, h1, false)
  resultView.setUint32(8, h2, false); resultView.setUint32(12, h3, false)
  resultView.setUint32(16, h4, false); resultView.setUint32(20, h5, false)
  resultView.setUint32(24, h6, false); resultView.setUint32(28, h7, false)
  return result
}

// xuechong 2026-06-26 检测 crypto.subtle 是否可用（localhost 视为安全上下文）
const isSecureContext = typeof crypto !== 'undefined' && typeof crypto.subtle !== 'undefined'

/**
 * 安全的多轮 SHA-256 哈希函数
 * 优先使用 crypto.subtle（HTTPS/localhost），降级到纯 JS 实现（HTTP IP 地址）
 * @param {string} password - 原始密码
 * @param {number} rounds - 迭代次数（默认 100000）
 * @returns {Promise<string>} - 十六进制哈希字符串
 */
export async function computePasswordHash(password, rounds = 100000) {
  const encoder = new TextEncoder()
  let hash = encoder.encode(password)

  if (isSecureContext) {
    // xuechong 2026-06-26 安全上下文（HTTPS/localhost）：使用原生 crypto.subtle
    for (let i = 0; i < rounds; i++) {
      hash = new Uint8Array(await crypto.subtle.digest('SHA-256', hash))
    }
  } else {
    // xuechong 2026-06-26 非安全上下文（HTTP IP 地址）：使用纯 JS 实现
    console.warn('[crypto] 非 HTTPS/localhost 环境，使用纯 JavaScript SHA-256（首次可能较慢）')
    for (let i = 0; i < rounds; i++) {
      hash = sha256Pure(hash)
    }
  }

  return Array.from(hash).map(b => b.toString(16).padStart(2, '0')).join('')
}
