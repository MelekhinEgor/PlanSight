import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

export type ProjectMapPoint={
  id:string
  projectId:string
  name:string
  subtitle:string
  kind:'project'|'object'
  lat:number
  lng:number
  status:string
  problemWorks:number
  maxDeviation:number
}

type XY={x:number;y:number}
const TILE=256
const clamp=(v:number,min:number,max:number)=>Math.max(min,Math.min(max,v))
const project=(lat:number,lng:number,zoom:number):XY=>{
  const size=TILE*Math.pow(2,zoom)
  const sin=Math.sin(lat*Math.PI/180)
  return {x:(lng+180)/360*size,y:(.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*size}
}
const unproject=(x:number,y:number,zoom:number)=>{
  const size=TILE*Math.pow(2,zoom)
  const lng=x/size*360-180
  const n=Math.PI-2*Math.PI*y/size
  const lat=180/Math.PI*Math.atan(.5*(Math.exp(n)-Math.exp(-n)))
  return {lat,lng}
}
const markerClass=(status:string)=>status==='DELAYED'?'critical':status==='AT_RISK'?'high':status==='ON_TRACK'||status==='COMPLETED'?'normal':'muted'

export function ProjectMap({points,onOpenProject}:{points:ProjectMapPoint[];onOpenProject:(projectId:string)=>void}){
  const ref=useRef<HTMLDivElement|null>(null)
  const [size,setSize]=useState({w:420,h:220})
  const [center,setCenter]=useState({lat:58.9,lng:33.5})
  const [zoom,setZoom]=useState(5)
  const [selected,setSelected]=useState<string|null>(null)
  const drag=useRef<{x:number;y:number;cx:number;cy:number}|null>(null)

  useEffect(()=>{
    if(!ref.current)return
    const ro=new ResizeObserver(([entry])=>setSize({w:entry.contentRect.width,h:entry.contentRect.height}))
    ro.observe(ref.current);return()=>ro.disconnect()
  },[])

  const signature=points.map(p=>p.id).sort().join('|')
  useEffect(()=>{
    if(!points.length){setSelected(null);return}
    const minLat=Math.min(...points.map(p=>p.lat)),maxLat=Math.max(...points.map(p=>p.lat))
    const minLng=Math.min(...points.map(p=>p.lng)),maxLng=Math.max(...points.map(p=>p.lng))
    const lat=(minLat+maxLat)/2,lng=(minLng+maxLng)/2
    const span=Math.max(maxLat-minLat,(maxLng-minLng)*.65)
    const z=span>8?4:span>3?5:span>1?6:span>.35?8:span>.08?10:12
    setCenter({lat,lng});setZoom(z);setSelected(null)
  // Подгонять карту только при смене отфильтрованного набора точек
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[signature])

  const world=project(center.lat,center.lng,zoom)
  const origin={x:world.x-size.w/2,y:world.y-size.h/2}
  const tiles=useMemo(()=>{
    const n=Math.pow(2,zoom);const out:{x:number;y:number;srcX:number;left:number;top:number;key:string}[]=[]
    const x0=Math.floor(origin.x/TILE),x1=Math.floor((origin.x+size.w)/TILE)
    const y0=Math.max(0,Math.floor(origin.y/TILE)),y1=Math.min(n-1,Math.floor((origin.y+size.h)/TILE))
    for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
      const srcX=((x%n)+n)%n
      out.push({x,y,srcX,left:x*TILE-origin.x,top:y*TILE-origin.y,key:`${zoom}-${x}-${y}`})
    }
    return out
  },[zoom,origin.x,origin.y,size.w,size.h])

  const selectedPoint=points.find(p=>p.id===selected)??null
  const pointerDown=(e:ReactPointerEvent<HTMLDivElement>)=>{
    const p=project(center.lat,center.lng,zoom);drag.current={x:e.clientX,y:e.clientY,cx:p.x,cy:p.y};e.currentTarget.setPointerCapture(e.pointerId)
  }
  const pointerMove=(e:ReactPointerEvent<HTMLDivElement>)=>{
    if(!drag.current)return
    const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y
    setCenter(unproject(drag.current.cx-dx,drag.current.cy-dy,zoom))
  }
  const pointerUp=(e:ReactPointerEvent<HTMLDivElement>)=>{drag.current=null;try{e.currentTarget.releasePointerCapture(e.pointerId)}catch{}}
  const setZoomSafe=(next:number)=>setZoom(clamp(next,3,16))

  useEffect(()=>{
    const el=ref.current
    if(!el)return
    const onWheel=(e:WheelEvent)=>{
      e.preventDefault()
      e.stopPropagation()
      const delta=e.deltaY
      if(delta===0)return
      setZoom(z=>{
        const next=clamp(z+(delta>0?-1:1),3,16)
        if(next===z)return z
        const rect=el.getBoundingClientRect()
        const mx=e.clientX-rect.left,my=e.clientY-rect.top
        setCenter(c=>{
          const before=project(c.lat,c.lng,z)
          const worldX=before.x-size.w/2+mx
          const worldY=before.y-size.h/2+my
          const anchor=unproject(worldX,worldY,z)
          const after=project(anchor.lat,anchor.lng,next)
          return unproject(after.x-mx+size.w/2,after.y-my+size.h/2,next)
        })
        return next
      })
    }
    el.addEventListener('wheel',onWheel,{passive:false})
    return()=>el.removeEventListener('wheel',onWheel)
  },[size.w,size.h])

  return <div className="project-map" ref={ref} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
    <div className="osm-tiles" aria-hidden="true">{tiles.map(t=><img key={t.key} draggable={false} alt="" src={`https://tile.openstreetmap.org/${zoom}/${t.srcX}/${t.y}.png`} style={{left:t.left,top:t.top}}/>)}</div>
    <div className="map-shade" aria-hidden="true"/>
    {points.map(p=>{const xy=project(p.lat,p.lng,zoom);const left=xy.x-origin.x,top=xy.y-origin.y;const active=selected===p.id;return <button key={p.id} type="button" className={`geo-marker ${p.kind} ${markerClass(p.status)} ${active?'selected':''}`} style={{left,top}} title={p.name} onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();setSelected(p.id)}}><span>{p.kind==='project'?(p.problemWorks||1):''}</span></button>})}
    {selectedPoint&&<div className="map-popup" onPointerDown={e=>e.stopPropagation()}>
      <button className="map-popup-close" type="button" onClick={()=>setSelected(null)}>×</button>
      <small>{selectedPoint.kind==='project'?'Проект':'Объект'}</small><b>{selectedPoint.name}</b><span>{selectedPoint.subtitle}</span>
      <div className="map-popup-metrics"><span>Проблемных работ <b>{selectedPoint.problemWorks}</b></span><span>Макс. отклонение <b>+{selectedPoint.maxDeviation} дн.</b></span></div>
      <button type="button" className="map-open" onClick={()=>onOpenProject(selectedPoint.projectId)}>Открыть график →</button>
    </div>}
    {!points.length&&<div className="map-empty">Нет объектов для выбранных фильтров</div>}
    <div className="map-controls" onPointerDown={e=>e.stopPropagation()}><button type="button" onClick={()=>setZoomSafe(zoom+1)}>+</button><button type="button" onClick={()=>setZoomSafe(zoom-1)}>−</button></div>
    <div className="map-attribution">© OpenStreetMap</div>
  </div>
}
