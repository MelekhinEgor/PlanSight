/**
 * Минимальный генератор .docx (OOXML + ZIP STORE) без внешних зависимостей.
 * Поддерживает текст, таблицы и вложенные PNG/JPEG.
 */

function crc32(buf: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1
  }
  return (c ^ 0xffffffff) >>> 0
}

function u16(n: number): Uint8Array {
  const b = new Uint8Array(2)
  new DataView(b.buffer).setUint16(0, n, true)
  return b
}

function u32(n: number): Uint8Array {
  const b = new Uint8Array(4)
  new DataView(b.buffer).setUint32(0, n, true)
  return b
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const len = chunks.reduce((s, c) => s + c.length, 0)
  const out = new Uint8Array(len)
  let o = 0
  for (const c of chunks) {
    out.set(c, o)
    o += c.length
  }
  return out
}

function encUtf8(s: string): Uint8Array {
  return new TextEncoder().encode(s)
}

type ZipEntry = { name: string; data: Uint8Array }

/** ZIP с несжатыми записями (method 0). */
export function zipStore(entries: ZipEntry[]): Uint8Array {
  const locals: Uint8Array[] = []
  const centrals: Uint8Array[] = []
  let offset = 0
  for (const e of entries) {
    const nameBytes = encUtf8(e.name)
    const crc = crc32(e.data)
    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(e.data.length),
      u32(e.data.length),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      e.data,
    ])
    const central = concat([
      u32(0x02014b50),
      u16(20),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(e.data.length),
      u32(e.data.length),
      u16(nameBytes.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      nameBytes,
    ])
    locals.push(local)
    centrals.push(central)
    offset += local.length
  }
  const centralDir = concat(centrals)
  const end = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(entries.length),
    u16(entries.length),
    u32(centralDir.length),
    u32(offset),
    u16(0),
  ])
  return concat([...locals, centralDir, end])
}

function escXml(s: string): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export type DocImage = {
  data: Uint8Array
  ext: 'png' | 'jpeg' | 'jpg'
  widthPx?: number
  heightPx?: number
  widthCm?: number
}

export type DocBlock =
  | { type: 'h1' | 'h2' | 'h3'; text: string }
  | { type: 'p'; text: string }
  | { type: 'bullet'; text: string }
  | { type: 'kv'; rows: [string, string][] }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'image'; image: DocImage; caption?: string }

function pRun(text: string, bold = false): string {
  const b = bold ? '<w:b/>' : ''
  return `<w:r><w:rPr>${b}<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">${escXml(text)}</w:t></w:r>`
}

function para(text: string, opts?: { bold?: boolean; style?: string }): string {
  const style = opts?.style ? `<w:pStyle w:val="${opts.style}"/>` : ''
  return `<w:p><w:pPr>${style}</w:pPr>${pRun(text || 'Не установлено', opts?.bold)}</w:p>`
}

function heading(text: string, level: 1 | 2 | 3): string {
  return para(text, { bold: true, style: `Heading${level}` })
}

