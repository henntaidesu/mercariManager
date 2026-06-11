<template>
  <!-- 点链接打开网页，双击空白处编辑 -->
  <div class="gtn-cell-url" @dblclick="startEdit" @click.stop>
    <a v-if="!editing && modelValue" :href="modelValue" target="_blank" rel="noopener"
       class="gtn-url-link" @click.stop>{{ modelValue }}</a>
    <span v-else-if="!editing" class="gtn-empty-hint">—</span>
    <el-input
      v-else ref="inputRef"
      v-model="editVal"
      placeholder="https://..."
      size="small"
      @blur="commit"
      @keydown.enter="commit"
      @keydown.esc="cancel"
    />
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
const props = defineProps({ modelValue: { default: '' } })
const emit = defineEmits(['update:modelValue', 'change'])
const editing = ref(false)
const editVal = ref('')
const inputRef = ref(null)

function startEdit() {
  if (editing.value) return // 编辑中点击输入框不重置内容
  editVal.value = props.modelValue || ''
  editing.value = true
  nextTick(() => inputRef.value?.focus())
}
function commit() {
  editing.value = false
  if (editVal.value !== props.modelValue) {
    emit('update:modelValue', editVal.value)
    emit('change', editVal.value)
  }
}
function cancel() { editing.value = false }
</script>

<style scoped>
.gtn-cell-url { width:100%; height:100%; padding:0 6px; cursor:text; overflow:hidden; }
.gtn-url-link { color:#8fb8ff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; display:block; max-width:100%; }
.gtn-url-link:hover { color:#b3d1ff; }
.gtn-empty-hint { color:#5c6b85; }

/* 编辑时隐藏输入框的边框和背景，像直接在单元格里输入；
   同时对冲全局 .el-input { width:180px !important } */
.gtn-cell-url :deep(.el-input) {
  width: 100% !important;
}
.gtn-cell-url :deep(.el-input__wrapper) {
  box-shadow: none !important;
  background: transparent;
  padding: 0;
}
.gtn-cell-url :deep(.el-input__inner) {
  font-size: 13px;
  color: inherit;
  height: 28px;
}
</style>
