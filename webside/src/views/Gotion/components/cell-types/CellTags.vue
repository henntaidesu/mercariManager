<template>
  <div class="gtn-cell-tags" @click.stop @mousedown.stop>
    <el-popover
      :visible="popVisible"
      :width="240"
      placement="bottom-start"
      :teleported="false"
      @update:visible="v => { if (!v) popVisible = false }"
    >
      <template #reference>
        <div class="gtn-tags-display" @click="popVisible = !popVisible">
          <el-tag
            v-for="tag in currentTags"
            :key="tag"
            :color="tagColor(tag)"
            effect="dark"
            size="small"
            round
            closable
            @close.stop="removeTag(tag)"
            class="gtn-tag-chip"
          >{{ tag }}</el-tag>
          <span v-if="!currentTags.length" class="gtn-empty-hint">{{ t('gotion.cell.clickToAddTags') }}</span>
        </div>
      </template>

      <div class="gtn-tags-panel">
        <div class="gtn-tags-title">{{ t('gotion.cell.selectTags') }}</div>
        <div class="gtn-tags-opts">
          <div
            v-for="opt in options"
            :key="opt.label"
            class="gtn-tag-opt-item"
            @click="toggleTag(opt.label)"
          >
            <el-tag :color="opt.color" effect="dark" size="small" round>{{ opt.label }}</el-tag>
            <el-icon v-if="currentTags.includes(opt.label)" class="gtn-check-icon"><Check /></el-icon>
          </div>
        </div>
        <div v-if="!options.length" class="gtn-no-opts">{{ t('gotion.cell.noTagOptions') }}</div>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Check } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const props = defineProps({
  modelValue: { default: () => [] },
  column: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'change'])

const popVisible = ref(false)
const options = computed(() => props.column?.config?.options || [])
const currentTags = computed(() => {
  if (!props.modelValue) return []
  return Array.isArray(props.modelValue) ? props.modelValue : [props.modelValue]
})

function tagColor(label) {
  return options.value.find(o => o.label === label)?.color || '#909399'
}

function toggleTag(label) {
  const tags = [...currentTags.value]
  const idx = tags.indexOf(label)
  if (idx === -1) tags.push(label)
  else tags.splice(idx, 1)
  emit('update:modelValue', tags)
  emit('change', tags)
}

function removeTag(label) {
  const tags = currentTags.value.filter(t2 => t2 !== label)
  emit('update:modelValue', tags)
  emit('change', tags)
}
</script>

<style scoped>
.gtn-cell-tags { width:100%; height:100%; padding:0 4px; cursor:pointer; }
.gtn-tags-display { display:flex; flex-wrap:wrap; align-items:center; gap:3px; min-height:28px; padding:2px 0; }
.gtn-tag-chip { cursor:default; }
.gtn-empty-hint { color:#5c6b85; font-size:12px; }
.gtn-tags-title { font-size:12px; color:#9ba8bf; margin-bottom:8px; }
.gtn-tags-opts { display:flex; flex-direction:column; gap:4px; }
.gtn-tag-opt-item { display:flex; align-items:center; justify-content:space-between; padding:4px 6px; border-radius:4px; cursor:pointer; }
.gtn-tag-opt-item:hover { background:#1b2942; }
.gtn-check-icon { color:#67c23a; font-size:14px; }
.gtn-no-opts { color:#5c6b85; font-size:12px; text-align:center; padding:8px 0; }
</style>
