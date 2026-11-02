<template>
  <!-- /legacy：V1 大屏整体挂在 .legacy-scope 作用域内，
       theme.css 里 .legacy-scope 已把 V1 的变量与组件外观逐字还原 -->
  <div class="legacy-scope">
    <V1Screen />
  </div>
</template>

<script setup>
import V1Screen from './V1Screen.vue'
</script>
