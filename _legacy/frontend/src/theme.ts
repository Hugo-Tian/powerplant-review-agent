import { theme } from 'antd'
import type { ThemeConfig } from 'antd'

const { darkAlgorithm } = theme

export const appTheme: ThemeConfig = {
  algorithm: darkAlgorithm,
  token: {
    colorPrimary: '#00B4D8',
    colorSuccess: '#52c41a',
    colorWarning: '#fa8c16',
    colorError: '#ff4d4f',
    colorInfo: '#00B4D8',
    colorBgBase: '#0a0a0a',
    colorBgContainer: '#141414',
    colorBgLayout: '#0a0a0a',
    colorBgElevated: '#1a1a1a',
    colorBorder: '#2a2a2a',
    colorBorderSecondary: '#1f1f1f',
    colorText: '#e8e8e8',
    colorTextSecondary: '#c0c0d0',
    colorTextTertiary: '#9898b0',
    borderRadius: 8,
    borderRadiusLG: 12,
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    fontFamilyCode: "'SF Mono', 'Fira Code', 'Consolas', monospace",
    fontSize: 13,
    lineHeight: 1.6,
    controlHeight: 32,
    motionDurationMid: '0.15s',
  },
  components: {
    Layout: {
      siderBg: '#0d0d0d',
      headerBg: '#111111',
      bodyBg: '#0a0a0a',
      triggerBg: '#1a1a1a',
    },
    Menu: {
      darkItemBg: '#0d0d0d',
      darkSubMenuItemBg: '#0d0d0d',
      darkItemSelectedBg: 'rgba(0, 180, 216, 0.12)',
      darkItemSelectedColor: '#00B4D8',
      itemHeight: 40,
    },
    Card: {
      colorBgContainer: '#141414',
      paddingLG: 16,
    },
    Table: {
      colorBgContainer: '#141414',
      headerBg: '#1a1a1a',
      rowHoverBg: '#1f1f1f',
      borderColor: '#2a2a2a',
      headerSplitColor: '#2a2a2a',
      fontSize: 12,
    },
    Tabs: {
      inkBarColor: '#00B4D8',
      itemSelectedColor: '#00B4D8',
      itemHoverColor: '#e8e8e8',
    },
    Progress: {
      defaultColor: '#00B4D8',
    },
    Tag: {
      defaultBg: 'rgba(255,255,255,0.04)',
      defaultColor: '#c0c0d0',
    },
    Statistic: {
      titleFontSize: 12,
      contentFontSize: 24,
    },
    Tooltip: {
      colorBgSpotlight: '#1f1f1f',
    },
  },
}
