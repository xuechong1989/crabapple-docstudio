<template>
  <router-view v-slot="{ Component }">
    <keep-alive include="EditPdfPage">
      <component :is="Component" />
    </keep-alive>
  </router-view>
  <ToastContainer />
</template>

<script setup>
import ToastContainer from './components/ToastContainer.vue'
</script>
