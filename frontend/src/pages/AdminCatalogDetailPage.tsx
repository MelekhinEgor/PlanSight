import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { Download, FileUp, Plus, Save, Search, X } from 'lucide-react'
import { api } from '../api/client'
import {
  getCatalogMeta,
  getCatalogRecords,
  isCatalogVisible,
  type CatalogKey,
  type CatalogRecord,
} from '../admin/catalogs'
import {
  EQUIPMENT_CATEGORY_LABEL,
  equipmentByCategory,
  getEquipmentById,
  getEquipmentCatalog,
  subscribeEquipment,
  syncEquipmentFromRecords,
  type EquipmentCategory,
} from '../admin/equipmentCatalog'
import {
  ROLE_LABEL,
  cloneProfile,
  compactTechniqueNames,
  profileStatus,
  statusLabel,
  suggestProfile,
  type EquipmentRole,
  type WorkEquipmentLink,
  type WorkProfile,
} from '../admin/workProfiles'

const ROLES:EquipmentRole[]=['required','expected','optional']

export function AdminCatalogDetailPage(){
  const {catalogKey=''}=useParams()
  const valid=isCatalogVisible(catalogKey)
  const key=(valid?catalogKey:'') as CatalogKey|''
  const meta=key?getCatalogMeta(key):null
  const isWorkTypes=key==='work-types'
  const liveEquipment=useSyncExternalStore(subscribeEquipment,getEquipmentCatalog,getEquipmentCatalog)

  const [rows,setRows]=useState<CatalogRecord[]>([])
  const [profiles,setProfiles]=useState<Record<string,WorkProfile>>({})
  const [baseline,setBaseline]=useState('')
  const [search,setSearch]=useState('')
  const [groupFilter,setGroupFilter]=useState('all')
  const [selected,setSelected]=useState<Set<string>>(new Set())
  const [drawerId,setDrawerId]=useState<string|null>(null)
  const [adding,setAdding]=useState(false)
  const [eqSearch,setEqSearch]=useState('')
  const [pickIds,setPickIds]=useState<Set<string>>(new Set())
  const [massOpen,setMassOpen]=useState(false)
  const [massRole,setMassRole]=useState<EquipmentRole>('required')
  const [massQty,setMassQty]=useState(1)
  const [toast,setToast]=useState('')
  const [saving,setSaving]=useState(false)
  const fileRef=useRef<HTMLInputElement>(null)

  useEffect(()=>{
    if(!key)return
    let cancelled=false
    ;(async()=>{
      try{
        const server=await api.getCatalog(key==='work-types'?'work_types':key) as {
          items?:{id?:string;external_id?:string;name?:string;group?:string;group_name?:string;payload?:Record<string,unknown>;code?:string;unit?:string;status?:string;updatedAt?:string}[]
        }
        const mapped:CatalogRecord[]=(server.items||[]).map((it,i)=>{
          const payload=it.payload||{}
          return{
            id:String(it.id||it.external_id||`row-${i}`),
            code:String(it.code||payload.code||it.external_id||''),
            name:String(it.name||'—'),
            unit:String(it.unit||payload.unit||'компл.'),
            status:(it.status as CatalogRecord['status'])||'active',
            updatedAt:String(it.updatedAt||new Date().toISOString().slice(0,10)),
            group:String(it.group||it.group_name||payload.group||'Прочая'),
            cvCode:typeof payload.cv_code==='string'?payload.cv_code:typeof payload.kb_code==='string'?payload.kb_code:undefined,
            kbCode:typeof payload.kb_code==='string'?payload.kb_code:typeof payload.kb_work_code==='string'?payload.kb_work_code:undefined,
          } as CatalogRecord
        })
        const list=mapped.length?mapped:getCatalogRecords(key)
        if(cancelled)return
        setRows(list)
        if(key==='equipment'){
          syncEquipmentFromRecords(list.map(r=>({
            id:r.id,code:r.code,name:r.name,unit:r.unit,group:r.group,
            cvCode:(r as CatalogRecord&{cvCode?:string}).cvCode,
          })))
        }
        if(key==='work-types'){
          let next:Record<string,WorkProfile>={}
          try{
            const wp=await api.getWorkProfiles() as {items?:Array<WorkProfile&{
              work_type_key?:string;equipment_key?:string;equipmentId?:string;role?:string
              min_qty?:number;minQty?:number;confirmed?:boolean;payload?:{source?:string}
              items?:WorkProfile['items']
            }>}
            if(wp.items?.length){
              for(const row of wp.items){
                // Вложенный WorkProfile с предыдущего сохранения
                if(Array.isArray(row.items)&&row.workTypeId){
                  next[row.workTypeId]=row
                  continue
                }
                const wt=String(row.workTypeId||row.work_type_key||'')
                const eq=String(row.equipmentId||row.equipment_key||'')
                if(!wt||!eq)continue
                const cur=next[wt]??{workTypeId:wt,items:[],confirmed:!!row.confirmed,source:(row.payload?.source==='auto'?'auto':'manual') as WorkProfile['source']}
                if(!cur.items.some(i=>i.equipmentId===eq)){
                  cur.items.push({
                    equipmentId:eq,
                    role:(row.role as WorkProfile['items'][0]['role'])||'expected',
                    minQty:Number(row.minQty??row.min_qty??1)||1,
                  })
                }
                cur.confirmed=cur.confirmed||!!row.confirmed
                next[wt]=cur
              }
            }
          }catch{/* оставляем suggested */}
          if(!Object.keys(next).length){
            for(const r of list){
              const suggested=suggestProfile(r.id,r.name)
              if(suggested)next[r.id]=suggested
            }
          }
          if(cancelled)return
          setProfiles(next)
          setBaseline(JSON.stringify({rows:list,profiles:next}))
        }else{
          setProfiles({})
          setBaseline(JSON.stringify({rows:list,profiles:{}}))
        }
      }catch{
        if(cancelled)return
        const list=getCatalogRecords(key)
        setRows(list)
        if(key==='work-types'){
          const next:Record<string,WorkProfile>={}
          for(const r of list){
            const suggested=suggestProfile(r.id,r.name)
            if(suggested)next[r.id]=suggested
          }
          setProfiles(next)
          setBaseline(JSON.stringify({rows:list,profiles:next}))
        }else{
          setProfiles({})
          setBaseline(JSON.stringify({rows:list,profiles:{}}))
        }
      }
      setSearch('')
      setGroupFilter('all')
      setSelected(new Set())
      setDrawerId(null)
      setAdding(false)
    })()
    return()=>{cancelled=true}
  },[key])

  // Справочник «Техника» сразу попадает в пикер назначения на виды работ
  useEffect(()=>{
    if(key!=='equipment')return
    syncEquipmentFromRecords(rows)
  },[key,rows])

  const groups=useMemo(()=>[...new Set(rows.map(r=>r.group).filter(Boolean) as string[])],[rows])
  const dirty=JSON.stringify({rows,profiles})!==baseline
  const drawerRow=drawerId?rows.find(r=>r.id===drawerId)??null:null
  const drawerProfile=drawerId?profiles[drawerId]:undefined

  const visible=useMemo(()=>{
    const q=search.trim().toLowerCase()
    return rows.filter(r=>{
      if(groupFilter!=='all'&&r.group!==groupFilter)return false
      if(!q)return true
      return `${r.code} ${r.name} ${r.group??''}`.toLowerCase().includes(q)
    })
  },[rows,search,groupFilter])

  const catMap=useMemo(()=>equipmentByCategory(liveEquipment),[liveEquipment])
  const filteredEq=useMemo(()=>{
    const q=eqSearch.trim().toLowerCase()
    if(!q)return liveEquipment
    return liveEquipment.filter(e=>e.name.toLowerCase().includes(q)||EQUIPMENT_CATEGORY_LABEL[e.category].toLowerCase().includes(q))
  },[eqSearch,liveEquipment])

  if(!key||!meta)return <Navigate to="/admin/catalogs" replace/>

  const notify=(text:string)=>{setToast(text);window.setTimeout(()=>setToast(''),2800)}

  const setProfile=(workTypeId:string,profile:WorkProfile|null)=>{
    setProfiles(prev=>{
      const next={...prev}
      if(!profile||!profile.items.length)delete next[workTypeId]
      else next[workTypeId]=profile
      return next
    })
  }

  const openDrawer=(id:string)=>{
    setDrawerId(id)
    setAdding(false)
    setEqSearch('')
    setPickIds(new Set())
    setMassOpen(false)
  }

  const updateLink=(workTypeId:string,equipmentId:string,patch:Partial<WorkEquipmentLink>)=>{
    const cur=profiles[workTypeId]??{workTypeId,items:[],confirmed:true,source:'manual' as const}
    const items=cur.items.map(i=>i.equipmentId===equipmentId?{...i,...patch}:i)
    setProfile(workTypeId,{...cur,items,source:cur.confirmed?'manual':cur.source})
  }

  const removeLink=(workTypeId:string,equipmentId:string)=>{
    const cur=profiles[workTypeId]
    if(!cur)return
    const items=cur.items.filter(i=>i.equipmentId!==equipmentId)
    setProfile(workTypeId,items.length?{...cur,items}:null)
  }

  const confirmProfile=(workTypeId:string)=>{
    const cur=profiles[workTypeId]
    if(!cur?.items.length)return
    setProfile(workTypeId,{...cur,confirmed:true,source:'manual'})
    notify('Профиль техники подтверждён')
  }

  const addPickedToWork=(workTypeId:string,ids:string[],role:EquipmentRole,minQty:number,confirm=true)=>{
    const cur=profiles[workTypeId]?cloneProfile(profiles[workTypeId]):{workTypeId,items:[],confirmed:confirm,source:'manual' as const}
    for(const equipmentId of ids){
      if(cur.items.some(i=>i.equipmentId===equipmentId))continue
      cur.items.push({equipmentId,role,minQty:Math.max(1,minQty)})
    }
    cur.confirmed=confirm
    cur.source='manual'
    setProfile(workTypeId,cur)
  }

  const applyPicksToDrawer=()=>{
    if(!drawerId||!pickIds.size)return
    addPickedToWork(drawerId,[...pickIds],'required',1,true)
    setPickIds(new Set())
    setAdding(false)
    setEqSearch('')
    notify('Техника добавлена')
  }

  const applyMass=()=>{
    if(!pickIds.size||!selected.size)return
    for(const workTypeId of selected){
      addPickedToWork(workTypeId,[...pickIds],massRole,massQty,true)
    }
    setPickIds(new Set())
    setMassOpen(false)
    setEqSearch('')
    notify(`Техника назначена для ${selected.size} работ`)
  }

  const toggleSelect=(id:string)=>{
    setSelected(prev=>{
      const n=new Set(prev)
      n.has(id)?n.delete(id):n.add(id)
      return n
    })
  }
  const toggleAllVisible=(on:boolean)=>{
    if(!on){setSelected(new Set());return}
    setSelected(new Set(visible.map(r=>r.id)))
  }

  const addRecord=()=>{
    const id=`new-${Date.now()}`
    const row:CatalogRecord=isWorkTypes?{
      id,
      code:`12.99.${rows.length+1}.`,
      name:'Новый вид работ',
      unit:'—',
      status:'active',
      updatedAt:new Date().toISOString().slice(0,10),
      group:groups[0]??'',
    }:{
      id,
      code:`EQ-${String(rows.length+1).padStart(3,'0')}`,
      name:'Новая единица техники',
      unit:'маш.-ч',
      status:'active',
      updatedAt:new Date().toISOString().slice(0,10),
      group:groups[0]??'Прочая',
    }
    setRows(list=>[row,...list])
    notify(isWorkTypes?'Запись добавлена — нажмите «Сохранить»':'Техника добавлена и доступна в назначении на виды работ')
  }

  const saveAll=async()=>{
    setSaving(true)
    try{
      if(key==='equipment')syncEquipmentFromRecords(rows.map(r=>({
        id:r.id,code:r.code,name:r.name,unit:r.unit,group:r.group,
        cvCode:(r as CatalogRecord&{cvCode?:string}).cvCode,
      })))
      const catalogPayload={
        items:rows.map(r=>{
          const extra=r as CatalogRecord&{cvCode?:string;kbCode?:string}
          return{
            id:r.id,
            external_id:r.id,
            name:r.name,
            group:r.group,
            group_name:r.group,
            code:r.code,
            unit:r.unit,
            status:r.status,
            payload:{
              code:r.code,
              unit:r.unit,
              cv_code:extra.cvCode,
              kb_code:extra.kbCode||(isWorkTypes&&!String(r.id).startsWith('wt-')&&!String(r.id).startsWith('new-')?r.id:undefined),
              kb_work_code:extra.kbCode,
            },
          }
        }),
      }
      await api.putCatalog(key==='work-types'?'work_types':key,catalogPayload)
      if(key==='work-types'||profiles){
        const profileItems=Object.values(profiles||{}).map(p=>{
          const row=rows.find(r=>r.id===p.workTypeId) as (CatalogRecord&{kbCode?:string})|undefined
          const kbCode=row?.kbCode||(!String(p.workTypeId).startsWith('wt-')&&!String(p.workTypeId).startsWith('new-')?p.workTypeId:undefined)
          return{
            ...p,
            workTypeId:p.workTypeId,
            work_type_key:p.workTypeId,
            payload:{kb_work_code:kbCode,kb_code:kbCode,source:p.source==='auto'?'auto':'admin'},
            items:p.items.map(link=>{
              const eq=getEquipmentById(link.equipmentId)
              return{
                ...link,
                equipmentId:link.equipmentId,
                equipment_key:link.equipmentId,
                cv_code:eq?.cvCode,
                role:link.role,
                minQty:link.minQty,
              }
            }),
          }
        })
        try{await api.putWorkProfiles({items:profileItems})}catch{/* опционально */}
      }
      setBaseline(JSON.stringify({rows,profiles}))
      notify('Изменения сохранены — профили связаны с детекцией техники')
    }catch(e){
      notify((e as Error).message||'Ошибка сохранения')
    }finally{setSaving(false)}
  }

  const itemsByRole=(profile?:WorkProfile)=>{
    const map:Record<EquipmentRole,WorkEquipmentLink[]>={required:[],expected:[],optional:[]}
    for(const item of profile?.items??[])map[item.role].push(item)
    return map
  }

  const renderEqPicker=(onApply:()=>void,applyLabel:string)=>{
    const grouped=[...catMap.entries()] as [EquipmentCategory,ReturnType<typeof getEquipmentCatalog>][]
    return <div className="wp-picker">
      <label className="admin-search wp-picker-search">
        <Search size={14} strokeWidth={1.8}/>
        <input value={eqSearch} onChange={e=>setEqSearch(e.target.value)} placeholder="Поиск техники…"/>
      </label>
      <div className="wp-picker-list">
        {grouped.map(([cat,items])=>{
          const list=items.filter(e=>filteredEq.some(f=>f.id===e.id))
          if(!list.length)return null
          return <div key={cat} className="wp-picker-group">
            <b>{EQUIPMENT_CATEGORY_LABEL[cat]}</b>
            {list.map(e=>(
              <label key={e.id} className="wp-picker-item">
                <input type="checkbox" checked={pickIds.has(e.id)} onChange={()=>{
                  setPickIds(prev=>{const n=new Set(prev);n.has(e.id)?n.delete(e.id):n.add(e.id);return n})
                }}/>
                <span>{e.name}</span>
              </label>
            ))}
          </div>
        })}
        {!filteredEq.length&&<div className="admin-empty">Ничего не найдено</div>}
      </div>
      <div className="wp-picker-foot">
        <button type="button" className="admin-btn" onClick={()=>{setAdding(false);setMassOpen(false);setPickIds(new Set())}}>Отмена</button>
        <button type="button" className="admin-btn primary" disabled={!pickIds.size} onClick={onApply}>{applyLabel}</button>
      </div>
    </div>
  }

  return <div className={`admin-panel${drawerId||massOpen?' has-drawer':''}`}>
    <div className="admin-detail-head">
      <div>
        <h2>{meta.name}</h2>
        <p>{meta.description}</p>
      </div>
      <div className="admin-detail-actions">
        <button type="button" className="admin-btn" onClick={addRecord}><Plus size={14} strokeWidth={1.8}/>Добавить</button>
        <button type="button" className="admin-btn" onClick={()=>fileRef.current?.click()}><FileUp size={14} strokeWidth={1.8}/>Импорт</button>
        <button type="button" className="admin-btn" onClick={()=>notify(`Экспорт «${meta.name}» — демо`)}><Download size={14} strokeWidth={1.8}/>Экспорт</button>
        <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={e=>{if(e.target.files?.[0])notify(`Файл «${e.target.files[0].name}» принят (демо)`);e.target.value=''}}/>
      </div>
    </div>

    <div className="admin-toolbar">
      <label className="admin-search">
        <Search size={14} strokeWidth={1.8}/>
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Поиск по коду или названию…"/>
      </label>
      {groups.length>1&&<label className="admin-filter">
        <span>Группа</span>
        <select value={groupFilter} onChange={e=>setGroupFilter(e.target.value)}>
          <option value="all">Все</option>
          {groups.map(g=><option key={g} value={g}>{g}</option>)}
        </select>
      </label>}
      <span className="admin-toolbar-meta">{visible.length} из {rows.length}{dirty?' · есть изменения':''}</span>
    </div>

    {isWorkTypes&&selected.size>0&&(
      <div className="admin-bulk-bar">
        <span><b>{selected.size}</b> {selected.size===1?'работа выбрана':selected.size<5?'работы выбрано':'работ выбрано'}</span>
        <button type="button" className="admin-btn primary" onClick={()=>{setMassOpen(true);setAdding(false);setDrawerId(null);setPickIds(new Set());setEqSearch('')}}>
          Назначить технику
        </button>
        <button type="button" className="admin-btn" onClick={()=>setSelected(new Set())}>Сбросить</button>
      </div>
    )}

    <div className="admin-table-wrap">
      <table className="admin-table admin-table-records">
        <thead>
          <tr>
            {isWorkTypes&&<th className="admin-check"><input type="checkbox" checked={!!visible.length&&visible.every(r=>selected.has(r.id))} onChange={e=>toggleAllVisible(e.target.checked)} aria-label="Выбрать все"/></th>}
            <th>Код</th>
            <th>Наименование</th>
            <th>Группа</th>
            {isWorkTypes&&<th className="admin-col-tech">Техника</th>}
          </tr>
        </thead>
        <tbody>
          {visible.map(r=>{
            const profile=profiles[r.id]
            const st=profileStatus(profile)
            const {shown,rest}=compactTechniqueNames(profile,2)
            return <tr key={r.id} className={selected.has(r.id)?'is-selected':''}>
              {isWorkTypes&&<td className="admin-check"><input type="checkbox" checked={selected.has(r.id)} onChange={()=>toggleSelect(r.id)} aria-label={`Выбрать ${r.code}`}/></td>}
              <td><code>{r.code}</code></td>
              <td><b>{r.name}</b></td>
              <td>{r.group||'—'}</td>
              {isWorkTypes&&(
                <td className="admin-col-tech">
                  <button type="button" className="tech-cell" onClick={()=>openDrawer(r.id)}>
                    <span className={`tech-status tech-status-${st}`}>{statusLabel(st,profile?.items.length??0)}</span>
                    {shown.length>0
                      ? <span className="tech-compact">{shown.join(' · ')}{rest>0?` · +${rest}`:''}</span>
                      : <span className="tech-compact is-empty">Настроить…</span>}
                  </button>
                </td>
              )}
            </tr>
          })}
        </tbody>
      </table>
      {!visible.length&&<div className="admin-empty">Нет записей по выбранным условиям</div>}
    </div>

    <div className="admin-panel-foot">
      <span className="admin-foot-hint">{dirty?'Есть несохранённые изменения':'Все изменения сохранены'}</span>
      <button type="button" className="admin-btn primary" disabled={!dirty||saving} onClick={saveAll}>
        <Save size={14} strokeWidth={1.8}/>{saving?'Сохраняю…':'Сохранить'}
      </button>
    </div>

    {drawerRow&&(
      <aside className="wp-drawer" aria-label="Техника для вида работ">
        <div className="wp-drawer-head">
          <div>
            <small>Техника для вида работ</small>
            <h3>{drawerRow.name}</h3>
            <span className="wp-drawer-code">{drawerRow.code}</span>
          </div>
          <button type="button" className="admin-btn icon" onClick={()=>setDrawerId(null)} aria-label="Закрыть"><X size={16}/></button>
        </div>

        <div className="wp-drawer-body">
          {!adding?(
            <>
              {ROLES.map(role=>{
                const list=itemsByRole(drawerProfile)[role]
                return <section key={role} className="wp-role-block">
                  <h4>{ROLE_LABEL[role]}</h4>
                  {list.length?list.map(item=>{
                    const eq=getEquipmentById(item.equipmentId)
                    return <div key={item.equipmentId} className="wp-role-row">
                      <b>{eq?.name??item.equipmentId}</b>
                      <label className="wp-qty">×
                        <input type="number" min={1} value={item.minQty} onChange={e=>updateLink(drawerRow.id,item.equipmentId,{minQty:Math.max(1,Number(e.target.value)||1)})}/>
                      </label>
                      <select value={item.role} onChange={e=>updateLink(drawerRow.id,item.equipmentId,{role:e.target.value as EquipmentRole})}>
                        {ROLES.map(r=><option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                      </select>
                      <button type="button" className="admin-link-btn" onClick={()=>removeLink(drawerRow.id,item.equipmentId)}>Убрать</button>
                    </div>
                  }):<p className="wp-role-empty">Нет позиций</p>}
                </section>
              })}

              {drawerProfile&&!drawerProfile.confirmed&&drawerProfile.items.length>0&&(
                <div className="wp-review-banner">
                  <span>Связи предложены автоматически и требуют проверки</span>
                  <button type="button" className="admin-btn primary" onClick={()=>confirmProfile(drawerRow.id)}>Подтвердить</button>
                </div>
              )}

              <button type="button" className="admin-btn wp-add-btn" onClick={()=>{setAdding(true);setPickIds(new Set());setEqSearch('')}}>
                <Plus size={14} strokeWidth={1.8}/>Добавить технику
              </button>
            </>
          ):renderEqPicker(applyPicksToDrawer,'Добавить выбранные')}
        </div>
      </aside>
    )}

    {massOpen&&(
      <aside className="wp-drawer" aria-label="Массовое назначение техники">
        <div className="wp-drawer-head">
          <div>
            <small>Массовое назначение</small>
            <h3>{selected.size} работ выбрано</h3>
          </div>
          <button type="button" className="admin-btn icon" onClick={()=>setMassOpen(false)} aria-label="Закрыть"><X size={16}/></button>
        </div>
        <div className="wp-drawer-body">
          <div className="wp-mass-params">
            <label>Роль
              <select value={massRole} onChange={e=>setMassRole(e.target.value as EquipmentRole)}>
                {ROLES.map(r=><option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </label>
            <label>Мин. кол-во
              <input type="number" min={1} value={massQty} onChange={e=>setMassQty(Math.max(1,Number(e.target.value)||1))}/>
            </label>
          </div>
          {renderEqPicker(applyMass,'Назначить выбранным')}
        </div>
      </aside>
    )}

    {(drawerId||massOpen)&&<button type="button" className="wp-drawer-backdrop" aria-label="Закрыть" onClick={()=>{setDrawerId(null);setMassOpen(false);setAdding(false)}}/>}

    {toast&&<div className="admin-toast" onClick={()=>setToast('')}>{toast}<span>×</span></div>}
  </div>
}
