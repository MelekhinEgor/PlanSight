export type DecisionSchemeNode = {
  id: string
  title: string
  status: 'passed' | 'limited' | 'unknown'
  result: string
  detail?: string
}

const CLASS_COLOR: Record<string, string> = {
  excavator: '#d4a017',
  tower_crane: '#2f6fed',
  wheel_machine: '#2a9d8f',
  wheel_construction_equipment: '#2a9d8f',
  wheel_loader: '#c47a3a',
  pile_drilling_rig: '#8e44ad',
  dump_truck: '#c0392b',
  concrete_mixer: '#16a085',
  mobile_crane: '#2980b9',
}

export function demoClassColor(colorKey?: string | null, equipmentCode?: string | null): string {
  const key = colorKey || equipmentCode || ''
  return CLASS_COLOR[key] || '#d4a017'
}
