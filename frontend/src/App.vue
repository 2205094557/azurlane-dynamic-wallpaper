<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="watercolor-bg"></div>
      <div class="watercolor-grain"></div>
      <div class="app-content">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { NConfigProvider, NMessageProvider } from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#4a6fa5',
    primaryColorHover: '#5c82b8',
    primaryColorPressed: '#3f5f8f',
    borderRadius: '16px',
    bodyColor: 'transparent',
    cardColor: '#faf8f5',
    modalColor: '#faf8f5',
    popoverColor: '#fffdfa',
    inputColor: 'rgba(255, 255, 255, 0.6)',
    textColorBase: '#3a3a3a',
    textColor1: '#3a3a3a',
    textColor2: '#4a6fa5',
    textColor3: '#8a8a8a',
    borderColor: 'rgba(74, 111, 165, 0.2)',
    dividerColor: 'rgba(74, 111, 165, 0.16)',
    fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
  },
  Button: {
    borderRadiusSmall: '12px',
    borderRadiusMedium: '16px',
    borderRadiusLarge: '18px',
    fontWeight: '300',
    color: 'rgba(74, 111, 165, 0.8)',
    colorHover: 'rgba(74, 111, 165, 0.92)',
    colorPressed: 'rgba(74, 111, 165, 0.7)',
    textColor: '#fff',
    textColorHover: '#fff',
    textColorPressed: '#fff',
    colorSecondary: 'rgba(74, 111, 165, 0.10)',
    colorSecondaryHover: 'rgba(74, 111, 165, 0.16)',
    colorSecondaryPressed: 'rgba(74, 111, 165, 0.22)',
    textColorSecondary: '#4a6fa5',
    textColorSecondaryHover: '#4a6fa5',
    textColorSecondaryPressed: '#4a6fa5',
    borderSecondary: '1px solid rgba(74, 111, 165, 0.5)',
    borderSecondaryHover: '1px solid rgba(74, 111, 165, 0.65)',
  },
}

</script>
