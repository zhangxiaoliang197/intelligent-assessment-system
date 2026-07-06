import axios from 'axios'
import { ElMessage } from 'element-plus'

const service = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

service.interceptors.response.use(
  (response) => {
    const res = response.data
    if (res.success === false) {
      const serverMsg = res.message || '请求失败'
      return Promise.reject({ ...response, serverMessage: serverMsg })
    }
    return res
  },
  (error) => {
    // Extract server error message if available
    const serverMsg = error?.response?.data?.message
    const msg = serverMsg || error.message || '网络请求失败'
    console.error('响应错误:', msg)
    error.serverMessage = msg
    return Promise.reject(error)
  }
)

export default service
