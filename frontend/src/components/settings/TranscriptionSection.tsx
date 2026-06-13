import { useCallback, useEffect, useState } from "react"
import { CheckmarkRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import type { WhisperModelInfo } from "@/lib/types"
import { useSettings } from "@/context/SettingsContext"
import { useI18n } from "@/i18n/I18nContext"

/* ── Transcription (Whisper) section ───────────────────────── */
export function TranscriptionSection() {
  const { t } = useI18n()
  const { whisperModel, setWhisperModel, hfEndpoint, setHfEndpoint } = useSettings()
  const [models, setModels] = useState<WhisperModelInfo[]>([])
  const [downloading, setDownloading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await api.whisperModels()
      setModels(data.data)
    } catch {
      /* leave list empty; section still usable */
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleDownload = useCallback(
    async (size: string) => {
      setError(null)
      setDownloading(size)
      try {
        await api.whisperModelDownload(size, hfEndpoint)
        await refresh()
      } catch (e) {
        setError(t("model_download_failed") + (e as Error).message)
      } finally {
        setDownloading(null)
      }
    },
    [hfEndpoint, refresh, t],
  )

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold">{t("whisper_settings")}</h3>
        <p className="text-xs text-muted-foreground">{t("whisper_offline_hint")}</p>
      </div>

      <div className="space-y-2">
        <Label>{t("whisper_model_label")}</Label>
        <div className="space-y-1.5">
          {models.map((m) => {
            const selected = whisperModel === m.size
            const busy = downloading === m.size
            return (
              <div key={m.size} className="flex h-8 items-center gap-2">
                <button
                  type="button"
                  disabled={!m.downloaded}
                  onClick={() => m.downloaded && setWhisperModel(m.size)}
                  className={`flex h-full flex-1 items-center gap-2 rounded-md border px-2.5 text-left text-sm disabled:opacity-60 ${
                    selected ? "border-primary" : "border-border"
                  }`}
                >
                  {selected && <CheckmarkRegular className="h-3 w-3 text-primary" />}
                  <span className="font-medium">{m.size}</span>
                  <span className="text-xs text-muted-foreground">~{m.approx_mb} MB</span>
                </button>
                {m.builtin ? (
                  <span className="text-xs text-muted-foreground">{t("model_builtin")}</span>
                ) : m.downloaded ? (
                  <span className="text-xs text-muted-foreground">{t("model_downloaded")}</span>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => handleDownload(m.size)}
                    className="h-7 px-2 text-xs"
                  >
                    {busy ? t("downloading_model") : t("download_model")}
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="hf-endpoint">{t("download_source")}</Label>
        <Input
          id="hf-endpoint"
          value={hfEndpoint}
          onChange={(e) => setHfEndpoint(e.target.value)}
          placeholder={t("download_source_ph")}
        />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
