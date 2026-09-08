import axios, { AxiosError } from 'axios'
import type { AxiosResponse } from 'axios'

// 假定你使用 Element Plus 的 ElMessage
import { ElMessage } from 'element-plus'

// -------------------- 类型定义 --------------------
export interface ApiError {
  detail: string | Record<string, any>  // 后端 HTTPException 的 detail
  status?: number
}

// -------------------- 创建实例 --------------------
export const client = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
})

// -------------------- 请求拦截器 --------------------
client.interceptors.request.use(
  (config) => {
    // 示例：从 localStorage 获取 token 并添加到请求头
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 可选：添加请求日志
    // console.log('Request:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => Promise.reject(error),
)

// -------------------- 响应拦截器 --------------------
client.interceptors.response.use(
  (response: AxiosResponse) => {
    // 直接返回 data，方便组件调用。
    // 类型上调用方请用 axios 第二泛型取响应体：client.get<T, T>(url) 返回 Promise<T>
    return response.data
  },
  (error: AxiosError<ApiError>) => {
    // 统一处理错误
    let message = '未知错误'
    if (error.response) {
      const { status, data } = error.response
      // 后端 FastAPI HTTPException 的 detail 可能是字符串或字典
      const detail = data?.detail
      if (typeof detail === 'string') {
        message = detail
      } else if (typeof detail === 'object') {
        // 如果 detail 是对象（如 {"errors": [...]}），提取为可读字符串
        message = JSON.stringify(detail)
      } else {
        // 根据状态码补充默认信息
        if (status === 400) message = '请求参数错误'
        else if (status === 401) message = '未授权，请重新登录'
        else if (status === 403) message = '无权限执行此操作'
        else if (status === 404) message = '资源未找到'
        else if (status >= 500) message = '服务器内部错误'
      }
    } else if (error.request) {
      message = '网络连接失败，请检查网络'
    } else {
      message = error.message || '请求配置错误'
    }

    // 显示错误提示（可配置是否统一提示）
    ElMessage.error(message)

    // 将错误继续抛出，让调用方可以额外处理
    return Promise.reject({
      ...error,
      userMessage: message,  // 附加友好信息
    })
  },
)