/**
 * 从文本中提取经纬度坐标点
 * 支持多种中文/英文经纬度格式
 */

export interface GeoPoint {
  name: string
  lng: number  // 经度
  lat: number  // 纬度
  raw: string  // 原始匹配文本
}

/**
 * 将度分秒转换为十进制度数
 */
function dmsToDecimal(d: number, m: number, s: number, direction: string): number {
  let decimal = d + m / 60 + s / 3600
  if (direction === 'S' || direction === 'W' || direction === '南' || direction === '西') {
    decimal = -decimal
  }
  return parseFloat(decimal.toFixed(6))
}

/**
 * 解析单组 DMS 格式: 39°54′24″N 或 北纬39°54′
 */
function parseDMS(text: string): { value: number; rest: string } | null {
  let m: RegExpMatchArray | null

  // 中文度分秒/十进制: 从文本提取方向前缀 + 数字序列，兼容任意度/分/秒分隔符
  // 注意: 数字序列中的 \S+ 不能跨越范围分隔符（至/到/～），否则会把范围结束值也吞进去
  const dirMatch = text.match(/^([北南东西])(纬|经)(\s*\d+(?:[^\u81f3至到～，,、。\s]*\d+)*)/)
  if (dirMatch) {
    const direction = dirMatch[1]
    const nums = dirMatch[3].match(/\d+(?:\.\d+)?/g)
    if (nums && nums.length >= 1) {
      const d = parseFloat(nums[0])
      if (nums.length >= 2) {
        // 度分秒格式: 39°54′24″
        const m = parseFloat(nums[1])
        const s = nums.length >= 3 ? parseFloat(nums[2]) : 0
        return {
          value: dmsToDecimal(d, m, s, direction),
          rest: text.slice(dirMatch[0].length),
        }
      } else {
        // 十进制格式: 39.9°
        const v = (direction === '南' || direction === '西') ? -d : d
        return {
          value: parseFloat(v.toFixed(6)),
          rest: text.slice(dirMatch[0].length),
        }
      }
    }
  }
  // 英文: 39°54′24″N
  m = text.match(/(\d+)\s*[°]\s*(\d+)\s*[′]\s*(\d+)\s*[″]\s*([NSEW])/i)
  if (m) {
    return { value: dmsToDecimal(+m[1], +m[2], +m[3], m[4]), rest: text.slice(m[0].length) }
  }
  m = text.match(/(\d+)\s*[°]\s*(\d+)\s*[′]\s*([NSEW])/i)
  if (m) {
    return { value: dmsToDecimal(+m[1], +m[2], 0, m[3]), rest: text.slice(m[0].length) }
  }
  // 简化: 39°54'N
  m = text.match(/(\d+)\s*[°]\s*(\d+)\s*[']\s*([NSEW])/i)
  if (m) {
    return { value: dmsToDecimal(+m[1], +m[2], 0, m[3]), rest: text.slice(m[0].length) }
  }
  // 回退: 纯 DMS 数字无方向标识 (范围结束值, 如 "41°03′", "117°30′")
  m = text.match(/^(\d+)\s*[°]\s*(\d+)\s*[′](?:\s*(\d+)\s*[″])?/)
  if (m) {
    const d = parseInt(m[1])
    const min = parseInt(m[2])
    const s = m[3] ? parseInt(m[3]) : 0
    return { value: d + min / 60 + s / 3600, rest: text.slice(m[0].length) }
  }
  return null
}

/**
 * 解析十进制格式: 39.9°N / 39.9 / N39.9
 */
function parseDecimal(text: string): { value: number; rest: string } | null {
  let m = text.match(/(\d+\.?\d*)\s*[°]\s*([NSEW])/i)
  if (m) {
    const v = parseFloat(m[1])
    const dir = m[2].toUpperCase()
    return { value: dir === 'S' || dir === 'W' ? -v : v, rest: text.slice(m[0].length) }
  }
  return null
}

/**
 * 从文本中提取所有经纬度坐标点
 * 支持格式:
 *   "北纬39°54′，东经116°23′"       — 中文 DMS
 *   "39.9°N, 116.4°E"                — 英文小数
 *   "(39.9042, 116.4074)"            — 纯小数对
 *   "纬度39.9，经度116.4"             — 中文小数
 *   "39°54′24″N, 116°23′30″E"       — 英文 DMS
 */
function normalizeText(text: string): string {
  // 统一度符号: °(U+00B0) 各种变体 → °
  return text
    .replace(/[º˚]/g, '°')
    // 统一分符号: ′(U+2032) ' ' 各种变体 → ′
    .replace(/['\u2018\u2019\u201B\u2035\u02B9\u0374]/g, '\u2032')
    // 统一秒符号: ″(U+2033) " " 各种变体 → ″
    .replace(/["\u201C\u201D\u2036\u02BA]/g, '\u2033')
}

function findPlaceName(normalized: string, matchIndex: number, matchLength: number): string {
  const ctxStart = Math.max(0, matchIndex - 30)
  const ctxEnd = Math.min(normalized.length, matchIndex + matchLength + 30)
  const ctx = normalized.slice(ctxStart, ctxEnd)
  const nameMatch = ctx.match(/([\u4e00-\u9fa5]{2,8})(?:的|位于|[经伟]度|[坐]标|地理)/)
  return nameMatch ? nameMatch[1] : ''
}

export function extractCoordinates(text: string): GeoPoint[] {
  const points: GeoPoint[] = []
  const normalized = normalizeText(text)

  // --- 模式0: 中文 DMS 范围格式 "北纬39°26′至41°03′、东经115°25′至117°30′" ---
  const cnRangeRegex = /([北南]纬[^\u81f3至到～\n]+)[\u81f3至到～]([^\u81f3至到～，,、。\n]+)[，,、\s]+([东西]经[^\u81f3至到～\n]+)[\u81f3至到～]([^\u81f3至到～，,、。\n]*)/g
  let match: RegExpExecArray | null
  while ((match = cnRangeRegex.exec(normalized)) !== null) {
    const lat1 = parseDMS(match[1])
    const lat2 = lat1 ? parseDMS(match[2]) : null
    const lng1 = lat2 ? parseDMS(match[3]) : null
    const lng2 = lng1 ? parseDMS(match[4]) : null
    if (lat1 && lat2 && lng1 && lng2) {
      const name = findPlaceName(normalized, match.index, match[0].length) || `区域${points.length + 1}`
      // 范围结束值继承起始值的方向符号 (回退解析的纯数字总是正数)
      const lat2Signed = lat1.value >= 0 ? Math.abs(lat2.value) : -Math.abs(lat2.value)
      const lng2Signed = lng1.value >= 0 ? Math.abs(lng2.value) : -Math.abs(lng2.value)
      const centerLat = (lat1.value + lat2Signed) / 2
      const centerLng = (lng1.value + lng2Signed) / 2
      points.push({
        name,
        lat: parseFloat(centerLat.toFixed(6)),
        lng: parseFloat(centerLng.toFixed(6)),
        raw: match[0],
      })
    }
  }

  // --- 模式1: 中文 DMS 格式 "北纬XX°XX′，东经XX°XX′" ---
  // 排除范围分隔符，避免把范围文本误解析为单个点
  const cnDmsRegex = /([北南]纬[^\u81f3至到～，,、。\n]*)[，,、\s]+([东西]经[^\u81f3至到～，,、。\n]*)/g
  while ((match = cnDmsRegex.exec(normalized)) !== null) {
    const latResult = parseDMS(match[1])
    const lngResult = latResult ? parseDMS(match[2]) : null
    if (latResult && lngResult) {
      const name = findPlaceName(normalized, match.index, match[0].length) || `坐标点${points.length + 1}`

      const isDup = points.some(p => Math.abs(p.lat - latResult.value) < 0.5 && Math.abs(p.lng - lngResult.value) < 0.5)
      if (!isDup) {
        points.push({
          name,
          lat: latResult.value,
          lng: lngResult.value,
          raw: match[0],
        })
      }
    }
  }

  // --- 模式2: 英文 DMS 格式 "39°54′24″N, 116°23′30″E" ---
  const enDmsRegex = /(\d+\s*[°]\s*\d+\s*[′]\s*(?:\d+\s*[″])?\s*[NS])\s*[，,、\s]+\s*(\d+\s*[°]\s*\d+\s*[′]\s*(?:\d+\s*[″])?\s*[EW])/gi
  while ((match = enDmsRegex.exec(normalized)) !== null) {
    const latResult = parseDMS(match[1])
    const lngResult = latResult ? parseDMS(match[2]) : null
    if (latResult && lngResult) {
      const isDup = points.some(p => Math.abs(p.lat - latResult.value) < 0.5 && Math.abs(p.lng - lngResult.value) < 0.5)
      if (!isDup) {
        points.push({
          name: `坐标点${points.length + 1}`,
          lat: latResult.value,
          lng: lngResult.value,
          raw: match[0],
        })
      }
    }
  }

  // --- 模式3: 英文小数格式 "39.9°N, 116.4°E" ---
  const enDecRegex = /(\d+\.?\d*\s*[°]\s*[NS])\s*[，,、\s]+\s*(\d+\.?\d*\s*[°]\s*[EW])/gi
  while ((match = enDecRegex.exec(normalized)) !== null) {
    const latResult = parseDecimal(match[1])
    const lngResult = latResult ? parseDecimal(match[2]) : null
    if (latResult && lngResult) {
      const isDup = points.some(p => Math.abs(p.lat - latResult.value) < 0.5 && Math.abs(p.lng - lngResult.value) < 0.5)
      if (!isDup) {
        points.push({
          name: `坐标点${points.length + 1}`,
          lat: latResult.value,
          lng: lngResult.value,
          raw: match[0],
        })
      }
    }
  }

  // --- 模式4: 纯小数对 "(39.9042, 116.4074)" 或 "39.9042, 116.4074" ---
  const pureDecRegex = /\(?\s*(-?\d{1,3}\.\d+)\s*[，,、\s]\s*(-?\d{1,3}\.\d+)\s*\)?/g
  pureDecRegex.lastIndex = 0
  while ((match = pureDecRegex.exec(normalized)) !== null) {
    const a = parseFloat(match[1])
    const b = parseFloat(match[2])
    let lat: number, lng: number
    if (a >= 15 && a <= 55 && b >= 70 && b <= 140) {
      lat = a; lng = b
    } else if (b >= 15 && b <= 55 && a >= 70 && a <= 140) {
      lat = b; lng = a
    } else if (a >= -90 && a <= 90 && b >= -180 && b <= 180) {
      lat = a; lng = b
    } else {
      continue
    }
    const raw = match[0]
    if (raw.includes('°') || raw.includes('′')) continue
    const isDup = points.some(p => Math.abs(p.lat - lat) < 0.5 && Math.abs(p.lng - lng) < 0.5)
    if (!isDup) {
      points.push({ name: `坐标点${points.length + 1}`, lat, lng, raw })
    }
  }

  // --- 模式5: 中文小数 "纬度39.9，经度116.4" ---
  const cnDecRegex = /纬度\s*(\d+\.?\d*)\s*[，,、\s]+\s*经度\s*(\d+\.?\d*)/g
  while ((match = cnDecRegex.exec(normalized)) !== null) {
    const lat = parseFloat(match[1])
    const lng = parseFloat(match[2])
    const isDup = points.some(p => Math.abs(p.lat - lat) < 0.5 && Math.abs(p.lng - lng) < 0.5)
    if (!isDup) {
      points.push({ name: `坐标点${points.length + 1}`, lat, lng, raw: match[0] })
    }
  }

  return points
}
