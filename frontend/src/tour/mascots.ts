/** Кадры маскота PlanSight — импортируются в бандл (не зависят от /mascots в nginx). */

import img_planner_intro from '../assets/mascots/planner-intro.png'
import img_planner_run from '../assets/mascots/planner-run.png'
import img_planner_laptop from '../assets/mascots/planner-laptop.png'
import img_planner_hologram from '../assets/mascots/planner-hologram.png'
import img_planner_win from '../assets/mascots/planner-win.png'
import img_planner_coffee from '../assets/mascots/planner-coffee.png'
import img_camera_wave from '../assets/mascots/camera-wave.png'
import img_camera_fly from '../assets/mascots/camera-fly.png'
import img_camera_inspect from '../assets/mascots/camera-inspect.png'
import img_camera_alert from '../assets/mascots/camera-alert.png'
import img_camera_tablet from '../assets/mascots/camera-tablet.png'
import img_camera_dance from '../assets/mascots/camera-dance.png'

export const MASCOT_IDS = [
  'planner-intro',
  'planner-run',
  'planner-laptop',
  'planner-hologram',
  'planner-win',
  'planner-coffee',
  'camera-wave',
  'camera-fly',
  'camera-inspect',
  'camera-alert',
  'camera-tablet',
  'camera-dance',
] as const

export type MascotId = (typeof MASCOT_IDS)[number]

export const WELCOME_MASCOT: MascotId = 'planner-intro'

const MASCOT_URL: Record<MascotId, string> = {
  'planner-intro': img_planner_intro,
  'planner-run': img_planner_run,
  'planner-laptop': img_planner_laptop,
  'planner-hologram': img_planner_hologram,
  'planner-win': img_planner_win,
  'planner-coffee': img_planner_coffee,
  'camera-wave': img_camera_wave,
  'camera-fly': img_camera_fly,
  'camera-inspect': img_camera_inspect,
  'camera-alert': img_camera_alert,
  'camera-tablet': img_camera_tablet,
  'camera-dance': img_camera_dance,
}

export function mascotSrc(id: MascotId | string | undefined): string {
  const key = (id && MASCOT_IDS.includes(id as MascotId) ? id : WELCOME_MASCOT) as MascotId
  return MASCOT_URL[key] || MASCOT_URL[WELCOME_MASCOT]
}

/** Кадр по номеру шага (цикл по 12 позам). */
export function mascotForStepIndex(index: number): MascotId {
  const i = ((index % MASCOT_IDS.length) + MASCOT_IDS.length) % MASCOT_IDS.length
  return MASCOT_IDS[i]
}
