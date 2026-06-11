<template>
  <div class="gtn-emoji-picker">
    <div class="gtn-emoji-grid">
      <span
        v-for="emoji in commonEmojis"
        :key="emoji"
        class="gtn-emoji-item"
        :class="{ selected: modelValue === emoji }"
        @click="select(emoji)"
      >{{ emoji }}</span>
    </div>
    <div class="gtn-emoji-input">
      <el-input
        v-model="customInput"
        :placeholder="t('gotion.emoji.customPlaceholder')"
        size="small"
        clearable
        @input="onCustomInput"
      />
    </div>
    <div v-if="modelValue" class="gtn-emoji-clear">
      <el-button size="small" text type="danger" @click="select('')">{{ t('common.clear') }}</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])

const customInput = ref(props.modelValue || '')

const commonEmojis = [
  '📋', '📝', '📊', '📈', '📁', '📂', '🗂️', '📌',
  '🎮', '🎯', '🎲', '🕹️', '🎨', '🎭', '🎵', '🎬',
  '⭐', '🌟', '💫', '✨', '🔥', '💎', '🏆', '🎁',
  '🐉', '🐲', '🦊', '🐺', '🦁', '🐯', '🐻', '🐼',
  '🌸', '🌺', '🌻', '🌹', '🍀', '🌈', '☀️', '🌙',
  '⚔️', '🛡️', '🗡️', '🏹', '🔮', '💊', '🧪', '⚗️',
  '🚀', '🚄', '🚗', '🚲', '✈️', '🛸', '🏰', '🏯',
  '❤️', '💙', '💚', '💛', '💜', '🖤', '🤍', '💖',
]

function select(emoji) {
  customInput.value = emoji
  emit('update:modelValue', emoji)
}

function onCustomInput(val) {
  emit('update:modelValue', val)
}
</script>

<style scoped>
.gtn-emoji-picker { display: flex; flex-direction: column; gap: 8px; width: 100%; }
.gtn-emoji-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 4px;
  max-height: 160px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid #2a3446;
  border-radius: 6px;
  background: #18233a;
}
.gtn-emoji-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 18px;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}
.gtn-emoji-item:hover { background: #1b2942; transform: scale(1.1); }
.gtn-emoji-item.selected { background: rgba(24, 144, 255, 0.2); box-shadow: 0 0 0 2px #1890ff; }
.gtn-emoji-clear { display: flex; justify-content: flex-end; }

/* 对冲全局 .el-input { width:180px !important } */
.gtn-emoji-input :deep(.el-input) {
  width: 100% !important;
}
</style>
