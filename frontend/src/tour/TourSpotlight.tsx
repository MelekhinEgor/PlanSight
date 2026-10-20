import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { queryTourTarget } from './tourDom'

/** Виртуальная цель: рамка разрастается на весь экран и гаснет (финал тура). */
export const TOUR_EXPAND_EXIT_ID = 'tour-expand-exit'

type Rect = { top: number; left: number; width: number; height: number; radius: number }

function readRect(el: Element): Rect {
  const r = el.getBoundingClientRect()
  const cs = window.getComputedStyle(el)
  const radius = parseFloat(cs.borderRadius || '8') || 8
  return {
    top: r.top,
    left: r.left,
    width: Math.max(8, r.width),
    height: Math.max(8, r.height),
    radius: Math.min(radius, 16),
  }
}

function jumpedFar(prev: Rect | null, next: Rect): boolean {
  if (!prev) return false
  const dx = Math.abs(prev.left - next.left)
  const dy = Math.abs(prev.top - next.top)
  const dw = Math.abs(prev.width - next.width)
  const dh = Math.abs(prev.height - next.height)
  return dx > 120 || dy > 120 || dw > 160 || dh > 160
}

type Props = {
  targetId: string | null
  pulse?: boolean
  dim?: boolean
  reducedMotion?: boolean
}

/**
 * Рамка + затемнение «вырезом» (box-shadow).
 * При смене соседних целей затемнение не мигает: контур и вырез просто смещаются.
 * При большом скачке (смена экрана) — snap без «ползущей» рамки.
 * `tour-expand-exit` — финальный жест: разрастание на весь сервис и исчезновение.
 */
