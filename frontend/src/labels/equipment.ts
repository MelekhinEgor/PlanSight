export const EQUIPMENT_RU: Record<string, string> = {
  excavator: 'Экскаватор',
  dump_truck: 'Самосвал',
  truck_unknown: 'Грузовик (не уточнён)',
  vehicle_unknown: 'Транспорт (не уточнён)',
  equipment_unknown: 'Объект/техника (не уточнены)',
  crane_unknown: 'Кран (тип не уточнён)',
  concrete_mixer: 'Автобетоносмеситель',
  concrete_pump: 'Бетононасос',
  bulldozer: 'Бульдозер',
  grader: 'Грейдер',
  roller: 'Каток',
  loader: 'Погрузчик',
  forklift: 'Вилочный погрузчик',
  telehandler: 'Телескопический погрузчик',
  mobile_crane: 'Автокран',
  loader_crane: 'Кран-манипулятор',
  person: 'Человек',
}

export function equipmentRu(code: string | null | undefined): string {
  if (!code) return '—'
  const key = String(code).trim()
  return EQUIPMENT_RU[key] || EQUIPMENT_RU[key.toLowerCase()] || key.replace(/_/g, ' ')
}

export function equipmentListRu(items: (string | null | undefined)[] | null | undefined): string {
  const vals = (items || []).map(equipmentRu).filter((x) => x && x !== '—')
  return vals.length ? vals.join(', ') : '—'
}

