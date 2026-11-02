<template>
  <!-- /mobile：真实移动端界面（手机外壳见 MobileShell.vue） -->
  <div class="mobile">
    <MobileShell />
  </div>
</template>

<script setup>
import MobileShell from '../components/MobileShell.vue'
</script>

<style scoped>
.mobile { min-height: 100%; }
</style>
