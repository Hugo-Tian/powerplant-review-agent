// Render the architecture diagrams (docs/diagrams/diagrams.html) to PNG and the
// competition docs (docs/competition/*.md) to PDF, using Playwright's Chromium.
//   node render-docs.mjs diagrams        -> docs/images/architecture.png, agent_dispatch.png, agent_team.png
//   node render-docs.mjs pdf <out-dir> <a.md> [b.md ...]
import { chromium } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { basename, dirname, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const ROOT = resolve(import.meta.dirname, '..')

async function diagrams(browser) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 })
  await page.goto(pathToFileURL(join(ROOT, 'docs/diagrams/diagrams.html')).href)
  for (const id of ['architecture', 'agent_dispatch', 'agent_team', 'results']) {
    const out = join(ROOT, 'docs/images', `${id}.png`)
    await page.locator(`#${id}`).screenshot({ path: out })
    console.log(out)
  }
}

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = s => esc(s)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')

// 只支持本仓库文档用到的 Markdown：标题、段落、列表（两级）、表格、引用、代码块、图片
function markdown(src, baseDir) {
  const lines = src.replace(/\r/g, '').split('\n')
  const html = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    if (line.startsWith('```')) {
      const body = []
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) body.push(lines[i])
      i++
      html.push(`<pre>${esc(body.join('\n'))}</pre>`)
    } else if (/^#{1,4} /.test(line)) {
      const n = line.match(/^#+/)[0].length
      html.push(`<h${n}>${inline(line.slice(n + 1))}</h${n}>`)
      i++
    } else if (/^!\[/.test(line)) {
      const [, alt, src] = line.match(/^!\[([^\]]*)\]\(([^)]+)\)/)
      html.push(`<figure><img src="${pathToFileURL(resolve(baseDir, src)).href}"><figcaption>${inline(alt)}</figcaption></figure>`)
      i++
    } else if (line.startsWith('|')) {
      const rows = []
      for (; i < lines.length && lines[i].startsWith('|'); i++) rows.push(lines[i])
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
      const head = cells(rows[0]).map(c => `<th>${inline(c)}</th>`).join('')
      const body = rows.slice(2).map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')
      html.push(`<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`)
    } else if (line.startsWith('> ')) {
      const body = []
      for (; i < lines.length && lines[i].startsWith('>'); i++) body.push(lines[i].replace(/^>\s?/, ''))
      html.push(`<blockquote>${inline(body.join(' '))}</blockquote>`)
    } else if (/^\s*([-*]|\d+\.) /.test(line)) {
      const ordered = /^\d+\./.test(line.trim())
      const items = []
      for (; i < lines.length && /^\s*([-*]|\d+\.) /.test(lines[i]); i++) {
        const sub = /^\s{2,}/.test(lines[i])
        const text = inline(lines[i].replace(/^\s*([-*]|\d+\.) /, ''))
        if (sub && items.length) items[items.length - 1].sub.push(text)
        else items.push({ text, sub: [] })
      }
      const tag = ordered ? 'ol' : 'ul'
      html.push(`<${tag}>${items.map(it => `<li>${it.text}${it.sub.length ? `<ul>${it.sub.map(s => `<li>${s}</li>`).join('')}</ul>` : ''}</li>`).join('')}</${tag}>`)
    } else {
      const body = []
      for (; i < lines.length && lines[i].trim() && !/^(#|\||>|```|!\[|\s*([-*]|\d+\.) )/.test(lines[i]); i++) body.push(lines[i])
      html.push(`<p>${inline(body.join(''))}</p>`)
    }
  }
  return html.join('\n')
}

const CSS = `
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #1f2a33; font-size: 10.5pt; line-height: 1.65; }
  h1 { font-size: 20pt; border-bottom: 3px solid #d9902f; padding-bottom: 6px; margin: 0 0 14px; }
  h2 { font-size: 14pt; margin: 22px 0 8px; padding-left: 8px; border-left: 4px solid #1f2a33; }
  h3 { font-size: 12pt; margin: 16px 0 6px; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.5pt; page-break-inside: auto; }
  th, td { border: 1px solid #b9c2c9; padding: 5px 7px; vertical-align: top; text-align: left; }
  th { background: #e6eaed; }
  tr { page-break-inside: avoid; }
  code { font-family: Consolas, monospace; background: #f0f2f4; padding: 0 3px; border-radius: 3px; font-size: 9pt; }
  pre { background: #f0f2f4; padding: 8px 10px; border-radius: 4px; font-size: 9pt; white-space: pre-wrap; }
  blockquote { margin: 10px 0; padding: 8px 12px; background: #fbefdc; border-left: 4px solid #d9902f; }
  figure { margin: 10px 0 14px; text-align: center; page-break-inside: avoid; }
  img { max-width: 100%; max-height: 225mm; width: auto; border: 1px solid #d5dbe0; }
  h1, h2, h3 { page-break-after: avoid; }
  figcaption { color: #5b6874; font-size: 9pt; margin-top: 4px; }
  ul, ol { padding-left: 22px; margin: 6px 0; }
  li { margin: 2px 0; }
  a { color: #3c6e95; text-decoration: none; }
`

async function pdf(browser, outDir, files) {
  await mkdir(outDir, { recursive: true })
  const page = await browser.newPage()
  for (const file of files) {
    const src = await readFile(file, 'utf8')
    const title = (src.match(/^# (.+)$/m) || [, basename(file)])[1]
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(title)}</title><style>${CSS}</style></head><body>${markdown(src, dirname(resolve(file)))}</body></html>`
    const tmp = join(outDir, basename(file).replace(/\.md$/, '.html'))
    await writeFile(tmp, html)
    await page.goto(pathToFileURL(tmp).href)
    await page.waitForLoadState('networkidle')
    const out = join(outDir, basename(file).replace(/\.md$/, '.pdf'))
    await page.pdf({ path: out, format: 'A4', printBackground: true,
      displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="font-size:8pt;color:#888;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
      margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' } })
    console.log(out)
  }
}

const [mode, ...rest] = process.argv.slice(2)
const browser = await chromium.launch()
try {
  if (mode === 'diagrams') await diagrams(browser)
  else if (mode === 'pdf') await pdf(browser, resolve(rest[0]), rest.slice(1))
  else throw new Error('usage: node render-docs.mjs diagrams | pdf <out-dir> <files...>')
} finally {
  await browser.close()
}
