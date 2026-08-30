import React, { Fragment } from 'react'

function renderInline(text, keyPrefix) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return parts.map((s, i) => {
    if (s.startsWith('**') && s.endsWith('**')) {
      return (
        <strong key={`${keyPrefix}-${i}`} className="text-slate-100">
          {s.slice(2, -2)}
        </strong>
      )
    }
    if (s.startsWith('`') && s.endsWith('`')) {
      return (
        <code
          key={`${keyPrefix}-${i}`}
          className="bg-edge/60 text-indigo-200 px-1 py-0.5 rounded font-mono text-[0.9em]"
        >
          {s.slice(1, -1)}
        </code>
      )
    }
    return <Fragment key={`${keyPrefix}-${i}`}>{s}</Fragment>
  })
}

function cleanTrailingNoise(t) {
  // Drop stray decorative tokens LLMs leave behind (**:, ,, ...) and collapse
  // accidental double spaces so the text reads clean.
  return t
    .replace(/\*\*|__|`/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\s+$/g, '')
}

/** Minimal safe markdown: headings, lists, code, bold, inline code. */
export default function Markdown({ text, className = '' }) {
  if (!text) return null
  const lines = String(text).split('\n')
  const out = []
  let inCode = false
  let codeBuf = []

  lines.forEach((line, i) => {
    const trimmed = line.trim()

    if (/^```/.test(trimmed)) {
      if (inCode) {
        out.push(
          <pre
            key={i}
            className="bg-ink border border-edge rounded-lg px-3 py-2 font-mono text-xs overflow-x-auto my-1"
          >
            {codeBuf.join('\n')}
          </pre>
        )
        codeBuf = []
        inCode = false
      } else {
        inCode = true
      }
      return
    }
    if (inCode) {
      codeBuf.push(line)
      return
    }
    if (!trimmed) {
      out.push(<div key={i} className="h-2.5" />)
      return
    }
    if (/^(---+|\*\*\*+|___+)$/.test(trimmed)) {
      out.push(<div key={i} className="my-1 border-t border-edge/60" />)
      return
    }
    const heading = /^(#{1,6})\s*(.*)$/.exec(trimmed)
    if (heading) {
      const size = heading[1].length
      out.push(
        <p
          key={i}
          className={`font-semibold text-slate-100 leading-relaxed ${
            size === 1 ? 'text-lg' : size === 2 ? 'text-base' : 'text-sm'
          }`}
        >
          {renderInline(cleanTrailingNoise(heading[2]), i)}
        </p>
      )
      return
    }
    const bullet = /^([-•*])\s+(.*)$/.exec(trimmed)
    if (bullet) {
      out.push(
        <div key={i} className="flex gap-2 leading-relaxed">
          <span className="text-indigo-400">•</span>
          <span>{renderInline(cleanTrailingNoise(bullet[2]), i)}</span>
        </div>
      )
      return
    }
    const numbered = /^(\d+)[.)]\s+(.*)$/.exec(trimmed)
    if (numbered) {
      out.push(
        <div key={i} className="flex gap-2 leading-relaxed">
          <span className="text-slate-400 tabular-nums">{numbered[1]}.</span>
          <span>{renderInline(cleanTrailingNoise(numbered[2]), i)}</span>
        </div>
      )
      return
    }
    if (trimmed.startsWith('> ')) {
      out.push(
        <p key={i} className="leading-relaxed pl-2 border-l-2 border-edge text-slate-400">
          {renderInline(cleanTrailingNoise(trimmed.slice(2)), i)}
        </p>
      )
      return
    }
    out.push(
      <p key={i} className="leading-relaxed">
        {renderInline(cleanTrailingNoise(trimmed), i)}
      </p>
    )
  })

  return <div className={`whitespace-pre-wrap ${className}`}>{out}</div>
}