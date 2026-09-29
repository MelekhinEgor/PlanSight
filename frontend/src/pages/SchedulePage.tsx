import { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type DependencyEdit, type EvidenceComment, type ImportPreview, type ImportResult, type MappingOverride, type NetworkRecoveryModel, type ScheduleActivity, type ScheduleDependency, type WbsNode, setRemoteProjectId } from '../api/client'
import { useHttpBackend } from '../api/remoteBackend'
import { CanonicalMappingModal } from '../components/CanonicalMappingModal'
import { DateRuInput } from '../components/DateRuInput'
import { FindingDrawer, type FindingEvidence } from '../components/FindingDrawer'
import {
  activityStateRu,
  asOfCaption,
  deviationCodeRu,
  fmtRuDate,
  lifecycleRu,
  todayCaptionShort,
  todayIsoMoscow,
} from '../labels/ru'

type FlatRow = {
  id:string; kind:'wbs'|'activity'; level:number; name:string; unit:string; qty:number|null; plan:number; fact:number;
  start:string|null; end:string|null; forecast:string|null; deviation:number|null; state:string; activity?:ScheduleActivity
}
type Snapshot = {activities:ScheduleActivity[]; dependencies:DependencyEdit[]}
type ConnectorSide = 'start'|'finish'
type ConnectorDraft = {activityId:string; side:ConnectorSide}
type DisplayDep = DependencyEdit & {displayKind:'confirmed'|'proposed'; proposalId?:string}
type ColKey = 'code'|'name'|'unit'|'qty'|'plan'|'fact'|'start'|'end'|'actualStart'|'duration'|'forecast'|'deviation'|'status'|'predecessors'|'ai'
type Column = {key:ColKey; label:string; width:number; min:number; hideable?:boolean}

const DAY=86400000
const cloneActivities=(items:ScheduleActivity[])=>items.map(a=>({...a}))
const cloneDeps=(items:DependencyEdit[])=>items.map(d=>({...d}))
const toDate=(iso:string)=>new Date(`${iso}T00:00:00Z`)
const iso=(d:Date)=>d.toISOString().slice(0,10)
const addDays=(value:string,delta:number)=>{const d=toDate(value);d.setUTCDate(d.getUTCDate()+delta);return iso(d)}
const diffDays=(a:string,b:string)=>Math.round((toDate(b).getTime()-toDate(a).getTime())/DAY)
const durationDays=(a:ScheduleActivity)=>a.planned_start&&a.planned_end?Math.max(1,diffDays(a.planned_start,a.planned_end)+1):Math.max(1,Math.round(a.planned_duration??1))
/** Срез статусов: сначала с сервера (workspace.meta.as_of), иначе демо-fallback. */
/** Календарное «сегодня» для демо — всегда текущая дата (Москва), не зафиксированный срез сида. */
const todayIso = () => todayIsoMoscow()
const fmt=(d:string|null)=>fmtRuDate(d)
const monthLabel=(d:string)=>toDate(d).toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'UTC'}).replace(' г.','')
const shortMonth=(d:string)=>toDate(d).toLocaleDateString('ru-RU',{month:'short',year:'numeric',timeZone:'UTC'}).replace(' г.','')
const activeEnd=(a:ScheduleActivity)=>{const pe=a.planned_end,fe=a.forecast_end;if(pe&&fe&&fe>pe)return fe;return pe}

function SvgIcon({name,size=16}:{name:string;size?:number}){
  const common={width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.8,strokeLinecap:'round' as const,strokeLinejoin:'round' as const,'aria-hidden':true}
  if(name==='back')return <svg {...common}><path d="M15 18l-6-6 6-6"/><path d="M9 12h10"/></svg>
  if(name==='upload')return <svg {...common}><path d="M12 16V4"/><path d="M7.5 8.5L12 4l4.5 4.5"/><path d="M5 14v5h14v-5"/></svg>
  if(name==='download')return <svg {...common}><path d="M12 4v12"/><path d="M7.5 11.5L12 16l4.5-4.5"/><path d="M5 19h14"/></svg>
  if(name==='save')return <svg {...common}><path d="M5 4h11l3 3v13H5z"/><path d="M8 4v6h8V4"/><path d="M8 20v-6h8v6"/></svg>
  if(name==='check')return <svg {...common}><path d="M5 12.5l4.2 4.2L19 7"/></svg>
  if(name==='filter')return <svg {...common}><path d="M4 6h16"/><path d="M7 12h10"/><path d="M10 18h4"/></svg>
  if(name==='search')return <svg {...common}><circle cx="10.8" cy="10.8" r="5.8"/><path d="M15 15l4.5 4.5"/></svg>
  if(name==='calendar')return <svg {...common}><rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M8 3.5v4M16 3.5v4M4 10h16"/></svg>
  if(name==='chevLeft')return <svg {...common}><path d="M14.5 6l-6 6 6 6"/></svg>
  if(name==='chevRight')return <svg {...common}><path d="M9.5 6l6 6-6 6"/></svg>
  if(name==='more')return <svg {...common}><circle cx="12" cy="5" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1" fill="currentColor" stroke="none"/></svg>
  if(name==='folder')return <svg {...common}><path d="M3.5 7.5h6l2-2h9v13h-17z"/></svg>
  if(name==='file')return <svg {...common}><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/></svg>
  if(name==='gear')return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="M12 2.8v2M12 19.2v2M21.2 12h-2M4.8 12h-2M18.5 5.5l-1.4 1.4M6.9 17.1l-1.4 1.4M18.5 18.5l-1.4-1.4M6.9 6.9L5.5 5.5"/></svg>
  if(name==='link')return <svg {...common}><path d="M9.5 14.5l5-5"/><path d="M7 17H5.5a3.5 3.5 0 010-7H9"/><path d="M15 7h3.5a3.5 3.5 0 010 7H15"/></svg>
  return <svg {...common}><circle cx="12" cy="12" r="8"/></svg>
}

function deriveState(a:ScheduleActivity){
  const fact=a.actual_progress??0, plan=a.planned_progress??0, today=todayIso()
  if(fact>=100) return 'COMPLETED'
  if(a.planned_start&&today<a.planned_start) return 'PLANNED_FUTURE'
  if(a.planned_end&&today>a.planned_end&&fact<100) return 'DELAYED'
  if(a.planned_start&&a.planned_end&&today>=a.planned_start&&today<=a.planned_end){if(fact+10<plan)return'AT_RISK';return fact===0?'SHOULD_BE_ACTIVE':'ON_TRACK'}
  return 'ON_TRACK'
}
type CvDeviation = {
  id:number
  code?:string
  signal_kind?:string
  lifecycle?:string
  schedule_item_id?:number|string|null
  schedule_item_name?:string|null
  explanation_ru?:string
  details?:Record<string,unknown>
  risk_score?:number
  has_evidence_frames?:boolean
}

/** Красный ромб = только CV с кадрами; жёлтый = риск по графику. */
function evidenceSignal(
  a:ScheduleActivity,
  cvByActivity?:Map<string,CvDeviation>,
):'DEVIATION'|'RISK'|null{
  const cv=cvByActivity?.get(a.id)
  if(cv&&(cv.lifecycle||'OPEN').toUpperCase()!=='RESOLVED'){
    if(cv.signal_kind==='CV_VERIFIED_FINDING'||cv.has_evidence_frames)return 'DEVIATION'
    // Коды SCHEDULE_EDITORIAL / UNVERIFIED без кадров → риск графика, не камера
  }
  const state=deriveState(a), fact=a.actual_progress??0
  if(fact>=100||state==='PLANNED_FUTURE')return null
  if(cv&&(cv.signal_kind==='SCHEDULE_EDITORIAL'||cv.code==='SCHEDULE_LAG'))return 'RISK'
  if(state==='DELAYED'||state==='AT_RISK'||state==='SHOULD_BE_ACTIVE')return 'RISK'
  if(a.planned_end&&a.forecast_end&&a.forecast_end>a.planned_end)return 'RISK'
  return null
}
function deviationDays(a:ScheduleActivity){if(!a.planned_end||!a.forecast_end)return 0;return Math.max(0,diffDays(a.planned_end,a.forecast_end))}
function stateLabel(state:string){return activityStateRu(state)}
function versionLabel(state:string){return state==='WORKING'?'Рабочая':state==='PUBLISHED'?'Опубликована':'Импорт'}
function evidenceLabel(signal:'DEVIATION'|'RISK'){return signal==='DEVIATION'?'Отклонение по камере':'Риск по графику'}
function evidenceCopy(a:ScheduleActivity,signal:'DEVIATION'|'RISK',cv?:CvDeviation|null){
  const lag=deviationDays(a)
  const plan=Math.round(a.planned_progress??0)
  const fact=Math.round(a.actual_progress??0)
  if(signal==='DEVIATION'){
    const detail=typeof cv?.details?.message==='string'?String(cv.details.message):null
    const expl=(cv?.explanation_ru||'').split('\n').map(s=>s.trim()).filter(Boolean)
    // Берём первую понятную строку без внутренних кодов
    const cleanExpl=expl.find(s=>!/^[A-Z_]+$/.test(s)&&!s.startsWith('Ограничение:'))||detail
    return{
      title:deviationCodeRu(cv?.code),
      text:cleanExpl
        ||`По работе «${a.name}» камеры зафиксировали пониженную активность относительно ожидаемого окна. Это сигнал наблюдения, а не процент готовности (${plan}% / ${fact}%).`,
      rule:'Сравнение ожидаемой активности в зоне камеры с наблюдениями',
      expected:'Техника и работы в плановом окне по привязке камеры',
      detected:lifecycleRu(cv?.lifecycle),
      asOf:asOfCaption(),
    }
  }
  return{
    title:lag>0?`Сдвиг прогноза на +${lag} дн.`:'Риск по срокам графика',
    text:lag>0
      ?`Прогноз окончания ${fmt(a.forecast_end)} позже плана ${fmt(a.planned_end)} (+${lag} дн.). Оценка по полям графика, без подтверждения камерами.`
      :`План ${plan}% · факт ${fact}% на ${fmt(todayIso())}. Статус работы: ${activityStateRu(deriveState(a))}.`,
    rule:'Сравнение плана, факта и прогноза по календарному графику',
    expected:`Завершение по плану: ${fmt(a.planned_end)}`,
    detected:lag>0?`Прогноз: ${fmt(a.forecast_end)}`:`Статус: ${activityStateRu(deriveState(a))}`,
    asOf:asOfCaption(),
  }
}

