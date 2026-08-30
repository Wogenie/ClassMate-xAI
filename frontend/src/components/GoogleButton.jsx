import { useEffect, useRef, useState } from 'react'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const SCRIPT_SRC = 'https://accounts.google.com/gsi/client'

export default function GoogleButton({ onSuccess, onError, label = 'Continue with Google' }) {
  const [ready, setReady] = useState(false)
  const [clicked, setClicked] = useState(false)
  const running = useRef(false)

  useEffect(() => {
    if (!CLIENT_ID) return

    const existing = document.getElementById('gsi-script')
    if (existing && window.google) {
      setReady(true)
      return
    }
    if (existing) {
      existing.addEventListener('load', () => window.google && setReady(true))
      return
    }

    const s = document.createElement('script')
    s.id = 'gsi-script'
    s.src = SCRIPT_SRC
    s.async = true
    s.onload = () => setReady(true)
    document.body.appendChild(s)
  }, [])

  if (!CLIENT_ID) return null

  const doLogin = async (event) => {
    if (clicked || !window.google) return
    event.preventDefault()
    setClicked(true)
    running.current = true
    try {
      const { id_token } = await window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (resp) => {
          if (resp?.credential) {
            try {
              await onSuccess(resp.credential, resp)
            } catch (e) {
              onError?.(e)
            }
          } else {
            onError?.(new Error('Google sign-in did not return a credential'))
          }
          running.current = false
          window.google.accounts.id.cancel()
        },
        ux_mode: 'popup',
        context: 'signin',
      })
      if (running.current) {
        window.google.accounts.id.prompt()
        running.current = false
      }
      setClicked(true)
    } catch (e) {
      setClicked(false)
      onError?.(e)
    }
  }

  return (
    <button
      type="button"
      className="btn-social w-full"
      onClick={doLogin}
      disabled={!ready || clicked}
    >
      <svg width="18" height="18" viewBox="0 0 48 48" className="inline mr-2 align-middle" aria-hidden>
        <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.2 29.4 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/>
        <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.2 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
        <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
        <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.1 5.7l6.2 5.2C36.9 40.6 44 36 44 24c0-1.3-.1-2.6-.4-3.9z"/>
      </svg>
      {clicked ? 'Connecting…' : label}
    </button>
  )
}
