import { getEquipmentById, getEquipmentCatalog } from './equipmentCatalog'

export type EquipmentRole='required'|'expected'|'optional'

export type WorkEquipmentLink={
  equipmentId:string
  role:EquipmentRole
  minQty:number
}

export type WorkProfile={
  workTypeId:string
  items:WorkEquipmentLink[]
  /** false = авто-предложение, ждёт подтверждения */
  confirmed:boolean
  source:'manual'|'auto'
}

export const ROLE_LABEL:Record<EquipmentRole,string>={
  required:'Обязательная',
  expected:'Ожидаемая',
  optional:'Дополнительная',
}

export type TechniqueStatus='empty'|'ok'|'review'

export function profileStatus(profile?:WorkProfile|null):TechniqueStatus{
  if(!profile?.items.length)return 'empty'
  if(!profile.confirmed)return 'review'
  return 'ok'
}

export function statusLabel(status:TechniqueStatus,count:number){
  if(status==='empty')return 'Не настроено'
  if(status==='review')return 'Требует проверки'
  const n=count%100
  const n1=count%10
  const word=n>=11&&n<=14?'типов':n1===1?'тип':n1>=2&&n1<=4?'типа':'типов'
  return `${count} ${word} техники`
}

export function compactTechniqueNames(profile?:WorkProfile|null,limit=2){
  const names=(profile?.items??[])
    .map(i=>getEquipmentById(i.equipmentId)?.name)
    .filter(Boolean) as string[]
  const shown=names.slice(0,limit)
  const rest=Math.max(0,names.length-limit)
  return {shown,rest,total:names.length}
}

/** Авто-предложения по ключевым словам в наименовании работы */
export function suggestProfile(workTypeId:string,workName:string):WorkProfile|null{
  const n=workName.toLowerCase()
  const items:WorkEquipmentLink[]=[]
  const add=(equipmentId:string,role:EquipmentRole,minQty:number)=>{
    if(items.some(i=>i.equipmentId===equipmentId))return
    if(!getEquipmentCatalog().some(e=>e.id===equipmentId))return
    items.push({equipmentId,role,minQty})
  }

  if(/котлован|землян|разработк|выемк|транше/.test(n)){
    add('eq-excavator','required',1)
    add('eq-dump','required',2)
    add('eq-loader','expected',1)
    add('eq-bulldozer','optional',1)
  }else if(/свай|бурен|фундамент/.test(n)){
    add('eq-drill','required',1)
    add('eq-crane','expected',1)
  }else if(/монтаж.*кран|башенн|подъем|подъём/.test(n)){
    add('eq-crane','required',1)
  }else if(/бетон|опалубк|монолит/.test(n)){
    add('eq-mixer','expected',1)
    add('eq-crane','expected',1)
  }else if(/окон|фасад|витраж/.test(n)){
    add('eq-lift','required',1)
  }else if(/вынос.*сет|демонтаж|снос/.test(n)){
    add('eq-excavator','expected',1)
    add('eq-dump','expected',1)
  }else if(/погрузк|мусор|перевоз/.test(n)){
    add('eq-dump','required',1)
    add('eq-loader','expected',1)
  }

  if(!items.length)return null
  return {workTypeId,items,confirmed:false,source:'auto'}
}

export function cloneProfile(p:WorkProfile):WorkProfile{
  return {...p,items:p.items.map(i=>({...i}))}
}