const EVIDENCE_FRAMES=[
  {src:'/evidence/frame-1.jpg',time:'18.09.2026 12:42:19',label:'Строгино 360'},
  {src:'/evidence/frame-2.jpg',time:'18.09.2026 12:41:49',label:'Строгино 360'},
  {src:'/evidence/frame-3.jpg',time:'18.09.2026 12:45:13',label:'Строгино 360'},
  {src:'/evidence/frame-4.jpg',time:'18.09.2026 12:37:19',label:'Строгино 360'},
] as const
type EvidenceFrame={src:string;time:string;label:string}

function aggregateFromOwn(node:WbsNode,own:ScheduleActivity[]):FlatRow{
  const starts=own.map(a=>a.planned_start).filter(Boolean) as string[];const ends=own.map(a=>a.planned_end).filter(Boolean) as string[];const forecasts=own.map(a=>a.forecast_end).filter(Boolean) as string[]
  const avg=(key:'planned_progress'|'actual_progress')=>own.length?own.reduce((s,a)=>s+(a[key]??0),0)/own.length:0;const states=own.map(deriveState);const state=states.includes('DELAYED')?'DELAYED':states.includes('AT_RISK')?'AT_RISK':states.includes('ON_TRACK')?'ON_TRACK':'PLANNED_FUTURE'
  starts.sort();ends.sort();forecasts.sort()
  return{id:node.id,kind:'wbs',level:node.level,name:node.name,unit:'',qty:null,plan:avg('planned_progress'),fact:avg('actual_progress'),start:starts[0]??null,end:ends.at(-1)??null,forecast:forecasts.at(-1)??null,deviation:Math.max(0,...own.map(deviationDays)),state}
}
/** По умолчанию: всё дерево WBS развёрнуто при входе в проект. */
function defaultExpandedIds(wbs:WbsNode[]):Set<string>{
  return new Set(wbs.map(n=>n.id))
}
function buildRows(wbs:WbsNode[],activities:ScheduleActivity[],expanded:Set<string>):FlatRow[]{
  const children=new Map<string|null,WbsNode[]>()
  for(const n of wbs){
    const key=n.parent_id
    let list=children.get(key)
    if(!list){list=[];children.set(key,list)}
    list.push(n)
  }
  for(const list of children.values())list.sort((a,b)=>a.sort_order-b.sort_order)

  const byNode=new Map<string,ScheduleActivity[]>()
  for(const a of activities){
    if(!a.wbs_node_id)continue
    let list=byNode.get(a.wbs_node_id)
    if(!list){list=[];byNode.set(a.wbs_node_id,list)}
    list.push(a)
  }
  for(const list of byNode.values())list.sort((a,b)=>a.sort_order-b.sort_order)

  // Снизу вверх: работы под каждым WBS (свои + потомки) — O(nodes+acts), не O(n²) фильтр на узел
  const rollup=new Map<string,ScheduleActivity[]>()
  const collect=(id:string):ScheduleActivity[]=>{
    const cached=rollup.get(id)
    if(cached)return cached
    const own=[...(byNode.get(id)??[])]
    for(const c of children.get(id)??[])own.push(...collect(c.id))
    rollup.set(id,own)
    return own
  }
  for(const n of wbs)collect(n.id)

  const out:FlatRow[]=[]
  const walk=(node:WbsNode)=>{
    out.push(aggregateFromOwn(node,rollup.get(node.id)??[]))
    if(!expanded.has(node.id))return
    for(const a of byNode.get(node.id)??[]){
      out.push({id:a.id,kind:'activity',level:node.level+1,name:a.name,unit:a.unit??'',qty:a.planned_quantity,plan:a.planned_progress??0,fact:a.actual_progress??0,start:a.planned_start,end:a.planned_end,forecast:a.forecast_end,deviation:deviationDays(a),state:deriveState(a),activity:a})
    }
    for(const c of children.get(node.id)??[])walk(c)
  }
  for(const root of children.get(null)??[])walk(root)
  for(const a of activities){
    if(a.wbs_node_id)continue
    out.push({id:a.id,kind:'activity',level:0,name:a.name,unit:a.unit??'',qty:a.planned_quantity,plan:a.planned_progress??0,fact:a.actual_progress??0,start:a.planned_start,end:a.planned_end,forecast:a.forecast_end,deviation:deviationDays(a),state:deriveState(a),activity:a})
  }
  return out
}

function depFromServer(d:ScheduleDependency):DependencyEdit|null{return d.predecessor_activity_id?{id:d.id,predecessor_activity_id:d.predecessor_activity_id,successor_activity_id:d.successor_activity_id,relation_type:(d.relation_type??'FS') as DependencyEdit['relation_type'],lag_days:d.lag_days??0}:null}
function relationFor(source:ConnectorSide,target:ConnectorSide):DependencyEdit['relation_type']{return source==='finish'&&target==='start'?'FS':source==='start'&&target==='start'?'SS':source==='finish'&&target==='finish'?'FF':'SF'}
function relationSides(relation:string):[ConnectorSide,ConnectorSide]{return relation==='SS'?['start','start']:relation==='FF'?['finish','finish']:relation==='SF'?['start','finish']:['finish','start']}
function depStroke(state:string){return state==='COMPLETED'?'#2fbf6b':state==='DELAYED'?'#ef6b7a':state==='AT_RISK'?'#e89a2e':'#6db3f5'}

