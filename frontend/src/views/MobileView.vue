<template>
  <div class="mobile">
    <div class="mobile-card panel">
      <div class="panel-title">
        <span class="t-left"><span class="bar"></span>移动端预览</span>
      </div>
      <p class="ph-title">移动端预览（第三步交付）</p>
      <p class="ph-desc">
        本步骤只交付桌面端决策中枢。<br />
        移动端外壳、竖屏布局与大字模式将在第三步一并实现。
      </p>
      <div class="ph-actions">
        <button class="btn primary" type="button" @click="go('/')">返回决策中枢</button>
        <button class="btn" type="button" @click="go('/legacy')">查看 V1 大屏</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { navigate } from '../router'

function go(path) {
  navigate(path)
}
</script>

<style scoped>
.mobile {
  min-height: 100%;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.mobile-card { width: 100%; max-width: 420px; padding: 18px 20px; }
.ph-title { margin: 6px 0 8px; font-size: 16px; color: var(--v2-cyan); letter-spacing: 0.06em; }
.ph-desc { margin: 0 0 16px; font-size: 12.5px; line-height: 1.9; color: var(--v2-sub); }
.ph-actions { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
