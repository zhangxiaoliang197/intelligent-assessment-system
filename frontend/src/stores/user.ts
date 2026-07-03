import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUserStore = defineStore('user', () => {
  const username = ref('管理员')
  const avatar = ref('')
  const token = ref(localStorage.getItem('token') || '')

  const setUserInfo = (info: { username: string; avatar?: string }) => {
    username.value = info.username
    if (info.avatar) {
      avatar.value = info.avatar
    }
  }

  const setToken = (newToken: string) => {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  const logout = () => {
    username.value = ''
    avatar.value = ''
    token.value = ''
    localStorage.removeItem('token')
  }

  return {
    username,
    avatar,
    token,
    setUserInfo,
    setToken,
    logout
  }
})