/** Ортогональная стрелка: якоря на левом (start) / правом (finish) краю полоски, не в центре. */
function dependencyArrowPath(
  relation:DependencyEdit['relation_type'],
  ax:number, ay:number, // точка на крае A
  bx:number, by:number, // точка на крае B
){
  const stub=12
  const r=Math.min(5, Math.max(2, Math.abs(by-ay)/3))
  const sy=by>=ay?1:-1

  if(relation==='FS'){
    // Конец A → начало B (горизонталь или простой ортогональный)
    if(Math.abs(by-ay)<0.5){
      const mid=ax+(bx-ax)/2
      return `M ${ax} ${ay} L ${mid} ${ay} L ${bx} ${by}`
    }
    const ex=ax+stub
    const sx=bx>=ex?1:-1
    return `M ${ax} ${ay} L ${ex-r} ${ay} Q ${ex} ${ay} ${ex} ${ay+sy*r} L ${ex} ${by-sy*r} Q ${ex} ${by} ${ex+sx*r} ${by} L ${bx} ${by}`
  }

  if(relation==='SS'){
    // Начало A → начало B: уход влево/вниз, подход к левому краю B слева
    const out=Math.min(ax,bx)-stub
    return `M ${ax} ${ay} L ${out+r} ${ay} Q ${out} ${ay} ${out} ${ay+sy*r} L ${out} ${by-sy*r} Q ${out} ${by} ${out+r} ${by} L ${bx} ${by}`
  }

  if(relation==='FF'){
    // Конец A → конец B: уход вправо/вверх, подход к правому краю B справа
    const out=Math.max(ax,bx)+stub
    return `M ${ax} ${ay} L ${out-r} ${ay} Q ${out} ${ay} ${out} ${ay+sy*r} L ${out} ${by-sy*r} Q ${out} ${by} ${out-r} ${by} L ${bx} ${by}`
  }

  // SF: Начало A → конец B
  const top=Math.min(ay,by)-stub
  const sOut=ax-Math.min(8,stub/2)
  const eOut=bx+stub
  return `M ${ax} ${ay} L ${sOut} ${ay} L ${sOut} ${top+r} Q ${sOut} ${top} ${sOut+r} ${top} L ${eOut-r} ${top} Q ${eOut} ${top} ${eOut} ${top+r} L ${eOut} ${by} L ${bx} ${by}`
}
function createsCycle(deps:DependencyEdit[],candidate:DependencyEdit){
  const all=[...deps.filter(d=>!(d.predecessor_activity_id===candidate.predecessor_activity_id&&d.successor_activity_id===candidate.successor_activity_id)),candidate]
  const adj=new Map<string,string[]>();all.forEach(d=>adj.set(d.predecessor_activity_id,[...(adj.get(d.predecessor_activity_id)??[]),d.successor_activity_id]));const target=candidate.predecessor_activity_id;const stack=[candidate.successor_activity_id];const seen=new Set<string>()
  while(stack.length){const n=stack.pop()!;if(n===target)return true;if(seen.has(n))continue;seen.add(n);(adj.get(n)??[]).forEach(x=>stack.push(x))}return false
}
function recalcDraft(items:ScheduleActivity[],deps:DependencyEdit[]){
  const activities=cloneActivities(items),byId=new Map(activities.map(a=>[a.id,a]));const indegree=new Map(activities.map(a=>[a.id,0]));const outgoing=new Map<string,DependencyEdit[]>(),incoming=new Map<string,DependencyEdit[]>()
  deps.forEach(d=>{if(!byId.has(d.predecessor_activity_id)||!byId.has(d.successor_activity_id))return;outgoing.set(d.predecessor_activity_id,[...(outgoing.get(d.predecessor_activity_id)??[]),d]);incoming.set(d.successor_activity_id,[...(incoming.get(d.successor_activity_id)??[]),d]);indegree.set(d.successor_activity_id,(indegree.get(d.successor_activity_id)??0)+1)})
  // Топологический проход: при сдвиге предшественника даты всех FS/SS/FF/SF-последователей пересчитываются с сохранением lag
  const q=[...indegree.entries()].filter(([,v])=>v===0).map(([k])=>k);while(q.length){const id=q.shift()!;const a=byId.get(id)!;const requirements:(string|null)[]=(incoming.get(id)??[]).map(d=>{const p=byId.get(d.predecessor_activity_id)!;const dur=durationDays(a);if(d.relation_type==='FS'&&p.planned_end)return addDays(p.planned_end,1+d.lag_days);if(d.relation_type==='SS'&&p.planned_start)return addDays(p.planned_start,d.lag_days);if(d.relation_type==='FF'&&p.planned_end)return addDays(p.planned_end,d.lag_days-(dur-1));if(d.relation_type==='SF'&&p.planned_start)return addDays(p.planned_start,d.lag_days-(dur-1));return null});const valid=requirements.filter(Boolean) as string[];if(valid.length){const required=valid.sort().at(-1)!;if(a.planned_start!==required){const dur=durationDays(a);a.planned_start=required;a.planned_end=addDays(required,dur-1);a.planned_duration=dur}}
    ;(outgoing.get(id)??[]).forEach(d=>{const next=d.successor_activity_id;indegree.set(next,(indegree.get(next)??1)-1);if(indegree.get(next)===0)q.push(next)})}
  return activities
}

const DEFAULT_COLUMNS:Column[]=[
  {key:'code',label:'#',width:44,min:40},{key:'name',label:'Наименование',width:220,min:170,hideable:false},{key:'status',label:'Статус',width:90,min:78},{key:'unit',label:'Ед. изм.',width:58,min:52},{key:'qty',label:'Общий объём',width:74,min:64},{key:'plan',label:'План %',width:64,min:56},{key:'fact',label:'Факт, %',width:62,min:56},{key:'start',label:'План. начало',width:102,min:96},{key:'end',label:'План. окончание',width:108,min:100},{key:'actualStart',label:'Факт. начало',width:102,min:96},{key:'duration',label:'Длит.',width:60,min:54},{key:'forecast',label:'Прогноз окончания',width:108,min:100},{key:'deviation',label:'Отклонение, дни',width:92,min:84},{key:'predecessors',label:'Предшественники',width:128,min:104},{key:'ai',label:'Сигнал',width:100,min:90},
]

