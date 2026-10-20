import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { queryTourTarget } from './tourDom'

type Props = {
  targetId: string | null
  active: boolean
  reducedMotion?: boolean
  /** Задержка старта движения — чтобы рамка успела встать на цель. */
  startDelayMs?: number
  onArrived?: () => void
}

/** Декоративный указатель (не системный курсор, не DOM-клики). */
export function TourPointer({ targetId, active, reducedMotion, startDelayMs = 0, onArrived }: Props) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [visible, setVisible] = useState(false)
  const [press, setPress] = useState(false)

  useEffect(() => {
    if (!active || !targetId) {
      setPos(null)
      setVisible(false)
      setPress(false)
      return
    }

    let cancelled = false
    let tStart: number | undefined
    let tPress: number | undefined
    let tEnd: number | undefined

    const place = () => {
      const el = queryTourTarget(targetId)
      if (!el || cancelled) return false
      const r = el.getBoundingClientRect()
      const x = r.left + Math.min(r.width * 0.7, Math.max(12, r.width - 8))
      const y = r.top + Math.min(r.height * 0.55, Math.max(12, r.height - 8))
      setPos({ x, y })
      return true
    }

    // Ждём рамку, затем показываем курсор
    tStart = window.setTimeout(() => {
      if (cancelled) return
      if (!place()) return
      setVisible(true)
      setPress(false)
      tPress = window.setTimeout(() => {
        if (!cancelled) setPress(true)
      }, reducedMotion ? 40 : 380)
      tEnd = window.setTimeout(() => {
        if (cancelled) return
        setPress(false)
        onArrived?.()
      }, reducedMotion ? 140 : 720)
    }, Math.max(0, startDelayMs))

    return () => {
      cancelled = true
      if (tStart) window.clearTimeout(tStart)
      if (tPress) window.clearTimeout(tPress)
      if (tEnd) window.clearTimeout(tEnd)
    }
  }, [active, targetId, reducedMotion, startDelayMs, onArrived])

  if (!active || !pos || !visible) return null

  return createPortal(
    <div
      className={`tour-pointer${press ? ' is-press' : ''}${reducedMotion ? ' is-reduced' : ''}`}
      style={{ transform: `translate(${pos.x}px, ${pos.y}px)`, ['--x' as string]: `${pos.x}px`, ['--y' as string]: `${pos.y}px` }}
      aria-hidden
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
        <path
          d="M5 3.5l14 8.2-6.2 1.5L10.5 21 5 3.5z"
          fill="#6B4EFF"
          stroke="#fff"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </svg>
    </div>,
    document.body,
  )
}
