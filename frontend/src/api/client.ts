import * as XLSX from 'xlsx'
import {applyCanonicalToActivities, calendarDepsFromRecovery, recoverNetworkModel, recoverNetworkModelWithQwen, refreshGroups, type NetworkRecoveryModel, type ProposedDependency} from '../network'
import {suggestProfile} from '../admin/workProfiles'
import {WORK_TYPES_LTC} from '../admin/workTypesLtc'
import {companyGroupName} from '../data/companyGroups'
import strogino360Rows from '../data/strogino360Schedule.json'
import { remote, useHttpBackend, setRemoteProjectId } from './remoteBackend'

export { setRemoteProjectId }
export type {NetworkRecoveryModel, ProposedDependency}
export type Project = { id:string; name:string; address:string|null; region:string|null; status:string; timezone:string; developer:{id:string;name:string;groupId:string|null}|null; imageUrl?:string|null; commissioning?:string|null; metro?:string|null; metroWalk?:string|null; slug?:string|null; is_demo?:boolean; badge_schedule?:string|null; badge_photos?:string|null; as_of?:string|null; data_origin?:string|null }
export type ProjectObject = { id:string; project_id:string; parent_id:string|null; name:string; object_type:string }
export type MappingDraftRow = {
  row_index: number
  source_name: string
  code: string | null
  canonical_work_id: string | null
  canonical_work_code: string | null
  canonical_work_name: string | null
  mapping_status: 'MATCHED' | 'AMBIGUOUS' | 'UNMAPPED'
  needs_confirmation: boolean
  /** 0..1 — уверенность мэтчинга (строковый score / Qwen) */
  confidence: number
  candidates: {id: string; code: string; name: string; score: number}[]
}

export type MappingOverride = {
  row_index: number
  canonical_work_id: string | null
}

export type ImportIssue = { level:'critical'|'warning'|'info'; code:string; message:string; row?:number|null }
export type ImportPreview = {
  filename:string; rows:number; activities:number; wbs_nodes:number; milestones:number; dependencies:number
  period_start:string|null; period_end:string|null; matched_works:number; manual_mapping_required:number
  mapped_columns:Record<string,string>; issues:ImportIssue[]; can_import:boolean
  network_summary?:NetworkRecoveryModel['summary']|null
  mapping_rows?:MappingDraftRow[]
}
export type ImportResult = ScheduleVersion & {network_recovery:NetworkRecoveryModel|null}
export type ScheduleVersion = { id:string; version:number; uploaded_at:string; is_active:boolean; source_filename:string; row_count:number; warning_count:number; version_state:'IMPORTED'|'WORKING'|'PUBLISHED'; parent_version_id:string|null; updated_at:string|null; published_at:string|null }
export type WbsNode = { id:string; parent_id:string|null; name:string; code:string|null; level:number; sort_order:number }
export type EvidenceComment={id:string;author:string;role:string;initials:string;text:string;at:string;kind:'user'|'pm'|'system'}
export type ScheduleActivity = { id:string; wbs_node_id:string|null; external_id:string|null; code:string|null; name:string; canonical_work_id:string|null; canonical_work_code:string|null; canonical_work_name:string|null; mapping_status:string; expected_equipment_profile_id:string|null; unit:string|null; actual_start:string|null; planned_start:string|null; planned_end:string|null; planned_duration:number|null; planned_quantity:number|null; planned_progress:number|null; actual_progress:number|null; forecast_end:string|null; activity_type:string; sort_order:number }
export type ScheduleDependency = { id:string; successor_activity_id:string; predecessor_activity_id:string|null; predecessor_reference:string; relation_type:string|null; lag_text:string|null; lag_days:number; raw_expression:string }
export type DependencyEdit = { id?:string|null; predecessor_activity_id:string; successor_activity_id:string; relation_type:'FS'|'SS'|'FF'|'SF'; lag_days:number }
export type ActivityEdit = { id:string; name?:string; code?:string|null; unit?:string|null; actual_start?:string|null; wbs_node_id?:string|null; planned_start?:string|null; planned_end?:string|null; planned_duration?:number|null; planned_quantity?:number|null; planned_progress?:number|null; actual_progress?:number|null; forecast_end?:string|null }
export type EditorSaveResult = { version_id:string; updated_activities:number; dependency_count:number; recalculated_activities:number; updated_at:string }
export type ScheduleResponse = { project_id:string; active_version:ScheduleVersion|null; wbs:WbsNode[]; activities:ScheduleActivity[]; dependencies:ScheduleDependency[]; network_recovery:NetworkRecoveryModel|null; selected_object_id?:string|null; analysis?:{as_of?:string; status?:string}; meta?:{as_of?:string; is_demo?:boolean; badge_schedule?:string|null; badge_photos?:string|null; data_origin?:string|null} }
export type PortfolioObject = { id:string; name:string; type:string; lat:number; lng:number }
export type SeverityWorks = { critical:number; high:number; medium:number; normal:number }
export type PortfolioRow = { id:string; developer:string; companyGroupId:string|null; companyGroup:string|null; name:string; region:string; address:string; status:string; problemWorks:number; maxDeviation:number; change:number; lastAnalysis:string; lastAnalysisDate:string; totalWorks:number; progress:number; lat:number; lng:number; objects:PortfolioObject[]; severityWorks?:SeverityWorks; imageUrl?:string|null; commissioning?:string|null; metro?:string|null; metroWalk?:string|null; slug?:string|null; is_demo?:boolean; badge_schedule?:string|null; badge_photos?:string|null; as_of?:string|null; data_origin?:string|null; analysis_source?:string|null; status_source?:string|null; openFindings?:number; lastObservationAt?:string|null; lastCvAnalysisAt?:string|null }
export type PortfolioResponse = { projects:PortfolioRow[]; trend:{day:string;deviations:number}[]; as_of?:string; meta?:{as_of?:string; project_count?:number; trend_kind?:string; note?:string} }

type LocalVersion = { meta:ScheduleVersion; wbs:WbsNode[]; activities:ScheduleActivity[]; dependencies:ScheduleDependency[]; network_recovery?:NetworkRecoveryModel|null }
type LocalState = { projects:Project[]; objects:Record<string,ProjectObject[]>; schedules:Record<string,LocalVersion[]> }

const STORAGE_KEY='plansight_demo_frontend_v29'
const STORAGE_KEY_PREFIX='plansight_demo_frontend_'
const COMMENTS_KEY='plansight_evidence_comments_v2'
const DAY=86400000
const pad=(n:number)=>String(n).padStart(2,'0')
const isoDate=(d:Date)=>`${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`
const diffDays=(a:string,b:string)=>Math.round((new Date(`${b}T00:00:00Z`).getTime()-new Date(`${a}T00:00:00Z`).getTime())/DAY)
const uid=()=>Math.random().toString(36).slice(2,10)
const deep=<T,>(v:T):T=>JSON.parse(JSON.stringify(v))

