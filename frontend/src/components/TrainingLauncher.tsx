import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { buildCompetitionDemoContext, enrichCompetitionDemo } from '../tour/competitionDemo'
import { WELCOME_MASCOT } from '../tour/mascots'
import { buildScenarios } from '../tour/scenarios'
import { getTourBridge } from '../tour/tourBridge'
import { useTourOptional } from '../tour/TourProvider'
import { TrainingMascot } from './TrainingMascot'

type Props = {
  projectId: string
  /** false, пока в портфеле нет Строгино (не стартовать тур с неверным id). */
  projectReady?: boolean
  onClose: () => void
  /** Если true — оверлей не закрывается кликом по серому фону, только «Пропустить». */
  lockUntilSkip?: boolean
  /** Проекты портфеля для контекста обучения. */
  projects?: { id: string | number; name?: string | null; developer?: string | null; slug?: string | null }[]
}

/** Панель режима обучения справа снизу. */
export function TrainingLauncher({
  projectId,
  projectReady = true,
  onClose,
  lockUntilSkip = false,
  projects = [],
}: Props) {
  const navigate = useNavigate()
  const tour = useTourOptional()
  const scenarios = buildScenarios(projectId)
  const demoTour = scenarios.find((s) => s.id === 'competition')
  const guided = scenarios.find((s) => s.id === 'full')
  const [busy, setBusy] = useState(false)

  const startGuided = () => {
    if (!projectReady || !guided) return
    onClose()
    if (tour) {
      tour.startScenario(guided.id, projectId)
      return
    }
    if (guided.steps[0]) navigate(guided.steps[0].route)
  }

  const startLearning = async () => {
    if (!projectReady || !demoTour || busy) return
    setBusy(true)
    try {
      const demoProjects = (projects.length ? projects : [{ id: projectId }]).map((p) => ({
        id: String(p.id),
        name: p.name,
        developer: p.developer ?? null,
        slug: p.slug,
      }))
      let ctx = buildCompetitionDemoContext(demoProjects)
      ctx = await enrichCompetitionDemo(ctx, {
        getDeviations: (pid) => api.getDeviations(pid),
        getSchedule: (pid) => api.getSchedule(pid),
      })
      getTourBridge().competition = {
        developer: ctx.developer,
        projectId: ctx.projectId,
        activityId: ctx.activityId,
        deviationId: ctx.deviationId,
        cameraId: ctx.cameraId,
      }
      onClose()
      if (tour) {
        tour.startScenario(demoTour.id, ctx.projectId || projectId)
        return
      }
      navigate('/')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div
        className="training-backdrop"
        aria-hidden
        onClick={lockUntilSkip ? undefined : onClose}
      />
      <div
        className="training-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Режим обучения"
        data-tour-id="training-panel"
      >
        <button type="button" className="training-close" onClick={onClose} aria-label="Пропустить">
          ×
        </button>

        <div className="training-hero">
          <TrainingMascot id={WELCOME_MASCOT} size={104} />
          <div className="training-hero-copy">
            <span className="training-kicker">PlanSight · гид</span>
            <b>Познакомьтесь с системой</b>
            <p>
              Короткий тур по ЖК «Строгино 360»: аналитика, фильтры, график, камеры и предупреждения.
              Данные не меняются — только подсказки и управляемая демонстрация.
            </p>
          </div>
        </div>

        {!projectReady && <p className="training-wait">Ищем ЖК «Строгино 360» в портфеле…</p>}

        <div className="training-steps-preview" aria-hidden>
          <span>Строгино</span>
          <i />
          <span>График</span>
          <i />
          <span>Камеры</span>
          <i />
          <span>Сигналы</span>
          <i />
          <span>Аналитика</span>
        </div>

        <button
          type="button"
          className="training-primary"
          onClick={() => void startLearning()}
          disabled={!projectReady || !demoTour || busy}
          data-tour-id="training-start"
        >
          {busy ? 'Подготовка…' : 'Начать обучение'}
        </button>
        <button
          type="button"
          className="training-skip"
          onClick={startGuided}
          disabled={!projectReady || !guided}
          data-tour-id="training-start-guided"
        >
          Обучение с подсказками
        </button>
        <button type="button" className="training-skip" onClick={onClose} data-tour-id="training-skip">
          Пропустить
        </button>
      </div>
    </>
  )
}
