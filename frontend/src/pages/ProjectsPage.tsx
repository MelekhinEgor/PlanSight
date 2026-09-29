import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ClipboardList, Download, HelpCircle } from 'lucide-react'
import { api, type PortfolioRow, type Project, type ProjectObject, type ScheduleActivity } from '../api/client'
import { projectStatusRu } from '../labels/ru'
import { useTourOptional } from '../tour/TourProvider'

const toneOf=(status:string)=>status==='DELAYED'?'delayed':status==='AT_RISK'?'risk':status==='ON_TRACK'||status==='COMPLETED'?'ok':'muted'

function dayWord(n:number){
  const m=n%100
  if(m>=11&&m<=14)return'дней'
  const d=n%10
  return d===1?'день':d>=2&&d<=4?'дня':'дней'
}
function fmtDate(iso:string|null|undefined){
  if(!iso)return'—'
  const [y,m,d]=iso.slice(0,10).split('-')
  return `${d}.${m}.${y}`
}
function workWord(n:number){
  const m=n%100
  if(m>=11&&m<=14)return'работ'
  const d=n%10
  return d===1?'работа':d>=2&&d<=4?'работы':'работ'
}

type Report={maxDeviation:number;problemWorks:number;plannedEnd:string|null;forecastEnd:string|null;lastAnalysis:string;status:string}

function buildReport(p:Project,portfolio:PortfolioRow|undefined,acts:ScheduleActivity[]):Report{
  const ends=acts.map(a=>a.planned_end).filter(Boolean) as string[]
  const forecasts=acts.map(a=>a.forecast_end||a.planned_end).filter(Boolean) as string[]
  // Не обнулять серверные KPI по локальным status-лейблам
  return{
    maxDeviation:portfolio?.maxDeviation??0,
    problemWorks:portfolio?.problemWorks??0,
    plannedEnd:ends.sort().at(-1)??null,
    forecastEnd:forecasts.sort().at(-1)??null,
    lastAnalysis:portfolio?.lastAnalysis??'—',
    status:portfolio?.status||p.status,
  }
}

