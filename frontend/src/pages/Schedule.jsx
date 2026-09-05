import React, { useEffect, useState } from 'react'
import { CalendarDays, ChevronDown, ChevronUp, Loader2, MapPin, ScrollText, Sparkles } from 'lucide-react'
import api from '../services/api.js'
import Markdown from '../components/Markdown.jsx'

const TABS = [
  { id: 'classes', label: 'Classes & changes' },
  { id: 'assessments', label: 'Quizzes & exams' },
  { id: 'missed', label: 'Missed classes' },
]

function CoverageBlock({ q, onAnswered }) {
  const [busy, setBusy] = useState('')
  if (!q.coverage_status) return null

  const run = async (path, label) => {
    if (busy) return
    setBusy(label)
    try {
      await api.post(path)
      onAnswered && onAnswered()
    } catch { /* ignore */ }
    setBusy('')
  }

  const topics = (q.topics || []).filter((t) => t && t.name)
  const bounds = q.coverage || {}
  const hasBounds = (bounds.start || bounds.end)

  return (
    <div className="mt-2 rounded-xl border border-edge/70 overflow-hidden">
      <div className="px-3 py-2.5 space-y-2 bg-panel/40">
        {q.winning_portion && (
          <p className="text-xs">
            <span className="font-semibold text-slate-200">Voted portion: </span>
            <span className="text-slate-300">{q.winning_portion}</span>
          </p>
        )}

        {hasBounds && (
          <p className="text-xs font-mono text-slate-300">
            {bounds.start}{bounds.end ? ` → ${bounds.end}` : ''}
          </p>
        )}

        {topics.length > 0 && (
          <div className="space-y-1.5 pt-1">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Topics</div>
            {topics.map((t, i) => (
              <div key={i} className="text-xs">
                <span className="font-medium text-slate-200">{t.name}</span>
                {t.description && <p className="text-slate-400 mt-0.5">{t.description}</p>}
              </div>
            ))}
          </div>
        )}

        {q.portion_summary ? (
          <div className="pt-1 border-t border-edge/70">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Portion summary</div>
            <div className="max-h-64 overflow-y-auto bg-ink rounded-xl border border-edge/70 px-3 py-2.5 text-xs">
              <Markdown text={q.portion_summary} />
            </div>
          </div>
        ) : (
          <div className="pt-1">
            <button
              className="btn-ghost text-[11px]"
              disabled={!!busy}
              onClick={() => run(`/quizzes/portion-summary/${q.id}`, 'sum')}
            >
              {busy === 'sum' ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Sparkles size={12} className="inline mr-1" />
              )}
              Summarize the portion from the course outline
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function AssessmentCard({ q, onAnswered }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="py-2 border-b border-edge/60 last:border-0">
      <div className="flex items-center gap-2">
        <span className="font-medium">{q.course}</span>
        <span className={`badge ${q.assessType === 'Exam' ? 'bg-rose-500/15 text-rose-300' : 'bg-indigo-500/15 text-indigo-300'}`}>
          {q.assessType}
        </span>
      </div>
      <div className="text-xs text-slate-400 mt-0.5">
        {q.topic || q.description?.slice(0, 100) || 'scope unknown'}
      </div>
      <div className="text-xs text-slate-500 mt-1 font-mono">{q.event_date}</div>

      <CoverageBlock q={q} onAnswered={onAnswered} />

      {q.study_guide && (
        <>
          <button
            className="mt-2 btn-ghost text-xs"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            <span className="ml-1">Study guide</span>
          </button>
          {open && (
            <div className="mt-2 max-h-80 overflow-y-auto bg-ink rounded-xl border border-edge/70 px-3 py-2.5">
              <Markdown text={q.study_guide} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function Schedule() {
  const [tab, setTab] = useState('classes')
  const [data, setData] = useState({})
  const [assess, setAssess] = useState({ quizzes: [], exams: [] })
  const [missed, setMissed] = useState([])

  const loadAssess = () =>
    api.get('/quizzes').then(({ data }) => setAssess(data)).catch(() => {})

  useEffect(() => {
    api.get('/schedule').then(({ data }) => setData(data)).catch(() => {})
    loadAssess()
    api.get('/missed').then(({ data }) => setMissed(data)).catch(() => {})
  }, [])

  const classes = data.classes || []
  const changes = data.changes || []
  const { quizzes, exams } = assess
  const combined = [
    ...quizzes.map((q) => ({ ...q, assessType: 'Quiz' })),
    ...exams.map((e) => ({ ...e, assessType: 'Exam' })),
  ]
  const dt = (s) => {
    if (!s) return null
    const d = new Date(s)
    return Number.isNaN(d.getTime()) ? null : d.getTime()
  }
  const allAssessments = [...combined].sort((a, b) => {
    const ca = a.created_at || ''
    const cb = b.created_at || ''
    if (ca !== cb) return cb.localeCompare(ca)
    const da = dt(a.event_date) || 0
    const dba = dt(b.event_date) || 0
    return dba - da
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <CalendarDays size={20} className="text-indigo-400" /> Schedule · Quizzes · Missed
        </h1>
        <p className="text-sm text-slate-400 mt-1">Live timetable, assessments and catch-up summaries from your group.</p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1 -mb-1 sm:flex-wrap sm:overflow-visible">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 rounded-xl text-sm transition whitespace-nowrap ${
              tab === t.id ? 'bg-indigo-500 text-white' : 'bg-edge/60 text-slate-300 hover:bg-edge'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'classes' && (
        <div className="space-y-6">
          {changes.length > 0 && (
            <div className="card border-amber-500/40 space-y-2">
              <h2 className="font-semibold text-amber-200">Schedule changes</h2>
              {changes.map((c) => (
                <div key={c.id} className="text-sm border-b border-edge/60 last:border-0 py-2">
                  <div className="font-medium">
                    {c.course} — {c.title || 'change'}
                  </div>
                  {c.description && <p className="text-xs text-slate-400 mt-0.5">{c.description}</p>}
                  <div className="text-xs text-slate-500 mt-0.5">
                    {c.event_date} {c.start_time && `· ${c.start_time}${c.end_time ? `–${c.end_time}` : ''}`}{' '}
                    <span className={`badge ${c.source === 'confirmed' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-sky-500/15 text-sky-300'}`}>
                      {c.source}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="card space-y-3">
            <h2 className="font-semibold">Classes</h2>
            {classes.length === 0 && <p className="text-sm text-slate-500">No classes detected yet.</p>}
            {classes.map((c) => (
              <div key={c.id} className="py-3 border-b border-edge/60 last:border-0">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="font-semibold">{c.course}</span>
                    <span className="mx-2 text-slate-500">·</span>
                    <span className="text-sm">{c.topic || c.title || 'topic unknown'}</span>
                  </div>
                  <span className={`badge shrink-0 ${c.source === 'confirmed' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-sky-500/15 text-sky-300'}`}>
                    {c.source}
                  </span>
                </div>
                <div className="text-xs text-slate-400 mt-1 flex items-center gap-4">
                  <span className="font-mono">
                    {c.event_date || '—'} {c.start_time && `${c.start_time}${c.end_time ? `–${c.end_time}` : ''}`}
                  </span>
                  {c.location && (
                    <span className="flex items-center gap-1">
                      <MapPin size={12} /> {c.location}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'assessments' && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Quizzes &amp; exams</h2>
          {allAssessments.length === 0 && (
            <p className="text-sm text-slate-500">None detected.</p>
          )}
          {allAssessments.map((q) => (
            <AssessmentCard key={q.id} q={q} onAnswered={loadAssess} />
          ))}
        </div>
      )}

      {tab === 'missed' && (
        <div className="space-y-4">
          <h2 className="font-semibold flex items-center gap-2">
            <ScrollText size={17} className="text-sky-300" /> Catch-up summaries
          </h2>
          {missed.length === 0 && (
            <p className="text-sm text-slate-500">
              No missed-class summaries yet. They're generated automatically after a class from the lecture-sync poll
              (+ RAG over your course materials).
            </p>
          )}
          {missed.map((m) => (
            <div key={m.id} className="card space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="font-semibold">
                  {m.course} <span className="text-slate-500 font-normal">· {m.date}</span>
                </span>
                <span className="badge bg-edge text-slate-300">{m.topic}</span>
              </div>
              <Markdown text={m.summary} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}