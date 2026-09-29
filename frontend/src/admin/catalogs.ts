import { WORK_TYPES_LTC } from './workTypesLtc'
import {
  EQUIPMENT_CATEGORY_LABEL,
  getEquipmentCatalog,
} from './equipmentCatalog'

export type CatalogKey='work-types'|'equipment'

export type CatalogMeta={
  key:CatalogKey
  name:string
  description:string
  /** false — каталог остаётся в registry, но скрыт из UI */
  visible:boolean
}

export type CatalogRecord={
  id:string
  code:string
  name:string
  unit:string
  status:'active'|'archived'
  updatedAt:string
  group?:string
  /** Мост кода техники CV/KB */
  cvCode?:string
  /** Код вида работ KB, если строка каталога pipeline-native */
  kbCode?:string
}

/** Реестр всех каталогов. Новые ключи сюда; visible:true — показать в UI. */
export const CATALOG_REGISTRY:CatalogMeta[]=[
  {
    key:'work-types',
    name:'Виды работ',
    description:'Виды работ KB + профили техники (связаны с детекцией на камерах)',
    visible:true,
  },
  {
    key:'equipment',
    name:'Техника',
    description:'Справочник машин и механизмов для WorkProfile',
    visible:true,
  },
]

function equipmentAsRecords():CatalogRecord[]{
  return getEquipmentCatalog().map(e=>({
    id:e.id,
    code:e.code??e.id,
    name:e.name,
    unit:e.unit??'маш.-ч',
    status:'active' as const,
    updatedAt:'2026-09-18',
    group:EQUIPMENT_CATEGORY_LABEL[e.category],
  }))
}

export function getVisibleCatalogs(){
  return CATALOG_REGISTRY.filter(c=>c.visible)
}

export function getDefaultCatalogKey(){
  return getVisibleCatalogs()[0]?.key??'work-types'
}

export function getCatalogMeta(key:CatalogKey){
  return CATALOG_REGISTRY.find(c=>c.key===key)
}

export function isCatalogVisible(key:string):key is CatalogKey{
  return CATALOG_REGISTRY.some(c=>c.key===key&&c.visible)
}

export function getCatalogRecords(key:CatalogKey){
  if(key==='equipment')return equipmentAsRecords()
  return (WORK_TYPES_LTC as CatalogRecord[]).map(r=>({...r}))
}
