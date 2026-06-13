import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '@/lib/api'
import type { BotPlatformConfig, ModelInfo } from '@/lib/types'
import { useI18n } from '@/i18n/I18nContext'

export interface FetchStatus {
  cls: '' | 'ok' | 'err'
  msg: string
}

interface SettingsValue {
  baseUrl: string
  apiKey: string
  model: string
  summaryLang: string
  twoStep: boolean
  models: ModelInfo[]
  whisperModel: string
  hfEndpoint: string
  fetchStatus: FetchStatus
  whisperReady: boolean
  whisperError: string | null
  configured: boolean
  setBaseUrl: (v: string) => void
  setApiKey: (v: string) => void
  setModel: (v: string) => void
  setSummaryLang: (v: string) => void
  setTwoStep: (v: boolean) => void
  setWhisperModel: (v: string) => void
  setHfEndpoint: (v: string) => void
  /* Bot 集成配置（持久化到 localStorage，与 API Key 同样的存法）。 */
  botConfigs: Record<string, BotPlatformConfig>
  setBotConfig: (platform: string, patch: Partial<BotPlatformConfig>) => void
  /* 把启用的 Bot 配置 + 当前 LLM 配置一并下发后端。 */
  pushBotConfigs: () => ReturnType<typeof api.botsConfigure>
  fetchModels: (silent?: boolean) => Promise<void>
  refreshInterfaceStatus: () => Promise<void>
  /* Appends the standard model/auth fields to a FormData, matching
     the original _buildFormData / _rssCreateTask behavior. */
  appendModelFields: (fd: FormData) => void
}

const SettingsContext = createContext<SettingsValue | null>(null)

const STORAGE_KEY = 'vt_settings'

interface Persisted {
  baseUrl?: string
  apiKey?: string
  model?: string
  summaryLang?: string
  useTwoStep?: boolean
  models?: ModelInfo[]
  whisperModel?: string
  hfEndpoint?: string
  botConfigs?: Record<string, BotPlatformConfig>
}

