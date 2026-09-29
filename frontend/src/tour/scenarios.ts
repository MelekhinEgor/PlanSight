import type { TourScenario } from './types'

/** Резолв `:projectId` в маршрутах сценария. */
export function resolveRoute(template: string, projectId: string): string {
  return template.replaceAll(':projectId', projectId)
}

/** Ключ прогресса основного quick-tour (human copy + logic dwell). */
export const QUICK_TOUR_STORAGE_KEY = 'plansight.tour.quick.v3'

/**
 * Продуктовый тренинг — реальные экраны, без авто-confirm предупреждений.
 * Тексты для строительства / PMO, не для инженеров.
 */
export function buildScenarios(projectId: string): TourScenario[] {
  const pid = projectId || '0'
  return [
    {
      id: 'quick',
      title: 'Быстрое знакомство',
      description: 'От портфеля до разбора предупреждения — около 5 минут',
      storageKey: QUICK_TOUR_STORAGE_KEY,
      steps: [
        {
          id: 'quick-portfolio',
          route: '/projects',
          target: 'portfolio-list',
          title: 'С чего начать',
          text: 'Откройте карточку объекта, который требует внимания: со статусом «Отстаёт» или «Риск». Так вы попадёте в рабочий контур проекта.',
          expectedAction: 'Откройте карточку проекта',
          successCondition: { type: 'route', includes: '/schedule' },
        },
        {
          id: 'quick-gantt',
          route: `/projects/${pid}/schedule`,
          target: 'gantt-workspace',
          title: 'Календарный график',
          text: 'Здесь видны работы и сроки по объекту. Это «план стройки» в системе: по нему сравнивают, что должно идти сейчас и что уже вызывает вопросы.',
          expectedAction: 'Осмотрите график',
          successCondition: { type: 'dwell', target: 'gantt-workspace', minMs: 9000, minRatio: 0.4 },
        },
        {
          id: 'quick-cameras',
          route: `/projects/${pid}/cameras`,
          target: 'camera-workspace',
          title: 'Камеры и зоны обзора',
          text: 'Сюда поступают снимки и видео с площадки. Зона на кадре — это область обзора; пока её не подтвердили, она ещё не равна конкретному корпусу или участку в графике.',
          expectedAction: 'Осмотрите раздел камер',
          successCondition: { type: 'dwell', target: 'camera-workspace', minMs: 9000, minRatio: 0.4 },
        },
        {
          id: 'quick-finding',
          route: `/projects/${pid}/deviations`,
          target: 'deviations-table',
          title: 'Список предупреждений',
          text: 'Откройте любую строку слева. Справа появится карточка: что заметили, к какой работе это относится и что стоит проверить.',
          expectedAction: 'Откройте строку предупреждения',
          successCondition: { type: 'click', target: 'deviations-table', pauseMs: 600 },
        },
        {
          id: 'quick-card',
          route: `/projects/${pid}/deviations`,
          target: 'finding-card',
          title: 'Карточка предупреждения',
          text: 'Во вкладке «Обзор» — краткий разбор простым языком. «Кадры» покажут фото, если они есть. Ничего не подтверждается само — решение остаётся за вами.',
          expectedAction: 'Просмотрите карточку',
          successCondition: { type: 'dwell', target: 'finding-card', minMs: 10000, minRatio: 0.3 },
          optional: true,
          missingHint: 'Сначала откройте предупреждение в списке слева — затем вернитесь к этому шагу или нажмите «Далее».',
        },
        {
          id: 'quick-logic-open',
          route: `/projects/${pid}/deviations`,
          target: 'finding-logic-tab',
          title: 'Почему система так решила',
          text: 'Если у предупреждения есть вкладка «Логика», откройте её. Там по шагам видно путь от камеры и зоны до работы в графике — без «чёрного ящика».',
          expectedAction: 'Нажмите «Логика»',
          successCondition: { type: 'click', target: 'finding-logic-tab', pauseMs: 800 },
          optional: true,
          missingHint: 'У этого предупреждения подробная цепочка может отсутствовать — это нормально. Нажмите «Далее».',
        },
        {
          id: 'quick-logic-read',
          route: `/projects/${pid}/deviations`,
          target: 'finding-logic-panel',
          title: 'Цепочка разбора',
          text: 'Прочитайте шаги: что увидели на площадке, к какой работе это сопоставили и какое правило сработало. Обучение само ничего не подтверждает и не меняет статусы.',
          expectedAction: 'Ознакомьтесь с цепочкой',
          successCondition: { type: 'dwell', target: 'finding-logic-panel', minMs: 14000, minRatio: 0.2 },
          optional: true,
          missingHint: 'Цепочка не открылась — можно продолжить без неё. Нажмите «Далее».',
        },
        {
          id: 'quick-impact',
          route: `/projects/${pid}/schedule`,
          target: 'gantt-workspace',
          title: 'Влияние на сроки',
          text: 'После разбора предупреждения можно оценить, как задержка одной работы сдвинет связанные. Если связей в графике мало, прогноз может быть недоступен — это ожидаемо, а не сбой.',
          expectedAction: 'Осмотрите график',
          successCondition: { type: 'dwell', target: 'gantt-workspace', minMs: 9000, minRatio: 0.4 },
        },
      ],
    },
    {
      id: 'finding',
      title: 'Как проверить предупреждение',
      description: 'Открыть сигнал, прочитать разбор, понять действия',
      steps: [
        {
          id: 'find-list',
          route: `/projects/${pid}/deviations`,
          target: 'deviations-table',
          title: 'Выберите предупреждение',
          text: 'Удобнее начать с сигнала по камерам или комбинированного: у него обычно есть кадры и понятный разбор.',
          expectedAction: 'Откройте строку в списке',
          successCondition: { type: 'click', target: 'deviations-table', pauseMs: 500 },
        },
        {
          id: 'find-card',
          route: `/projects/${pid}/deviations`,
          target: 'finding-card',
          title: 'Разберите карточку',
          text: 'Сначала «Обзор», затем при необходимости «Кадры». Так вы быстро поймёте суть, не углубляясь в технические детали.',
          expectedAction: 'Просмотрите карточку',
          successCondition: { type: 'dwell', target: 'finding-card', minMs: 10000, minRatio: 0.3 },
          optional: true,
          missingHint: 'Откройте предупреждение слева, чтобы увидеть карточку.',
        },
        {
          id: 'find-logic',
          route: `/projects/${pid}/deviations`,
          target: 'finding-logic-tab',
          title: 'Откройте «Логику»',
          text: 'Вкладка появляется, когда система сохранила цепочку рассуждений. Откройте её — следующий шаг даст время спокойно прочитать текст.',
          expectedAction: 'Нажмите «Логика»',
          successCondition: { type: 'click', target: 'finding-logic-tab', pauseMs: 800 },
          optional: true,
          missingHint: 'Подробной логики для этой записи нет — перейдите дальше.',
        },
        {
          id: 'find-logic-read',
          route: `/projects/${pid}/deviations`,
          target: 'finding-logic-panel',
          title: 'Прочитайте цепочку',
          text: 'Это ответ на вопрос «почему именно так». Подтверждать или отклонять вывод нужно только осознанно — обучение на статусы не влияет.',
          expectedAction: 'Прочитайте шаги разбора',
          successCondition: { type: 'dwell', target: 'finding-logic-panel', minMs: 14000, minRatio: 0.2 },
          optional: true,
          missingHint: 'Цепочка не отображается — нажмите «Далее».',
        },
        {
          id: 'find-ack-explain',
          route: `/projects/${pid}/deviations`,
          target: 'finding-ack',
          title: 'Ваши действия',
          text: '«Принять к проверке», «Подтвердить» или «Отклонить» меняют данные только после вашего нажатия. Обучение лишь показывает, где находятся эти кнопки.',
          expectedAction: 'Осмотрите блок действий внизу карточки',
          successCondition: { type: 'dwell', target: 'finding-ack', minMs: 9000, minRatio: 0.3 },
          optional: true,
          missingHint: 'Кнопки действий появятся после открытия предупреждения.',
        },
      ],
    },
    {
      id: 'gantt',
      title: 'Календарный график',
      description: 'Работы, сроки и актуальная версия плана',
      steps: [
        {
          id: 'gantt-title',
          route: `/projects/${pid}/schedule`,
          target: 'schedule-title',
          title: 'Объект и версия плана',
          text: 'В шапке — название объекта и пометка «Актуальная версия». Так вы понимаете, с каким планом работаете сейчас.',
          expectedAction: 'Осмотрите заголовок',
          successCondition: { type: 'dwell', target: 'schedule-title', minMs: 7000, minRatio: 0.35 },
        },
        {
          id: 'gantt-board',
          route: `/projects/${pid}/schedule`,
          target: 'gantt-workspace',
          title: 'Работы на шкале времени',
          text: 'Листайте список работ и полосы сроков. Проверочные сценарии «что если» не меняют утверждённый график сами — только показывают прогноз.',
          expectedAction: 'Осмотрите график',
          successCondition: { type: 'dwell', target: 'gantt-workspace', minMs: 9000, minRatio: 0.4 },
        },
      ],
    },
    {
      id: 'cameras',
      title: 'Камеры и наблюдения',
      description: 'Откуда берутся снимки с площадки',
      steps: [
        {
          id: 'cam-workspace',
          route: `/projects/${pid}/cameras`,
          target: 'camera-workspace',
          title: 'Рабочая область камер',
          text: 'Слева — камеры, справа — кадр и зоны. Здесь видно, что реально попало в обзор, и можно уточнить привязку к участку.',
          expectedAction: 'Осмотрите раздел',
          successCondition: { type: 'dwell', target: 'camera-workspace', minMs: 9000, minRatio: 0.4 },
        },
        {
          id: 'cam-ingest',
          route: `/projects/${pid}/cameras`,
          target: 'observation-source-cta',
          title: 'Добавить наблюдения',
          text: 'Через эту кнопку загружают снимки или короткое видео с площадки. Онлайн-поток с камер пока в планах развития — в обучении он не имитируется.',
          expectedAction: 'Нажмите кнопку или «Далее»',
          successCondition: { type: 'click', target: 'observation-source-cta', pauseMs: 500 },
          optional: true,
          missingHint: 'Кнопка появится, когда открыт раздел камер. Можно продолжить без неё.',
        },
      ],
    },
    {
      id: 'catalogs',
      title: 'Справочники',
      description: 'Для администратора: виды работ и техника',
      steps: [
        {
          id: 'admin-catalogs',
          route: '/admin/catalogs',
          target: 'admin-catalogs',
          title: 'Общие справочники',
          text: 'Здесь настраивают каталоги видов работ и техники. Обучение их не меняет — только показывает, где живут эталоны для сопоставления с графиком.',
          expectedAction: 'Осмотрите раздел',
          successCondition: { type: 'dwell', target: 'admin-catalogs', minMs: 8000, minRatio: 0.35 },
        },
      ],
    },
  ]
}