const DEMO_SCHEDULE_FILE='demo_schedule.xlsx'
const DEMO_SCHEDULE_ROWS:Record<string,unknown>[]=[
  {'Код':'A01','WBS':'Подготовка','Наименование':'Получение РД','Ед. изм.':'компл.','Объем':1,'План %':100,'Факт %':100,'План. начало':'01.07.2026','План. окончание':'18.07.2026','Факт. начало':'01.07.2026','Прогноз':'18.07.2026','Предшественники':''},
  {'Код':'A02','WBS':'Подготовка','Наименование':'Разработка ППР','Ед. изм.':'компл.','Объем':1,'План %':100,'Факт %':100,'План. начало':'12.07.2026','План. окончание':'28.07.2026','Факт. начало':'12.07.2026','Прогноз':'28.07.2026','Предшественники':'A01SS+5'},
  {'Код':'A03','WBS':'Подготовка','Наименование':'Мобилизация техники','Ед. изм.':'компл.','Объем':1,'План %':100,'Факт %':100,'План. начало':'22.07.2026','План. окончание':'05.08.2026','Факт. начало':'22.07.2026','Прогноз':'05.08.2026','Предшественники':'A02FS'},
  {'Код':'A04','WBS':'Подготовка','Наименование':'Организация стройплощадки','Ед. изм.':'компл.','Объем':1,'План %':100,'Факт %':100,'План. начало':'01.08.2026','План. окончание':'14.08.2026','Факт. начало':'01.08.2026','Прогноз':'14.08.2026','Предшественники':'A03FS'},
  {'Код':'A05','WBS':'Нулевой цикл','Наименование':'Разработка котлована','Ед. изм.':'м3','Объем':18420,'План %':100,'Факт %':100,'План. начало':'10.08.2026','План. окончание':'28.08.2026','Факт. начало':'10.08.2026','Прогноз':'28.08.2026','Предшественники':'A04FS'},
  {'Код':'A06','WBS':'Нулевой цикл','Наименование':'Вывоз грунта','Ед. изм.':'м3','Объем':15200,'План %':100,'Факт %':100,'План. начало':'12.08.2026','План. окончание':'30.08.2026','Факт. начало':'12.08.2026','Прогноз':'30.08.2026','Предшественники':'A05SS+2'},
  {'Код':'A07','WBS':'Нулевой цикл','Наименование':'Устройство свайного основания','Ед. изм.':'шт.','Объем':640,'План %':100,'Факт %':92,'План. начало':'29.08.2026','План. окончание':'14.09.2026','Факт. начало':'29.08.2026','Прогноз':'25.09.2026','Предшественники':'A05FS'},
  {'Код':'A08','WBS':'Нулевой цикл','Наименование':'Ростверк','Ед. изм.':'м3','Объем':2100,'План %':88,'Факт %':70,'План. начало':'10.09.2026','План. окончание':'02.10.2026','Факт. начало':'12.09.2026','Прогноз':'06.10.2026','Предшественники':'A07SS+8'},
  {'Код':'A09','WBS':'Нулевой цикл','Наименование':'Фундаментная плита','Ед. изм.':'м3','Объем':4250,'План %':65,'Факт %':48,'План. начало':'08.09.2026','План. окончание':'07.10.2026','Факт. начало':'10.09.2026','Прогноз':'12.10.2026','Предшественники':'A07FS'},
  {'Код':'A10','WBS':'Каркас','Наименование':'Монолитный каркас секция 1','Ед. изм.':'м3','Объем':5200,'План %':42,'Факт %':28,'План. начало':'01.09.2026','План. окончание':'20.11.2026','Факт. начало':'05.09.2026','Прогноз':'28.11.2026','Предшественники':'A09FS'},
  {'Код':'A11','WBS':'Каркас','Наименование':'Монолитный каркас секция 2','Ед. изм.':'м3','Объем':4650,'План %':30,'Факт %':12,'План. начало':'25.10.2026','План. окончание':'16.12.2026','Факт. начало':'','Прогноз':'24.12.2026','Предшественники':'A10SS+12'},
  {'Код':'A12','WBS':'Каркас','Наименование':'Лестничные клетки','Ед. изм.':'м3','Объем':980,'План %':18,'Факт %':5,'План. начало':'10.11.2026','План. окончание':'20.12.2026','Факт. начало':'','Прогноз':'28.12.2026','Предшественники':'A10SS+20'},
  {'Код':'A13','WBS':'Контур','Наименование':'Кладка наружных стен','Ед. изм.':'м2','Объем':12400,'План %':10,'Факт %':4,'План. начало':'20.10.2026','План. окончание':'24.11.2026','Факт. начало':'','Прогноз':'02.12.2026','Предшественники':'A10SS+8'},
  {'Код':'A14','WBS':'Контур','Наименование':'Монтаж окон','Ед. изм.':'м2','Объем':5200,'План %':0,'Факт %':0,'План. начало':'15.11.2026','План. окончание':'14.12.2026','Факт. начало':'','Прогноз':'20.12.2026','Предшественники':'A13SS+10'},
  {'Код':'A15','WBS':'Контур','Наименование':'Устройство фасада','Ед. изм.':'м2','Объем':16800,'План %':0,'Факт %':0,'План. начало':'01.12.2026','План. окончание':'17.01.2027','Факт. начало':'','Прогноз':'28.01.2027','Предшественники':'A14SS+10'},
  {'Код':'A16','WBS':'Контур','Наименование':'Кровля','Ед. изм.':'м2','Объем':3200,'План %':0,'Факт %':0,'План. начало':'05.12.2026','План. окончание':'30.12.2026','Факт. начало':'','Прогноз':'10.01.2027','Предшественники':'A11FS'},
  {'Код':'A17','WBS':'Инженерия','Наименование':'Внутренние сети ХВС/ГВС','Ед. изм.':'компл.','Объем':1,'План %':0,'Факт %':0,'План. начало':'20.12.2026','План. окончание':'15.02.2027','Факт. начало':'','Прогноз':'22.02.2027','Предшественники':'A12FS'},
  {'Код':'A18','WBS':'Инженерия','Наименование':'Электромонтажные работы','Ед. изм.':'компл.','Объем':1,'План %':0,'Факт %':0,'План. начало':'10.01.2027','План. окончание':'05.03.2027','Факт. начало':'','Прогноз':'12.03.2027','Предшественники':'A16FS'},
  {'Код':'A19','WBS':'Инженерия','Наименование':'Вентиляция и кондиционирование','Ед. изм.':'компл.','Объем':1,'План %':0,'Факт %':0,'План. начало':'20.01.2027','План. окончание':'20.03.2027','Факт. начало':'','Прогноз':'28.03.2027','Предшественники':'A17SS+15'},
  {'Код':'A20','WBS':'Отделка','Наименование':'Черновая отделка','Ед. изм.':'м2','Объем':28600,'План %':0,'Факт %':0,'План. начало':'15.02.2027','План. окончание':'20.04.2027','Факт. начало':'','Прогноз':'28.04.2027','Предшественники':'A17FS'},
  {'Код':'A21','WBS':'Отделка','Наименование':'Чистовая отделка МОП','Ед. изм.':'м2','Объем':4200,'План %':0,'Факт %':0,'План. начало':'01.04.2027','План. окончание':'25.05.2027','Факт. начало':'','Прогноз':'05.06.2027','Предшественники':'A20SS+20'},
  {'Код':'A22','WBS':'Отделка','Наименование':'Благоустройство территории','Ед. изм.':'компл.','Объем':1,'План %':0,'Факт %':0,'План. начало':'10.05.2027','План. окончание':'30.06.2027','Факт. начало':'','Прогноз':'10.07.2027','Предшественники':'A15FS'},
]
const DEMO_SCHEDULE_MAPPED:Record<string,string>={
  code:'Код',wbs:'WBS',name:'Наименование',unit:'Ед. изм.',qty:'Объем',plan:'План %',fact:'Факт %',
  start:'План. начало',end:'План. окончание',actualStart:'Факт. начало',forecast:'Прогноз',pred:'Предшественники',
}
const STROGINO_SCHEDULE_FILE='PlanSight_Строгино360_4_колонки_для_загрузки.xlsx'
const STROGINO_SCHEDULE_MAPPED:Record<string,string>={code:'code',wbs:'wbs',name:'name',start:'start',end:'end'}
const STROGINO_SCHEDULE_ROWS=(strogino360Rows as {code:string;wbs:string;name:string;start:string|null;end:string|null}[]).map(r=>({
  code:r.code,wbs:r.wbs,name:r.name,start:r.start??'',end:r.end??'',
}))

function toIsoDate(v:unknown):string|null{
  if(v==null||v==='')return null
  if(typeof v==='number'){
    try{
      const d=XLSX.SSF?.parse_date_code?.(v)
      if(d)return `${d.y}-${pad(d.m)}-${pad(d.d)}`
    }catch{/* запасной вариант ниже */}
    const utc=Math.round((v-25569)*86400*1000)
    const dt=new Date(utc)
    return Number.isNaN(dt.getTime())?null:`${dt.getUTCFullYear()}-${pad(dt.getUTCMonth()+1)}-${pad(dt.getUTCDate())}`
  }
  const s=String(v).trim();const m=s.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2,4})$/);if(m){const y=m[3].length===2?`20${m[3]}`:m[3];return `${y}-${pad(Number(m[2]))}-${pad(Number(m[1]))}`}
  if(/^\d{4}-\d{2}-\d{2}/.test(s))return s.slice(0,10)
  const d=new Date(s);return Number.isNaN(d.getTime())?null:isoDate(d)
}
function n(v:unknown){const x=Number(String(v??'').replace(',','.').replace(/\s/g,''));return Number.isFinite(x)?x:null}

/** Родительский код: "1.3.2.1.3" → "1.3.2.1" */
function parentCodeOf(code:string):string|null{
  const i=code.lastIndexOf('.')
  return i>0?code.slice(0,i):null
}

/** Имя листа Excel / техническая обёртка — не строительный этап */
function isSheetLikeWbs(name:string){
  const n=name.trim().toLowerCase().replace(/ё/g,'е')
  return /^(график|schedule|gantt|лист(\s*\d+)?|sheet(\s*\d+)?|book\d*|таблица)$/i.test(n)
}