function loadPersisted(): Persisted {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Persisted) : {}
  } catch {
    return {}
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n()
  const persisted = useRef<Persisted>(loadPersisted())

  const [baseUrl, setBaseUrl] = useState(persisted.current.baseUrl || '')
  const [apiKey, setApiKey] = useState(persisted.current.apiKey || '')
  const [model, setModel] = useState(persisted.current.model || '')
  const [summaryLang, setSummaryLang] = useState(persisted.current.summaryLang || 'en')
  const [twoStep, setTwoStep] = useState(
    persisted.current.useTwoStep !== undefined ? persisted.current.useTwoStep : true,
  )
  const [models, setModels] = useState<ModelInfo[]>(persisted.current.models || [])
  const [whisperModel, setWhisperModel] = useState(persisted.current.whisperModel || 'base')
  const [hfEndpoint, setHfEndpoint] = useState(persisted.current.hfEndpoint || '')
  const [botConfigs, setBotConfigs] = useState<Record<string, BotPlatformConfig>>(
    persisted.current.botConfigs || {},
  )
  const [fetchStatus, setFetchStatus] = useState<FetchStatus>({ cls: '', msg: '' })
  const [whisperReady, setWhisperReady] = useState(false)
  const [whisperError, setWhisperError] = useState<string | null>(null)

  const configured = Boolean(apiKey.trim() && baseUrl.trim() && model.trim())

  /* Persist settings whenever they change. */
  useEffect(() => {
    const s: Persisted = { baseUrl, apiKey, model, summaryLang, useTwoStep: twoStep, models, whisperModel, hfEndpoint, botConfigs }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    } catch {
      /* ignore */
    }
  }, [baseUrl, apiKey, model, summaryLang, twoStep, models, whisperModel, hfEndpoint, botConfigs])

  const fetchModels = useCallback(
    async (silent = false) => {
      const url = baseUrl.trim().replace(/\/$/, '')
      const key = apiKey.trim()
      if (!url || !key) {
        if (!silent) setFetchStatus({ cls: 'err', msg: t('api_url_required') })
        return
      }
      if (!silent) setFetchStatus({ cls: '', msg: t('fetching_models') })
      try {
        const fd = new FormData()
        fd.append('base_url', url)
        fd.append('api_key', key)
        const data = await api.fetchModels(fd)
        const list = data.data || data.models || []
        setModels(list)
        /* Re-select previously saved model, otherwise default to the first. */
        const saved = persisted.current.model
        if (saved && list.some((m) => m.id === saved)) {
          setModel(saved)
          persisted.current.model = ''
        } else if (list.length > 0) {
          setModel(list[0].id)
        }
        const loaded = t('models_loaded')
        setFetchStatus({
          cls: 'ok',
          msg: typeof loaded === 'function' ? loaded(list.length) : `${list.length} models`,
        })
      } catch (e) {
        setFetchStatus({ cls: 'err', msg: t('models_error') + ': ' + (e as Error).message })
      }
    },
    [baseUrl, apiKey, t],
  )

  /* On first mount, if both base URL and key were persisted, fetch models. */
  const didAutoFetch = useRef(false)
  useEffect(() => {
    if (didAutoFetch.current) return
    didAutoFetch.current = true
    if (persisted.current.baseUrl && persisted.current.apiKey) {
      const id = setTimeout(() => void fetchModels(true), 400)
      return () => clearTimeout(id)
    }
  }, [fetchModels])

  const refreshWhisperStatus = useCallback(async () => {
    const data = await api.modelStatus()
    if (!data) return false
    setWhisperReady(data.whisper_ready)
    setWhisperError(data.whisper_error)
    return data.whisper_ready
  }, [])

  const refreshInterfaceStatus = useCallback(async () => {
    await Promise.all([
      configured ? fetchModels(true) : Promise.resolve(),
      refreshWhisperStatus(),
    ])
  }, [configured, fetchModels, refreshWhisperStatus])

  /* Whisper model status polling (stops once ready). */
  useEffect(() => {
    let timer: number | undefined
    let cancelled = false
    const poll = async () => {
      const ready = await refreshWhisperStatus()
      if (cancelled) return
      if (ready && timer) {
        clearInterval(timer)
        timer = undefined
      }
    }
    void poll()
    timer = window.setInterval(poll, 15000)
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [refreshWhisperStatus])

  const setBotConfig = useCallback((platform: string, patch: Partial<BotPlatformConfig>) => {
    setBotConfigs((prev) => {
      const current = prev[platform] || { enabled: false, token: '' }
      return { ...prev, [platform]: { ...current, ...patch } }
    })
  }, [])

  const pushBotConfigs = useCallback(() => {
    return api.botsConfigure({
      bots: botConfigs,
      llm: {
        api_key: apiKey.trim(),
        base_url: baseUrl.trim().replace(/\/$/, ''),
        model: model,
        summary_language: summaryLang,
        whisper_model: whisperModel,
      },
    })
  }, [botConfigs, apiKey, baseUrl, model, summaryLang, whisperModel])

  /* 后端只在内存里持有 Bot 配置，重启后会丢失。应用加载时若有启用的 Bot，
     自动重新下发一次，让 Bot 随页面打开而恢复（与浏览器里保存的 API Key 同理）。 */
  const didPushBots = useRef(false)
  useEffect(() => {
    if (didPushBots.current) return
    const hasEnabled = Object.values(persisted.current.botConfigs || {}).some((b) => b?.enabled)
    if (!hasEnabled) return
    didPushBots.current = true
    const id = setTimeout(() => void pushBotConfigs().catch(() => {}), 600)
    return () => clearTimeout(id)
  }, [pushBotConfigs])

  const appendModelFields = useCallback(
    (fd: FormData) => {
      fd.append('summary_language', summaryLang)
      const key = apiKey.trim()
      const url = baseUrl.trim().replace(/\/$/, '')
      if (key) fd.append('api_key', key)
      if (url) fd.append('model_base_url', url)
      if (model) fd.append('model_id', model)
      if (whisperModel) fd.append('whisper_model', whisperModel)
    },
    [summaryLang, apiKey, baseUrl, model, whisperModel],
  )

  return (
    <SettingsContext.Provider
      value={{
        baseUrl, apiKey, model, summaryLang, twoStep, models, whisperModel, hfEndpoint, fetchStatus,
        whisperReady, whisperError, configured,
        setBaseUrl, setApiKey, setModel, setSummaryLang, setTwoStep, setWhisperModel, setHfEndpoint,
        botConfigs, setBotConfig, pushBotConfigs,
        fetchModels, refreshInterfaceStatus, appendModelFields,
      }}
    >
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings(): SettingsValue {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}
