import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type PortfolioRow, type SeverityWorks } from '../api/client'
import { ProjectMap, type ProjectMapPoint } from '../components/ProjectMap'
import { TrainingLauncher } from '../components/TrainingLauncher'
import { COMPANY_GROUP_OPTIONS, companyGroupById } from '../data/companyGroups'
import { projectStatusRu } from '../labels/ru'
import { useTourOptional } from '../tour/TourProvider'

const STATUS_OPTIONS:[string,string][]=[
  ['ON_TRACK','В норме'],
  ['AT_RISK','Риск'],
  ['DELAYED','Отставание'],
  ['NO_DATA','Нет данных'],
  ['COMPLETED','Завершён'],
]
type Filters={companyGroup:string;developer:string;project:string;object:string;region:string;status:string;from:string;to:string;onlyDelayed:boolean;showProjects:boolean;showObjects:boolean}
const initialFilters:Filters={companyGroup:'all',developer:'all',project:'all',object:'all',region:'all',status:'all',from:'',to:'',onlyDelayed:false,showProjects:true,showObjects:true}

const matchesCompanyGroup=(p:PortfolioRow,filter:string)=>{
  if(filter==='all')return true
  if(p.companyGroupId===filter)return true
  // Устаревшее: раньше в фильтр писали имя группы, а не group_id
  if(p.companyGroup===filter)return true
  return false
}

const severityOf=(p:PortfolioRow):SeverityWorks=>{
  if(p.severityWorks)return p.severityWorks
  // Запасной вариант, пока API не отдаёт бакеты по работам
  if(p.maxDeviation>10)return {critical:p.problemWorks,high:0,medium:0,normal:Math.max(0,p.totalWorks-p.problemWorks)}
  if(p.maxDeviation>5)return {critical:0,high:p.problemWorks,medium:0,normal:Math.max(0,p.totalWorks-p.problemWorks)}
  if(p.problemWorks)return {critical:0,high:0,medium:p.problemWorks,normal:Math.max(0,p.totalWorks-p.problemWorks)}
  return {critical:0,high:0,medium:0,normal:p.totalWorks}
}

