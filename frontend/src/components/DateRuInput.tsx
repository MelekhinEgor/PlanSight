import { useEffect, useMemo, useRef, useState } from 'react'
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react'

const MONTHS=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
const WEEK=['пн','вт','ср','чт','пт','сб','вс']

const pad=(n:number)=>String(n).padStart(2,'0')
const fmt=(d:string|null)=>{if(!d)return'';const [y,m,day]=d.slice(0,10).split('-');return `${day}.${m}.${y}`}
const parseRu=(value:string)=>{const m=value.trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);if(!m)return null;const day=Number(m[1]),mon=Number(m[2]),y=Number(m[3]);if(mon<1||mon>12||day<1||day>31)return null;return `${y}-${pad(mon)}-${pad(day)}`}
const isoFromParts=(y:number,m:number,d:number)=>`${y}-${pad(m+1)}-${pad(d)}`

type Props={value:string|null;onCommit:(iso:string|null)=>void;allowEmpty?:boolean}

export function DateRuInput({value,onCommit,allowEmpty=true}:Props){
  const rootRef=useRef<HTMLDivElement>(null)
  const [text,setText]=useState(fmt(value))
  const [open,setOpen]=useState(false)
  const selected=value?new Date(`${value}T00:00:00`):null
  const [viewY,setViewY]=useState(selected?.getFullYear()??new Date().getFullYear())
  const [viewM,setViewM]=useState(selected?.getMonth()??new Date().getMonth())

  useEffect(()=>{setText(fmt(value))},[value])
  useEffect(()=>{if(!open)return;if(selected){setViewY(selected.getFullYear());setViewM(selected.getMonth())}},[open,value])

  useEffect(()=>{
    if(!open)return
    const close=(e:MouseEvent)=>{if(!rootRef.current?.contains(e.target as Node))setOpen(false)}
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')setOpen(false)}
    document.addEventListener('mousedown',close)
    document.addEventListener('keydown',onKey)
    return()=>{document.removeEventListener('mousedown',close);document.removeEventListener('keydown',onKey)}
  },[open])

  const days=useMemo(()=>{
    const first=new Date(viewY,viewM,1)
    const startOffset=(first.getDay()+6)%7
    const count=new Date(viewY,viewM+1,0).getDate()
    const cells:( {key:string;day:number;iso:string;inMonth:boolean}|null)[]=[]
    for(let i=0;i<startOffset;i++)cells.push(null)
    for(let d=1;d<=count;d++)cells.push({key:`${viewY}-${viewM}-${d}`,day:d,iso:isoFromParts(viewY,viewM,d),inMonth:true})
    while(cells.length%7)cells.push(null)
    return cells
  },[viewY,viewM])

  const commitText=()=>{
    const next=text.trim()
    if(!next){if(allowEmpty)onCommit(null);else setText(fmt(value));return}
    const parsed=parseRu(next)
    if(parsed)onCommit(parsed)
    else setText(fmt(value))
  }

  const pick=(iso:string)=>{onCommit(iso);setText(fmt(iso));setOpen(false)}
  const shiftMonth=(delta:number)=>{const d=new Date(viewY,viewM+delta,1);setViewY(d.getFullYear());setViewM(d.getMonth())}
  const todayIso=()=>{const n=new Date();return isoFromParts(n.getFullYear(),n.getMonth(),n.getDate())}

  return <div className={`date-ru-wrap${open?' is-open':''}`} ref={rootRef}>
    <input className="date-ru" value={text} placeholder="ДД.ММ.ГГГГ" onChange={e=>setText(e.target.value)} onBlur={commitText} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}} onFocus={()=>setOpen(false)}/>
    <button type="button" className="date-ru-cal" title="Календарь" aria-label="Открыть календарь" onMouseDown={e=>e.preventDefault()} onClick={()=>setOpen(v=>!v)}>
      <Calendar size={13} strokeWidth={1.8} aria-hidden/>
    </button>
    {open&&<div className="date-picker-pop" role="dialog" aria-label="Выбор даты">
      <div className="date-picker-head">
        <button type="button" onClick={()=>shiftMonth(-1)} aria-label="Предыдущий месяц"><ChevronLeft size={14} strokeWidth={1.8}/></button>
        <b>{MONTHS[viewM]} {viewY}</b>
        <button type="button" onClick={()=>shiftMonth(1)} aria-label="Следующий месяц"><ChevronRight size={14} strokeWidth={1.8}/></button>
      </div>
      <div className="date-picker-weeks">{WEEK.map(w=><span key={w}>{w}</span>)}</div>
      <div className="date-picker-grid">
        {days.map((cell,i)=>cell
          ? <button type="button" key={cell.key} className={`date-picker-day${value===cell.iso?' is-selected':''}${cell.iso===todayIso()?' is-today':''}`} onClick={()=>pick(cell.iso)}>{cell.day}</button>
          : <span key={`e-${i}`} className="date-picker-empty"/>)}
      </div>
      <div className="date-picker-foot">
        <button type="button" onClick={()=>pick(todayIso())}>Сегодня</button>
        {allowEmpty&&<button type="button" onClick={()=>{onCommit(null);setText('');setOpen(false)}}>Очистить</button>}
      </div>
    </div>}
  </div>
}
