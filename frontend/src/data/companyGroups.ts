/** Справочник групп компаний: стабильный group_id + отображаемое имя */
export const COMPANY_GROUPS = [
  {id:'3s-group',name:'3S Group'},
  {id:'afi-development',name:'AFI Development'},
  {id:'alvek',name:'ALVEK'},
  {id:'baza-development',name:'BAZA Development'},
  {id:'capital-group',name:'Capital Group'},
  {id:'dars-development',name:'DARS Development'},
  {id:'dominanta',name:'Dominanta'},
  {id:'element',name:'ELEMENT'},
  {id:'forma',name:'Forma'},
  {id:'kr-properties',name:'KR Properties'},
  {id:'legenda',name:'LEGENDA Intelligent Development'},
  {id:'level-group',name:'Level Group'},
  {id:'mos-city-group',name:'MOS CITY GROUP'},
  {id:'mr-group',name:'MR Group'},
  {id:'seven-suns',name:'Seven Suns Development'},
  {id:'sezar-group',name:'Sezar Group'},
  {id:'sminex',name:'Sminex'},
  {id:'stone',name:'STONE'},
  {id:'touch',name:'TOUCH'},
  {id:'uniq-development',name:'UNIQ Development'},
  {id:'upside',name:'UPSIDE ДЕВЕЛОПМЕНТ'},
  {id:'vesper',name:'Vesper'},
  {id:'voshod',name:"VOS'HOD"},
  {id:'ziggurat',name:'Ziggurat'},
  {id:'a101',name:'А101'},
  {id:'absolut',name:'АБСОЛЮТ'},
  {id:'aeon',name:'Аеон Девелопмент'},
  {id:'akvilon',name:'Аквилон'},
  {id:'apsis-glob',name:'Апсис Глоб'},
  {id:'atlant',name:'Атлант'},
  {id:'afinastroy',name:'АфинаСтрой'},
  {id:'brusnika',name:'Брусника'},
  {id:'vektor',name:'Вектор'},
  {id:'gals-development',name:'Галс-Девелопмент'},
  {id:'glavstroy',name:'Главстрой'},
  {id:'grad-development',name:'Град Девелопмент'},
  {id:'granel',name:'Гранель'},
  {id:'forsayt',name:'Группа компаний «Форсайт Девелопмент»'},
  {id:'sever',name:'Девелоперская компания "Север"'},
  {id:'donstroy',name:'ДОНСТРОЙ'},
  {id:'idil',name:'ИДИЛЬ ДЕВЕЛОПМЕНТ'},
  {id:'ingeocenter',name:'ИнгеоЦентр'},
  {id:'koldi',name:'КОЛДИ'},
  {id:'krost',name:'Концерн КРОСТ'},
  {id:'kortros',name:'КОРТРОС'},
  {id:'lsr',name:'ЛСР'},
  {id:'mangazeya',name:'Мангазея'},
  {id:'om-development',name:'ОМ Девелопмент'},
  {id:'osnova',name:'ОСНОВА'},
  {id:'otrada',name:'Отрада'},
  {id:'pik',name:'ПИК'},
  {id:'pioner',name:'Пионер'},
  {id:'plus-development',name:'ПЛЮС Девелопмент'},
  {id:'razvitie',name:'Развитие'},
  {id:'rg-development',name:'РГ-Девелопмент'},
  {id:'rks-development',name:'РКС Девелопмент'},
  {id:'rodina',name:'Родина'},
  {id:'samolet',name:'Самолет'},
  {id:'ssk',name:'ССК'},
  {id:'strana-development',name:'Страна Девелопмент'},
  {id:'stroykom',name:'Стройком'},
  {id:'stroytex',name:'Стройтэкс'},
  {id:'talan',name:'Талан'},
  {id:'tashir',name:'Ташир'},
  {id:'tekta',name:'ТЕКТА ГРУПП'},
  {id:'tochno',name:'ТОЧНО'},
  {id:'tpu-rasskazovka',name:'ТПУ РАССКАЗОВКА'},
  {id:'uez',name:'УЭЗ'},
  {id:'fsk',name:'ФСК'},
  {id:'tsentstroy',name:'Центрстрой'},
  {id:'elit-eko',name:'Элит Эко'},
  {id:'etalon',name:'Эталон'},
  {id:'unikey',name:'Юникей'},
] as const

export type CompanyGroupId = (typeof COMPANY_GROUPS)[number]['id']
export type CompanyGroupName = (typeof COMPANY_GROUPS)[number]['name']

const BY_ID = Object.fromEntries(COMPANY_GROUPS.map(g=>[g.id,g])) as Record<CompanyGroupId,{id:CompanyGroupId;name:CompanyGroupName}>

export function companyGroupById(groupId: string | null | undefined) {
  if (!groupId) return null
  return BY_ID[groupId as CompanyGroupId] ?? null
}

export function companyGroupName(groupId: string | null | undefined): string | null {
  return companyGroupById(groupId)?.name ?? null
}

/** Опции для FilterSelect: [group_id, label] */
export const COMPANY_GROUP_OPTIONS: [string, string][] = COMPANY_GROUPS.map(g=>[g.id,g.name])
