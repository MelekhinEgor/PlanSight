import { useState } from 'react'
import { mascotSrc, type MascotId, WELCOME_MASCOT } from '../tour/mascots'

type Props = {
  id?: MascotId | string
  className?: string
  size?: number
}

/** Кадр маскота из бандла — URL стабильный после сборки Vite. */
export function TrainingMascot({ id = WELCOME_MASCOT, className = '', size = 96 }: Props) {
  const [failed, setFailed] = useState(false)
  const src = failed ? mascotSrc(WELCOME_MASCOT) : mascotSrc(id)

  return (
    <span
      className={`training-mascot-wrap ${className}`.trim()}
      aria-hidden
      style={{ width: size, height: size, flex: `0 0 ${size}px` }}
    >
      <img
        className="training-mascot"
        src={src}
        alt=""
        width={size}
        height={size}
        draggable={false}
        decoding="async"
        onError={() => {
          if (!failed) setFailed(true)
        }}
      />
    </span>
  )
}
