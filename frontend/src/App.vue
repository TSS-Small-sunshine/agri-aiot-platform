<template>
  <div class="app-root">
    <MainView v-if="route.path === '/'" />
    <LegacyView v-else-if="route.path === '/legacy'" />
    <MobileView v-else />
    <ToastHost />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import MainView from './views/MainView.vue'
import LegacyView from './views/LegacyView.vue'
import MobileView from './views/MobileView.vue'
import ToastHost from './components/ToastHost.vue'
import { initRouter, route } from './router'

onMounted(initRouter)
</script>

<style scoped>
.app-root { min-height: 100%; }
</style>
