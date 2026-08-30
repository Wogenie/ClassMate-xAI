import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { UserPlus } from 'lucide-react'
import api, { errText } from '../services/api.js'
import GoogleButton from '../components/GoogleButton.jsx'

export default function Register() {
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const afterAuth = (data) => {
    localStorage.setItem('cm_token', data.access_token)
    localStorage.setItem('cm_user', data.username)
    localStorage.setItem('cm_name', data.name || data.username)
    localStorage.setItem('cm_email', data.email || '')
    localStorage.setItem('cm_picture', data.picture || '')
    nav('/setup')
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/auth/register', { username, email, password })
      afterAuth(data)
    } catch (e2) {
      setError(errText(e2))
    } finally {
      setBusy(false)
    }
  }

  const googleLogin = async (credential) => {
    const { data } = await api.post('/auth/google', { credential })
    afterAuth(data)
  }

  return (
    <div className="min-h-screen grid place-items-center bg-ink">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-6 text-center">Create your ClassMateX account</h1>
        <div className="card space-y-4">
          <GoogleButton onSuccess={googleLogin} onError={(e) => setError(errText(e))} />
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="h-px flex-1 bg-slate-700" />
            <span>or with username</span>
            <span className="h-px flex-1 bg-slate-700" />
          </div>
          <form onSubmit={submit} className="space-y-4">
            {error && <div className="text-sm text-rose-400 bg-rose-500/10 rounded-xl px-3 py-2">{error}</div>}
            <div>
              <label className="label">Username</label>
              <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} required />
            </div>
            <div>
              <label className="label">Email (optional, used to sign in later)</label>
              <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </div>
            <div>
              <label className="label">Password (min 6)</label>
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={6} required />
            </div>
            <p className="text-xs text-slate-400">
              After registering you'll bring your <strong className="text-slate-200">own</strong> Telegram bot token and
              Groq API key in Setup — nothing is shared between users.
            </p>
            <button className="btn-primary w-full" disabled={busy}>
              <UserPlus size={16} className="inline mr-1" /> {busy ? 'Creating…' : 'Create account'}
            </button>
            <p className="text-sm text-slate-400 text-center">
              Already have an account?{' '}
              <Link to="/login" className="text-indigo-300 hover:underline">
                Sign in
              </Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  )
}