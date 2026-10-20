import { demoClassColor } from '../lib/stroginoDemoFrames'

export type OverlayDetection = {
  id?: string
  equipment_code?: string
  label_ru?: string
  confidence?: number
  confidence_type?: string
  color_key?: string
  /** Нормализованные углы 0..1 относительно исходного кадра */
  bbox_norm?: { x1: number; y1: number; x2: number; y2: number }
}

export type OverlayZone = {
  label: string
  legend?: string
  polygon_norm: number[][]
}

type LayerMode = 'all' | 'equipment' | 'zone'

type Props = {
  detections?: OverlayDetection[]
  zone?: OverlayZone | null
  naturalWidth: number
  naturalHeight: number
  selectedDet: number | null
  onSelectDet?: (index: number | null) => void
  showLabels?: boolean
  showConfidence?: boolean
  layers?: LayerMode
  zoneSelected?: boolean
  onSelectZone?: () => void
  className?: string
  tourId?: string
}

const FONT = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'

function isRealConfidence(d: OverlayDetection, showConfidence: boolean): boolean {
  if (!showConfidence || d.confidence == null) return false
  return d.confidence_type !== 'SIMULATED_DEMO_VALUE'
}

/** Ширина бирки с запасом под кириллицу */
function estimateTagWidth(text: string, fontSize: number): number {
  return Math.ceil(text.length * fontSize * 0.72 + 20)
}

function clamp(v: number, min: number, max: number) {
  return Math.min(max, Math.max(min, v))
}

function zoneBounds(points: number[][], w: number, h: number) {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    const x = (p[0] ?? 0) * w
    const y = (p[1] ?? 0) * h
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  }
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, maxX: w, maxY: h }
  return { minX, minY, maxX, maxY }
}

/** Угловые скобки «окна» — короткие L на углах рамки */
function CornerBrackets({
  x,
  y,
  bw,
  bh,
  color,
  arm,
}: {
  x: number
  y: number
  bw: number
  bh: number
  color: string
  arm: number
}) {
  const a = Math.min(arm, bw * 0.35, bh * 0.35)
  const sw = 2.25
  return (
    <g stroke={color} strokeWidth={sw} fill="none" strokeLinecap="square" vectorEffect="non-scaling-stroke">
      <path d={`M ${x} ${y + a} V ${y} H ${x + a}`} />
      <path d={`M ${x + bw - a} ${y} H ${x + bw} V ${y + a}`} />
      <path d={`M ${x + bw} ${y + bh - a} V ${y + bh} H ${x + bw - a}`} />
      <path d={`M ${x + a} ${y + bh} H ${x} V ${y + bh - a}`} />
    </g>
  )
}

function LabelTag({
  x,
  y,
  text,
  fill,
  fontSize,
  tagH,
  maxWidth,
}: {
  x: number
  y: number
  text: string
  fill: string
  fontSize: number
  tagH: number
  maxWidth: number
}) {
  const tagW = Math.min(estimateTagWidth(text, fontSize), maxWidth)
  return (
    <g className="evidence-label-tag">
      {/* тень */}
      <rect x={x + 1.5} y={y + 1.5} width={tagW} height={tagH} rx={3} fill="rgba(0,0,0,.28)" />
      <rect x={x} y={y} width={tagW} height={tagH} rx={3} fill={fill} />
      <text
        x={x + 10}
        y={y + tagH / 2}
        fill="#fff"
        fontFamily={FONT}
        fontSize={fontSize}
        fontWeight={700}
        dominantBaseline="central"
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {text}
      </text>
    </g>
  )
}

