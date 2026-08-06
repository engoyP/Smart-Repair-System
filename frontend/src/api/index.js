import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// 请求拦截器：自动携带 JWT token + 规范化 URL
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 规范化 URL：根路径资源补尾斜杠，避免 FastAPI 307 重定向丢失 Authorization header
    if (config.url) {
      const qIdx = config.url.indexOf('?')
      const path = qIdx >= 0 ? config.url.substring(0, qIdx) : config.url
      const query = qIdx >= 0 ? config.url.substring(qIdx) : ''
      const segments = path.split('/').filter(s => s.length > 0)
      // 只有一段路径（如 /users, /duty-schedules）且不以 / 结尾 → 补尾斜杠
      if (segments.length === 1 && !path.endsWith('/')) {
        config.url = path + '/' + query
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    // 401 未授权 → 跳转登录页
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('current_user')
      if (window.location.pathname !== '/login') {
        ElMessage.error('登录已过期，请重新登录')
        window.location.href = '/login'
      }
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export default request