function kvTable(rows: [string, string][]): string {
  const trs = rows
    .map(
      ([k, v]) =>
        `<w:tr><w:tc><w:tcPr><w:tcW w:w="3500" w:type="dxa"/></w:tcPr>${para(k, { bold: true })}</w:tc>` +
        `<w:tc><w:tcPr><w:tcW w:w="6500" w:type="dxa"/></w:tcPr>${para(v || 'Не установлено')}</w:tc></w:tr>`,
    )
    .join('')
  return (
    `<w:tbl><w:tblPr><w:tblW w:w="10000" w:type="dxa"/><w:tblBorders>` +
    `<w:top w:val="single" w:sz="4" w:color="D0D7DE"/><w:left w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `<w:bottom w:val="single" w:sz="4" w:color="D0D7DE"/><w:right w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `<w:insideH w:val="single" w:sz="4" w:color="D0D7DE"/><w:insideV w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `</w:tblBorders></w:tblPr>${trs}</w:tbl>`
  )
}

function dataTable(headers: string[], rows: string[][]): string {
  const hdr = `<w:tr>${headers
    .map((h) => `<w:tc><w:tcPr><w:shd w:val="clear" w:fill="EEF2F6"/></w:tcPr>${para(h, { bold: true })}</w:tc>`)
    .join('')}</w:tr>`
  const body = rows.map((r) => `<w:tr>${r.map((c) => `<w:tc>${para(c || '—')}</w:tc>`).join('')}</w:tr>`).join('')
  return (
    `<w:tbl><w:tblPr><w:tblW w:w="10000" w:type="dxa"/><w:tblBorders>` +
    `<w:top w:val="single" w:sz="4" w:color="D0D7DE"/><w:left w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `<w:bottom w:val="single" w:sz="4" w:color="D0D7DE"/><w:right w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `<w:insideH w:val="single" w:sz="4" w:color="D0D7DE"/><w:insideV w:val="single" w:sz="4" w:color="D0D7DE"/>` +
    `</w:tblBorders></w:tblPr>${hdr}${body}</w:tbl>`
  )
}

/** 1 cm = 360000 EMU */
function cmToEmu(cm: number): number {
  return Math.round(cm * 360000)
}

function imageDrawingXml(rId: string, img: DocImage, docPrId: number): string {
  const widthCm = img.widthCm ?? 14
  const ratio =
    img.widthPx && img.heightPx && img.widthPx > 0 ? img.heightPx / img.widthPx : 10 / 16
  const heightCm = widthCm * ratio
  const cx = cmToEmu(widthCm)
  const cy = cmToEmu(heightCm)
  return `<w:p><w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0"
        xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
        xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
        xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <wp:extent cx="${cx}" cy="${cy}"/>
        <wp:docPr id="${docPrId}" name="Picture ${docPrId}"/>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr>
                <pic:cNvPr id="0" name="image${docPrId}"/>
                <pic:cNvPicPr/>
              </pic:nvPicPr>
              <pic:blipFill>
                <a:blip r:embed="${rId}"/>
                <a:stretch><a:fillRect/></a:stretch>
              </pic:blipFill>
              <pic:spPr>
                <a:xfrm>
                  <a:off x="0" y="0"/>
                  <a:ext cx="${cx}" cy="${cy}"/>
                </a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
              </pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r></w:p>`
}

const ROOT_RELS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`

const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/>
    <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="200" w:after="100"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="160" w:after="80"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>
</w:styles>`

export function buildDocxBlob(blocks: DocBlock[]): Blob {
  const media: { name: string; data: Uint8Array; contentType: string; rId: string }[] = []
  let imgN = 0
  let docPrId = 1

  const bodyParts: string[] = []
  for (const b of blocks) {
    if (b.type === 'h1') bodyParts.push(heading(b.text, 1))
    else if (b.type === 'h2') bodyParts.push(heading(b.text, 2))
    else if (b.type === 'h3') bodyParts.push(heading(b.text, 3))
    else if (b.type === 'p') bodyParts.push(para(b.text))
    else if (b.type === 'bullet') bodyParts.push(para(`• ${b.text}`))
    else if (b.type === 'kv') bodyParts.push(kvTable(b.rows))
    else if (b.type === 'table') bodyParts.push(dataTable(b.headers, b.rows))
    else if (b.type === 'image') {
      imgN += 1
      const ext = b.image.ext === 'jpg' ? 'jpeg' : b.image.ext
      const fileExt = ext === 'jpeg' ? 'jpg' : ext
      const rId = `rIdImg${imgN}`
      const name = `word/media/image${imgN}.${fileExt}`
      const contentType = ext === 'png' ? 'image/png' : 'image/jpeg'
      media.push({ name, data: b.image.data, contentType, rId })
      bodyParts.push(imageDrawingXml(rId, b.image, docPrId++))
      if (b.caption) bodyParts.push(para(b.caption))
    }
  }

  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>${bodyParts.join('')}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body>
</w:document>`

  const relLines = [
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`,
    ...media.map(
      (m) =>
        `<Relationship Id="${m.rId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/${m.name.split('/').pop()}"/>`,
    ),
  ]
  const docRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
${relLines.join('\n')}
</Relationships>`

  const defaults = new Set(['rels', 'xml', 'png', 'jpg', 'jpeg'])
  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>`

  void defaults

  const entries: ZipEntry[] = [
    { name: '[Content_Types].xml', data: encUtf8(contentTypes) },
    { name: '_rels/.rels', data: encUtf8(ROOT_RELS) },
    { name: 'word/document.xml', data: encUtf8(documentXml) },
    { name: 'word/_rels/document.xml.rels', data: encUtf8(docRels) },
    { name: 'word/styles.xml', data: encUtf8(STYLES) },
    ...media.map((m) => ({ name: m.name, data: m.data })),
  ]

  const bytes = zipStore(entries)
  return new Blob([bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function fetchImageAsDoc(url: string): Promise<DocImage | null> {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    const buf = new Uint8Array(await res.arrayBuffer())
    const lower = url.toLowerCase()
    const ext: DocImage['ext'] = lower.includes('.jpg') || lower.includes('.jpeg') ? 'jpeg' : 'png'
    // dimensions from PNG IHDR if possible
    let widthPx: number | undefined
    let heightPx: number | undefined
    if (ext === 'png' && buf.length > 24 && buf[0] === 0x89) {
      const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
      widthPx = dv.getUint32(16)
      heightPx = dv.getUint32(20)
    }
    return { data: buf, ext, widthPx, heightPx, widthCm: 14 }
  } catch {
    return null
  }
}
