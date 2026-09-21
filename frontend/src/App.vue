<template>
  <div id="app">
    <!-- 仅缓存态势对话页：进入态势图详情页后返回，问答内容/执行面板/滚动位置完整保留 -->
    <router-view v-slot="{ Component }">
      <keep-alive include="SituationMap">
        <component :is="Component" />
      </keep-alive>
    </router-view>
  </div>
</template>

<script setup lang="ts">
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  width: 100%;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
}
</style>
