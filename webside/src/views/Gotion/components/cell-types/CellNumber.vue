<template>
  <!-- 双击编辑，单击不响应以便选中复制 -->
  <div class="gtn-cell-number" @dblclick="startEdit" @click.stop>
    <span v-if="!editing" class="gtn-cell-display">{{ modelValue ?? '' }}</span>
    <el-input-number
      v-else
      ref="inputRef"
      v-model="editVal"
      :controls="false"
      size="small"
      @blur="commit"
      @keydown.enter="commit"
      @keydown.esc="cancel"
    />
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
const props = defineProps({ modelValue: { default: null } })
const emit = defineEmits(['update:modelValue', 'change'])
const editing = ref(false)
const editVal = ref(null)
const inputRef = ref(null)

function startEdit() {
  if (editing.value) return // 编辑中点击输入框不重置内容
  editVal.value = props.modelValue
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
.gtn-cell-number { width:100%; height:100%; padding:0 6px; cursor:text; }

/* 编辑时隐藏输入框的边框和背景，像直接在单元格里输入；
   同时对冲全局 .el-input { width:180px !important } */
.gtn-cell-number :deep(.el-input-number) {
  width: 100% !important;
}
.gtn-cell-number :deep(.el-input) {
  width: 100% !important;
}
.gtn-cell-number :deep(.el-input__wrapper) {
  box-shadow: none !important;
  background: transparent;
  padding: 0;
}
.gtn-cell-number :deep(.el-input__inner) {
  font-size: 13px;
  color: inherit;
  height: 28px;
  text-align: left;
}
.gtn-cell-display { font-variant-numeric: tabular-nums; }
</style>