export function AnalyticsPage(){
  const navigate=useNavigate()
  const tour=useTourOptional()
  const [scenarioPickerOpen,setScenarioPickerOpen]=useState(false)
  const q=useQuery({
    queryKey:['portfolio'],
    queryFn:api.getPortfolio,
    staleTime:60_000,
    refetchOnWindowFocus:false,
    refetchOnReconnect:true,
    retry:2,
  })
  const [draft,setDraft]=useState<Filters>(initialFilters)
  const [applied,setApplied]=useState<Filters>(initialFilters)
  const [tableSearch,setTableSearch]=useState('')
  const [appliedPulse,setAppliedPulse]=useState(false)
  const projects=q.data?.projects??[]
  const trainingProjectId=useMemo(()=>{
    const attention=projects.find(p=>p.status==='DELAYED'||p.status==='AT_RISK')
    return String(attention?.id||projects[0]?.id||'0')
  },[projects])

  const startQuickTour=()=>{
    tour?.startScenario('quick', trainingProjectId)
  }

  useEffect(()=>{
    const normalize=(f:Filters)=>{
      if(f.companyGroup==='all'||companyGroupById(f.companyGroup))return f
      const byName=COMPANY_GROUP_OPTIONS.find(([,name])=>name===f.companyGroup)
      return {...f,companyGroup:byName?.[0]??'all',developer:'all',project:'all',object:'all'}
    }
    setDraft(prev=>normalize(prev))
    setApplied(prev=>normalize(prev))
  },[])

  const reseedAttempted=useRef(false)
  useEffect(()=>{
    if(!q.isFetched||q.isFetching||q.isError)return
    if((q.data?.projects.length??0)>0){reseedAttempted.current=false;return}
    if(reseedAttempted.current)return
    reseedAttempted.current=true
    api.resetDemo()
    void q.refetch()
  },[q.isFetched,q.isFetching,q.isError,q.data?.projects.length,q.refetch])

  const developers=useMemo(()=>{
    const list=draft.companyGroup==='all'
      ? projects.map(p=>p.developer)
      : projects.filter(p=>matchesCompanyGroup(p,draft.companyGroup)).map(p=>p.developer)
    return [...new Set(list)].sort()
  },[projects,draft.companyGroup])
  const regions=[...new Set(projects.map(p=>p.region))].sort()
  const draftProjects=projects.filter(p=>{
    if(!matchesCompanyGroup(p,draft.companyGroup))return false
    if(draft.developer!=='all'&&p.developer!==draft.developer)return false
    return true
  })
  const draftObjects=draft.project==='all'
    ? draftProjects.flatMap(p=>p.objects.map(o=>({value:o.id,label:`${p.name} — ${o.name}`})))
    : (projects.find(p=>p.id===draft.project)?.objects??[]).map(o=>({value:o.id,label:o.name}))

  const rows=useMemo(()=>projects.filter(p=>{
    if(!matchesCompanyGroup(p,applied.companyGroup))return false
    if(applied.developer!=='all'&&p.developer!==applied.developer)return false
    if(applied.project!=='all'&&p.id!==applied.project)return false
    if(applied.object!=='all'&&!p.objects.some(o=>o.id===applied.object))return false
    if(applied.region!=='all'&&p.region!==applied.region)return false
    if(applied.status!=='all'&&p.status!==applied.status)return false
    if(applied.onlyDelayed&&p.status!=='DELAYED'&&p.status!=='AT_RISK')return false
    if(applied.from&&p.lastAnalysisDate&&p.lastAnalysisDate<applied.from)return false
    if(applied.to&&p.lastAnalysisDate&&p.lastAnalysisDate>applied.to)return false
    return true
  }),[projects,applied])

  const visibleRows=useMemo(()=>{const s=tableSearch.trim().toLowerCase();return !s?rows:rows.filter(p=>`${p.name} ${p.developer} ${p.region} ${p.address}`.toLowerCase().includes(s))},[rows,tableSearch])
  const delayed=rows.filter(p=>p.status==='DELAYED').length
  const problemWorks=rows.reduce((s,p)=>s+p.problemWorks,0)
  const totalWorks=rows.reduce((s,p)=>s+p.totalWorks,0)
  const max=rows.reduce<PortfolioRow|null>((best,p)=>!best||p.maxDeviation>best.maxDeviation?p:best,null)
  const hasFilter=JSON.stringify(applied)!==JSON.stringify(initialFilters)

  const severity=useMemo(()=>{
    let critical=0,high=0,medium=0,normal=0
    rows.forEach(p=>{
      const b=severityOf(p)
      critical+=b.critical;high+=b.high;medium+=b.medium;normal+=b.normal
    })
    const sum=critical+high+medium+normal||1
    return [
      {name:'Критические (> 10 дней)',value:critical,color:'#ff3348',pct:Math.round(critical/sum*100)},
      {name:'Значительные (5–10 дней)',value:high,color:'#ff8a27',pct:Math.round(high/sum*100)},
      {name:'Незначительные (1–5 дней)',value:medium,color:'#ffc51f',pct:Math.round(medium/sum*100)},
      {name:'Без отклонений (активные)',value:normal,color:'#24b985',pct:Math.round(normal/sum*100)}
    ]
  },[rows])

  const barData=useMemo(()=>rows.slice(0,6).map(p=>{
    const b=severityOf(p)
    return {name:p.name.replace('ЖК «','').replace('»',''),critical:b.critical,high:b.high,medium:b.medium,normal:b.normal,total:p.problemWorks}
  }),[rows])

  const mapPoints=useMemo(()=>{
    const out:ProjectMapPoint[]=[]
    rows.forEach(p=>{
      if(applied.showProjects)out.push({id:`p-${p.id}`,projectId:p.id,name:p.name,subtitle:`${p.developer} · ${p.region}`,kind:'project',lat:p.lat,lng:p.lng,status:p.status,problemWorks:p.problemWorks,maxDeviation:p.maxDeviation})
      if(applied.showObjects)p.objects.filter(o=>applied.object==='all'||o.id===applied.object).forEach(o=>out.push({id:`o-${o.id}`,projectId:p.id,name:o.name,subtitle:`${p.name} · ${p.developer}`,kind:'object',lat:o.lat,lng:o.lng,status:p.status,problemWorks:p.problemWorks,maxDeviation:p.maxDeviation}))
    })
    return out
  },[rows,applied.showProjects,applied.showObjects,applied.object])

  const setDraftValue=<K extends keyof Filters>(key:K,value:Filters[K])=>setDraft(prev=>{
    const next={...prev,[key]:value}
    if(key==='companyGroup'){next.developer='all';next.project='all';next.object='all'}
    if(key==='developer'){next.project='all';next.object='all'}
    if(key==='project')next.object='all'
    return next
  })
  const apply=()=>{setApplied({...draft});setAppliedPulse(true);window.setTimeout(()=>setAppliedPulse(false),1000)}
  const reset=()=>{setDraft(initialFilters);setApplied(initialFilters);setTableSearch('')}
  const quickApply=<K extends keyof Filters>(key:K,value:Filters[K])=>{
    setDraftValue(key,value)
    setApplied(prev=>({
      ...prev,
      [key]:value,
      ...(key==='companyGroup'?{developer:'all',project:'all',object:'all'}:{}),
      ...(key==='developer'?{project:'all',object:'all'}:{}),
      ...(key==='project'?{object:'all'}:{}),
    }))
  }

  return <div className="analytics-screen">
    <aside className="filter-panel">
      <div className="filter-title"><h2>Фильтры</h2><button type="button" onClick={reset}>Сбросить</button></div>
      <FilterSelect label="Группа компаний" allLabel="Все группы" value={draft.companyGroup} onChange={v=>setDraftValue('companyGroup',v)} options={COMPANY_GROUP_OPTIONS}/>
      <FilterSelect label="Застройщик" allLabel="Все застройщики" value={draft.developer} onChange={v=>setDraftValue('developer',v)} options={developers.map(x=>[x,x] as [string,string])}/>
      <FilterSelect label="Проект" allLabel="Все проекты" value={draft.project} onChange={v=>setDraftValue('project',v)} options={draftProjects.map(p=>[p.id,p.name] as [string,string])}/>
      <FilterSelect label="Объект / Корпус" allLabel="Все объекты" value={draft.object} onChange={v=>setDraftValue('object',v)} options={draftObjects.map(o=>[o.value,o.label] as [string,string])}/>
      <FilterSelect label="Регион" allLabel="Все регионы" value={draft.region} onChange={v=>setDraftValue('region',v)} options={regions.map(x=>[x,x] as [string,string])}/>
      <FilterSelect label="Статус отклонения" allLabel="Все статусы" value={draft.status} onChange={v=>setDraftValue('status',v)} options={STATUS_OPTIONS}/>
      <label className="field-label">Период</label><div className="period-field"><input type="date" value={draft.from} onChange={e=>setDraftValue('from',e.target.value)}/><b>—</b><input type="date" value={draft.to} onChange={e=>setDraftValue('to',e.target.value)}/><CalendarIcon/></div>
      <label className="toggle-line"><span>Только с отставанием</span><input type="checkbox" checked={draft.onlyDelayed} onChange={e=>setDraftValue('onlyDelayed',e.target.checked)}/><i/></label>
      <div className="filter-show"><b>Показывать</b><label><input type="checkbox" checked={draft.showProjects} onChange={e=>setDraftValue('showProjects',e.target.checked)}/> Проекты</label><label><input type="checkbox" checked={draft.showObjects} onChange={e=>setDraftValue('showObjects',e.target.checked)}/> Объекты</label></div>
      <button className={`apply-filter ${appliedPulse?'done':''}`} type="button" onClick={apply}>{appliedPulse?'Применено ✓':'Применить'}</button>

      <div className="filter-training" data-tour-id="training-home">
        <b>Режим обучения</b>
        <p>Познакомьтесь с PlanSight за 5 минут</p>
        <div className="filter-training-actions">
          <button type="button" className="training-launcher-btn" onClick={startQuickTour} data-tour-id="training-start">
            Начать
          </button>
          <button type="button" className="training-launcher-btn" onClick={()=>setScenarioPickerOpen(true)} data-tour-id="training-pick-scenario">
            Выбрать сценарий
          </button>
        </div>
      </div>
      {scenarioPickerOpen&&(
        <TrainingLauncher projectId={trainingProjectId} onClose={()=>setScenarioPickerOpen(false)}/>
      )}
    </aside>

    <div className="analytics-main">
      <div className="analytics-heading">
        <h1>Аналитика по всем проектам</h1>
        <p>Общая картина по портфелю объектов: отклонения сроков, риски и ключевые показатели.</p>
        {q.isError&&<p className="analytics-live-note is-error">Нет связи с API — показаны последние загруженные данные. Нажмите «Обновить».</p>}
        {!q.isError&&!projects.length&&q.isFetched&&!q.isFetching&&<p className="analytics-live-note is-error">Портфель пуст или ещё не загружен.</p>}
      </div>
      <div className="kpi-row five">
        <Kpi icon="building" tone="green" label="Всего проектов" value={rows.length} note={hasFilter?'В фильтрации':'По портфелю API'}/>
        <Kpi icon="list" tone="blue" label="Всего работ" value={totalWorks.toLocaleString('ru-RU')} note={hasFilter?'По выбранным проектам':'Сумма по проектам'}/>
        <Kpi icon="alert" tone="red" label="Работ с отклонением" value={problemWorks} note={`${totalWorks?Math.round(problemWorks/totalWorks*100):0}% от всех работ`}/>
        <Kpi icon="warning" tone="orange" label="Проектов с отставанием" value={delayed} note={`${rows.length?Math.round(delayed/rows.length*100):0}% от всех проектов`}/>
        <Kpi icon="calendar" tone="violet" label="Макс. отклонение" value={max?`+${max.maxDeviation} ${dayWord(max.maxDeviation)}`:'—'} note={max?`по проекту ${max.name}`:'Нет данных'}/>
      </div>

      <div className="analytics-widgets">
        <section className={`dash-card deviation-card${q.isError?' is-stale':''}`}>
          <div className="dash-card-head"><div><h2>Отклонения по проектам</h2><span>Количество работ с отставанием</span></div><button type="button" onClick={()=>void q.refetch()}>Обновить</button></div>
          <div className="deviation-chart"><ResponsiveContainer width="100%" height="100%"><BarChart layout="vertical" data={barData} margin={{top:4,right:18,bottom:2,left:4}} barCategoryGap={9}><CartesianGrid stroke="#e9eff5" horizontal={false}/><XAxis type="number" tick={{fontSize:9,fill:'#7b8ca0'}} axisLine={false} tickLine={false}/><YAxis type="category" dataKey="name" width={112} tick={{fontSize:9,fill:'#40556e'}} axisLine={false} tickLine={false}/><Tooltip contentStyle={{fontSize:10,border:'1px solid #dce6ef',borderRadius:6}}/><Bar dataKey="critical" name="Критические" stackId="a" fill="#ff3348" radius={[3,0,0,3]}/><Bar dataKey="high" name="Значительные" stackId="a" fill="#ff8a27"/><Bar dataKey="medium" name="Незначительные" stackId="a" fill="#ffc51f"/><Bar dataKey="normal" name="Без отклонений" stackId="a" fill="#24b985" radius={[0,3,3,0]}/></BarChart></ResponsiveContainer></div>
          <div className="legend"><span><i className="critical"/>&gt; 10 дней</span><span><i className="high"/>5–10 дней</span><span><i className="medium"/>1–5 дней</span><span><i className="normal"/>Без отклонений</span></div>
        </section>

        <section className={`dash-card severity-card${q.isError?' is-stale':''}`}><div className="dash-card-head"><div><h2>Распределение отклонений</h2><span>По степени критичности</span></div></div><div className="severity-wrap"><div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart margin={{top:4,right:4,bottom:4,left:4}}><Pie data={severity} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius="58%" outerRadius="88%" stroke="none" paddingAngle={1}>{severity.map(s=><Cell key={s.name} fill={s.color}/>)}</Pie><Tooltip contentStyle={{fontSize:10,border:'1px solid #dce6ef',borderRadius:6}}/></PieChart></ResponsiveContainer><div className="donut-center"><b>{problemWorks}</b><span>работ</span></div></div><div className="severity-list">{severity.map(s=><div key={s.name}><i style={{background:s.color}}/><span>{s.name}<small>{s.value} ({s.pct}%)</small></span></div>)}</div></div></section>

        <section className="dash-card map-card"><div className="dash-card-head"><div><h2>Отклонения по локации</h2></div></div><ProjectMap points={mapPoints} onOpenProject={id=>navigate(`/projects/${id}/schedule`)}/><div className="map-legend"><span><i className="critical"/>Критический</span><span><i className="high"/>Высокий</span><span><i className="normal"/>В норме</span><span><i className="map-object-dot"/>Объект</span></div></section>
      </div>

      <section className="dash-card portfolio-table-card">
        <div className="table-toolbar"><h2>Проекты</h2><div className="table-search"><SearchIcon/><input value={tableSearch} onChange={e=>setTableSearch(e.target.value)} placeholder="Поиск по проекту, застройщику..."/></div><MiniSelect value={applied.developer} onChange={v=>quickApply('developer',v)} label="Застройщик" options={developers.map(x=>[x,x] as [string,string])}/><MiniSelect value={applied.region} onChange={v=>quickApply('region',v)} label="Регион" options={regions.map(x=>[x,x] as [string,string])}/><MiniSelect value={applied.status} onChange={v=>quickApply('status',v)} label="Статус" options={STATUS_OPTIONS}/><button type="button" className="period-mini">Период <ChevronDown size={14} strokeWidth={1.8} className="ui-chevron" aria-hidden/></button></div>
        <div className="portfolio-table-wrap"><table className="portfolio-table"><thead><tr><th>Проект / Объект</th><th>Застройщик</th><th>Регион</th><th>Всего работ</th><th>С отклонением</th><th>Макс. отклонение</th><th>Статус</th><th>Последний анализ</th><th/></tr></thead><tbody>{visibleRows.map((p,i)=><tr key={p.id} onClick={()=>navigate(`/projects/${p.id}/schedule`)}><td><div className="project-cell"><ProjectThumb index={i}/><span><b>{p.name}</b><small>{p.objects.slice(0,2).map(o=>o.name).join(' · ')}</small></span></div></td><td>{p.developer}</td><td>{p.region}</td><td>{p.totalWorks}</td><td><b className="red-number">{p.problemWorks}</b></td><td><b className={p.maxDeviation>10?'red-number':''}>{p.maxDeviation?`+${p.maxDeviation} ${dayWord(p.maxDeviation)}`:'—'}</b></td><td><span className={`project-status ${p.status.toLowerCase()}`}><i/>{projectStatusRu(p.status)}</span></td><td>{p.lastAnalysis}</td><td className="arrow-cell">→</td></tr>)}</tbody></table>{!visibleRows.length&&<div className="table-empty">Нет проектов по выбранным условиям</div>}</div>
      </section>
    </div>
  </div>
}

