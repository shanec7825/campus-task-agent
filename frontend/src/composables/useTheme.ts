import { computed, ref, type ComputedRef, type Ref } from 'vue'

export type AppTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'cta_theme'

const THEME_CHANGE_EVENT = 'cta-theme-change'

const theme = ref<AppTheme>('light')
const isDark = computed(() => theme.value === 'dark')

let manualChoice = false
let initialized = false
let systemQuery: MediaQueryList | null = null

function readStoredTheme(): AppTheme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : null
  } catch {
    return null
  }
}

function preferredTheme(): AppTheme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

function onSystemChange(event: MediaQueryListEvent): void {
  // 用户手动选择后不再跟随系统
  if (manualChoice) return
  applyTheme(event.matches ? 'dark' : 'light')
}

export function applyTheme(next: AppTheme): void {
  theme.value = next
  const root = document.documentElement
  root.classList.toggle('dark', next === 'dark')
  root.dataset.theme = next
  window.dispatchEvent(new CustomEvent<AppTheme>(THEME_CHANGE_EVENT, { detail: next }))
}

export function initTheme(): void {
  if (initialized) return
  initialized = true

  const stored = readStoredTheme()
  if (stored) {
    manualChoice = true
    applyTheme(stored)
    return
  }

  applyTheme(preferredTheme())
  try {
    systemQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemQuery.addEventListener('change', onSystemChange)
  } catch {
    systemQuery = null
  }
}

export function setTheme(next: AppTheme): void {
  manualChoice = true
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, next)
  } catch {
    // 存储不可用时仍应用主题，仅本次会话生效
  }
  applyTheme(next)
}

export function useTheme(): {
  theme: Ref<AppTheme>
  isDark: ComputedRef<boolean>
  toggleTheme: () => void
  setTheme: (next: AppTheme) => void
} {
  return {
    theme,
    isDark,
    toggleTheme: () => setTheme(theme.value === 'dark' ? 'light' : 'dark'),
    setTheme,
  }
}