/** Убрать узлы вроде «График»: детей и работы поднять к родителю */
function pruneSheetLikeWbs(wbs:WbsNode[],activities:ScheduleActivity[]):{wbs:WbsNode[];activities:ScheduleActivity[]}{
  const byId=new Map(wbs.map(n=>[n.id,n]))
  const remove=new Set(wbs.filter(n=>isSheetLikeWbs(n.name)).map(n=>n.id))
  if(!remove.size)return {wbs,activities}
  const resolveParent=(id:string|null):string|null=>{
    let cur=id
    while(cur&&remove.has(cur))cur=byId.get(cur)?.parent_id??null
    return cur
  }
  const nextWbs=wbs.filter(n=>!remove.has(n.id)).map(n=>({...n,parent_id:resolveParent(n.parent_id)}))
  const levelOf=(id:string|null,guard=0):number=>{
    if(!id||guard>50)return 0
    const n=nextWbs.find(x=>x.id===id)
    if(!n)return 0
    return n.parent_id==null?0:levelOf(n.parent_id,guard+1)+1
  }
  nextWbs.forEach(n=>{n.level=levelOf(n.parent_id)})
  const nextActs=activities.map(a=>({
    ...a,
    wbs_node_id:a.wbs_node_id&&remove.has(a.wbs_node_id)?resolveParent(a.wbs_node_id):a.wbs_node_id,
  }))
  return {wbs:nextWbs,activities:nextActs}
}

/** Строки с детьми по dotted-коду → WBS; листья → работы. Без иерархии кодов — плоский WBS из колонки. */
function buildImported(projectId:string,fileName:string,rows:Record<string,unknown>[],mapped:Record<string,string>,version:number,parent:string|null,rootName?:string,network_recovery?:NetworkRecoveryModel|null):LocalVersion{
  const named=rows.map((r,i)=>({r,i})).filter(({r})=>String(r[mapped.name]??'').trim())
  const codeOf=(r:Record<string,unknown>,i:number)=>String(r[mapped.code]||`A${pad(i+1)}`).trim()
  const codes=named.map(({r,i})=>codeOf(r,i))
  const codeSet=new Set(codes)
  const parentCodes=new Set<string>()
  codes.forEach(c=>{for(const other of codeSet){if(other!==c&&other.startsWith(`${c}.`)){parentCodes.add(c);break}}})

  let wbs:WbsNode[]=[]
  let activities:ScheduleActivity[]=[]
  const leafRows: {r:Record<string,unknown>;i:number;code:string;wbs_node_id:string}[]=[]

  if(parentCodes.size>0){
    const wbsIdByCode=new Map<string,string>()
    const parents=[...parentCodes].sort((a,b)=>{
      const da=a.split('.').length,db=b.split('.').length
      return da!==db?da-db:a.localeCompare(b,'en',{numeric:true})
    })
    const nameByCode=new Map(named.map(({r,i})=>[codeOf(r,i),String(r[mapped.name]).trim()]))
    parents.forEach((code,idx)=>{
      let parent_id:string|null=null
      let level=0
      let p=parentCodeOf(code)
      while(p){
        const id=wbsIdByCode.get(p)
        if(id){parent_id=id;level=(wbs.find(n=>n.id===id)?.level??0)+1;break}
        p=parentCodeOf(p)
      }
      const id=`${projectId}-imp-${version}-w${idx+1}`
      wbsIdByCode.set(code,id)
      wbs.push({id,parent_id,name:nameByCode.get(code)||code,code,level,sort_order:idx+1})
    })
    const nearestWbs=(code:string):string=>{
      let p=parentCodeOf(code)
      while(p){const id=wbsIdByCode.get(p);if(id)return id;p=parentCodeOf(p)}
      return wbs[0]?.id??`${projectId}-imp-${version}-w1`
    }
    named.forEach(({r,i})=>{
      const code=codeOf(r,i)
      if(parentCodes.has(code))return
      leafRows.push({r,i,code,wbs_node_id:nearestWbs(code)})
    })
  }else{
    // Плоский режим: разделы из колонки WBS как корни. Без узла «График» / имени листа.
    const wbsMap=new Map<string,string>()
    const projectRootId=`${projectId}-imp-${version}-root`
    const projectRootName=(rootName||'').trim()
    const ensureProjectRoot=()=>{
      if(wbs.some(n=>n.id===projectRootId))return projectRootId
      wbs.unshift({id:projectRootId,parent_id:null,name:projectRootName||'Проект',code:'0',level:0,sort_order:0})
      return projectRootId
    }
    const getWbs=(value:unknown)=>{
      const label=String(value||'').trim()
      if(!label||isSheetLikeWbs(label)){
        // Техническое имя листа — не создаём узел; работы вешаем на корень проекта только если нет других разделов
        return ensureProjectRoot()
      }
      if(wbsMap.has(label))return wbsMap.get(label)!
      const id=`${projectId}-imp-${version}-w${wbsMap.size+1}`
      wbsMap.set(label,id)
      wbs.push({id,parent_id:null,name:label,code:String(wbsMap.size),level:0,sort_order:wbsMap.size})
      return id
    }
    named.forEach(({r,i})=>{
      const code=codeOf(r,i)
      let wbsVal=mapped.wbs?r[mapped.wbs]:null
      if(!wbsVal||!String(wbsVal).trim()||isSheetLikeWbs(String(wbsVal))){
        const parts=code.split('.').filter(Boolean)
        wbsVal=parts.length>=2?`Раздел ${parts.slice(0,2).join('.')}`:null
      }
      leafRows.push({r,i,code,wbs_node_id:getWbs(wbsVal)})
    })
    // Если корень проекта пустой (все работы в именованных разделах) — убрать его
    if(wbs.some(n=>n.id===projectRootId)&&!leafRows.some(l=>l.wbs_node_id===projectRootId)&&!wbs.some(n=>n.parent_id===projectRootId)){
      wbs=wbs.filter(n=>n.id!==projectRootId)
    }
  }

  activities=leafRows.map(({r,i,code,wbs_node_id},ord)=>{
    const ps=toIsoDate(r[mapped.start]),pe=toIsoDate(r[mapped.end])
    const dur=ps&&pe?diffDays(ps,pe)+1:null
    return {id:`${projectId}-imp-${version}-a${ord+1}`,wbs_node_id,external_id:code,code,name:String(r[mapped.name]).trim(),canonical_work_id:null,canonical_work_code:null,canonical_work_name:null,mapping_status:'UNMAPPED',expected_equipment_profile_id:null,unit:mapped.unit?String(r[mapped.unit]||''):null,actual_start:toIsoDate(r[mapped.actualStart]),planned_start:ps,planned_end:pe,planned_duration:dur,planned_quantity:mapped.qty?n(r[mapped.qty]):null,planned_progress:mapped.plan?n(r[mapped.plan]):0,actual_progress:mapped.fact?n(r[mapped.fact]):0,forecast_end:toIsoDate(r[mapped.forecast])??pe,activity_type:'TASK',sort_order:ord+1}
  })

  ;({wbs,activities}=pruneSheetLikeWbs(wbs,activities))

  const byCode=new Map(activities.map(a=>[a.code??'',a.id]));const dependencies:ScheduleDependency[]=[]
  leafRows.forEach(({r,i},ord)=>{
    if(!mapped.pred)return
    const a=activities[ord];if(!a)return
    const raw=String(r[mapped.pred]??'').trim();if(!raw)return
    raw.split(/[;,]+/).map(x=>x.trim()).filter(Boolean).forEach((token,j)=>{
      const m=token.match(/^(.+?)(FS|SS|FF|SF)?([+-]\d+)?(?:d|д)?$/i)
      const ref=(m?.[1]??token).trim();const pred=byCode.get(ref);if(!pred)return
      const rel=(m?.[2]?.toUpperCase()||'FS') as 'FS'|'SS'|'FF'|'SF';const lag=Number(m?.[3]||0)
      dependencies.push({id:`${projectId}-imp-${version}-d${i}-${j}`,successor_activity_id:a.id,predecessor_activity_id:pred,predecessor_reference:ref,relation_type:rel,lag_text:lag?`${lag>0?'+':''}${lag}d`:null,lag_days:lag,raw_expression:token})
    })
  })

  // Сетевая модель: календарный анализ + авто-FS по датам + CanonicalWork (даты Excel не меняем)
  const recovery=network_recovery??recoverNetworkModel(
    activities.map(a=>({id:a.id,name:a.name,planned_start:a.planned_start,planned_end:a.planned_end,wbs_node_id:a.wbs_node_id,code:a.code})),
    dependencies.filter(d=>d.predecessor_activity_id).map(d=>({predecessor_activity_id:d.predecessor_activity_id!,successor_activity_id:d.successor_activity_id,relation_type:d.relation_type,lag_days:d.lag_days})),
  )
  activities=applyCanonicalToActivities(activities,recovery)

  // Материализуем базовое правило «последовательные даты → FS» в реальные связи графика
  const have=new Set(dependencies.filter(d=>d.predecessor_activity_id).map(d=>`${d.predecessor_activity_id}>${d.successor_activity_id}`))
  calendarDepsFromRecovery(recovery).forEach((d,i)=>{
    const key=`${d.predecessor_activity_id}>${d.successor_activity_id}`
    if(have.has(key))return
    have.add(key)
    const pred=activities.find(a=>a.id===d.predecessor_activity_id)
    dependencies.push({
      id:`${projectId}-imp-${version}-cfs${i+1}`,
      successor_activity_id:d.successor_activity_id,
      predecessor_activity_id:d.predecessor_activity_id,
      predecessor_reference:pred?.code??pred?.external_id??'',
      relation_type:d.relation_type,
      lag_text:d.lag_days?`${d.lag_days>0?'+':''}${d.lag_days}d`:null,
      lag_days:d.lag_days,
      raw_expression:'calendar:sequential-fs',
    })
  })

  const now=new Date().toISOString();const meta:ScheduleVersion={id:`${projectId}-v${version}-${uid()}`,version,uploaded_at:now,is_active:true,source_filename:fileName,row_count:activities.length,warning_count:recovery.summary.need_confirmation,version_state:'IMPORTED',parent_version_id:parent,updated_at:now,published_at:null}
  return {meta,wbs,activities,dependencies,network_recovery:recovery}
}

