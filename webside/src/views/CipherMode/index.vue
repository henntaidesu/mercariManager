<template>
  <div class="cipher-mode-page">
    <el-card class="cipher-card" shadow="never">
      <template #header>
        <div class="cipher-header">
          <span>管理番号暗号 · 编码模式</span>
          <el-tag size="small" type="info">隐藏页 /x9</el-tag>
        </div>
      </template>

      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="切换后编码与解析都只按所选进制（非兼容解析）。用另一进制生成的旧暗号将无法被解析，请确保现有库存暗号与此设置一致。"
        style="margin-bottom: 16px"
      />

      <el-form label-width="96px" v-loading="loading">
        <el-form-item label="编码方式">
          <el-radio-group v-model="mode">
            <el-radio value="base5">五进制（-=~&lt;&gt;）</el-radio>
            <el-radio value="binary">二进制（◇◆，◇=0 ◆=1）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="预览">
          <div class="cipher-preview">
            <div v-for="s in sampleIds" :key="s" class="cipher-preview-row">
              <span class="cipher-preview-id">id {{ s }}</span>
              <span class="cipher-preview-arrow">→</span>
              <span class="cipher-preview-code">{{ previewEncode(s) }}</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button @click="load">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { configApi } from '@/api/index.js'
import { encodeMgmtId, setCipherMode } from '@/utils/mgmtIdCipher.js'

const mode = ref('base5')
const loading = ref(false)
const saving = ref(false)
const sampleIds = [1, 5, 26, 12345]

function previewEncode(id) {
  try {
    return encodeMgmtId(id, mode.value)
  } catch {
    return '-'
  }
}

async function load() {
  loading.value = true
  try {
    const res = await configApi.getMgmtCipherMode()
    mode.value = res?.mode === 'binary' ? 'binary' : 'base5'
  } catch {
    ElMessage.error('读取编码模式失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await configApi.putMgmtCipherMode(mode.value)
    const applied = res?.mode === 'binary' ? 'binary' : 'base5'
    mode.value = applied
    setCipherMode(applied)
    ElMessage.success(`已切换为${applied === 'binary' ? '二进制 ◇◆' : '五进制 -=~<>'}`)
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.cipher-mode-page {
  padding: 24px;
  display: flex;
  justify-content: center;
}
.cipher-card {
  width: 100%;
  max-width: 560px;
}
.cipher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cipher-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cipher-preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: Consolas, Menlo, monospace;
}
.cipher-preview-id {
  color: var(--el-text-color-secondary);
  min-width: 72px;
}
.cipher-preview-arrow {
  color: var(--el-text-color-placeholder);
}
.cipher-preview-code {
  font-size: 18px;
  letter-spacing: 2px;
}

/* ── 手机端（iOS / Android）────────────────────────────────── */
@media (max-width: 768px) {
  .cipher-mode-page {
    padding: 0;
  }
  /* 标题与模式切换并排在 375px 下放不开 */
  .cipher-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  /* 番号 → 暗号的对照行是等宽字体，暗号本身还带 2px 字距，
     窄屏下要允许折行，否则右边的暗号会被挤出卡片 */
  .cipher-preview-row {
    flex-wrap: wrap;
    gap: 6px 10px;
  }
  .cipher-preview-code {
    font-size: 16px;
    letter-spacing: 1px;
    word-break: break-all;
  }
}
</style>
