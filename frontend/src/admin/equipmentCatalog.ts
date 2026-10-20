export type EquipmentCategory='earth'|'transport'|'lift'|'other'

export type EquipmentItem={
  id:string
  name:string
  category:EquipmentCategory
  code?:string
  unit?:string
  /** Код CV/KB (excavator, dump_truck…) — связь с пайплайном */
  cvCode?:string
}

export const EQUIPMENT_CATEGORY_LABEL:Record<EquipmentCategory,string>={
  earth:'Землеройная',
  transport:'Транспорт',
  lift:'Подъёмная',
  other:'Прочая',
}

const LABEL_TO_CATEGORY:Record<string,EquipmentCategory>=Object.fromEntries(
  (Object.entries(EQUIPMENT_CATEGORY_LABEL) as [EquipmentCategory,string][]).map(([k,v])=>[v,k])
)

/** Базовый seed справочника техники (cvCode = код детектора/KB) */
export const EQUIPMENT_SEED:EquipmentItem[]=[
  {id:'eq-excavator',name:'Экскаватор',category:'earth',code:'EQ-001',unit:'маш.-ч',cvCode:'excavator'},
  {id:'eq-mini-excavator',name:'Мини-экскаватор',category:'earth',code:'EQ-002',unit:'маш.-ч',cvCode:'excavator'},
  {id:'eq-bulldozer',name:'Бульдозер',category:'earth',code:'EQ-003',unit:'маш.-ч',cvCode:'bulldozer'},
  {id:'eq-loader',name:'Погрузчик',category:'earth',code:'EQ-004',unit:'маш.-ч',cvCode:'loader'},
  {id:'eq-drill',name:'Буровая установка',category:'earth',code:'EQ-005',unit:'маш.-ч',cvCode:'equipment_unknown'},
  {id:'eq-dump',name:'Самосвал',category:'transport',code:'EQ-006',unit:'маш.-ч',cvCode:'dump_truck'},
  {id:'eq-truck',name:'Грузовой автомобиль',category:'transport',code:'EQ-007',unit:'маш.-ч',cvCode:'truck_unknown'},
  {id:'eq-mixer',name:'Автобетоносмеситель',category:'transport',code:'EQ-008',unit:'маш.-ч',cvCode:'concrete_mixer'},
  {id:'eq-crane',name:'Автокран',category:'lift',code:'EQ-009',unit:'маш.-ч',cvCode:'mobile_crane'},
  {id:'eq-tower-crane',name:'Башенный кран',category:'lift',code:'EQ-010',unit:'маш.-ч',cvCode:'crane_unknown'},
  {id:'eq-lift',name:'Автовышка',category:'lift',code:'EQ-011',unit:'маш.-ч',cvCode:'equipment_unknown'},
]

/** @deprecated use getEquipmentCatalog() — оставлен для совместимости импортов */
export const EQUIPMENT_CATALOG=EQUIPMENT_SEED

const STORAGE_KEY='plansight-equipment-v1'
type Listener=()=>void
const listeners=new Set<Listener>()
let live:EquipmentItem[]=loadLive()

function loadLive():EquipmentItem[]{
  try{
    const raw=localStorage.getItem(STORAGE_KEY)
    if(!raw)return EQUIPMENT_SEED.map(e=>({...e}))
    const parsed=JSON.parse(raw) as EquipmentItem[]
    if(!Array.isArray(parsed)||!parsed.length)return EQUIPMENT_SEED.map(e=>({...e}))
    return parsed.map(e=>({...e}))
  }catch{
    return EQUIPMENT_SEED.map(e=>({...e}))
  }
}

function persist(){
  try{localStorage.setItem(STORAGE_KEY,JSON.stringify(live))}catch{/* игнорировать */}
}

function emit(){listeners.forEach(l=>l())}

export function getEquipmentCatalog(){
  // Стабильная ссылка нужна для useSyncExternalStore getSnapshot
  return live
}

export function subscribeEquipment(listener:Listener){
  listeners.add(listener)
  return()=>{listeners.delete(listener)}
}

export function categoryFromGroup(group?:string):EquipmentCategory{
  if(!group)return 'other'
  return LABEL_TO_CATEGORY[group]??'other'
}

export function setEquipmentCatalog(items:EquipmentItem[]){
  live=items.map(e=>({...e}))
  persist()
  emit()
}

/** Синхронизация из таблицы справочника «Техника» */
export function syncEquipmentFromRecords(rows:{id:string;code:string;name:string;unit:string;group?:string;cvCode?:string}[]){
  const seedById=Object.fromEntries(EQUIPMENT_SEED.map(e=>[e.id,e]))
  const next=rows.map(r=>({
    id:r.id,
    name:r.name,
    code:r.code,
    unit:r.unit,
    category:categoryFromGroup(r.group),
    cvCode:r.cvCode||seedById[r.id]?.cvCode||live.find(x=>x.id===r.id)?.cvCode,
  }))
  const same=
    next.length===live.length&&
    next.every((item,i)=>{
      const cur=live[i]
      return cur&&cur.id===item.id&&cur.name===item.name&&cur.code===item.code&&cur.unit===item.unit&&cur.category===item.category&&cur.cvCode===item.cvCode
    })
  if(same)return
  setEquipmentCatalog(next)
}

export function getEquipmentById(id:string){
  return live.find(e=>e.id===id)
}

export function equipmentByCategory(list?:EquipmentItem[]){
  const source=list??live
  const map=new Map<EquipmentCategory,EquipmentItem[]>()
  for(const item of source){
    const arr=map.get(item.category)??[]
    arr.push(item)
    map.set(item.category,arr)
  }
  return map
}