/** Явная привязка проекта → group_id (не выводится из названия юрлица) */
const PROJECT_GROUP_ID:Record<string,string>={
  parkline:'pik',
  strogino:'pik',
  amursky:'pik',
  teatralny:'krost',
  nevsky:'krost',
  pravda:'dars-development',
  plekhanova:'pik',
}

function seedState():LocalState{
  // [id, name, юр. имя застройщика, region, address, status, image, commissioning, metro, metroWalk]
  const projectDefs:[string,string,string,string,string,string,string,string|null,string|null,string|null][]=[
    ['parkline','ЖК «Зелёный парк»','АО СЗ ЗЕЛЕНОГРАДСКИЙ','Москва','Зеленоград','NO_DATA','/projects/zeleniy-park.png','II кв. 2027',null,null],
    ['strogino','ЖК «Строгино 360»','ООО СЗ ЛУЧ','Москва','Строгино','DELAYED','/projects/strogino-360.png','IV кв. 2028',null,null],
    ['amursky','ЖК «Амурский парк»','АО СЗ ГЛОРИ','Москва','Район Гольяново','ON_TRACK','/projects/amursky-park.png','I кв. 2029','Черкизовская','14 мин пешком'],
    ['teatralny','ЖК «Театральный квартал»','ООО СЗ ФРИЗ-ИНВЕСТ','Москва','ул. Ротмистрова','AT_RISK','/projects/teatralny-kvartal.png','IV кв. 2026','Октябрьское поле','13 мин пешком'],
    ['nevsky','NEVSKY PLAZA','ООО СЗ ПОДОЛИНО','Москва','Войковский район','ON_TRACK','/projects/nevsky-plaza.png','II кв. 2027','Водный стадион','12 мин пешком'],
    ['pravda','Апартаменты «Правда»','ООО СЗ ВЕГА','Москва','Район Беговой','AT_RISK','/projects/pravda.png','II кв. 2027','Савёловская','10 мин пешком'],
    ['plekhanova','ЖК «Плеханова 11»','ООО СЗ ЯСЕНЕВЫЙ ПАРК','Москва','Район Перово','DELAYED','/projects/plekhanova-11.png','III кв. 2026','Шоссе Энтузиастов','25 мин пешком'],
  ]
  const projects:Project[]=projectDefs.map((p,i)=>({id:p[0],name:p[1],developer:{id:`dev-${i+1}`,name:p[2],groupId:PROJECT_GROUP_ID[p[0]]??null},region:p[3],address:p[4],status:p[5],timezone:'Europe/Moscow',imageUrl:p[6],commissioning:p[7],metro:p[8],metroWalk:p[9]}))
  const objects:Record<string,ProjectObject[]>={}
  const schedules:Record<string,LocalVersion[]>={}
  const objectTrees:Record<string,{name:string;type:string;children?:{name:string;type:string}[]}[]>={
    parkline:[
      {name:'Этап строительства 1',type:'stage',children:[{name:'Корпус 1',type:'building'},{name:'Корпус 2',type:'building'}]},
      {name:'Этап строительства 2',type:'stage',children:[{name:'Детский сад',type:'building'},{name:'Паркинг',type:'parking'}]},
    ],
    strogino:[
      {name:'Этап строительства 1',type:'stage',children:[{name:'Корпус 1.1.1',type:'building'},{name:'Корпус 1.1.2',type:'building'},{name:'Корпус 1.1.3',type:'building'},{name:'Корпус 1.1.4',type:'building'},{name:'Корпус 1.1.5',type:'building'}]},
      {name:'Этап строительства 2',type:'stage',children:[{name:'Корпус 1.2',type:'building'},{name:'Корпус 1.3',type:'building'},{name:'Наружные сети / благоустройство',type:'site'}]},
    ],
    amursky:[{name:'Этап строительства 1',type:'stage',children:[{name:'Корпус 1',type:'building'},{name:'Корпус 2',type:'building'},{name:'Корпус 3',type:'building'},{name:'Паркинг',type:'parking'}]}],
    teatralny:[{name:'Этап строительства 1',type:'stage',children:[{name:'Корпус 1',type:'building'},{name:'Корпус 2',type:'building'},{name:'Корпус 3',type:'building'},{name:'Корпус 4',type:'building'}]}],
    nevsky:[{name:'Этап строительства 1',type:'stage',children:[{name:'Башня A',type:'building'},{name:'Башня B',type:'building'},{name:'Стилобат',type:'building'}]}],
    pravda:[{name:'Этап строительства 1',type:'stage',children:[{name:'Башня',type:'building'},{name:'Коммерция',type:'building'},{name:'Паркинг',type:'parking'}]}],
    plekhanova:[{name:'Этап строительства 1',type:'stage',children:[{name:'Корпус 1',type:'building'},{name:'Корпус 2',type:'building'},{name:'Корпус 3',type:'building'},{name:'Корпус 4',type:'building'}]}],
  }
  projects.forEach(p=>{
    const tree=objectTrees[p.id]??[{name:'Этап строительства 1',type:'stage',children:[{name:'Объект 1',type:'building'}]}]
    const list:ProjectObject[]=[];let n=0
    tree.forEach(stage=>{
      const stageId=`${p.id}-obj-${++n}`;list.push({id:stageId,project_id:p.id,parent_id:null,name:stage.name,object_type:stage.type})
      ;(stage.children??[]).forEach(child=>list.push({id:`${p.id}-obj-${++n}`,project_id:p.id,parent_id:stageId,name:child.name,object_type:child.type}))
    })
    objects[p.id]=list
    const scheduleRows=p.id==='strogino'?STROGINO_SCHEDULE_ROWS:DEMO_SCHEDULE_ROWS
    const scheduleMapped=p.id==='strogino'?STROGINO_SCHEDULE_MAPPED:DEMO_SCHEDULE_MAPPED
    const scheduleFile=p.id==='strogino'?STROGINO_SCHEDULE_FILE:DEMO_SCHEDULE_FILE
    const published=buildImported(p.id,scheduleFile,scheduleRows as Record<string,unknown>[],scheduleMapped,1,null,p.name)
    const now=new Date().toISOString()
    published.meta={...published.meta,id:`${p.id}-v1`,is_active:false,version_state:'PUBLISHED',published_at:now,updated_at:now}
    const working=deep(published)
    working.meta={...working.meta,id:`${p.id}-v2-demo`,version:2,is_active:true,version_state:'WORKING',parent_version_id:published.meta.id,source_filename:scheduleFile,updated_at:now,published_at:null}
    schedules[p.id]=[published,working]
  })
  return {projects,objects,schedules}
}

function ensureProjectGroups(state:LocalState):LocalState{
  let changed=false
  const projects=state.projects.map(p=>{
    const groupId=p.developer?.groupId||PROJECT_GROUP_ID[p.id]||null
    if(!p.developer)return p
    if(p.developer.groupId===groupId)return p
    changed=true
    return {...p,developer:{...p.developer,groupId}}
  })
  if(!changed)return state
  const next={...state,projects}
  saveState(next)
  return next
}

