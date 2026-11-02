<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind" @click="dismissToast(t.id)">
        <span class="t-mark"></span>
        <span class="t-text">{{ t.text }}</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { toasts, dismissToast } from '../toast'
</script>

<style scoped>
.toast-host {
  position: fixed; right: 18px; bottom: 18px; z-index: 120;
  display: flex; flex-direction: column; gap: 8px; align-items: flex-end;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex; align-items: center; gap: 8px;
  max-width: 420px;
  background: rgba(23, 23, 23, 0.96);
  border: var(--v2-line);
  border-radius: var(--v2-r);
  padding: 8px 12px;
  font-size: 12.5px;
  color: var(--v2-text);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
  cursor: pointer;
}
.toast .t-mark { width: 6px; height: 6px; border-radius: 50%; background: var(--v2-cyan); box-shadow: 0 0 6px var(--v2-cyan); flex: 0 0 auto; }
.toast.ok { border-color: rgba(0, 230, 118, 0.45); }
.toast.ok .t-mark { background: var(--v2-green); box-shadow: 0 0 6px var(--v2-green); }
.toast.err { border-color: rgba(255, 59, 48, 0.5); }
.toast.err .t-mark { background: var(--v2-red); box-shadow: 0 0 6px var(--v2-red); }

.toast-enter-active, .toast-leave-active { transition: opacity 0.18s, transform 0.18s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(14px); }
</style>
