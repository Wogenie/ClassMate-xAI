import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  Bell,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Clock,
  FileText,
  GraduationCap,
  Loader2,
  ScrollText,
} from 'lucide-react'
import api from '../services/api.js'

function Stat({ icon: Icon, label, value, tint = 'text-indigo-300' }) {
  return (
    <div className="card flex items-center gap-3 min-w-0">
      <span className="w-10 h-10 sm:w-11 sm:h-11 rounded-xl bg-edge grid place-items-center shrink-0">
        <Icon size={20} className={tint} />
      </span>
      <div className="min-w-0">
        <div className="text-2xl font-bold leading-none">{value ?? '—'}</div>
        <div className="text-[11px] sm:text-xs text-slate-400 mt-1 leading-tight">{label}</div>
      </div>
    </div>
  )
}

export default function Overview() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const { data: d } = await api.get('/dashboard/overview')
      setData(d)
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load overview')
    }
  }

  useEffect(() => {
    load()
  }, [])

  if (!data) {
    return (
      <div className="grid place-items-center py-40 text-slate-400">
        <Loader2 className="animate-spin" />
      </div>
    )
  }

  const { classes_today: today, deadlines, upcoming_quizzes: quizzes, announcements, missed, progress } = data
  const dueCounts = {
    overdue: deadlines?.overdue?.length || 0,
    due_today: deadlines?.due_today?.length || 0,
    due_soon: deadlines?.due_soon?.length || 0,
    upcoming: deadlines?.upcoming?.length || 0,
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-rose-500/10 text-rose-300 px-4 py-3 rounded-xl text-sm">{error}</div>
      )}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold">Your academic life, right now</h1>
          <p className="text-sm text-slate-400 mt-1">
            Today · {data.today} — everything ClassMateX has extracted from your Telegram group.
          </p>
        </div>
        <Link to="/assistant" className="btn-primary shrink-0">
          Ask the assistant
        </Link>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat icon={CalendarDays} label="Classes today" value={today.length} />
        <Stat icon={ClipboardList} label="Open assignments" value={progress.assignments_open} tint="text-amber-300" />
        <Stat icon={AlertTriangle} label="Deadlines ≤ 24h" value={dueCounts.due_today + dueCounts.due_soon} tint="text-rose-300" />
        <Stat icon={GraduationCap} label="Completion" value={`${progress.completed_pct}%`} tint="text-emerald-300" />
      </div>

      {dueCounts.overdue + dueCounts.due_today + dueCounts.due_soon > 0 && (
        <div className="card border-rose-500/40">
          <h2 className="font-semibold mb-3 flex items-center gap-2">
            <Clock size={17} className="text-rose-300" /> Priorities
          </h2>
          <div className="space-y-2">
            {deadlines.overdue.slice(0, 3).map((d) => (
              <div key={d.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-rose-300 flex-1 truncate">⏰ {d.title || d.course}</span>
                <span className="text-rose-300/80 text-xs">{d.deadline}</span>
              </div>
            ))}
            {deadlines.due_today.slice(0, 3).map((d) => (
              <div key={d.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-amber-200 flex-1 truncate">📌 {d.title || d.course} </span>
                <span className="text-amber-200/80 text-xs">{d.deadline}</span>
              </div>
            ))}
            {deadlines.due_soon.slice(0, 3).map((d) => (
              <div key={d.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-slate-200 flex-1 truncate">⚡ {d.title || d.course}</span>
                <span className="text-slate-400 text-xs">{d.deadline}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <CalendarDays size={17} className="text-indigo-300" /> Today's classes
          </h2>
          {today.length === 0 && <p className="text-sm text-slate-500">No classes detected today.</p>}
          {today.map((c) => (
            <div key={c.id} className="flex items-center justify-between py-2 border-b border-edge/60 last:border-0">
              <div>
                <div className="font-medium">{c.course}</div>
                <div className="text-xs text-slate-400">{c.topic || 'topic unknown'}</div>
              </div>
              <div className="text-right">
                <div className="text-sm font-mono">{c.start_time || '—'}{c.end_time ? `–${c.end_time}` : ''}</div>
                <div className="text-xs text-slate-500">{c.location || ''}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <FileText size={17} className="text-emerald-300" /> Upcoming quizzes &amp; exams
          </h2>
          {quizzes.length === 0 && <p className="text-sm text-slate-500">Nothing announced.</p>}
          {quizzes.map((q) => (
            <div key={q.id} className="py-2 border-b border-edge/60 last:border-0 flex items-center justify-between">
              <div>
                <div className="font-medium">
                  {q.type === 'exam' ? '📝 Exam' : '🧪 Quiz'} — {q.course}
                </div>
                <div className="text-xs text-slate-400">{q.topic || (q.portion_summary ? q.portion_summary.slice(0, 90) + '…' : q.description?.slice(0, 60)) || 'scope unknown'}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-mono text-slate-300">{q.event_date}</span>
              </div>
            </div>
          ))}
        </div>

        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <Bell size={17} className="text-amber-300" /> Recent announcements
          </h2>
          {announcements.length === 0 && <p className="text-sm text-slate-500">No announcements yet.</p>}
          {announcements.map((a) => (
            <div key={a.id} className="py-2 border-b border-edge/60 last:border-0">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium truncate">{a.title || a.course}</span>
              </div>
              {a.description && <p className="text-xs text-slate-400 mt-1 line-clamp-2">{a.description}</p>}
            </div>
          ))}
        </div>

        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <ScrollText size={17} className="text-sky-300" /> Missed classes
          </h2>
          {missed.length === 0 && <p className="text-sm text-slate-500">Nothing to catch up on — you're all set.</p>}
          {missed.map((m) => (
            <div key={m.id} className="py-2 border-b border-edge/60 last:border-0">
              <div className="flex items-center justify-between">
                <span className="font-medium">{m.course}</span>
                <span className="text-xs text-slate-500">{m.date}</span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5">{m.topic}</div>
            </div>
          ))}
          {missed.length > 0 && (
            <Link to="/schedule" className="text-xs text-indigo-300 hover:underline inline-block">
              See full catch-up summaries →
            </Link>
          )}
        </div>
      </div>

      {progress.assignments_total === 0 && (
        <div className="card border-indigo-500/40 bg-indigo-500/5 flex items-start gap-3">
          <CheckCircle2 size={18} className="text-indigo-300 mt-0.5" />
          <div className="text-sm text-slate-300">
            <strong>Nothing ingested yet.</strong> Go to{' '}
            <Link to="/setup" className="text-indigo-300 underline">Setup</Link> to connect your Telegram bot, then send
            a test message from the Assistant page or wait for your group's messages to arrive.
          </div>
        </div>
      )}
    </div>
  )
}