function ProjectCardThumb({index,name,imageUrl}:{index:number;name:string;imageUrl?:string|null}){
  return <div className={`project-card-thumb ${imageUrl?'has-photo':''} thumb-${index%4}`} aria-hidden>
    {imageUrl
      ? <img src={imageUrl} alt="" loading="lazy"/>
      : <>
        <svg viewBox="0 0 160 160" className="project-card-thumb-art">
          <rect x="0" y="0" width="160" height="160" fill="currentColor" opacity=".08"/>
          <path d="M28 128V58l36-22 48 18v74H28Z" fill="currentColor" opacity=".22"/>
          <path d="M42 122V72h22v50M78 122V52h34v70M48 84h10m36-8h20m-20 14h20m-20 14h20" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round"/>
        </svg>
        <span className="project-card-thumb-label">{name.replace(/^ЖК\s*[«"]?/,'').slice(0,1).toUpperCase()}</span>
      </>}
  </div>
}

export function ProjectsPage(){
  const navigate=useNavigate()
  const tour=useTourOptional()
  const projects=useQuery({queryKey:['projects'],queryFn:api.getProjects})
  const portfolio=useQuery({queryKey:['portfolio'],queryFn:api.getPortfolio})
  const objects=useQuery({queryKey:['all-project-objects'],queryFn:async()=>{
    const list=await api.getProjects()
    const entries=await Promise.all(list.map(async p=>[p.id,await api.getProjectObjects(p.id)] as const))
    return Object.fromEntries(entries) as Record<string,ProjectObject[]>
  }})
  const schedules=useQuery({queryKey:['all-schedules-lite'],queryFn:async()=>{
    const list=await api.getProjects()
    const entries=await Promise.all(list.map(async p=>[p.id,(await api.getSchedule(p.id)).activities] as const))
    return Object.fromEntries(entries) as Record<string,ScheduleActivity[]>
  }})
  const [search,setSearch]=useState('')
  const [developer,setDeveloper]=useState('all')
  const [openId,setOpenId]=useState<string|null>(null)

  const portfolioMap=useMemo(()=>{
    const m=new Map<string,PortfolioRow>()
    ;(portfolio.data?.projects??[]).forEach(p=>m.set(p.id,p))
    return m
  },[portfolio.data])

  const developers=useMemo(()=>{
    const names=[...new Set((projects.data??[]).map(p=>p.developer?.name).filter(Boolean) as string[])]
    return names.sort((a,b)=>a.localeCompare(b,'ru'))
  },[projects.data])

  const rows=useMemo(()=>{
    const q=search.trim().toLowerCase()
    let list=projects.data??[]
    if(developer!=='all')list=list.filter(p=>p.developer?.name===developer)
    if(!q)return list
    return list.filter(p=>{
      const objs=objects.data?.[p.id]??[]
      const haystack=[
        p.name,
        p.developer?.name??'',
        p.region??'',
        p.address??'',
        ...objs.map(o=>o.name),
      ].join(' ').toLowerCase()
      return haystack.includes(q)
    })
  },[projects.data,objects.data,search,developer])

  const canReset=developer!=='all'||search.trim()!==''
  const resetFilters=()=>{setDeveloper('all');setSearch('')}

  const downloadReport=(p:Project,report:Report)=>{
    const lines=[
      `Отчёт по проекту: ${p.name}`,
      `Застройщик: ${p.developer?.name??'—'}`,
      `Регион: ${p.region??'—'}`,
      `Статус: ${projectStatusRu(report.status)}`,
      `Макс. отставание: ${report.maxDeviation} ${dayWord(report.maxDeviation)}`,
      `Проблемных работ: ${report.problemWorks}`,
      `Плановое окончание: ${fmtDate(report.plannedEnd)}`,
      `Прогнозное окончание: ${fmtDate(report.forecastEnd)}`,
      `Последний анализ: ${report.lastAnalysis}`,
    ]
    const blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/plain;charset=utf-8'})
    const url=URL.createObjectURL(blob)
    const a=document.createElement('a')
    a.href=url;a.download=`${p.id}_report.txt`;a.click()
    URL.revokeObjectURL(url)
  }

  return <div className="projects-page">
    <div className="projects-head">
      <div>
        <h1>Проекты</h1>
      </div>
      <div className="projects-toolbar">
        <button
          type="button"
          className="admin-btn"
          data-tour-id="portfolio-tour-help"
          title="Как работает PlanSight"
          onClick={()=>{
            const first=projects.data?.[0]?.id || portfolio.data?.projects?.[0]?.id || '0'
            tour?.startScenario('quick', String(first))
          }}
        >
          <HelpCircle size={14}/> Как работает PlanSight
        </button>
        <label className="projects-developer">
          <span>Застройщик</span>
          <select value={developer} onChange={e=>setDeveloper(e.target.value)}>
            <option value="all">Все застройщики</option>
            {developers.map(name=><option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        {canReset&&<button type="button" className="projects-reset" onClick={resetFilters}>Сбросить</button>}
        <label className="projects-search"><span>⌕</span><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Проект, застройщик, регион, этап, объект…"/></label>
      </div>
    </div>
    <div className="projects-grid" data-tour-id="portfolio-list">
      {rows.map((p,index)=>{
        const report=buildReport(p,portfolioMap.get(p.id),schedules.data?.[p.id]??[])
        const tone=toneOf(report.status)
        const open=openId===p.id
        const delayShort=report.maxDeviation>0?`+${report.maxDeviation} ${dayWord(report.maxDeviation)}`:`0 дней`
        const delayLabel=report.maxDeviation>0?`+${report.maxDeviation} ${dayWord(report.maxDeviation)}`:`0 ${dayWord(0)}`
        const badge=projectStatusRu(report.status)
        const sourceLabel=({SCHEDULE:'По графику',OBSERVATION:'По наблюдениям',COMBINED:'Комбинированный анализ',EXPERT:'Подтверждено специалистом'} as Record<string,string>)[(portfolioMap.get(p.id) as {analysis_source?:string}|undefined)?.analysis_source||'']||null
        return <article
          key={p.id}
          className={`project-card ${open?'is-open':''}`}
          role="link"
          tabIndex={0}
          data-tour-id={report.status==='DELAYED'||report.status==='AT_RISK'?'portfolio-attention':'portfolio-card'}
          onClick={()=>navigate(`/projects/${p.id}/schedule`)}
          onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();navigate(`/projects/${p.id}/schedule`)}}}
        >
          <div className="project-card-main">
            <ProjectCardThumb index={index} name={p.name} imageUrl={p.imageUrl}/>
            <div className="project-card-content">
              <div className="project-card-title-row">
                <span className={`project-card-badge status-${report.status.toLowerCase()}`}>{badge}</span>
                {sourceLabel&&<span className="project-card-badge status-no_data" title="Источник статуса">{sourceLabel}</span>}
                <b className="project-card-title" title={p.name}>{p.name}</b>
              </div>              <small className="project-card-location">{[p.region,p.address].filter(Boolean).join(', ')}</small>
              <small className={`project-card-metro${!p.metro?' is-empty':''}`}>{p.metro?<><span>м.</span> {p.metro}</>:<>м.</>}</small>
              <div className="project-meta">
                <div className="project-meta-label">Ввод в эксплуатацию</div>
                <div className="project-meta-label">Застройщик</div>
                <div className="project-meta-value">{p.commissioning??'—'}</div>
                <div className="project-meta-value" title={p.developer?.name??undefined}>{p.developer?.name??'—'}</div>
              </div>
            </div>
          </div>

          <div className={`project-report tone-${tone}`}>
            <button type="button" className="project-report-toggle" onClick={e=>{e.stopPropagation();setOpenId(open?null:p.id)}} aria-expanded={open}>
              <ClipboardList size={15} strokeWidth={1.9} className="report-ico" aria-hidden/>
              {open
                ? <span className="report-toggle-title">Отчёт по проекту</span>
                : <span className="report-toggle-summary">
                    <span className="report-label">Отчёт</span>
                    <span className="report-metrics">
                      <em className="report-metric delay">{delayShort}</em>
                      <span className="report-metric works">{report.problemWorks} {workWord(report.problemWorks)}</span>
                    </span>
                  </span>}
              <ChevronDown size={16} strokeWidth={1.8} className={open?'report-chevron open':'report-chevron'} aria-hidden/>
            </button>

            {open&&<div className="project-report-body">
              <div className="project-report-rows">
                <div><span>Макс. отставание</span><b className="is-delay">{delayLabel}</b></div>
                <div><span>Проблемных работ</span><b>{report.problemWorks}</b></div>
                <div><span>Плановое окончание</span><b>{fmtDate(report.plannedEnd)}</b></div>
                <div><span>Прогнозное окончание</span><b className={report.forecastEnd&&report.plannedEnd&&report.forecastEnd>report.plannedEnd?'is-late':''}>{fmtDate(report.forecastEnd)}</b></div>
              </div>
              <div className="project-report-actions">
                <button type="button" className="report-download" onClick={e=>{e.stopPropagation();downloadReport(p,report)}}>
                  <Download size={14} strokeWidth={1.9} aria-hidden/>
                  Скачать отчёт
                </button>
              </div>
            </div>}
          </div>
        </article>
      })}
      {!rows.length&&<div className="projects-empty">Ничего не найдено</div>}
    </div>
  </div>
}
