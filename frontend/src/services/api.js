import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('cm_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401 && localStorage.getItem('cm_token')) {
      localStorage.removeItem('cm_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export const errText = (e) =>
  e?.response?.data?.detail || e?.response?.data?.message || e?.message || 'Request failed'

export default api