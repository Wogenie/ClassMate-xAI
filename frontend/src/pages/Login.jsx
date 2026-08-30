import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { GraduationCap, LogIn } from 'lucide-react'
import api, { errText } from '../services/api.js'
import GoogleButton from '../components/GoogleButton.jsx'

export default function Login() {
  const nav = useNavigate()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const afterAuth = (data) => {
    localStorage.setItem('cm_token', data.access_token)
    localStorage.setItem('cm_user', data.username)
    localStorage.setItem('cm_name', data.name || data.username)
    localStorage.setItem('cm_email', data.email || '')
    localStorage.setItem('cm_picture', data.picture || '')
    nav('/')
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await api.post('/auth/login', { email: identifier, username: identifier, password })
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
        <div className="mb-8 flex flex-col items-center gap-2">
          <span className="w-12 h-12 rounded-2xl bg-indigo-500 grid place-items-center">
            <GraduationCap size={26} />
          </span>
          <h1 className="text-2xl font-bold">ClassMateX</h1>
          <p className="text-sm text-slate-400">Never ask “what did we learn today?” again.</p>
        </div>
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
              <label className="label">Email or username</label>
              <input
                className="input"
                type="text"
                inputMode="email"
                autoComplete="username"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button className="btn-primary w-full" disabled={busy}>
              <LogIn size={16} className="inline mr-1" /> {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          <p className="text-sm text-slate-400 text-center">
            New here?{' '}
            <Link to="/register" className="text-indigo-300 hover:underline">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}