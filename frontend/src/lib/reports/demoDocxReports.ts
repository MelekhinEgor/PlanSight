/**
 * Клиентская генерация Word-отчётов по сценариям Строгино (Reports v2 §9–10).
 */
import type { FindingEvidence } from '../../components/FindingDrawer'
import {
  buildScenarioEvidence,
  listScenarioWarningRows,
  scenarioShortTitle,
  type ActivityLike,
  type ScenarioId,
  scenarioIdFromUiDeviationId,
} from '../evidenceScenariosV2'
import { REPORT_DISCLAIMER, REPORT_METHODOLOGY } from './disclaimer'
import { buildDocxBlob, downloadBlob, fetchImageAsDoc, type DocBlock } from './miniDocx'

function nowRu(): string {
  try {
    return new Intl.DateTimeFormat('ru-RU', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'Europe/Moscow',
    }).format(new Date())
  } catch {
    return new Date().toISOString()
  }
}

function safeName(s: string): string {
  return String(s || '')
    .replace(/[«»„“"']/g, '')
    .replace(/[^\wа-яА-ЯёЁ0-9\-]+/gi, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 80)
}

function reportDateStamp(d = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function fmtRuIso(iso?: string | null): string {
  if (!iso) return '—'
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso
}

function warningTitleRu(w: { id?: number | string; code?: string; title?: string }): string {
  if (w.title) return w.title
  const sid = scenarioIdFromUiDeviationId(Number(w.id))
  if (sid) return scenarioShortTitle(sid)
  const code = (w.code || '').toUpperCase()
  if (code.includes('EQUIPMENT') || code.includes('COMPOSITION')) return 'Проверить комплект техники'
  if (code.includes('PILE') || code.includes('FOUNDATION')) return 'Проверить технику для свайных работ'
  if (code.includes('HAULAGE') || code.includes('TEMPO')) return 'Проверить темп вывоза грунта'
  return w.code && !/^[A-Z0-9_]+$/.test(w.code) ? w.code : 'Предупреждение'
}

function forecastSectionBlocks(meta: FindingEvidence['demo_meta']): DocBlock[] {
  const blocks: DocBlock[] = [{ type: 'h2', text: 'Расчёт влияния на срок' }]
  if (meta?.forecast_status === 'Рассчитан' && meta.forecast_impact_days != null) {
    blocks.push({
      type: 'kv',
      rows: [
        ['Статус прогноза', 'Рассчитан'],
        ['Прогнозное влияние', `${meta.forecast_impact_days > 0 ? '+' : ''}${meta.forecast_impact_days} календарных дней`],
        ['Прогнозная дата завершения', fmtRuIso(meta.forecast_finish)],
        ['Краткий итог', meta.delay_note || '—'],
      ],
    })
    const trace = meta.forecast_trace
    if (trace && typeof trace === 'object') {
      const inputs = (trace as { inputs?: Record<string, unknown> }).inputs || {}
      blocks.push({
        type: 'kv',
        rows: [
          ['Методика', String((trace as { methodId?: string }).methodId || 'progress_rate_calendar_v1')],
          ['Версия', String((trace as { methodVersion?: string }).methodVersion || '1.0')],
          ['Прогресс на дату среза', String(inputs.currentProgressPercent ?? '—')],
          ['Дата среза', fmtRuIso(String(inputs.asOfDate || ''))],
          ['Плановое завершение', fmtRuIso(String(inputs.plannedFinish || ''))],
          [
            'Скорость, п.п./день',
            String(inputs.dailyProgressPercentagePoints ?? 'из измерений прогресса'),
          ],
        ],
      })
    }
  } else {
    blocks.push({
      type: 'p',
      text: meta?.delay_note || 'Прогноз не рассчитан: недостаточно согласованных входов.',
    })
    for (const r of meta?.forecast_block_reasons || []) {
      blocks.push({ type: 'bullet', text: r })
    }
  }
  return blocks
}

function normativeSectionBlocks(meta: FindingEvidence['demo_meta']): DocBlock[] {
  const blocks: DocBlock[] = [{ type: 'h2', text: 'Нормативно-договорной контекст' }]
  if (meta?.normative_observation) {
    blocks.push({ type: 'p', text: meta.normative_observation })
  }
  blocks.push({
    type: 'p',
    text:
      meta?.normative_formulation ||
      'Рекомендуется проверка по условиям контракта и проектной документации. Наблюдение само по себе не устанавливает нарушение.',
  })
  if (meta?.normative_refs?.length) {
    blocks.push({ type: 'p', text: `Ориентиры для проверки: ${meta.normative_refs.join('; ')}.` })
  }
  blocks.push({
    type: 'p',
    text: 'Формулировки носят рекомендательный характер и не являются автоматическим выводом о нарушении.',
  })
  return blocks
}

async function frameEvidenceBlocks(
  frames: FindingEvidence['frames'],
  opts?: { maxFrames?: number },
): Promise<DocBlock[]> {
  const list = (frames || []).slice(0, opts?.maxFrames ?? 12)
  const out: DocBlock[] = []
  if (!list.length) {
    out.push({ type: 'p', text: 'Кадры-доказательства не приложены' })
    return out
  }
  out.push({ type: 'p', text: `В отчёт включено кадров: ${list.length}` })
  for (let i = 0; i < list.length; i++) {
    const fr = list[i]
    const dets = (fr.detections || [])
      .map((d) => d.label_ru || d.equipment_code || 'объект')
      .join(', ')
    out.push({ type: 'h3', text: `Кадр ${i + 1}` })
    out.push({
      type: 'kv',
      rows: [
        [
          'Отметка на изображении',
          fr.source_visible_date
            ? `${fr.source_visible_date} (не метка камеры; не подтверждает период КСГ)`
            : fr.scenario_time_label || 'Не установлена',
        ],
        ['Область анализа', fr.control_zone?.label || fr.zone_label || 'Не задана'],
        ['Выделенная техника', dets || 'Нет размеченных объектов'],
      ],
    })
    if (fr.image_url) {
      const img = await fetchImageAsDoc(fr.image_url)
      if (img) {
        if (fr.natural_width && fr.natural_height) {
          img.widthPx = fr.natural_width
          img.heightPx = fr.natural_height
        }
        out.push({
          type: 'image',
          image: img,
          caption: `Кадр ${i + 1}: визуальное подтверждение наблюдения${dets ? ` (${dets})` : ''}`,
        })
      } else {
        out.push({ type: 'p', text: `Не удалось вложить изображение кадра ${i + 1}` })
      }
    } else {
      out.push({ type: 'p', text: `Изображение кадра ${i + 1} недоступно` })
    }
  }
  return out
}

export type ProjectWarningRow = {
  id: number | string
  code?: string
  title?: string
  schedule_item_name?: string | null
  explanation_ru?: string | null
  priority?: string
  observation_period?: string
  evidence_frames?: number
  review_status?: string
  signal_kind?: string
}

/** Индивидуальный отчёт (§9): паспорт → вывод → KPI/прогноз → кадры → наблюдения → цепочка → КСГ → расчёт → нормативка → действия → оговорка. */
export async function downloadFindingReportDocx(
  evidence: FindingEvidence,
  opts?: { projectName?: string; author?: string },
): Promise<void> {
  const meta = evidence.demo_meta
  const project = opts?.projectName || meta?.project_label || 'Проект'
  const sid = scenarioIdFromUiDeviationId(evidence.deviation_id)
  const title = meta?.title || (sid ? scenarioShortTitle(sid) : null) || 'Предупреждение'
  const work = meta?.work_label || evidence.schedule_item?.name || 'Не установлено'
  const plan = meta?.plan_window || evidence.schedule_item?.planned_finish || 'Не установлено'
  const stamp = meta?.observation_stamp || 'Не установлено'
  const frames = evidence.frames || []

  const blocks: DocBlock[] = [
    { type: 'h1', text: 'Отчёт по предупреждению PlanSight' },
    {
      type: 'kv',
      rows: [
        ['Проект', project],
        ['Предупреждение', title],
        ['Статус сигнала', meta?.display_status || evidence.lifecycle || 'Требует проверки'],
        ['Достаточность доказательств', meta?.evidence_status || 'Требует оценки'],
        ['Связь с КСГ', meta?.task_link_status || 'Предполагаемая'],
        ['Сформирован', nowRu()],
        ['Автор', opts?.author || 'PlanSight'],
        ['Снимок данных', 'Один согласованный снимок на момент формирования отчёта'],
      ],
    },
    { type: 'h2', text: 'Краткий вывод' },
    { type: 'p', text: meta?.brief || evidence.explanation_ru || 'Нет данных' },
    { type: 'h2', text: 'Ключевые показатели и прогноз' },
    {
      type: 'kv',
      rows: [
        ['Прогноз по срокам', meta?.delay_note || 'Прогноз не рассчитан'],
        ['Статус прогноза', meta?.forecast_status || 'Не рассчитан'],
        [
          'Прогнозное влияние, дн.',
          meta?.forecast_impact_days != null
            ? `${meta.forecast_impact_days > 0 ? '+' : ''}${meta.forecast_impact_days}`
            : '—',
        ],
        ['Прогнозная дата', fmtRuIso(meta?.forecast_finish)],
      ],
    },
    { type: 'h2', text: 'Кадры-доказательства' },
    ...(await frameEvidenceBlocks(frames)),
    { type: 'h2', text: 'Наблюдения' },
    {
      type: 'kv',
      rows: [
        ['Ожидается', meta?.expected || 'Не установлено'],
        ['На кадрах', meta?.observed_hint || 'Не установлено'],
        ['Основание сигнала', meta?.rule_result_ru || meta?.rule_name || 'Не установлено'],
        ['Отметка на изображении', stamp],
      ],
    },
    { type: 'p', text: evidence.explanation_ru || meta?.brief || '' },
    { type: 'h2', text: 'Цепочка разбора' },
    {
      type: 'bullet',
      text: 'Обнаружение на кадрах → доказательства → зона/предполагаемая связь с КСГ → правило → риск → прогноз (если рассчитан) → нормативный контекст → рекомендация → решение специалиста.',
    },
    { type: 'h2', text: 'Связь с КСГ' },
    {
      type: 'kv',
      rows: [
        ['Работа КСГ', work],
        ['Код работы', meta?.work_wbs || 'Не установлено'],
        ['Зона', meta?.zone_label || evidence.schedule_item?.building || 'Не установлено'],
        ['Период работы по КСГ', plan],
        ['Статус связи', meta?.task_link_status || 'Предполагаемая'],
        ['Отметка на кадрах (отдельно от плана)', stamp],
      ],
    },
    ...forecastSectionBlocks(meta),
    ...normativeSectionBlocks(meta),
    { type: 'h2', text: 'План действий' },
    {
      type: 'p',
      text:
        meta?.next_action ||
        evidence.card?.check ||
        'Подтвердите или отклоните сигнал после проверки на площадке.',
    },
    {
      type: 'bullet',
      text: 'Отделить отметку на изображении от планового периода работы КСГ при сверке.',
    },
    {
      type: 'bullet',
      text: 'Не трактовать отсутствие объекта на кадре как отсутствие техники на площадке.',
    },
    { type: 'h2', text: 'Ограничения' },
    ...(evidence.limitations || []).map((t): DocBlock => ({ type: 'bullet', text: t })),
    { type: 'p', text: REPORT_METHODOLOGY },
    { type: 'h2', text: 'Оговорка' },
    { type: 'p', text: REPORT_DISCLAIMER },
  ]

  const blob = buildDocxBlob(blocks)
  const projectPart = safeName(project) || 'проект'
  const warningPart = safeName(title) || 'предупреждение'
  downloadBlob(blob, `PlanSight_${projectPart}_${warningPart}_${reportDateStamp()}.docx`)
}

/** Сводный отчёт (§10): резюме → реестр с прогнозом → приоритетные случаи с фото → нормативка/план → оговорка. */
export async function downloadProjectReportDocx(opts: {
  projectName: string
  projectId?: string
  warnings: ProjectWarningRow[]
  activities?: ActivityLike[]
  author?: string
}): Promise<void> {
  const warnings = opts.warnings || []
  const byPriority = warnings.reduce(
    (acc, w) => {
      const p = w.priority || 'Средний'
      acc[p] = (acc[p] || 0) + 1
      return acc
    },
    {} as Record<string, number>,
  )
  const open = warnings.filter((w) => /проверк|open|требует/i.test(w.review_status || 'Требует проверки')).length

  const titled = warnings.map((w) => ({ ...w, titleRu: warningTitleRu(w) }))

  type Enriched = {
    row: (typeof titled)[number]
    evidence: FindingEvidence | null
    forecast: string
    brief: string
  }
  const enriched: Enriched[] = []
  for (const w of titled) {
    const sid = scenarioIdFromUiDeviationId(Number(w.id)) as ScenarioId | null
    let evidence: FindingEvidence | null = null
    let forecast = 'Прогноз не рассчитан'
    let brief = w.explanation_ru || ''
    if (sid) {
      try {
        evidence = buildScenarioEvidence(sid, opts.activities || [])
        forecast = evidence.demo_meta?.delay_note || forecast
        brief = evidence.demo_meta?.brief || evidence.explanation_ru || brief
      } catch {
        /* keep row text */
      }
    }
    enriched.push({ row: w, evidence, forecast, brief })
  }

  const calculated = enriched.filter((e) => e.evidence?.demo_meta?.forecast_status === 'Рассчитан').length
  const notCalculated = enriched.length - calculated

  const blocks: DocBlock[] = [
    { type: 'h1', text: 'Сводный отчёт по проекту PlanSight' },
    {
      type: 'kv',
      rows: [
        ['Проект', opts.projectName],
        ['Сформирован', nowRu()],
        ['Автор', opts.author || 'PlanSight'],
        ['Снимок данных', 'Один согласованный снимок на момент формирования отчёта'],
        ['Выборка', `Предупреждения с кадрами: ${warnings.length}`],
      ],
    },
    { type: 'h2', text: 'Управленческое резюме' },
    {
      type: 'kv',
      rows: [
        ['Всего предупреждений', String(warnings.length)],
        ['Требуют проверки / открыты', String(open || warnings.length)],
        ['Высокий приоритет', String(byPriority['Высокий'] || 0)],
        ['Средний приоритет', String(byPriority['Средний'] || 0)],
        ['Прогноз рассчитан', String(calculated)],
        ['Прогноз не рассчитан', String(notCalculated)],
      ],
    },
    {
      type: 'p',
      text: 'Отчёт сформирован по сигналам наблюдения. Связь с работами КСГ до подтверждения — предполагаемая. Правовая оценка и решения по контракту — за уполномоченными лицами.',
    },
    { type: 'h2', text: 'Реестр предупреждений' },
    {
      type: 'table',
      headers: ['№', 'Предупреждение', 'Работа КСГ', 'Период работ', 'Прогноз', 'Кадры', 'Статус'],
      rows: enriched.map((e, i) => [
        String(i + 1),
        e.row.titleRu,
        e.row.schedule_item_name || '—',
        e.row.observation_period || 'Не установлено',
        e.evidence?.demo_meta?.forecast_status === 'Рассчитан'
          ? `${e.evidence.demo_meta.forecast_impact_days != null ? (e.evidence.demo_meta.forecast_impact_days > 0 ? '+' : '') + e.evidence.demo_meta.forecast_impact_days + ' дн.' : e.forecast}`
          : 'Не рассчитан',
        String(e.row.evidence_frames ?? '—'),
        e.row.review_status || 'Требует проверки',
      ]),
    },
  ]

  const priorityCases = [...enriched].sort((a, b) => {
    const pa = a.row.priority === 'Высокий' ? 0 : 1
    const pb = b.row.priority === 'Высокий' ? 0 : 1
    return pa - pb
  })

  for (const e of priorityCases) {
    const w = e.row
    const meta = e.evidence?.demo_meta
    blocks.push(
      { type: 'h2', text: w.titleRu },
      { type: 'p', text: e.brief || 'Нет описания' },
      {
        type: 'kv',
        rows: [
          ['Работа КСГ', w.schedule_item_name || 'Не установлено'],
          ['Период работ по КСГ', w.observation_period || 'Не установлено'],
          ['Связь с КСГ', meta?.task_link_status || 'Предполагаемая'],
          ['Приоритет', w.priority || '—'],
          ['Статус', w.review_status || 'Требует проверки'],
          ['Прогноз по срокам', e.forecast],
          ['Ожидается', meta?.expected || 'Не установлено'],
          ['На кадрах', meta?.observed_hint || 'Не установлено'],
        ],
      },
      { type: 'h3', text: 'Кадры-доказательства' },
      ...(e.evidence
        ? await frameEvidenceBlocks(e.evidence.frames, { maxFrames: 2 })
        : [{ type: 'p' as const, text: 'Кадры недоступны' }]),
      { type: 'h3', text: 'Нормативный контекст (кратко)' },
      {
        type: 'p',
        text: meta?.normative_formulation || 'Рекомендуется проверка по контракту и документации.',
      },
      { type: 'h3', text: 'План действий' },
      {
        type: 'p',
        text: meta?.next_action || e.evidence?.card?.check || 'Подтвердите или отклоните сигнал после проверки.',
      },
    )
  }

  blocks.push(
    { type: 'h2', text: 'Методика и ограничения' },
    { type: 'p', text: REPORT_METHODOLOGY },
    {
      type: 'bullet',
      text: 'Отсутствие объекта на кадре не означает его отсутствие на площадке.',
    },
    {
      type: 'bullet',
      text: 'Число дней отставания не выводится из фото: либо воспроизводимый расчёт, либо «Прогноз не рассчитан».',
    },
    { type: 'h2', text: 'Оговорка' },
    { type: 'p', text: REPORT_DISCLAIMER },
  )

  const blob = buildDocxBlob(blocks)
  const projectPart = safeName(opts.projectName) || safeName(opts.projectId || 'project') || 'project'
  downloadBlob(blob, `PlanSight_${projectPart}_сводный_отчёт_${reportDateStamp()}.docx`)
}

/** Сводный отчёт Строгино из сценариев доказательств v2. */
export async function downloadStroginoProjectReportDocx(
  projectName: string,
  activities: ActivityLike[] = [],
  projectId = 'strogino',
): Promise<void> {
  const rows = listScenarioWarningRows(activities)
  await downloadProjectReportDocx({
    projectName,
    projectId,
    activities,
    warnings: rows.map((r) => ({
      id: r.id,
      code: r.code,
      title: scenarioShortTitle(scenarioIdFromUiDeviationId(r.id) || ''),
      schedule_item_name: r.schedule_item_name,
      explanation_ru: r.explanation_ru,
      priority: r.priority,
      observation_period: r.observation_period,
      evidence_frames: r.evidence_frames,
      review_status: r.review_status,
      signal_kind: r.signal_kind,
    })),
  })
}
