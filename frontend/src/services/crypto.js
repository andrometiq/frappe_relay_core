import { sha256 } from '@noble/hashes/sha256'
import { bytesToHex } from '@noble/hashes/utils'

// HTTP development sites do not expose SubtleCrypto or randomUUID.
// Keep the same SHA-256 retry identity on both HTTP and HTTPS.
export function sha256Hex(text) {
  return bytesToHex(sha256(new TextEncoder().encode(text)))
}

export function randomUUID() {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = bytesToHex(bytes)
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`
}