export function FindingFrameOverlay({
  detections = [],
  zone,
  naturalWidth,
  naturalHeight,
  selectedDet,
  onSelectDet,
  showLabels = true,
  showConfidence = false,
  layers = 'all',
  zoneSelected = false,
  onSelectZone,
  className = 'evidence-bbox-svg',
  tourId,
}: Props) {
  const w = Math.max(1, naturalWidth || 1)
  const h = Math.max(1, naturalHeight || 1)
  const showEquip = layers === 'all' || layers === 'equipment'
  const showZone = layers === 'all' || layers === 'zone'
  const fontSize = Math.max(13, Math.min(18, w * 0.0135))
  const tagH = Math.round(fontSize + 12)
  const cornerArm = Math.max(14, Math.min(28, w * 0.018))
  const zonePts = zone?.polygon_norm || []
  const zonePoints = zonePts.length ? zonePts.map(([nx, ny]) => `${nx * w},${ny * h}`).join(' ') : ''

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid meet"
      className={className}
      data-tour-id={tourId}
    >
      <defs>
        <filter id="ev-tag-soft" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="1" stdDeviation="1.2" floodColor="#000" floodOpacity="0.35" />
        </filter>
      </defs>

      {showZone && zonePoints && (
        <g
          className={`evidence-zone-group${zoneSelected ? ' is-zone-selected' : ''}`}
          style={{ cursor: onSelectZone ? 'pointer' : undefined }}
          onClick={(e) => {
            e.stopPropagation()
            onSelectZone?.()
          }}
        >
          <polygon
            points={zonePoints}
            className="evidence-zone-poly"
            fill={zoneSelected ? 'rgba(196, 30, 58, .16)' : 'rgba(196, 30, 58, .08)'}
            stroke={zoneSelected ? '#c41e3a' : '#e11d48'}
            strokeWidth={zoneSelected ? 3 : 2.5}
            strokeDasharray={zoneSelected ? undefined : '7 4'}
            vectorEffect="non-scaling-stroke"
          />
          {showLabels &&
            (() => {
              const bb = zoneBounds(zonePts, w, h)
              const zText = zone?.label || 'Область анализа'
              const tagW = Math.min(estimateTagWidth(zText, fontSize), w - 8)
              let tagX = clamp(bb.minX, 4, Math.max(4, w - tagW - 4))
              // бирка над верхней границей зоны; если не влезает — чуть ниже внутрь
              let tagY = bb.minY - tagH - 2
              if (tagY < 4) tagY = clamp(bb.minY + 4, 4, h - tagH - 4)
              return (
                <g filter="url(#ev-tag-soft)">
                  <LabelTag
                    x={tagX}
                    y={tagY}
                    text={zText}
                    fill={zoneSelected ? '#9f1239' : '#c41e3a'}
                    fontSize={fontSize}
                    tagH={tagH}
                    maxWidth={w - 8}
                  />
                </g>
              )
            })()}
        </g>
      )}

      {showEquip &&
        detections.map((d, i) => {
          const n = d.bbox_norm
          if (!n) return null
          const x = n.x1 * w
          const y = n.y1 * h
          const bw = Math.max(1, (n.x2 - n.x1) * w)
          const bh = Math.max(1, (n.y2 - n.y1) * h)
          const active = selectedDet === i
          const stroke = active ? '#1677ff' : demoClassColor(d.color_key, d.equipment_code)
          const label = d.label_ru || d.equipment_code || 'Объект'
          const confOk = isRealConfidence(d, showConfidence)
          const confTxt = confOk ? ` · ${Math.round(Number(d.confidence) * 100)}%` : ''
          const tagText = `#${i + 1}  ${label}${confTxt}`
          const tagW = Math.min(estimateTagWidth(tagText, fontSize), w - 8)
          let tagX = clamp(x, 4, Math.max(4, w - tagW - 4))
          const tagAbove = y >= tagH + 4
          const tagY = tagAbove ? y - tagH : y
          const dimmed = selectedDet != null && !active

          return (
            <g
              key={d.id || i}
              className={`evidence-bbox-window${active ? ' is-active' : ''}`}
              opacity={dimmed ? 0.32 : 1}
              style={{ cursor: onSelectDet ? 'pointer' : undefined }}
              onClick={(e) => {
                e.stopPropagation()
                onSelectDet?.(selectedDet === i ? null : i)
              }}
            >
              {/* лёгкая заливка окна */}
              <rect
                x={x}
                y={y}
                width={bw}
                height={bh}
                fill={active ? 'rgba(22,119,255,.10)' : 'rgba(255,255,255,.04)'}
                stroke="none"
              />
              {/* тонкая рамка */}
              <rect
                x={x}
                y={y}
                width={bw}
                height={bh}
                fill="none"
                stroke={stroke}
                strokeWidth={active ? 1.75 : 1.25}
                strokeOpacity={0.85}
                vectorEffect="non-scaling-stroke"
              />
              {/* угловые скобки — основной акцент «окна» */}
              <CornerBrackets x={x} y={y} bw={bw} bh={bh} color={stroke} arm={cornerArm} />

              {showLabels && (active || selectedDet == null) && (
                <g filter="url(#ev-tag-soft)">
                  {/* стык бирки с верхней кромкой рамки */}
                  {tagAbove && (
                    <rect x={tagX} y={y - 2} width={Math.min(tagW, bw)} height={2} fill={stroke} />
                  )}
                  <LabelTag
                    x={tagX}
                    y={tagY}
                    text={tagText}
                    fill={stroke}
                    fontSize={fontSize}
                    tagH={tagH}
                    maxWidth={w - 8}
                  />
                </g>
              )}
            </g>
          )
        })}
    </svg>
  )
}
