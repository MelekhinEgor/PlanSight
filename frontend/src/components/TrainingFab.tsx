import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GraduationCap } from 'lucide-react'
import { api } from '../api/client'
import { isStroginoProject, resolveDemoProjectId } from '../tour/demoProject'
import { markWelcomeSkipped, readWelcomeSkipped } from '../tour/welcome'
import { useTourOptional } from '../tour/TourProvider'
import { TrainingLauncher } from './TrainingLauncher'

/** Круглая кнопка обучения — всегда на экране; после входа панель открыта. */
export function TrainingFab() {
  const tour = useTourOptional()
  const [panelOpen, setPanelOpen] = useState(() => !readWelcomeSkipped())
  const [welcomeGate] = useState(() => !readWelcomeSkipped())
  const portfolio = useQuery({
    queryKey: ['portfolio'],
    queryFn: api.getPortfolio,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
  const projects = portfolio.data?.projects ?? []
  const projectId = useMemo(() => resolveDemoProjectId(projects), [projects])
  const projectReady = projects.some(isStroginoProject)

  const closePanel = () => {
    markWelcomeSkipped()
    setPanelOpen(false)
  }

  if (tour?.active) return null

  return (
    <>
      {!panelOpen && (
        <button
          type="button"
          className="training-fab"
          aria-label="Режим обучения"
          title="Режим обучения · Строгино 360"
          data-tour-id="training-home"
          onClick={() => setPanelOpen(true)}
        >
          <GraduationCap size={22} strokeWidth={1.8} aria-hidden />
        </button>
      )}
      {panelOpen && (
        <TrainingLauncher
          projectId={projectId}
          projectReady={projectReady}
          projects={projects}
          lockUntilSkip={welcomeGate}
          onClose={closePanel}
        />
      )}
    </>
  )
}
