import { useNavigate } from 'react-router-dom'
import { buildScenarios } from '../tour/scenarios'
import { useTourOptional } from '../tour/TourProvider'

type Props = { projectId: string; onClose: () => void }

/** Обучение из нижней зоны sidebar поверх рабочего продукта. */
export function TrainingLauncher({ projectId, onClose }: Props) {
  const navigate = useNavigate()
  const tour = useTourOptional()
  const scenarios = buildScenarios(projectId)

  const start = (scenarioId: string) => {
    onClose()
    if (tour) {
      tour.startScenario(scenarioId, projectId)
      return
    }
    // Запасной вариант без provider
    const sc = scenarios.find((s) => s.id === scenarioId)
    if (sc?.steps[0]) navigate(sc.steps[0].route)
  }

  return (
    <>
      <button type="button" className="training-backdrop" aria-label="Закрыть" onClick={onClose} />
      <div className="training-panel" role="dialog" aria-label="Режим обучения" data-tour-id="training-panel">
        <div className="training-panel-head">
          <b>Режим обучения</b>
          <button type="button" className="training-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        <p className="training-panel-lead">
          Короткие сценарии поверх рабочих экранов. Статусы и данные проекта сами не меняются — только подсказки.
        </p>
        <ul className="training-scenario-list">
          {scenarios.map((s) => (
            <li key={s.id}>
              <button type="button" className="training-scenario-btn" onClick={() => start(s.id)} data-tour-id={`training-scenario-${s.id}`}>
                <strong>{s.title}</strong>
                <span>{s.description}</span>
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="training-skip" onClick={onClose}>
          Закрыть
        </button>
      </div>
    </>
  )
}
