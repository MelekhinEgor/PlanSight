import { useEffect, useState, type CSSProperties, type ReactEventHandler } from 'react'
import {
  FindingFrameOverlay,
  type OverlayDetection,
  type OverlayZone,
} from './FindingFrameOverlay'

type LayerMode = 'all' | 'equipment' | 'zone'

type Props = {
  src: string
  alt?: string
  imgStyle?: CSSProperties
  imgKey?: string | number
  detections?: OverlayDetection[]
  zone?: OverlayZone | null
  naturalWidth: number
  naturalHeight: number
  showOverlay: boolean
  selectedDet?: number | null
  onSelectDet?: (index: number | null) => void
  showLabels?: boolean
  showConfidence?: boolean
  layers?: LayerMode
  zoneSelected?: boolean
  onSelectZone?: () => void
  tourId?: string
  onImgError?: ReactEventHandler<HTMLImageElement>
}

/** Прогрев URL, чтобы при открытии карточки фото успевало кэшироваться. */
export function preloadEvidenceImages(urls: Array<string | null | undefined>) {
  for (const url of urls) {
    if (!url) continue
    const img = new Image()
    img.decoding = 'async'
    img.src = url
  }
}

/**
 * Фото + SVG-разметка: оверлей только после загрузки кадра,
 * чтобы рамки не «висели» на сером фоне раньше картинки.
 */
export function EvidenceFrameView({
  src,
  alt = '',
  imgStyle,
  imgKey,
  detections,
  zone,
  naturalWidth,
  naturalHeight,
  showOverlay,
  selectedDet = null,
  onSelectDet,
  showLabels = true,
  showConfidence = false,
  layers = 'all',
  zoneSelected = false,
  onSelectZone,
  tourId,
  onImgError,
}: Props) {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    setReady(false)
    const probe = new Image()
    const mark = () => {
      if (!cancelled) setReady(true)
    }
    probe.onload = mark
    probe.onerror = mark
    probe.src = src
    if (probe.complete && probe.naturalWidth > 0) mark()
    return () => {
      cancelled = true
    }
  }, [src])

  return (
    <>
      {!ready && <div className="evidence-frame-pending" aria-hidden />}
      <img
        key={imgKey}
        src={src}
        alt={alt}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          display: 'block',
          opacity: ready ? 1 : 0,
          transition: 'opacity .12s ease',
          ...imgStyle,
        }}
        onLoad={() => setReady(true)}
        onError={(e) => {
          setReady(true)
          onImgError?.(e)
        }}
      />
      {ready && showOverlay && (
        <FindingFrameOverlay
          detections={detections}
          zone={zone}
          naturalWidth={naturalWidth}
          naturalHeight={naturalHeight}
          selectedDet={selectedDet}
          onSelectDet={onSelectDet}
          showLabels={showLabels}
          showConfidence={showConfidence}
          layers={layers}
          zoneSelected={zoneSelected}
          onSelectZone={onSelectZone}
          tourId={tourId}
        />
      )}
    </>
  )
}