export function SchedulePage(){
  const {projectId='parkline'}=useParams();const navigate=useNavigate();const queryClient=useQueryClient();const fileRef=useRef<HTMLInputElement>(null);const workspaceRef=useRef<HTMLDivElement>(null);const timelineRef=useRef<HTMLDivElement>(null);const tableRef=useRef<HTMLDivElement>(null);const draftRef=useRef<ScheduleActivity[]>([]);const scrollLock=useRef(false);const initialScrollKey=useRef('')
  useEffect(()=>{if(projectId)setRemoteProjectId(projectId)},[projectId])
  const httpMode=useHttpBackend()
  const [searchParams]=useSearchParams()
  const objectId=searchParams.get('objectId')
  const [selectedVersion,setSelectedVersion]=useState<number|undefined>();const [expanded,setExpanded]=useState<Set<string>|null>(null);const [scale,setScale]=useState<'day'|'week'|'month'>('week');const [zoom,setZoom]=useState(1);  const [importFile,setImportFile]=useState<File|null>(null);const [preview,setPreview]=useState<ImportPreview|null>(null);const [importOpen,setImportOpen]=useState(false)
  const [mappingOpen,setMappingOpen]=useState(false)
  const [networkModel,setNetworkModel]=useState<NetworkRecoveryModel|null>(null)
  const [draftActivities,setDraftActivities]=useState<ScheduleActivity[]>([]);const [draftDeps,setDraftDeps]=useState<DependencyEdit[]>([]);const [history,setHistory]=useState<Snapshot[]>([]);const [future,setFuture]=useState<Snapshot[]>([]);const [dirty,setDirty]=useState(false);const [autoRecalc,setAutoRecalc]=useState(true);const [connection,setConnection]=useState<ConnectorDraft|null>(null);const [selectedDep,setSelectedDep]=useState<number|null>(null);const [message,setMessage]=useState<string>('');const [search,setSearch]=useState('');const [columns,setColumns]=useState(DEFAULT_COLUMNS);const [hidden,setHidden]=useState<Set<ColKey>>(new Set(['unit','qty','plan','duration','actualStart','predecessors','ai']));const [columnMenu,setColumnMenu]=useState(false);const [tablePanePct,setTablePanePct]=useState(59);const [splitting,setSplitting]=useState(false)
  const [evidenceId,setEvidenceId]=useState<string|null>(null)
  const [commentDraft,setCommentDraft]=useState('');const [commentThread,setCommentThread]=useState<EvidenceComment[]>([]);const [commentSaving,setCommentSaving]=useState(false)
  const [serverAsOf,setServerAsOf]=useState<string>(todayIsoMoscow())
  const deviationsQuery=useQuery({
    queryKey:['deviations',projectId],
    queryFn:async()=>{
      const raw=await api.getDeviations(projectId) as {items?:CvDeviation[]}|CvDeviation[]
      if(Array.isArray(raw))return raw
      return Array.isArray(raw?.items)?raw.items:[]
    },
    enabled:!!projectId&&httpMode,
  })
  const cvByActivity=useMemo(()=>{
    const m=new Map<string,CvDeviation>()
    const raw=deviationsQuery.data as CvDeviation[]|{items?:CvDeviation[]}|undefined
    const list=Array.isArray(raw)?raw:Array.isArray(raw?.items)?raw.items:[]
    for(const d of list){
      if(d.schedule_item_id!=null)m.set(String(d.schedule_item_id),d)
    }
    return m
  },[deviationsQuery.data])
  const evidenceCv=evidenceId?cvByActivity.get(evidenceId):undefined
  const findingQuery=useQuery({
    queryKey:['finding-evidence',projectId,evidenceId,evidenceCv?.id,serverAsOf],
    queryFn:async():Promise<FindingEvidence>=>{
      if(!evidenceId)return {frames:[],signal_kind:'RISK_FROM_SCHEDULE'}
      if(evidenceCv&&(evidenceCv.signal_kind==='CV_VERIFIED_FINDING'||evidenceCv.has_evidence_frames)){
        return api.getDeviationEvidence(projectId,evidenceCv.id) as Promise<FindingEvidence>
      }
      return api.getScheduleItemEvidence(projectId,evidenceId,serverAsOf) as Promise<FindingEvidence>
    },
    enabled:!!projectId&&httpMode&&!!evidenceId,
  })


  const projectQuery=useQuery({queryKey:['project',projectId],queryFn:()=>api.getProject(projectId)});const scheduleQuery=useQuery({queryKey:['schedule',projectId,selectedVersion,objectId],queryFn:()=>api.getSchedule(projectId,selectedVersion,objectId)});const versionsQuery=useQuery({queryKey:['schedule-versions',projectId],queryFn:()=>api.getVersions(projectId)})
  const previewMutation=useMutation({mutationFn:(file:File)=>api.previewImport(projectId,file),onSuccess:data=>{setPreview(data);setImportOpen(true)}})
  const importMutation=useMutation({mutationFn:({file,overrides}:{file:File;overrides?:MappingOverride[]})=>api.importSchedule(projectId,file,overrides),onSuccess:async(result:ImportResult)=>{
    setSelectedVersion(undefined);setImportOpen(false);setMappingOpen(false);setPreview(null);setImportFile(null)
    if(result.network_recovery)setNetworkModel(result.network_recovery)
    setMessage('Версия создана. Сопоставление видов работ сохранено')
    await refreshAll()
  }})
  const workingMutation=useMutation({mutationFn:(sourceVersionId:string|null)=>api.createWorkingCopy(projectId,sourceVersionId),onSuccess:async v=>{setSelectedVersion(v.version);setMessage(`Создана рабочая версия v${v.version}`);await refreshAll()}})
  const finishEditMutation=useMutation({mutationFn:async()=>{
    if(!schedule?.active_version)throw new Error('Нет версии')
    const versionId=schedule.active_version.id
    if(dirty){
      await api.saveScheduleEdits(projectId,{version_id:versionId,activities:draftActivities.map(a=>({id:a.id,name:a.name,code:a.code,unit:a.unit,actual_start:a.actual_start,wbs_node_id:a.wbs_node_id,planned_start:a.planned_start,planned_end:a.planned_end,planned_duration:a.planned_duration,planned_quantity:a.planned_quantity,planned_progress:a.planned_progress,actual_progress:a.actual_progress,forecast_end:a.forecast_end})),dependencies:draftDeps,recalculate:autoRecalc})
    }
    return api.publishSchedule(projectId,versionId)
  },onSuccess:async v=>{setSelectedVersion(v.version);setDirty(false);setHistory([]);setFuture([]);setMessage('Изменения сохранены');await refreshAll()}})

  const refreshAll=async()=>{await queryClient.invalidateQueries({queryKey:['schedule',projectId]});await queryClient.invalidateQueries({queryKey:['schedule-versions',projectId]});await queryClient.invalidateQueries({queryKey:['portfolio']})}
  const schedule=scheduleQuery.data
  useEffect(()=>{
    // Для навигации и линии «сегодня» всегда берём календарную дату Москвы.
    // Срез с сервера может отставать (старый сид) — не подменяем им «актуальную дату».
    setServerAsOf(todayIsoMoscow())
  },[schedule?.active_version?.id])
  useEffect(()=>{
    if(!schedule)return
    // Не подставляем ответ от другого objectId (react-query может кратко держать previous data).
    const selected=schedule.selected_object_id==null||schedule.selected_object_id===''?null:String(schedule.selected_object_id)
    const want=objectId==null||objectId===''?null:String(objectId)
    if(selected!==want)return
    const acts=cloneActivities(schedule.activities)
    const deps=schedule.dependencies.map(depFromServer).filter(Boolean) as DependencyEdit[]
    setDraftActivities(acts);draftRef.current=acts;setDraftDeps(deps)
    const nr=schedule.network_recovery
    setNetworkModel(nr??null)
    setHistory([]);setFuture([]);setDirty(false);setConnection(null);setSelectedDep(null);setEvidenceId(null)
  },[schedule, objectId])
  useEffect(()=>{draftRef.current=draftActivities},[draftActivities])

  const editable=schedule?.active_version?.version_state==='WORKING'
  const defaultExpanded=useMemo(()=>defaultExpandedIds(schedule?.wbs??[]),[schedule?.active_version?.id,schedule?.wbs,objectId])
  useEffect(()=>setExpanded(null),[schedule?.active_version?.id, objectId])
  const effectiveExpanded=expanded??defaultExpanded
  const wbsById=useMemo(()=>{const m=new Map<string,WbsNode>();(schedule?.wbs??[]).forEach(n=>m.set(n.id,n));return m},[schedule?.wbs])
  const allRows=useMemo(()=>buildRows(schedule?.wbs??[],draftActivities,effectiveExpanded),[schedule?.wbs,draftActivities,effectiveExpanded])
  const rows=useMemo(()=>{
    const q=search.trim().toLowerCase()
    if(!q)return allRows
    const activityMatches=new Set(allRows.filter(r=>r.kind==='activity'&&(r.name.toLowerCase().includes(q)||(r.activity?.code??'').toLowerCase().includes(q))).map(r=>r.id))
    if(!activityMatches.size)return []
    const wbsIds=new Set<string>()
    draftActivities.filter(a=>activityMatches.has(a.id)&&a.wbs_node_id).forEach(a=>{
      let id:string|null|undefined=a.wbs_node_id
      while(id){wbsIds.add(id);id=wbsById.get(id)?.parent_id??null}
    })
    return allRows.filter(r=>r.kind==='activity'?activityMatches.has(r.id):wbsIds.has(r.id))
  },[allRows,search,draftActivities,wbsById])

  const rangeBounds=useMemo(()=>{
    const starts=draftActivities.map(r=>r.planned_start).filter(Boolean) as string[]
    const ends=draftActivities.flatMap(r=>[r.planned_end,r.forecast_end]).filter(Boolean) as string[]
    starts.sort();ends.sort()
    const today=todayIso()
    let rangeStart=starts[0]??today;let rangeEnd=ends.at(-1)??rangeStart
    rangeStart=addDays(rangeStart,-14);rangeEnd=addDays(rangeEnd,28)
    // Демо: линия «сегодня» всегда должна попадать в видимый диапазон
    if(today<rangeStart)rangeStart=addDays(today,-7)
    if(today>rangeEnd)rangeEnd=addDays(today,14)
    return {rangeStart,rangeEnd,totalDays:Math.max(1,diffDays(rangeStart,rangeEnd)+1)}
  },[draftActivities])
  let {rangeStart,rangeEnd,totalDays}=rangeBounds
  const basePixels=scale==='day'?28:scale==='week'?11:scale==='month'?4.5:11;const pixelsPerDay=basePixels*zoom;const timelineWidth=Math.max(760,totalDays*pixelsPerDay);const rowHeight=29;const dateX=(value:string|null)=>value?Math.max(0,diffDays(rangeStart,value)*pixelsPerDay):0;const barWidth=(a:ScheduleActivity)=>a.activity_type==='MILESTONE'?12:a.planned_start&&activeEnd(a)?Math.max(12,(diffDays(a.planned_start,activeEnd(a)!)+1)*pixelsPerDay):12;const baselineWidth=(a:ScheduleActivity)=>a.planned_start&&a.planned_end?Math.max(12,(diffDays(a.planned_start,a.planned_end)+1)*pixelsPerDay):12;const todayX=dateX(todayIso());
  const toggle=(id:string)=>startTransition(()=>setExpanded(prev=>{const base=new Set(prev??defaultExpanded);base.has(id)?base.delete(id):base.add(id);return base}))
    const dateField=(value:string|null,onCommit:(iso:string|null)=>void,allowEmpty=true)=>editable
    ? <DateRuInput value={value} onCommit={onCommit} allowEmpty={allowEmpty}/>
    : <span className="date-text">{fmt(value)}</span>
  const goToday=()=>{const el=timelineRef.current;if(!el)return;const x=dateX(todayIso());el.scrollLeft=Math.max(0,x-el.clientWidth*.42)}
  const scrollTimeline=(direction:number)=>{const el=timelineRef.current;if(el)el.scrollBy({left:direction*el.clientWidth*.7,behavior:'smooth'})}
  useEffect(()=>{const key=`${schedule?.active_version?.id}-${scale}-${todayIso()}`;if(!schedule?.active_version||initialScrollKey.current===key)return;initialScrollKey.current=key;requestAnimationFrame(()=>goToday())},[schedule?.active_version?.id,scale,timelineWidth])

  const monthSegments=useMemo(()=>{const out:{key:string;label:string;left:number;width:number}[]=[];const start=toDate(rangeStart);let cursor=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth(),1));const end=toDate(rangeEnd);while(cursor<=end){const next=new Date(Date.UTC(cursor.getUTCFullYear(),cursor.getUTCMonth()+1,1));const segStart=cursor<start?start:cursor;const segEnd=new Date(Math.min(next.getTime()-DAY,end.getTime()));const key=iso(cursor);out.push({key,label:monthLabel(iso(cursor)),left:diffDays(rangeStart,iso(segStart))*pixelsPerDay,width:Math.max(pixelsPerDay,(diffDays(iso(segStart),iso(segEnd))+1)*pixelsPerDay)});cursor=next}return out},[rangeStart,rangeEnd,pixelsPerDay])
  const timeTicks=useMemo(()=>{const out:{key:string,label:string;left:number;width:number}[]=[];if(scale==='month'){monthSegments.forEach(m=>out.push({key:`t-${m.key}`,label:'1',left:m.left,width:m.width}));return out}const step=scale==='day'?1:7;let cursor=rangeStart;if(scale==='week'){const d=toDate(cursor);const dow=(d.getUTCDay()+6)%7;cursor=addDays(cursor,-dow)}while(cursor<=rangeEnd){const left=diffDays(rangeStart,cursor)*pixelsPerDay;out.push({key:cursor,label:String(toDate(cursor).getUTCDate()),left,width:step*pixelsPerDay});cursor=addDays(cursor,step)}return out},[rangeStart,rangeEnd,pixelsPerDay,scale,monthSegments])

  const pushChange=(nextActivities:ScheduleActivity[],nextDeps=draftDeps)=>{const before={activities:cloneActivities(draftActivities),dependencies:cloneDeps(draftDeps)};let acts=cloneActivities(nextActivities);const deps=cloneDeps(nextDeps);if(autoRecalc)acts=recalcDraft(acts,deps);setHistory(h=>[...h.slice(-39),before]);setFuture([]);setDraftActivities(acts);setDraftDeps(deps);setDirty(true)}
  const undo=()=>{const prev=history.at(-1);if(!prev)return;setFuture(f=>[{activities:cloneActivities(draftActivities),dependencies:cloneDeps(draftDeps)},...f]);setHistory(h=>h.slice(0,-1));setDraftActivities(cloneActivities(prev.activities));setDraftDeps(cloneDeps(prev.dependencies));setDirty(true)}
  const redo=()=>{const next=future[0];if(!next)return;setHistory(h=>[...h,{activities:cloneActivities(draftActivities),dependencies:cloneDeps(draftDeps)}]);setFuture(f=>f.slice(1));setDraftActivities(cloneActivities(next.activities));setDraftDeps(cloneDeps(next.dependencies));setDirty(true)}
  const patchActivity=(id:string,patch:Partial<ScheduleActivity>)=>pushChange(draftActivities.map(a=>a.id===id?{...a,...patch}:a))
  const onChoose=(file?:File)=>{if(!file)return;setImportFile(file);previewMutation.mutate(file)}
  const startEdit=()=>schedule?.active_version&&workingMutation.mutate(schedule.active_version.id)

  const startDrag=(e:React.PointerEvent,a:ScheduleActivity,mode:'move'|'start'|'finish')=>{if(!editable||!a.planned_start||!a.planned_end||a.activity_type==='MILESTONE')return;e.preventDefault();e.stopPropagation();const startX=e.clientX;const before={activities:cloneActivities(draftRef.current),dependencies:cloneDeps(draftDeps)};const originalStart=a.planned_start,originalEnd=a.planned_end;let moved=false
    const onMove=(ev:PointerEvent)=>{const delta=Math.round((ev.clientX-startX)/pixelsPerDay);if(delta===0&&!moved)return;moved=true;setDraftActivities(current=>{const next=current.map(x=>{if(x.id!==a.id)return x;if(mode==='move')return{...x,planned_start:addDays(originalStart,delta),planned_end:addDays(originalEnd,delta),forecast_end:x.forecast_end?addDays(x.forecast_end,delta):x.forecast_end};if(mode==='start'){const ns=addDays(originalStart,delta);if(ns>originalEnd)return x;return{...x,planned_start:ns,planned_duration:diffDays(ns,originalEnd)+1}}const ne=addDays(originalEnd,delta);if(ne<originalStart)return x;return{...x,planned_end:ne,forecast_end:ne,planned_duration:diffDays(originalStart,ne)+1}});draftRef.current=next;return next})}
    const onUp=()=>{document.removeEventListener('pointermove',onMove);document.removeEventListener('pointerup',onUp);if(moved){let next=cloneActivities(draftRef.current);if(autoRecalc)next=recalcDraft(next,draftDeps);setDraftActivities(next);setHistory(h=>[...h.slice(-39),before]);setFuture([]);setDirty(true)}};document.addEventListener('pointermove',onMove);document.addEventListener('pointerup',onUp)
  }
  const connect=(activityId:string,side:ConnectorSide)=>{if(!editable)return;if(!connection){setConnection({activityId,side});setMessage('Выберите коннектор второй работы')}else{if(connection.activityId===activityId){setConnection(null);return}const candidate:DependencyEdit={predecessor_activity_id:connection.activityId,successor_activity_id:activityId,relation_type:relationFor(connection.side,side),lag_days:0};if(createsCycle(draftDeps,candidate)){setMessage('Связь не создана: возникнет цикл');setConnection(null);return}const filtered=draftDeps.filter(d=>!(d.predecessor_activity_id===candidate.predecessor_activity_id&&d.successor_activity_id===candidate.successor_activity_id));pushChange(draftActivities,[...filtered,candidate]);setConnection(null);setMessage(`Создана связь ${candidate.relation_type}`)}}
  const removeDep=(index:number)=>{if(!editable)return;pushChange(draftActivities,draftDeps.filter((_,i)=>i!==index));setSelectedDep(null)}
  const reconnectDep=(index:number)=>{if(!editable)return;const dep=draftDeps[index];if(!dep)return;const [sourceSide]=relationSides(dep.relation_type);const next=draftDeps.filter((_,i)=>i!==index);setHistory(h=>[...h,{activities:cloneActivities(draftActivities),dependencies:cloneDeps(draftDeps)}]);setDraftDeps(next);setDirty(true);setSelectedDep(null);setConnection({activityId:dep.predecessor_activity_id,side:sourceSide});setMessage('Связь отсоединена. Выберите новый коннектор назначения')}
  const updateDep=(index:number,patch:Partial<DependencyEdit>)=>{if(!editable)return;const deps=draftDeps.map((d,i)=>i===index?{...d,...patch}:d);if(createsCycle(deps,deps[index])){setMessage('Изменение создаёт цикл');return}pushChange(draftActivities,deps)}
  const exportFile=async(format:'xlsx'|'csv')=>{if(dirty){setMessage('Сначала завершите редактирование');return}const r=await api.exportSchedule(projectId,format,schedule?.active_version?.version);const url=URL.createObjectURL(r.blob);const link=document.createElement('a');link.href=url;link.download=r.filename;link.click();URL.revokeObjectURL(url)}

  const visibleColumns=columns.filter(c=>!hidden.has(c.key));const gridTemplate=visibleColumns.map(c=>`${c.width}px`).join(' ')
  const resizeColumn=(e:React.PointerEvent,key:ColKey)=>{e.preventDefault();const col=columns.find(c=>c.key===key);if(!col)return;const sx=e.clientX,sw=col.width;const move=(ev:PointerEvent)=>setColumns(cols=>cols.map(c=>c.key===key?{...c,width:Math.max(c.min,sw+ev.clientX-sx)}:c));const up=()=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up)};document.addEventListener('pointermove',move);document.addEventListener('pointerup',up)}
  const resizePanes=(e:React.PointerEvent)=>{e.preventDefault();const root=workspaceRef.current;if(!root)return;const splitter=6;setSplitting(true);const move=(ev:PointerEvent)=>{const rect=root.getBoundingClientRect();const usable=Math.max(1,rect.width-splitter);const pct=((ev.clientX-rect.left)/usable)*100;const minPct=(280/usable)*100;const maxPct=100-(300/usable)*100;setTablePanePct(Math.min(Math.max(pct,minPct),Math.max(minPct,maxPct)))};const up=()=>{setSplitting(false);document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up)};document.addEventListener('pointermove',move);document.addEventListener('pointerup',up)}
  const activityMap=useMemo(()=>new Map(draftActivities.map(a=>[a.id,a])),[draftActivities])
  const cell=(r:FlatRow,key:ColKey)=>{const a=r.activity
    if(key==='name'){const open=r.kind==='wbs'&&effectiveExpanded.has(r.id);return <span className={`activity-name ${r.kind==='wbs'?'is-wbs':'is-task'}`} style={{paddingLeft:`${6+r.level*16}px`}}>{r.kind==='wbs'?<><button type="button" className="expand-btn" onClick={()=>toggle(r.id)} aria-expanded={open} aria-label={open?'Свернуть':'Развернуть'}><ChevronDown size={14} strokeWidth={1.8} className={open?'expand-chevron open':'expand-chevron'} aria-hidden/></button><span className="row-kind-icon folder"><SvgIcon name="folder" size={14}/></span></>:<span className="row-kind-icon file"><SvgIcon name="file" size={13}/></span>}<span className="activity-label"><b>{r.name}</b></span></span>}
    if(key==='code')return <span>—</span>
    if(key==='unit')return a&&editable?<input value={a.unit??''} onChange={e=>patchActivity(a.id,{unit:e.target.value})}/>:<span>{r.unit||'—'}</span>
    if(key==='qty')return a&&editable?<input type="number" value={a.planned_quantity??''} onChange={e=>patchActivity(a.id,{planned_quantity:e.target.value?Number(e.target.value):null})}/>:<span>{r.qty==null?'—':r.qty.toLocaleString('ru-RU')}</span>
    if(key==='plan')return <span>{Math.round(r.plan)}%</span>
    if(key==='fact')return <span className="fact-cell">{Math.round(r.fact)}%</span>
    if(key==='start')return a?dateField(a.planned_start,v=>{if(!v)return;patchActivity(a.id,{planned_start:v,planned_duration:a.planned_end?diffDays(v,a.planned_end)+1:a.planned_duration})},false):<span className="date-text">{fmt(r.start)}</span>
    if(key==='end')return a?dateField(a.planned_end,v=>{if(!v)return;patchActivity(a.id,{planned_end:v,forecast_end:a.forecast_end&&a.forecast_end>v?a.forecast_end:v,planned_duration:a.planned_start?diffDays(a.planned_start,v)+1:a.planned_duration})},false):<span className="date-text">{fmt(r.end)}</span>
    if(key==='actualStart')return a?dateField(a.actual_start,v=>patchActivity(a.id,{actual_start:v})):<span className="date-text">—</span>
    if(key==='duration')return <span>{a?durationDays(a):r.start&&r.end?diffDays(r.start,r.end)+1:'—'}</span>
    if(key==='forecast')return a?dateField(a.forecast_end,v=>patchActivity(a.id,{forecast_end:v})):<span className="date-text">{fmt(r.forecast)}</span>
    if(key==='deviation')return <span className={(r.deviation??0)>0?'bad-text':''}>{(r.deviation??0)>0?`+${r.deviation}`:'0'}</span>
    if(key==='predecessors'){if(!a)return <span>—</span>;const incoming=draftDeps.filter(d=>d.successor_activity_id===a.id);return <span className="predecessor-cell">{incoming.length?incoming.map(d=>{const p=activityMap.get(d.predecessor_activity_id);return `${p?.code||p?.external_id||'Работа'} ${d.relation_type}${d.lag_days?`${d.lag_days>0?'+':''}${d.lag_days}д`:''}`}).join(', '):'—'}</span>}
    if(key==='ai'){const sig=a?evidenceSignal(a,cvByActivity):null;return <span className="ai-placeholder">{sig==='DEVIATION'?'● Камера':sig==='RISK'?'◐ Риск':'○ Нет'}</span>}
    return <span className={`schedule-state ${r.state.toLowerCase()}`}><i/>{stateLabel(r.state)}</span>
  }

  const displayDeps=useMemo<DisplayDep[]>(()=>[
    ...draftDeps.map(d=>({...d,displayKind:'confirmed' as const})),
    ...((networkModel?.proposed||[]).filter(p=>p.status==='proposed').map(p=>({
      id:p.id,
      predecessor_activity_id:p.predecessor_activity_id,
      successor_activity_id:p.successor_activity_id,
      relation_type:(p.relation_type||'FS') as DependencyEdit['relation_type'],
      lag_days:p.lag_days||0,
      displayKind:'proposed' as const,
      proposalId:p.id,
    }))),
  ],[draftDeps,networkModel?.proposed])

  const dependencyPaths=useMemo(()=>{
    const rowIndex=new Map(rows.map((r,i)=>[r.id,i]))
    // Только рёбра с обоими видимыми концами — свёрнутый WBS режет цепочки Строгино
    const out:{index:number;d:DisplayDep;color:string;path:string;proposed:boolean;proposalId?:string;fromSide:ConnectorSide;toSide:ConnectorSide}[]=[]
    displayDeps.forEach((d,i)=>{
      const pred=activityMap.get(d.predecessor_activity_id),succ=activityMap.get(d.successor_activity_id)
      const pi=rowIndex.get(d.predecessor_activity_id),si=rowIndex.get(d.successor_activity_id)
      if(!pred||!succ||pi==null||si==null||!pred.planned_start||!pred.planned_end||!succ.planned_start||!succ.planned_end)return
      const [fromSide,toSide]=relationSides(d.relation_type)
      const x1=fromSide==='finish'?dateX(pred.planned_start)+barWidth(pred):dateX(pred.planned_start)
      const x2=toSide==='finish'?dateX(succ.planned_start)+barWidth(succ):dateX(succ.planned_start)
      const y1=pi*rowHeight+13,y2=si*rowHeight+13
      const color=d.displayKind==='proposed'?'#8aa0b5':depStroke(deriveState(pred))
      out.push({index:i,d,color,path:dependencyArrowPath(d.relation_type,x1,y1,x2,y2),proposed:d.displayKind==='proposed',proposalId:d.proposalId,fromSide,toSide})
    })
    return out
  },[displayDeps,rows,activityMap,pixelsPerDay,rangeStart,rowHeight])
  const syncVertical=(source:'table'|'timeline')=>{if(scrollLock.current)return;const from=source==='table'?tableRef.current:timelineRef.current;const to=source==='table'?timelineRef.current:tableRef.current;if(!from||!to)return;scrollLock.current=true;to.scrollTop=from.scrollTop;requestAnimationFrame(()=>{scrollLock.current=false})}
  const rangeCaption=`${shortMonth(rangeStart)} — ${shortMonth(rangeEnd)}`
  const evidenceAct=evidenceId?activityMap.get(evidenceId)??draftActivities.find(a=>a.id===evidenceId)??null:null
  const evidenceKind=evidenceAct?evidenceSignal(evidenceAct,cvByActivity):null
  const evidenceMeta=evidenceAct&&evidenceKind?evidenceCopy(evidenceAct,evidenceKind,evidenceCv):null
  const evidenceWbs=evidenceAct?.wbs_node_id?schedule?.wbs.find(n=>n.id===evidenceAct.wbs_node_id):null
  const openEvidence=(id:string)=>{setEvidenceId(id);setSelectedDep(null)}
  useEffect(()=>{
    if(!evidenceId){setCommentDraft('');setCommentThread([]);return}
    let cancelled=false
    const signal=evidenceKind??'RISK'
    api.getEvidenceThread(evidenceId,signal).then(thread=>{if(!cancelled)setCommentThread(thread)})
    return()=>{cancelled=true}
  },[evidenceId,evidenceAct?.id,evidenceKind])
  const sendEvidenceComment=async()=>{
    if(!evidenceId||!commentDraft.trim()||commentSaving)return
    setCommentSaving(true)
    try{
      const thread=await api.addEvidenceComment(evidenceId,commentDraft,evidenceKind??'RISK')
      setCommentThread(thread);setCommentDraft('');setMessage('Комментарий сохранён')
    }finally{setCommentSaving(false)}
  }
  const discussion=useMemo(()=>[...commentThread].sort((a,b)=>b.at.localeCompare(a.at)),[commentThread])
  const hasUserComments=commentThread.some(c=>c.kind==='user')
  const commentCountLabel=(n:number)=>n===1?'1 комментарий':n>=2&&n<=4?`${n} комментария`:`${n} комментариев`
  const badgeSchedule=null

  const patchRecovery=async(proposalId:string,status:'confirmed'|'rejected')=>{
    const vid=schedule?.active_version?.id
    if(!vid||!networkModel)return
    const proposed=(networkModel.proposed||[]).map(p=>p.id===proposalId?{...p,status}:p)
    const next=await api.updateNetworkRecovery(projectId,vid,{...networkModel,proposed})
    setNetworkModel(next as NetworkRecoveryModel)
    setMessage(status==='confirmed'?'Связь подтверждена и записана в график':'Предложение отклонено')
    await refreshAll()
  }

  return <div className="schedule-layout"><div className="schedule-main schedule-editor-main">

      {(networkModel?.proposed||[]).some(p=>p.status==='proposed')&&(
        <div className="network-recovery-bar" style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap',padding:'6px 10px',background:'#fff8e8',border:'1px solid #f0d48a',borderRadius:6,margin:'0 0 8px',fontSize:12}}>
          <b>Восстановление связей:</b>
          <span>{(networkModel?.proposed||[]).filter(p=>p.status==='proposed').length} предложений</span>
          {(networkModel?.proposed||[]).filter(p=>p.status==='proposed').slice(0,5).map(p=>(
            <span key={p.id} style={{display:'inline-flex',gap:4,alignItems:'center'}}>
              <code>{p.relation_type||'FS'}</code>
              <button type="button" className="header-action" onClick={()=>patchRecovery(p.id,'confirmed')}>Принять</button>
              <button type="button" className="header-action" onClick={()=>patchRecovery(p.id,'rejected')}>Отклонить</button>
            </span>
          ))}
        </div>
      )}
    <div className="schedule-toolbar">
      <div className="schedule-title-area">
        <button className="back-button" onClick={()=>navigate('/')} aria-label="Назад"><SvgIcon name="back" size={20}/></button>
        <div className="schedule-title-block" data-tour-id="schedule-title"><div className="title-with-state"><h1>{projectQuery.data?.name??'Проект'}</h1>{schedule?.active_version&&<span className="version-chip"><i/>Актуальная версия</span>}{editable&&<span className="draft-chip">Черновик</span>}{dirty&&<span className="unsaved-dot">Есть изменения</span>}</div><small className="project-location">{[projectQuery.data?.region,projectQuery.data?.address].filter(Boolean).join(', ')}</small></div>
      </div>
      <div className="toolbar-actions editor-actions">
        <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={e=>onChoose(e.target.files?.[0])}/>
        <button className="header-action icon-only" onClick={()=>fileRef.current?.click()} title="Импорт" aria-label="Импорт"><SvgIcon name="upload"/></button>
        <button className="header-action icon-only" onClick={()=>exportFile('xlsx')} title="Экспорт" aria-label="Экспорт"><SvgIcon name="download"/></button>
        {!editable&&schedule?.active_version?<button className="primary finish-edit" disabled={workingMutation.isPending} onClick={startEdit}>Редактировать график</button>:editable&&<button className="primary finish-edit" disabled={finishEditMutation.isPending} onClick={()=>finishEditMutation.mutate()}><SvgIcon name="check"/>{finishEditMutation.isPending?'Сохраняю…':'Завершить редактирование'}</button>}
      </div>
    </div>
    <div className="workspace-controlbar">
      <div className="controlbar-left"><button className="filter-button"><SvgIcon name="filter"/>Фильтры</button><div className="workspace-search"><SvgIcon name="search"/><input placeholder="Поиск по задачам..." value={search} onChange={e=>setSearch(e.target.value)}/></div>{editable&&<><button className="editor-mini" title="Отменить" disabled={!history.length} onClick={undo}>↶</button><button className="editor-mini" title="Повторить" disabled={!future.length} onClick={redo}>↷</button></>}</div>
      <div className="workspace-tools"><label className="scale-select"><span>Масштаб:</span><select value={scale} onChange={e=>setScale(e.target.value as 'day'|'week'|'month')}><option value="day">Дни</option><option value="week">Недели</option><option value="month">Месяцы</option></select></label><span className="asof-chip" title="Календарная дата среза (Москва)">Сегодня · {todayCaptionShort(serverAsOf)}</span><button type="button" onClick={goToday} title={`Перейти к ${todayCaptionShort(todayIso())}`}>К актуальной дате</button><div className="period-nav"><button onClick={()=>scrollTimeline(-1)}><SvgIcon name="chevLeft"/></button><button onClick={()=>scrollTimeline(1)}><SvgIcon name="chevRight"/></button></div><button className="range-button"><SvgIcon name="calendar"/>{rangeCaption}</button><div className="header-more-wrap"><button className="more-button" onClick={()=>setColumnMenu(v=>!v)} title="Ещё" aria-label="Ещё"><SvgIcon name="more"/></button>{columnMenu&&<div className="header-more-menu"><label className="menu-caption">Версия<select value={selectedVersion??''} onChange={e=>setSelectedVersion(e.target.value?Number(e.target.value):undefined)}><option value="">Актуальная версия</option>{versionsQuery.data?.map(v=><option key={v.id} value={v.version}>v{v.version} · {versionLabel(v.version_state)}</option>)}</select></label><label className="menu-toggle"><input type="checkbox" checked={autoRecalc} onChange={e=>setAutoRecalc(e.target.checked)}/>Автопересчёт зависимостей</label><div className="menu-divider"/><b>Колонки таблицы</b>{columns.map(c=><label className="menu-toggle" key={c.key}><input type="checkbox" checked={!hidden.has(c.key)} disabled={c.hideable===false} onChange={()=>setHidden(h=>{const n=new Set(h);n.has(c.key)?n.delete(c.key):n.add(c.key);return n})}/>{c.label}</label>)}<button className="menu-export" onClick={()=>exportFile('csv')}>Экспорт CSV</button></div>}</div></div>
    </div>
    {message&&<div className="workspace-message" onClick={()=>setMessage('')}>{message}<span>×</span></div>}
    {connection&&<div className="connection-banner"><SvgIcon name="link"/>Выбрана исходная работа. Нажмите коннектор начала или окончания другой работы.<button onClick={()=>setConnection(null)}>Отмена</button></div>}
      {/* What-if panel скрыт: без подтверждённой сети сценарии выглядят сломанными */}
      {scheduleQuery.isLoading?<div className="schedule-empty">Загрузка графика…</div>:!schedule?.active_version?<div className="schedule-empty"><b>Календарный график ещё не загружен</b><span>Импортируйте XLSX или CSV. Перед сохранением PlanSight покажет предварительную проверку.</span><button className="primary" onClick={()=>fileRef.current?.click()}>Импортировать график</button></div>:
      <>
      <div className={`gantt-workspace${splitting?' is-splitting':''}`} ref={workspaceRef} data-tour-id="gantt-workspace">
        <div className="gantt-table-pane" ref={tableRef} style={{flex:`0 0 ${tablePanePct}%`}} onScroll={()=>syncVertical('table')}>
          <div className="editor-table-head" style={{gridTemplateColumns:gridTemplate}}>{visibleColumns.map(c=><div key={c.key} className={`editor-th th-${c.key}`}>{c.key==='code'?<><input type="checkbox" aria-label="Выбрать все"/><span>#</span></>:c.label}<span className="col-resizer" onPointerDown={e=>resizeColumn(e,c.key)}/></div>)}</div>
          <div className="editor-table-body">{rows.map((r,rowIndex)=><div className={`editor-table-row ${r.kind==='wbs'?'wbs-row':''}${evidenceId===r.id?' is-evidence-focus':''}`} style={{gridTemplateColumns:gridTemplate}} key={r.id}>{visibleColumns.map(c=><div className={`editor-cell cell-${c.key}`} key={c.key}>{c.key==='code'?<span className="row-selector"><input type="checkbox"/><b>{rowIndex+1}</b></span>:cell(r,c.key)}</div>)}</div>)}</div>
        </div>
        <div className="gantt-pane-splitter" role="separator" aria-orientation="vertical" aria-label="Изменить ширину таблицы и шкалы" onPointerDown={resizePanes}/>
        <div className="gantt-timeline-pane" ref={timelineRef} onScroll={()=>syncVertical('timeline')}>
          <div className="editor-timeline-track" style={{width:`${timelineWidth}px`}}>
            <div className="editor-time-head"><div className="editor-month-row">{monthSegments.map(m=><span key={m.key} style={{left:`${m.left}px`,width:`${m.width}px`}}>{m.label}</span>)}</div><div className="editor-tick-row">{timeTicks.map(t=><span key={t.key} style={{left:`${t.left}px`,width:`${t.width}px`}}>{t.label}</span>)}</div></div>
            <div className="editor-timeline-body" style={{height:`${rows.length*rowHeight}px`,backgroundSize:`${Math.max(1,(scale==='day'?1:7)*pixelsPerDay)}px 100%`}}>
              {todayX>=0&&todayX<=timelineWidth&&<div className="editor-today-line" style={{left:`${todayX}px`}}><b>{fmt(todayIso())}</b></div>}
              {rows.map((r,i)=><div className={`editor-time-row ${r.kind==='wbs'?'wbs-row':''}${evidenceId===r.id?' is-evidence-focus':''}`} style={{top:`${i*rowHeight}px`}} key={r.id}>
                {r.kind==='wbs'&&r.start&&r.end&&(()=>{const w=Math.max(12,(diffDays(r.start,r.end)+1)*pixelsPerDay);const l=dateX(r.start);return <div className="gantt-summary-bar" style={{left:`${l}px`,width:`${w}px`}}/>})()}
                {r.kind==='activity'&&r.activity&&r.start&&r.end&&r.activity.activity_type==='MILESTONE'&&<div className="gantt-milestone" style={{left:`${dateX(r.start)-6}px`}} title={r.name}><span/><em>{r.name}</em></div>}
                {r.kind==='activity'&&r.activity&&r.start&&r.end&&r.activity.activity_type!=='MILESTONE'&&(()=>{
                  const act=r.activity!;const planEnd=act.planned_end!;const forecast=act.forecast_end||planEnd;const late=!!(forecast&&planEnd&&forecast>planEnd);const left=dateX(r.start);const baseW=baselineWidth(act);const fullW=barWidth(act);const signal=evidenceSignal(act,cvByActivity)
                  return <>
                    <div className="gantt-baseline" style={{left:`${left}px`,width:`${baseW}px`}}/>
                    <div className={`editable-gantt-bar schedule-${r.state.toLowerCase()} ${late?'is-late':''} ${connection?.activityId===r.id?'connecting':''}`} style={{left:`${left}px`,width:`${fullW}px`}} onPointerDown={e=>startDrag(e,act,'move')}>
                      {editable&&<button className="connector connector-start" onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();connect(r.id,'start')}} title="Коннектор начала"/>}
                      {editable&&<span className="resize-handle resize-left" onPointerDown={e=>startDrag(e,act,'start')}/>}
                      <div className="bar-fact" style={{width:`${Math.min(100,r.fact)}%`}}/>
                      {late&&fullW>baseW&&<span className="gantt-delay-seg" style={{left:`${baseW}px`,width:`${Math.max(2,fullW-baseW)}px`}}/>}
                      {late&&!signal&&<i className="gantt-delay-end" aria-hidden/>}
                      {editable&&<span className="resize-handle resize-right" onPointerDown={e=>startDrag(e,act,'finish')}/>}
                      {editable&&<button className="connector connector-finish" onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();connect(r.id,'finish')}} title="Коннектор окончания"/>}
                    </div>
                    {signal&&<button type="button" className={`gantt-evidence evidence-${signal.toLowerCase()}${evidenceId===r.id?' is-active':''}`} style={{left:`${left+fullW-5}px`}} title={evidenceLabel(signal)} aria-label={evidenceLabel(signal)} onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();e.preventDefault();openEvidence(r.id)}}/>}
                  </>
                })()}
              </div>)}
              <svg className="dependency-layer" width={timelineWidth} height={rows.length*rowHeight}>
                <defs>
                  <marker id="dep-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">
                    <path d="M0,0.6 L6.5,3.5 L0,6.4 Z" fill="context-stroke"/>
                  </marker>
                  <marker id="dep-arrow-proposed" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto" markerUnits="userSpaceOnUse">
                    <path d="M0,0.6 L6.5,3.5 L0,6.4 Z" fill="#8aa0b5"/>
                  </marker>
                </defs>
                {dependencyPaths.map(p=><path key={`${p.d.predecessor_activity_id}-${p.d.successor_activity_id}-${p.index}`} className={`dependency-path ${p.proposed?'is-proposed':''} ${(selectedDep!=null&&!p.proposed&&draftDeps[selectedDep]?.predecessor_activity_id===p.d.predecessor_activity_id&&draftDeps[selectedDep]?.successor_activity_id===p.d.successor_activity_id)?'selected':''}`} d={p.path} style={{stroke:p.color}} markerEnd={p.proposed?'url(#dep-arrow-proposed)':'url(#dep-arrow)'} onClick={()=>{const di=draftDeps.findIndex(d=>d.predecessor_activity_id===p.d.predecessor_activity_id&&d.successor_activity_id===p.d.successor_activity_id);setSelectedDep(di>=0?di:null)}}/>)}
              </svg>
              <div className="gantt-pct-layer" aria-hidden>
                {rows.map((r,i)=>{
                  if(r.kind==='wbs'&&r.start&&r.end){
                    const w=Math.max(12,(diffDays(r.start,r.end)+1)*pixelsPerDay)
                    const l=dateX(r.start)
                    return <span key={`pct-${r.id}`} className="gantt-bar-pct" style={{top:`${i*rowHeight+2}px`,left:`${l+w+8}px`}}>{Math.round(r.fact)}%</span>
                  }
                  if(r.kind==='activity'&&r.activity&&r.start&&r.end&&r.activity.activity_type!=='MILESTONE'){
                    const act=r.activity
                    const left=dateX(r.start)
                    const fullW=barWidth(act)
                    const hasOut=displayDeps.some(d=>d.predecessor_activity_id===r.id&&(d.relation_type==='FS'||d.relation_type==='FF'))
                    return <span key={`pct-${r.id}`} className="gantt-bar-pct" style={{top:`${i*rowHeight+2}px`,left:`${left+fullW+(hasOut?14:8)}px`}}>{Math.round(r.fact)}%</span>
                  }
                  return null
                })}
              </div>
              {selectedDep!=null&&draftDeps[selectedDep]&&editable&&(()=>{const dep=draftDeps[selectedDep];const tip=dep.relation_type==='SS'?'Начало → начало':dep.relation_type==='FF'?'Конец → конец':dep.relation_type==='SF'?'Начало → конец':'Конец → начало';return <div className="dependency-popover"><b>Связь {dep.relation_type}</b><small className="dep-anchor-hint">{tip}</small><select value={dep.relation_type} onChange={e=>updateDep(selectedDep,{relation_type:e.target.value as DependencyEdit['relation_type']})}><option value="FS">FS · конец→начало</option><option value="SS">SS · начало→начало</option><option value="FF">FF · конец→конец</option><option value="SF">SF · начало→конец</option></select><label>Lag <input type="number" value={dep.lag_days} onChange={e=>updateDep(selectedDep,{lag_days:Number(e.target.value)})}/> дн.</label><button onClick={()=>reconnectDep(selectedDep)}>Переподключить</button><button className="danger-btn" onClick={()=>removeDep(selectedDep)}>Удалить</button><button onClick={()=>setSelectedDep(null)}>×</button></div>})()}
            </div>
          </div>
        </div>
      </div>
      <div className="gantt-footer"><div className="gantt-legend"><span><i className="dot task"/>Задача</span><span><i className="dot completed"/>Выполнено</span><span><i className="diamond evidence-deviation"/>Отклонение</span><span><i className="diamond evidence-risk"/>Риск</span><span><i className="line"/>Связь</span></div><div className="zoom-control"><button onClick={()=>setZoom(z=>Math.max(.7,Number((z-.1).toFixed(1))))}>−</button><span>{Math.round(zoom*100)}%</span><button onClick={()=>setZoom(z=>Math.min(1.5,Number((z+.1).toFixed(1))))}>+</button></div></div>
      </>
    }
  </div>
  <FindingDrawer
    open={Boolean(evidenceAct&&evidenceKind)}
    onClose={()=>setEvidenceId(null)}
    title={evidenceAct?.name||'Работа'}
    subtitle={[projectQuery.data?.name,evidenceWbs?.name].filter(Boolean).join(' · ')}
    loading={httpMode&&findingQuery.isLoading}
    evidence={httpMode?(findingQuery.data as FindingEvidence|undefined)||null:null}
    editorial={evidenceAct&&evidenceMeta?{
      title:evidenceMeta.title,
      text:evidenceMeta.text,
      expected:evidenceMeta.expected,
      detected:evidenceMeta.detected,
      rule:evidenceMeta.rule,
      asOf:asOfCaption(serverAsOf),
      plan:evidenceAct.planned_progress??0,
      fact:evidenceAct.actual_progress??0,
      plannedEnd:evidenceAct.planned_end,
      forecastEnd:evidenceAct.forecast_end,
      state:deriveState(evidenceAct),
    }:null}
    commentsSlot={<div className="evidence-comment">
      <div className="evidence-composer">
        <label>Комментарий аналитика
          <textarea rows={4} value={commentDraft} placeholder="Напишите комментарий по этому риску или отклонению…" onChange={e=>setCommentDraft(e.target.value)} onKeyDown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter')void sendEvidenceComment()}}/>
        </label>
        <button type="button" className="primary" disabled={commentSaving||!commentDraft.trim()} onClick={()=>void sendEvidenceComment()}>{commentSaving?'Отправляю…':'Отправить комментарий'}</button>
      </div>
      <div className="evidence-discussion">
        <div className="evidence-discussion-head"><b>Обсуждение</b><span>{commentCountLabel(discussion.length)}</span></div>
        <div className="evidence-discussion-list">
          {discussion.map(item=><article key={item.id} className={`evidence-msg kind-${item.kind}`}>
            <span className={`evidence-avatar kind-${item.kind}`}>{item.initials}</span>
            <div className="evidence-msg-body">
              <div className="evidence-msg-meta"><div><b>{item.author}</b><small>{item.role}</small></div><time>{api.formatEvidenceCommentAt(item.at)}</time></div>
              <p>{item.text}</p>
            </div>
          </article>)}
        </div>
      </div>
    </div>}
  />
  {(importOpen||previewMutation.isPending)&&<div className="modal-backdrop"><div className={`import-modal${preview?.mapping_rows?.length?' mapping-review-modal':''}`}>
    <div className="modal-head"><div><small>Предпросмотр импорта</small><h2>{importFile?.name}</h2></div><button onClick={()=>{setImportOpen(false);setMappingOpen(false)}}>×</button></div>
    {previewMutation.isPending?<div className="preview-loading">Разбираю файл и сопоставляю виды работ…</div>:preview&&(
      preview.mapping_rows?.length&&importFile?(
        <CanonicalMappingModal
          embedded
          rows={preview.mapping_rows}
          filename={importFile.name}
          recognizedCount={preview.activities}
          applying={importMutation.isPending}
          onCancel={()=>setImportOpen(false)}
          onApply={overrides=>importMutation.mutate({file:importFile,overrides})}
        />
      ):(
        <>
          <div className="preview-kpis">
            <div className="is-hero"><span>Распознано работ</span><b>{preview.activities}</b></div>
            <div><span>WBS узлов</span><b>{preview.wbs_nodes}</b></div>
            <div><span>Период</span><b>{fmt(preview.period_start)} — {fmt(preview.period_end)}</b></div>
            <div><span>Связей в файле</span><b>{preview.dependencies}</b></div>
          </div>
          <div className="mapped-columns"><b>Распознанные колонки</b><div>{Object.entries(preview.mapped_columns).map(([k,v])=><span key={k}><code>{k}</code> ← {v}</span>)}</div></div>
          <div className="issue-list">{preview.issues.length===0?<div className="issue ok">✓ Critical/Warning не обнаружены</div>:preview.issues.map((i,n)=><div className={`issue ${i.level}`} key={`${i.code}-${n}`}><b>{i.level.toUpperCase()}</b><span>{i.message}{i.row?` · строка ${i.row}`:''}</span></div>)}</div>
          <div className="modal-actions"><button onClick={()=>setImportOpen(false)}>Отмена</button><button className="primary" disabled={!preview.can_import||!importFile||importMutation.isPending} onClick={()=>importFile&&importMutation.mutate({file:importFile})}>{importMutation.isPending?'Импортирую…':'Создать новую версию'}</button></div>
        </>
      )
    )}
  </div></div>}
  </div>
}