function dayWord(n:number){const m=n%100;if(m>=11&&m<=14)return'дней';const d=n%10;return d===1?'день':d>=2&&d<=4?'дня':'дней'}
function Kpi({icon,tone,label,value,note}:{icon:IconName;tone:string;label:string;value:string|number;note:string}){return <div className="kpi-card"><span className={`kpi-icon ${tone}`}><UiIcon name={icon}/></span><div><span className="kpi-label">{label}</span><strong>{value}</strong><small className={note.startsWith('↑')?'positive-note':''}>{note}</small></div></div>}
function FilterSelect({label,allLabel,value,onChange,options}:{label:string;allLabel:string;value:string;onChange:(v:string)=>void;options:[string,string][]}){
  return <label className="filter-field">
    <span className="filter-field-label">{label}</span>
    <span className="filter-field-control">
      <select value={value} onChange={e=>onChange(e.target.value)}>
        <option value="all">{allLabel}</option>
        {options.map(o=><option key={o[0]} value={o[0]}>{o[1]}</option>)}
      </select>
      <SearchIcon/>
    </span>
  </label>
}
function MiniSelect({value,onChange,label,options}:{value:string;onChange:(v:string)=>void;label:string;options:[string,string][]}){return <select className="mini-select" value={value} onChange={e=>onChange(e.target.value)}><option value="all">{label}</option>{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select>}
function ProjectThumb({index}:{index:number}){return <span className={`project-thumb thumb-${index%4}`}><svg viewBox="0 0 28 28" aria-hidden="true"><path d="M5 23V10l8-5 10 4v14H5Z" fill="currentColor" opacity=".25"/><path d="M8 21v-9h4v9M15 21V9h5v12M9 14h2m5-2h3m-3 3h3m-3 3h3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round"/></svg></span>}
function SearchIcon(){return <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4.5" stroke="currentColor"/><path d="m10.5 10.5 3 3" stroke="currentColor" strokeLinecap="round"/></svg>}
function CalendarIcon(){return <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><rect x="2.5" y="3.5" width="11" height="10" rx="1.5" stroke="currentColor"/><path d="M5 2v3M11 2v3M3 7h10" stroke="currentColor" strokeLinecap="round"/></svg>}
type IconName='building'|'list'|'alert'|'warning'|'calendar'
function UiIcon({name}:{name:IconName}){const common={width:18,height:18,viewBox:'0 0 20 20',fill:'none'};if(name==='building')return <svg {...common}><path d="M4 17V4.5L10 2v15M10 6h6v11M2 17h16M6.5 6h1M6.5 9h1M6.5 12h1M12.5 9h1M12.5 12h1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>;if(name==='list')return <svg {...common}><path d="M7 5h10M7 10h10M7 15h10M3 5h.01M3 10h.01M3 15h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>;if(name==='alert')return <svg {...common}><path d="M10 2.5a6 6 0 0 0-3.8 10.64L5.5 17l3.48-1.37A6 6 0 1 0 10 2.5Z" stroke="currentColor" strokeWidth="1.5"/><path d="M10 6v4M10 13h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>;if(name==='warning')return <svg {...common}><path d="M10 2.8 18 17H2L10 2.8Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/><path d="M10 7v4M10 14h.01" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></svg>;return <svg {...common}><rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" strokeWidth="1.6"/><path d="M6 2v4M14 2v4M3 8h14M7 11h2v2H7z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>}
