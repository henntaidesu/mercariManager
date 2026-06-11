<template>
  <div class="gotion-page">
    <TableSidebar ref="sidebarRef" />
    <TableGrid @create-table="sidebarRef?.openCreate?.()" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import TableSidebar from './components/TableSidebar.vue'
import TableGrid from './components/TableGrid.vue'
import { useGotionTableStore } from '@/stores/gotionTable.js'

const sidebarRef = ref(null)
const store = useGotionTableStore()

onMounted(async () => {
  await store.fetchTables()
  // 恢复上次打开的表（localStorage），否则默认第一张
  await store.restoreSelection()
})
</script>

<style scoped>
.gotion-page {
  display: flex;
  height: calc(100vh - 40px);
  min-height: 420px;
  background: #131c2f;
  border: 1px solid #2a3446;
  border-radius: 8px;
  overflow: hidden;
}

@media (max-width: 767px) {
  .gotion-page {
    height: calc(100vh - 80px);
  }
}
</style>