function isHealthyState(state:LocalState|null|undefined):state is LocalState{
  if(!state?.projects?.length)return false
  const hasSchedules=state.projects.every(p=>{
    const versions=state.schedules?.[p.id]??[]
    return versions.some(v=>(v.activities?.length??0)>0)
  })
  const hasObjects=state.projects.every(p=>(state.objects?.[p.id]?.length??0)>0)
  return hasSchedules&&hasObjects
}

function clearDemoStorage(){
  try{
    const keys:string[]=[]
    for(let i=0;i<localStorage.length;i++){
      const k=localStorage.key(i)
      if(k&&(k===STORAGE_KEY||k.startsWith(STORAGE_KEY_PREFIX)||k===COMMENTS_KEY||k==='plansight_evidence_comments_v1'))keys.push(k)
    }
    keys.forEach(k=>localStorage.removeItem(k))
  }catch{localStorage.removeItem(STORAGE_KEY)}
}

function loadState():LocalState{
  try{
    const raw=localStorage.getItem(STORAGE_KEY)
    if(raw){
      const parsed=JSON.parse(raw) as LocalState
      if(isHealthyState(parsed))return ensureProjectGroups(parsed)
    }
  }catch{}
  clearDemoStorage()
  const seeded=seedState()
  try{localStorage.setItem(STORAGE_KEY,JSON.stringify(seeded))}catch{/* quota: оставляем in-memory на сессию */}
  return seeded
}
function saveState(state:LocalState){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(state))}catch{/* игнорировать квоту */}}
function state(){return loadState()}
function loadComments():Record<string,EvidenceComment[]>{
  try{
    const raw=localStorage.getItem(COMMENTS_KEY)
    if(raw){
      const parsed=JSON.parse(raw) as Record<string,unknown>
      const out:Record<string,EvidenceComment[]>={}
      for(const [id,value] of Object.entries(parsed)){
        if(Array.isArray(value))out[id]=value as EvidenceComment[]
        else if(typeof value==='string'&&value.trim())out[id]=[{id:`migrated-${id}`,author:'Вероника Широкова',role:'Аналитик',initials:'ВШ',text:value.trim(),at:'2026-09-18T12:42:00',kind:'user'}]
      }
      return out
    }
    const legacy=localStorage.getItem('plansight_evidence_comments_v1')
    if(legacy){
      const old=JSON.parse(legacy) as Record<string,string>
      const migrated:Record<string,EvidenceComment[]>={}
      for(const [id,text] of Object.entries(old)){
        if(text?.trim())migrated[id]=[{id:`migrated-${id}`,author:'Вероника Широкова',role:'Аналитик',initials:'ВШ',text:text.trim(),at:'2026-09-18T12:42:00',kind:'user'}]
      }
      saveComments(migrated)
      return migrated
    }
  }catch{}
  return{}
}
function saveComments(map:Record<string,EvidenceComment[]>){localStorage.setItem(COMMENTS_KEY,JSON.stringify(map))}
function seedThread(activityId:string,signal:'DEVIATION'|'RISK'):EvidenceComment[]{
  const base=signal==='DEVIATION'
    ?'Автоматически сформировано наблюдение по отклонению сроков. Требуется проверка аналитика.'
    :'Автоматически сформирован сигнал риска по камерам. Данных пока недостаточно для подтверждённого отклонения.'
  return[
    {id:`${activityId}-sys`,author:'PlanSight',role:'Системное сообщение',initials:'ИИ',text:base,at:'2026-09-18T12:20:00',kind:'system'},
    {id:`${activityId}-pm`,author:'Алексей Петров',role:'Руководитель проекта',initials:'АП',text:'Проверили по площадке. Самосвалы действительно работали в соседней зоне.',at:'2026-09-18T12:35:00',kind:'pm'},
  ]
}
function fmtCommentAt(iso:string){
  const d=new Date(iso.endsWith('Z')?iso:`${iso}Z`)
  if(Number.isNaN(d.getTime()))return iso
  return `${pad(d.getUTCDate())}.${pad(d.getUTCMonth()+1)}.${d.getUTCFullYear()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}
function getVersion(projectId:string,version?:number){const versions=state().schedules[projectId]??[];return version?versions.find(v=>v.meta.version===version):versions.find(v=>v.meta.is_active)??versions.at(-1)}

const normalize=(s:string)=>s.toLowerCase().replace(/ё/g,'е').replace(/[^a-zа-я0-9%]+/g,' ').trim()
const aliases:Record<string,string[]>={
  code:['код','id','шифр','номер','no','n'],
  wbs:['wbs','структура','раздел','этап'],
  name:['наименование','наименование работы','работа','activity','task name'],
  unit:['ед изм','единица','unit'],
  qty:['объем','объём','quantity'],
  plan:['план %','план процент','planned progress'],
  fact:['факт %','факт процент','actual progress'],
  start:['план начало','плановое начало','planned start','start','начало','дата начала'],
  end:['план окончание','плановый конец','planned finish','finish','end','окончание','дата окончания'],
  actualStart:['факт начало','фактическое начало','actual start'],
  forecast:['прогноз','прогноз окончания','forecast'],
  pred:['предшественники','предшественник','predecessors','predecessor']
}
function mapColumns(headers:string[]){
  const out:Record<string,string>={}
  for(const [key,names] of Object.entries(aliases)){
    const found=headers.find(h=>{
      const n=normalize(h)
      return names.includes(n)||n==='n'&&key==='code'||/^n$|^№$/.test(h.trim())&&key==='code'
    })
    if(found)out[key]=found
  }
  // № часто плохо нормализуется — берём первый заголовок, если похож на колонку номера
  if(!out.code){
    const num=headers.find(h=>/^№|^#|^no\b/i.test(h.trim())||normalize(h)===''||normalize(h)==='n')
    if(num)out.code=num
  }
  return out
}
async function parseFile(file:File){const data=await file.arrayBuffer();const wb=XLSX.read(data,{type:'array',cellDates:false});const ws=wb.Sheets[wb.SheetNames[0]];const rows=XLSX.utils.sheet_to_json(ws,{defval:''}) as Record<string,unknown>[];const headers=rows.length?Object.keys(rows[0]):[];return {rows,headers,mapped:mapColumns(headers)}}

export const api={
  async getProjects(){if(useHttpBackend())return remote.getProjects() as Promise<Project[]>;return deep(state().projects)},
  async getProject(projectId:string){if(useHttpBackend())return remote.getProject(projectId) as Promise<Project>;const p=state().projects.find(x=>x.id===projectId);if(!p)throw new Error('Project not found');return deep(p)},
  async getProjectObjects(projectId:string){if(useHttpBackend())return remote.getProjectObjects(projectId) as Promise<ProjectObject[]>;return deep(state().objects[projectId]??[])},
  async getSchedule(projectId:string,version?:number,objectId?:string|null):Promise<ScheduleResponse>{if(useHttpBackend())return remote.getSchedule(projectId,version,objectId) as Promise<ScheduleResponse>;const v=getVersion(projectId,version);let acts=v?deep(v.activities):[];if(v&&objectId){acts=acts.filter((a:ScheduleActivity&{project_object_id?:string|null})=>String(a.project_object_id||'')===String(objectId)||(a.wbs_node_id||'').includes(String(objectId)))}return v?{project_id:projectId,active_version:deep(v.meta),wbs:deep(v.wbs),activities:acts,dependencies:deep(v.dependencies),network_recovery:deep(v.network_recovery??null),selected_object_id:objectId??null}:{project_id:projectId,active_version:null,wbs:[],activities:[],dependencies:[],network_recovery:null,selected_object_id:objectId??null}},
  async getVersions(projectId:string){if(useHttpBackend())return remote.getVersions(projectId) as Promise<ScheduleVersion[]>;return deep((state().schedules[projectId]??[]).map(v=>v.meta).sort((a,b)=>b.version-a.version))},
  async getPortfolio():Promise<PortfolioResponse>{
    if(useHttpBackend())return remote.getPortfolio() as Promise<PortfolioResponse>
    const s=state();const now='2026-09-17'
    const geo:Record<string,[number,number]>={
      parkline:[55.9915,37.1905],strogino:[55.8034,37.4021],amursky:[55.8247,37.8119],teatralny:[55.7934,37.4936],nevsky:[55.8398,37.4869],pravda:[55.7930,37.5880],plekhanova:[55.7450,37.7650]
    }
    const analysisDates:Record<string,string>={parkline:'2026-09-14T16:20:00',strogino:'2026-09-17T12:15:00',amursky:'2026-09-17T17:10:00',teatralny:'2026-09-17T14:45:00',nevsky:'2026-09-16T19:20:00',pravda:'2026-09-17T11:30:00',plekhanova:'2026-09-17T16:05:00'}
    const objectOffsets:[[number,number],[number,number],[number,number],[number,number]]=[[.0025,.0028],[-.0022,.0032],[.0018,-.0030],[-.0028,-.0022]]
    const changeById:Record<string,number>={strogino:2,amursky:2,teatralny:1,nevsky:1,pravda:2,plekhanova:3}
    const rows:PortfolioRow[]=s.projects.map(p=>{
      const v=(s.schedules[p.id]??[]).find(x=>x.meta.is_active)??s.schedules[p.id]?.at(-1);const acts=v?.activities??[]
      let works_critical=0,works_high=0,works_medium=0,works_normal=0,max=0
      for(const a of acts){
        const fact=a.actual_progress??0
        const plan=a.planned_progress??0
        const isProblem=fact+10<plan||(!!a.planned_end&&a.planned_end<now&&fact<100)
        if(isProblem){
          const lag=a.planned_end&&a.planned_end<now?diffDays(a.planned_end,now):Math.max(1,Math.round((plan-fact)/4))
          max=Math.max(max,lag)
          if(lag>10)works_critical+=1
          else if(lag>5)works_high+=1
          else works_medium+=1
          continue
        }
        const started=fact>0||plan>0
        const due=(!!a.planned_start&&a.planned_start<=now)||(!!a.planned_end&&a.planned_end<=now)
        if(started||due)works_normal+=1
      }
      const problemWorks=works_critical+works_high+works_medium
      const progress=acts.length?Math.round(acts.reduce((q,a)=>q+(a.actual_progress??0),0)/acts.length):0
      const [lat,lng]=geo[p.id]??[55.75,37.62]
      const allObjs=s.objects[p.id]??[];const leafObjs=allObjs.filter(o=>o.object_type!=='stage'&&!allObjs.some(c=>c.parent_id===o.id))
      const objects=leafObjs.map((o,i)=>({id:o.id,name:o.name,type:o.object_type,lat:lat+(objectOffsets[i%objectOffsets.length]?.[0]??0),lng:lng+(objectOffsets[i%objectOffsets.length]?.[1]??0)}))
      const dt=analysisDates[p.id]??'2026-09-17T12:00:00';const d=new Date(dt+'Z');const lastAnalysis=`${pad(d.getUTCDate())}.${pad(d.getUTCMonth()+1)}.${d.getUTCFullYear()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
      const groupId=p.developer?.groupId||PROJECT_GROUP_ID[p.id]||null
      return{id:p.id,developer:p.developer?.name??'—',companyGroupId:groupId,companyGroup:companyGroupName(groupId),name:p.name,region:p.region??'—',address:p.address??'',status:p.status,problemWorks,maxDeviation:max,change:changeById[p.id]??0,lastAnalysis,lastAnalysisDate:dt.slice(0,10),totalWorks:acts.length,progress,lat,lng,objects,severityWorks:{critical:works_critical,high:works_high,medium:works_medium,normal:works_normal}}
    })
    const trend=[11,12,13,14,15,16,17].map((d,i)=>({day:`${d} сен`,deviations:[12,14,13,16,17,19,rows.reduce((q,p)=>q+p.problemWorks,0)][i]}));return {projects:rows,trend}
  },
  async previewImport(projectId:string,file:File):Promise<ImportPreview>{
    if(useHttpBackend()){
      const raw=await remote.previewImport(projectId,file) as {
        filename?:string;headers?:string[];rows?:Record<string,unknown>[];row_count?:number
        suggested_mapping?:Record<string,string>;note?:string
      }
      const mapped=raw.suggested_mapping||{}
      const issues:ImportIssue[]=[]
      if(!mapped.name)issues.push({level:'critical',code:'NO_NAME',message:'Не найдена колонка с наименованием работы'})
      return{
        filename:raw.filename||file.name,
        rows:raw.row_count??(raw.rows?.length??0),
        activities:raw.row_count??(raw.rows?.length??0),
        wbs_nodes:1,
        milestones:0,
        dependencies:0,
        period_start:null,
        period_end:null,
        matched_works:0,
        manual_mapping_required:raw.row_count??0,
        mapped_columns:mapped as ImportPreview['mapped_columns'],
        issues,
        can_import:!issues.some(i=>i.level==='critical'),
        network_summary:null,
        mapping_rows:[],
      }
    }
    const {rows,headers,mapped}=await parseFile(file)
    const issues:ImportIssue[]=[]
    if(!mapped.name)issues.push({level:'critical',code:'NO_NAME',message:'Не найдена колонка с наименованием работы'})
    if(!mapped.start||!mapped.end)issues.push({level:'warning',code:'NO_DATES',message:'Не все плановые даты распознаны'})
    const named=mapped.name?rows.filter((r:Record<string,unknown>)=>String(r[mapped.name]??'').trim()):[]
    const codeOf=(r:Record<string,unknown>,i:number)=>mapped.code?String(r[mapped.code]??'').trim()||`A${i+1}`:`A${i+1}`
    const allCodes=named.map((r,i)=>codeOf(r,i))
    const codeSet=new Set(allCodes)
    const parentCodes=new Set<string>()
    allCodes.forEach(c=>{for(const o of codeSet){if(o!==c&&o.startsWith(`${c}.`)){parentCodes.add(c);break}}})
    const leafNamed=parentCodes.size?named.filter((r,i)=>!parentCodes.has(codeOf(r,i))):named
    const dates=rows.flatMap((r:Record<string,unknown>)=>[toIsoDate(r[mapped.start]),toIsoDate(r[mapped.end])]).filter(Boolean) as string[]
    const excelDepRows=mapped.pred?named.filter((r:Record<string,unknown>)=>String(r[mapped.pred]??'').trim()).length:0
    // Черновой прогон сетевого анализа для KPI превью (без записи в storage)
    let matched=0,manual=leafNamed.length,network_summary:NetworkRecoveryModel['summary']|null=null
    let mapping_rows:MappingDraftRow[]=[]
    if(mapped.name&&leafNamed.length){
      const draft=leafNamed.map((r,i)=>{
        const name=String(r[mapped.name]).trim()
        const code=codeOf(r,i)
        return {id:`preview-${i}`,name,code,planned_start:toIsoDate(r[mapped.start]),planned_end:toIsoDate(r[mapped.end]),wbs_node_id:mapped.wbs?String(r[mapped.wbs]??'w'):undefined}
      })
      const model=await recoverNetworkModelWithQwen(draft,[])
      matched=model.canonical_matches.filter(m=>m.mapping_status==='MATCHED').length
      manual=model.canonical_matches.filter(m=>m.needs_confirmation||m.mapping_status!=='MATCHED').length
      network_summary=model.summary
      mapping_rows=model.canonical_matches.map((m,i)=>{
        const topScore=m.candidates[0]?.score??0
        const confidence=m.mapping_status==='MATCHED'&&!m.needs_confirmation
          ? Math.max(topScore,0.85)
          : m.mapping_status==='UNMAPPED'?0:Math.max(topScore,m.needs_confirmation?Math.min(topScore,0.84):topScore)
        return {
          row_index:i,
          source_name:m.source_name,
          code:draft[i]?.code??null,
          canonical_work_id:m.canonical_work_id,
          canonical_work_code:m.canonical_work_code,
          canonical_work_name:m.canonical_work_name,
          mapping_status:m.mapping_status,
          needs_confirmation:m.needs_confirmation,
          confidence,
          candidates:m.candidates,
        }
      })
      if(model.qwen?.used)issues.push({level:'info',code:'QWEN_MATCH',message:model.qwen.detail??'Сопоставление видов работ уточнено автоматически'})
      else if(model.qwen?.detail)issues.push({level:'info',code:'QWEN_FALLBACK',message:'Сопоставление выполнено по названиям (умный помощник недоступен)'})
    }
    const wbsCount=parentCodes.size>0?parentCodes.size:new Set(rows.map((r:Record<string,unknown>)=>String(r[mapped.wbs]??'Работы'))).size+1
    return{filename:file.name,rows:rows.length,activities:leafNamed.length,wbs_nodes:wbsCount,milestones:0,dependencies:excelDepRows,period_start:dates.sort()[0]??null,period_end:dates.sort().at(-1)??null,matched_works:matched,manual_mapping_required:manual,mapped_columns:mapped,issues,can_import:!issues.some(i=>i.level==='critical'),network_summary,mapping_rows}
  },
  async importSchedule(projectId:string,file:File,overrides?:MappingOverride[]):Promise<ImportResult>{
    if(useHttpBackend())return remote.importSchedule(projectId,file,overrides) as Promise<ImportResult>
    const {rows,mapped}=await parseFile(file)
    if(!mapped.name)throw new Error('Не найдена колонка Наименование')
    const s=state();const versions=s.schedules[projectId]??[];versions.forEach(v=>v.meta.is_active=false)
    const next=Math.max(0,...versions.map(v=>v.meta.version))+1;const parent=versions.at(-1)?.meta.id??null
    const rootName=s.projects.find(p=>p.id===projectId)?.name
    const v=buildImported(projectId,file.name,rows,mapped,next,parent,rootName)
    // Связи Excel отдельно от авто-FS (calendar:sequential-fs)
    const excelDeps=v.dependencies.filter(d=>!String(d.raw_expression||'').startsWith('calendar:'))
    const excelExisting=excelDeps.filter(d=>d.predecessor_activity_id).map(d=>({predecessor_activity_id:d.predecessor_activity_id!,successor_activity_id:d.successor_activity_id,relation_type:d.relation_type,lag_days:d.lag_days}))
    const recovery=await recoverNetworkModelWithQwen(
      v.activities.map(a=>({id:a.id,name:a.name,planned_start:a.planned_start,planned_end:a.planned_end,wbs_node_id:a.wbs_node_id,code:a.code})),
      excelExisting,
    )
    const byId=new Map(WORK_TYPES_LTC.map(w=>[w.id,w]))
    const overrideMap=new Map((overrides??[]).map(o=>[o.row_index,o.canonical_work_id]))
    let matches=recovery.canonical_matches
    if(overrideMap.size){
      matches=recovery.canonical_matches.map((m,i)=>{
        if(!overrideMap.has(i))return m
        const id=overrideMap.get(i)??null
        if(!id){
          return {...m,canonical_work_id:null,canonical_work_code:null,canonical_work_name:null,mapping_status:'UNMAPPED' as const,needs_confirmation:true}
        }
        const w=byId.get(id)
        if(!w)return m
        return {
          ...m,
          canonical_work_id:w.id,
          canonical_work_code:w.code,
          canonical_work_name:w.name,
          mapping_status:'MATCHED' as const,
          needs_confirmation:false,
        }
      })
    }
    // Пересобрать сеть с подтверждёнными видами работ + заново материализовать авто-FS
    const rebuilt=recoverNetworkModel(
      v.activities.map(a=>({id:a.id,name:a.name,planned_start:a.planned_start,planned_end:a.planned_end,wbs_node_id:a.wbs_node_id,code:a.code})),
      excelExisting,
      matches,
    )
    v.activities=applyCanonicalToActivities(v.activities,rebuilt).map(a=>{
      const wid=a.canonical_work_id
      if(!wid)return {...a,expected_equipment_profile_id:null}
      const profile=suggestProfile(wid,a.canonical_work_name||a.name)
      return {...a,expected_equipment_profile_id:profile?wid:null}
    })
    const have=new Set(excelDeps.filter(d=>d.predecessor_activity_id).map(d=>`${d.predecessor_activity_id}>${d.successor_activity_id}`))
    const autoFs=calendarDepsFromRecovery(rebuilt).flatMap((d,i)=>{
      const key=`${d.predecessor_activity_id}>${d.successor_activity_id}`
      if(have.has(key))return []
      have.add(key)
      const pred=v.activities.find(a=>a.id===d.predecessor_activity_id)
      return [{
        id:`${projectId}-imp-${next}-cfs${i+1}`,
        successor_activity_id:d.successor_activity_id,
        predecessor_activity_id:d.predecessor_activity_id,
        predecessor_reference:pred?.code??pred?.external_id??'',
        relation_type:d.relation_type,
        lag_text:d.lag_days?`${d.lag_days>0?'+':''}${d.lag_days}d`:null,
        lag_days:d.lag_days,
        raw_expression:'calendar:sequential-fs',
      }]
    })
    v.dependencies=[...excelDeps,...autoFs]
    v.network_recovery=rebuilt
    v.meta.warning_count=rebuilt.summary.need_confirmation
    versions.push(v);s.schedules[projectId]=versions;saveState(s)
    return {...deep(v.meta),network_recovery:deep(v.network_recovery??null)}
  },
  async updateNetworkRecovery(projectId:string,versionId:string,patch:Partial<NetworkRecoveryModel>&{proposed?:ProposedDependency[]}){
    if(useHttpBackend())return remote.updateNetworkRecovery(projectId,versionId,patch)
    const s=state();const v=(s.schedules[projectId]??[]).find(x=>x.meta.id===versionId)
    if(!v)throw new Error('Версия не найдена')
    const cur=v.network_recovery??recoverNetworkModel(v.activities.map(a=>({id:a.id,name:a.name,planned_start:a.planned_start,planned_end:a.planned_end,wbs_node_id:a.wbs_node_id,code:a.code})),[])
    const proposed=patch.proposed??cur.proposed
    const confirmed=proposed.filter(p=>p.status==='confirmed')
    const excelIds=new Set(v.dependencies.map(d=>`${d.predecessor_activity_id}>${d.successor_activity_id}`))
    confirmed.filter(p=>p.source==='rule'||p.source==='user').forEach(p=>{
      const key=`${p.predecessor_activity_id}>${p.successor_activity_id}`
      if(excelIds.has(key)){
        const d=v.dependencies.find(x=>x.predecessor_activity_id===p.predecessor_activity_id&&x.successor_activity_id===p.successor_activity_id)
        if(d){d.relation_type=p.relation_type;d.lag_days=p.lag_days;d.lag_text=p.lag_days?`${p.lag_days>0?'+':''}${p.lag_days}d`:null}
        return
      }
      v.dependencies.push({id:p.id,successor_activity_id:p.successor_activity_id,predecessor_activity_id:p.predecessor_activity_id,predecessor_reference:v.activities.find(a=>a.id===p.predecessor_activity_id)?.code??'',relation_type:p.relation_type,lag_text:p.lag_days?`${p.lag_days>0?'+':''}${p.lag_days}d`:null,lag_days:p.lag_days,raw_expression:`proposed:${p.rule_id??'user'}`})
      excelIds.add(key)
    })
    proposed.filter(p=>p.status==='rejected').forEach(p=>{
      v.dependencies=v.dependencies.filter(d=>!(d.predecessor_activity_id===p.predecessor_activity_id&&d.successor_activity_id===p.successor_activity_id&&String(d.raw_expression||'').startsWith('proposed:')))
    })
    const next=refreshGroups({...cur,...patch,proposed})
    v.network_recovery=next
    v.meta.updated_at=new Date().toISOString();saveState(s);return deep(v.network_recovery)
  },
  async createWorkingCopy(projectId:string,sourceVersionId?:string|null){if(useHttpBackend())return remote.createWorkingCopy(projectId,sourceVersionId) as Promise<ScheduleVersion>;const s=state();const versions=s.schedules[projectId]??[];const source=versions.find(v=>v.meta.id===sourceVersionId)??versions.find(v=>v.meta.is_active)??versions.at(-1);if(!source)throw new Error('Нет исходной версии');versions.forEach(v=>v.meta.is_active=false);const next=Math.max(...versions.map(v=>v.meta.version))+1;const now=new Date().toISOString();const copy:LocalVersion={meta:{...deep(source.meta),id:`${projectId}-v${next}-${uid()}`,version:next,is_active:true,version_state:'WORKING',parent_version_id:source.meta.id,uploaded_at:now,updated_at:now,published_at:null,source_filename:`Рабочая копия v${source.meta.version}`},wbs:deep(source.wbs),activities:deep(source.activities).map((a:ScheduleActivity)=>({...a,id:a.id.replace(/-v\d+-/,'-')})),dependencies:deep(source.dependencies),network_recovery:deep(source.network_recovery??null)};versions.push(copy);saveState(s);return deep(copy.meta)},
  async saveScheduleEdits(projectId:string,body:{version_id:string;activities:ActivityEdit[];dependencies:DependencyEdit[];recalculate:boolean}):Promise<EditorSaveResult>{if(useHttpBackend())return remote.saveScheduleEdits(projectId,body) as Promise<EditorSaveResult>;const s=state();const v=(s.schedules[projectId]??[]).find(x=>x.meta.id===body.version_id);if(!v)throw new Error('Версия не найдена');const map=new Map(body.activities.map(a=>[a.id,a]));v.activities=v.activities.map(a=>({...a,...(map.get(a.id)??{})}));v.dependencies=body.dependencies.map((d,i)=>({id:d.id??`${projectId}-local-d-${i}-${uid()}`,successor_activity_id:d.successor_activity_id,predecessor_activity_id:d.predecessor_activity_id,predecessor_reference:v.activities.find(a=>a.id===d.predecessor_activity_id)?.code??'',relation_type:d.relation_type,lag_text:d.lag_days?`${d.lag_days>0?'+':''}${d.lag_days}d`:null,lag_days:d.lag_days,raw_expression:''}));const now=new Date().toISOString();v.meta.updated_at=now;saveState(s);return{version_id:v.meta.id,updated_activities:body.activities.length,dependency_count:v.dependencies.length,recalculated_activities:body.recalculate?body.activities.length:0,updated_at:now}},
  async publishSchedule(projectId:string,versionId:string){if(useHttpBackend())return remote.publishSchedule(projectId,versionId) as Promise<ScheduleVersion>;const s=state();const versions=s.schedules[projectId]??[];const v=versions.find(x=>x.meta.id===versionId);if(!v)throw new Error('Версия не найдена');versions.forEach(x=>x.meta.is_active=x.meta.id===versionId);v.meta.version_state='PUBLISHED';v.meta.published_at=new Date().toISOString();saveState(s);return deep(v.meta)},
  async exportSchedule(projectId:string,format:'xlsx'|'csv',version?:number){if(useHttpBackend())return remote.exportSchedule(projectId,format,version);const v=getVersion(projectId,version);if(!v)throw new Error('Нет графика');const incoming=new Map<string,string[]>();v.dependencies.forEach(d=>{const p=v.activities.find(a=>a.id===d.predecessor_activity_id);if(!p)return;const t=`${p.code??p.external_id}${d.relation_type??'FS'}${d.lag_days?`${d.lag_days>0?'+':''}${d.lag_days}`:''}`;incoming.set(d.successor_activity_id,[...(incoming.get(d.successor_activity_id)??[]),t])});const rows=v.activities.map(a=>({'Код':a.code??'','WBS':v.wbs.find(w=>w.id===a.wbs_node_id)?.name??'','Наименование':a.name,'Ед. изм.':a.unit??'','Объем':a.planned_quantity??'','План %':a.planned_progress??0,'Факт %':a.actual_progress??0,'План. начало':a.planned_start??'','План. окончание':a.planned_end??'','Факт. начало':a.actual_start??'','Прогноз':a.forecast_end??'','Предшественники':(incoming.get(a.id)??[]).join('; ')}));const ws=XLSX.utils.json_to_sheet(rows);const wb=XLSX.utils.book_new();XLSX.utils.book_append_sheet(wb,ws,'Schedule');if(format==='csv'){const text=XLSX.utils.sheet_to_csv(ws,{FS:';'});return{blob:new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'}),filename:`${projectId}_schedule_v${v.meta.version}.csv`}}const arr=XLSX.write(wb,{bookType:'xlsx',type:'array'});return{blob:new Blob([arr],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}),filename:`${projectId}_schedule_v${v.meta.version}.xlsx`}},
  async getEvidenceComment(activityId:string){if(useHttpBackend())return remote.getEvidenceComment(activityId);const thread=loadComments()[activityId]??[];return thread.filter(c=>c.kind==='user').at(-1)?.text??''},
  async getEvidenceThread(activityId:string,signal:'DEVIATION'|'RISK'='RISK'){
    if(useHttpBackend())return remote.getEvidenceThread(activityId,signal) as Promise<EvidenceComment[]>
    const map=loadComments()
    if(!map[activityId]?.length){map[activityId]=seedThread(activityId,signal);saveComments(map)}
    return deep(map[activityId]??[])
  },
  async addEvidenceComment(activityId:string,text:string,signal:'DEVIATION'|'RISK'='RISK'){
    if(useHttpBackend())return remote.addEvidenceComment(activityId,text,signal) as Promise<EvidenceComment[]>
    const next=text.trim();if(!next)return deep(loadComments()[activityId]??[])
    const map=loadComments()
    const thread=map[activityId]?.length?[...map[activityId]]:seedThread(activityId,signal)
    thread.push({id:`${activityId}-u-${uid()}`,author:'Вероника Широкова',role:'Аналитик',initials:'ВШ',text:next,at:'2026-09-18T12:42:00',kind:'user'})
    map[activityId]=thread;saveComments(map);return deep(thread)
  },
  async saveEvidenceComment(activityId:string,text:string){
    const thread=await api.addEvidenceComment(activityId,text)
    return thread.filter(c=>c.kind==='user').at(-1)?.text??''
  },
  formatEvidenceCommentAt(iso:string){return fmtCommentAt(iso)},
  resetDemo(){clearDemoStorage()},
  /** CV-поверхности V4.2 (только HTTP; в demo mode — пусто) */
  async getCameras(projectId:string){if(useHttpBackend())return remote.getCameras(projectId);return []},
  async getZones(projectId:string,cameraId:number){if(useHttpBackend())return remote.getZones(projectId,cameraId);return {zones:[]}},
  async verifyZone(projectId:string,zoneId:number,building:string){if(useHttpBackend())return remote.verifyZone(projectId,zoneId,building);return {ok:true}},
  async demoZonesK1K2(projectId:string,cameraId:number){if(useHttpBackend())return remote.demoZonesK1K2(projectId,cameraId);return {ok:true}},
  async getFrames(projectId:string,cameraId?:number){if(useHttpBackend())return remote.getFrames(projectId,cameraId);return {items:[]}},
  async getFrameDetections(frameId:number){if(useHttpBackend())return remote.getFrameDetections(frameId);return {detections:[]}},
  async getDeviations(projectId:string){if(useHttpBackend())return remote.getDeviations(projectId);return {items:[]}},
  async getDeviationEvidence(projectId:string,deviationId:string|number){if(useHttpBackend())return remote.getDeviationEvidence(projectId,deviationId);return {frames:[],signal_kind:'RISK_FROM_SCHEDULE'}},
  async getDecisionTrace(projectId:string,deviationId:string|number){if(useHttpBackend())return remote.getDecisionTrace(projectId,deviationId);return null},
  async patchDeviation(projectId:string,deviationId:string|number,payload:{lifecycle?:string;note?:string}){if(useHttpBackend())return remote.patchDeviation(projectId,deviationId,payload);return {ok:true}},
  async submitDeviationVerdict(projectId:string,deviationId:string|number,payload:{verdict:string;correction?:Record<string,unknown>}){if(useHttpBackend())return remote.submitDeviationVerdict(projectId,deviationId,payload);return {ok:true,is_ml_label:payload.verdict!=='ack_for_review'}},
  async getJob(jobId:string){if(useHttpBackend())return remote.getJob(jobId);return {status:'COMPLETED'}},
  async vlmAssist(payload:Record<string,unknown>){if(useHttpBackend())return remote.vlmAssist(payload);return {user_explanation:'Пояснение недоступно в демо-режиме',source_of_truth:false}},
  async aiStatus(){if(useHttpBackend())return remote.aiStatus();return {ai_mode:'template',llm_enabled:false,vlm_ui_enabled:false,ollama_reachable:false,browser_ollama:false}},
  async createCamera(projectId:string,payload:{name:string;building_hint?:string|null}){if(useHttpBackend())return remote.createCamera(projectId,payload);return {id:0,name:payload.name}},
  async ingestObservations(projectId:string,opts:{file:File;cameraId?:number;cameraName?:string;buildingHint?:string;capturedAt:string;timezone?:string;videoIntervalSec?:number}){if(useHttpBackend())return remote.ingestObservations(projectId,opts);throw new Error('HTTP backend required')},
  async getScheduleItemEvidence(projectId:string,itemId:string,asOf?:string|null){if(useHttpBackend())return remote.getScheduleItemEvidence(projectId,itemId,asOf);return {frames:[],signal_kind:'RISK_FROM_SCHEDULE',schedule_item_id:itemId}},
  async getOverview(projectId:string){if(useHttpBackend())return remote.getOverview(projectId);return null},
  async getCatalog(catalogKey:string){if(useHttpBackend())return remote.getCatalog(catalogKey);return {items:[],revision:0}},
  async putCatalog(catalogKey:string,payload:unknown){if(useHttpBackend())return remote.putCatalog(catalogKey,payload);return {ok:true}},
  async getWorkProfiles(){if(useHttpBackend())return remote.getWorkProfiles();return {items:[],revision:0}},
  async putWorkProfiles(payload:unknown){if(useHttpBackend())return remote.putWorkProfiles(payload);return {ok:true}},
}
