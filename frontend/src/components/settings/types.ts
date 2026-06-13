import type { ReactNode } from "react"

/* 每个设置分区都是自包含组件；侧栏与内容区都由 SECTIONS 列表驱动。
   新增配置区时往 SettingsDialog 的 SECTIONS 追加一项即可。 */
export interface SettingsSection {
  id: string
  labelKey: string
  icon: ReactNode
  render: () => ReactNode
}
