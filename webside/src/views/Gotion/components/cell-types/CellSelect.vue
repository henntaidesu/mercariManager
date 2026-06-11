<template>
  <div class="gtn-cell-select" @click.stop @mousedown.stop>
    <el-popover
      :visible="popVisible"
      :width="200"
      placement="bottom-start"
      :teleported="false"
      @update:visible="v => { if (!v) popVisible = false }"
    >
      <template #reference>
        <div class="gtn-cell-display" @click="popVisible = !popVisible">
          <el-tag v-if="modelValue" :color="optionColor(modelValue)" effect="dark" size="small" round>
            {{ modelValue }}
          </el-tag>
          <span v-else class="gtn-empty-hint">{{ t('gotion.cell.clickToSelect') }}</span>
        </div>
      </template>

      <div class="gtn-select-options">
        <div
          v-for="opt in options"
          :key="opt.label"
          class="gtn-select-opt-item"
          :class="{ active: modelValue === opt.label }"
          @click="choose(opt.label)"
        >
          <el-tag :color="opt.color" effect="dark" size="small" round>{{ opt.label }}</el-tag>
        </div>
        <div v-if="modelValue" class="gtn-clear-btn" @click="choose(null)">
          <el-icon><Close /></el-icon> {{ t('common.clear') }}
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const props = defineProps({
  modelValue: { default: null },
  column: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'change'])

const popVisible = ref(false)
const options = computed(() => props.column?.config?.options || [])

function optionColor(label) {
  return options.value.find(o => o.label === label)?.color || '#909399'
}

function choose(val) {
  popVisible.value = false
  emit('update:modelValue', val)
  emit('change', val)
}
</script>

<style scoped>
.gtn-cell-select { width:100%; height:100%; padding:0 6px; cursor:pointer; }
.gtn-cell-display { display:flex; align-items:center; height:100%; }
.gtn-empty-hint { color:#5c6b85; font-size:12px; }
.gtn-select-options { display:flex; flex-direction:column; gap:4px; }
.gtn-select-opt-item { padding:4px 6px; border-radius:4px; cursor:pointer; }
.gtn-select-opt-item:hover { background:#1b2942; }
.gtn-select-opt-item.active { background:rgba(24, 144, 255, 0.15); }
.gtn-clear-btn { display:flex; align-items:center; gap:4px; padding:4px 6px; cursor:pointer; color:#9ba8bf; font-size:12px; border-top:1px solid #28354a; margin-top:4px; }
.gtn-clear-btn:hover { color:#f56c6c; }
</style>