export function TourSpotlight({ targetId, pulse = true, dim = true, reducedMotion }: Props) {
  const [rect, setRect] = useState<Rect | null>(null)
  const [ready, setReady] = useState(false)
  const [pulseOn, setPulseOn] = useState(false)
  const [snap, setSnap] = useState(false)
  const [expandExit, setExpandExit] = useState(false)
  const readyRef = useRef(false)
  const lastTargetRef = useRef<string | null>(null)
  const lastRectRef = useRef<Rect | null>(null)

  useEffect(() => {
    if (!targetId) {
      setRect(null)
      lastRectRef.current = null
      setReady(false)
      readyRef.current = false
      setPulseOn(false)
      setSnap(false)
      setExpandExit(false)
      lastTargetRef.current = null
      return
    }

    // Финал: от текущей (или запасной) рамки — на весь экран и fade-out
    if (targetId === TOUR_EXPAND_EXIT_ID) {
      let cancelled = false
      let tExpand: number | undefined
      let tFade: number | undefined
      let tClear: number | undefined
      setExpandExit(true)
      setPulseOn(false)
      setSnap(Boolean(reducedMotion))
      lastTargetRef.current = targetId

      const start =
        lastRectRef.current ||
        ({
          top: Math.max(24, window.innerHeight * 0.28),
          left: Math.max(24, window.innerWidth * 0.18),
          width: Math.min(640, window.innerWidth * 0.64),
          height: 140,
          radius: 12,
        } satisfies Rect)

      setRect(start)
      setReady(true)
      readyRef.current = true

      const expandMs = reducedMotion ? 160 : 920
      const fadeMs = reducedMotion ? 120 : 420

      tExpand = window.setTimeout(() => {
        if (cancelled) return
        const full: Rect = {
          top: -12,
          left: -12,
          width: window.innerWidth + 24,
          height: window.innerHeight + 24,
          radius: 0,
        }
        lastRectRef.current = full
        setRect(full)
        tFade = window.setTimeout(() => {
          if (cancelled) return
          setReady(false)
          readyRef.current = false
          tClear = window.setTimeout(() => {
            if (!cancelled) {
              setRect(null)
              setExpandExit(false)
            }
          }, fadeMs)
        }, Math.round(expandMs * 0.72))
      }, reducedMotion ? 20 : 50)

      return () => {
        cancelled = true
        if (tExpand) window.clearTimeout(tExpand)
        if (tFade) window.clearTimeout(tFade)
        if (tClear) window.clearTimeout(tClear)
      }
    }

    let cancelled = false
    let ro: ResizeObserver | null = null
    let pulseTimer: number | undefined
    let readyTimer: number | undefined
    let snapTimer: number | undefined
    const switching = lastTargetRef.current != null && lastTargetRef.current !== targetId
    lastTargetRef.current = targetId
    setExpandExit(false)

    const update = () => {
      const el = queryTourTarget(targetId)
      if (!el || cancelled) {
        if (!el && !cancelled) {
          setRect(null)
          lastRectRef.current = null
        }
        return false
      }
      const next = readRect(el)
      const far = jumpedFar(lastRectRef.current, next)
      if (far || switching) {
        setSnap(true)
        if (snapTimer) window.clearTimeout(snapTimer)
        snapTimer = window.setTimeout(() => {
          if (!cancelled) setSnap(false)
        }, reducedMotion ? 40 : 140)
      }
      lastRectRef.current = next
      setRect(next)
      return true
    }

    const attach = (el: Element) => {
      const r = el.getBoundingClientRect()
      const inView =
        r.top >= 12 &&
        r.left >= 12 &&
        r.bottom <= (window.innerHeight || 0) - 12 &&
        r.right <= (window.innerWidth || 0) - 12
      if (!inView) {
        el.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' })
      }
      update()
      window.requestAnimationFrame(() => {
        if (!cancelled) update()
      })

      if (switching && readyRef.current && !jumpedFar(lastRectRef.current, readRect(el))) {
        setReady(true)
        if (pulse && !reducedMotion) {
          setPulseOn(true)
          pulseTimer = window.setTimeout(() => setPulseOn(false), 500)
        }
      } else {
        setReady(false)
        readyRef.current = false
        readyTimer = window.setTimeout(() => {
          if (!cancelled) {
            update()
            setReady(true)
            readyRef.current = true
            if (pulse && !reducedMotion) {
              setPulseOn(true)
              pulseTimer = window.setTimeout(() => setPulseOn(false), 650)
            }
          }
        }, reducedMotion ? 40 : 200)
      }

      ro = new ResizeObserver(() => update())
      ro.observe(el)
      window.addEventListener('scroll', update, true)
      window.addEventListener('resize', update)
    }

    setPulseOn(false)

    if (!update()) {
      const poll = window.setInterval(() => {
        const el = queryTourTarget(targetId)
        if (el) {
          window.clearInterval(poll)
          attach(el)
        }
      }, 80)
      return () => {
        cancelled = true
        window.clearInterval(poll)
      }
    }

    const el = queryTourTarget(targetId)
    if (el) attach(el)

    return () => {
      cancelled = true
      ro?.disconnect()
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
      if (pulseTimer) window.clearTimeout(pulseTimer)
      if (readyTimer) window.clearTimeout(readyTimer)
      if (snapTimer) window.clearTimeout(snapTimer)
    }
  }, [targetId, pulse, reducedMotion])

  if (!targetId || !rect) return null

  const pad = expandExit ? 0 : 6
  const style: CSSProperties = {
    top: rect.top - pad,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
    borderRadius: expandExit ? Math.max(0, rect.radius) : Math.max(6, rect.radius + 2),
  }

  return createPortal(
    <div
      className={`tour-spotlight-root${dim ? ' is-dim' : ''}${ready ? ' is-ready' : ''}${pulseOn ? ' is-pulse' : ''}${snap || reducedMotion ? ' is-snap' : ''}${reducedMotion ? ' is-reduced' : ''}${expandExit ? ' is-expand-exit' : ''}`}
      aria-hidden
    >
      <div className="tour-spotlight-ring" style={style} />
    </div>,
    document.body,
  )
}
