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
  const dirMatch = text.match(/^([北南东西])(纬|经)(\s*\d+(?:\S+\d+)*)/)
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

export function extractCoordinates(text: string): GeoPoint[] {
  const points: GeoPoint[] = []
  const normalized = normalizeText(text)

  // --- 模式1: 中文 DMS 格式 "北纬XX°XX′，东经XX°XX′" ---
  // 宽松匹配: 北纬/南纬 + 非分隔符文本, 分隔符, 东经/西经 + 非分隔符文本
  const cnDmsRegex = /([北南]纬[^，,、。\n]*)[，,、\s]+([东西]经[^，,、。\n]*)/g
  let match: RegExpExecArray | null
  while ((match = cnDmsRegex.exec(normalized)) !== null) {
    const latResult = parseDMS(match[1])
    const lngResult = latResult ? parseDMS(match[2]) : null
    if (latResult && lngResult) {
      // 匹配名称（括号中的地名）
      const ctxStart = Math.max(0, match.index - 20)
      const ctxEnd = Math.min(normalized.length, match.index + match[0].length + 20)
      const ctx = normalized.slice(ctxStart, ctxEnd)
      const nameMatch = ctx.match(/([\u4e00-\u9fa5]{2,8})(?:的|位于|[经伟]度|[坐]标)/)
      const name = nameMatch ? nameMatch[1] : `坐标点${points.length + 1}`

      points.push({
        name,
        lat: latResult.value,
        lng: lngResult.value,
        raw: match[0],
      })
    }
  }

  // --- 模式2: 英文 DMS 格式 "39°54′24″N, 116°23′30″E" ---
  const enDmsRegex = /(\d+\s*[°]\s*\d+\s*[′]\s*(?:\d+\s*[″])?\s*[NS])\s*[，,、\s]+\s*(\d+\s*[°]\s*\d+\s*[′]\s*(?:\d+\s*[″])?\s*[EW])/gi
  while ((match = enDmsRegex.exec(normalized)) !== null) {
    const latResult = parseDMS(match[1])
    const lngResult = latResult ? parseDMS(match[2]) : null
    if (latResult && lngResult) {
      points.push({
        name: `坐标点${points.length + 1}`,
        lat: latResult.value,
        lng: lngResult.value,
        raw: match[0],
      })
    }
  }

  // --- 模式3: 英文小数格式 "39.9°N, 116.4°E" ---
  const enDecRegex = /(\d+\.?\d*\s*[°]\s*[NS])\s*[，,、\s]+\s*(\d+\.?\d*\s*[°]\s*[EW])/gi
  while ((match = enDecRegex.exec(normalized)) !== null) {
    const latResult = parseDecimal(match[1])
    const lngResult = latResult ? parseDecimal(match[2]) : null
    if (latResult && lngResult) {
      points.push({
        name: `坐标点${points.length + 1}`,
        lat: latResult.value,
        lng: lngResult.value,
        raw: match[0],
      })
    }
  }

  // --- 模式4: 纯小数对 "(39.9042, 116.4074)" 或 "39.9042, 116.4074" ---
  // 经度范围 -180~180，纬度范围 -90~90
  const pureDecRegex = /\(?\s*(-?\d{1,3}\.\d+)\s*[，,、\s]\s*(-?\d{1,3}\.\d+)\s*\)?/g
  // 重置 lastIndex
  pureDecRegex.lastIndex = 0
  while ((match = pureDecRegex.exec(normalized)) !== null) {
    const a = parseFloat(match[1])
    const b = parseFloat(match[2])
    // 中国范围粗略过滤：纬度 15~55，经度 70~140
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
    // 避免与已匹配的 DMS 格式重复
    const raw = match[0]
    if (raw.includes('°') || raw.includes('′')) continue
    // 避免与已有点重复
    const isDup = points.some(p => Math.abs(p.lat - lat) < 0.001 && Math.abs(p.lng - lng) < 0.001)
    if (!isDup) {
      points.push({ name: `坐标点${points.length + 1}`, lat, lng, raw })
    }
  }

  // --- 模式5: 中文小数 "纬度39.9，经度116.4" ---
  const cnDecRegex = /纬度\s*(\d+\.?\d*)\s*[，,、\s]+\s*经度\s*(\d+\.?\d*)/g
  while ((match = cnDecRegex.exec(normalized)) !== null) {
    const lat = parseFloat(match[1])
    const lng = parseFloat(match[2])
    const isDup = points.some(p => Math.abs(p.lat - lat) < 0.001 && Math.abs(p.lng - lng) < 0.001)
    if (!isDup) {
      points.push({ name: `坐标点${points.length + 1}`, lat, lng, raw: match[0] })
    }
  }

  return points
}
