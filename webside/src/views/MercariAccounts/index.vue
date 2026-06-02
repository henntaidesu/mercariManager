<template>
  <div>
    <el-card shadow="never" class="list-card" v-loading="loading">
      <el-row :gutter="16">
        <el-col :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <div class="add-card">
            <div class="add-card-main" @click="openCreate">
              <el-icon class="add-card-icon"><Plus /></el-icon>
              <span>{{ t('mercariAccounts.addAccount') }}</span>
            </div>
          </div>
        </el-col>
        <el-col v-for="row in list" :key="row.id" :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <el-card shadow="hover" class="account-card">
            <div class="card-header">
              <div class="card-title">{{ row.account_name || '-' }}</div>
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
                {{ row.status === 'active' ? t('mercariAccounts.enabled') : t('mercariAccounts.disabled') }}
              </el-tag>
            </div>
            <div class="card-item"><span>{{ t('mercariAccounts.platformLabel') }}</span>{{ row.value?.x_platform || '-' }}</div>
            <div class="card-item"><span>{{ t('mercariAccounts.sellerIdLabel') }}</span>{{ row.seller_id || '-' }}</div>
            <div class="card-item">
              <span>{{ t('mercariAccounts.autoFetchLabel') }}</span>
              <template v-if="row.is_open === 1 && row.status === 'active'">
                {{ t('mercariAccounts.autoFetchOn') }} · {{ fetchIntervalLabel(row.fetch_interval) }}
                <template v-if="autoFetchTasksLabel(row)">（{{ autoFetchTasksLabel(row) }}）</template>
                <template v-if="pauseWindowLabel(row)"> · {{ t('mercariAccounts.pauseShort') }} {{ pauseWindowLabel(row) }}</template>
              </template>
              <template v-else>{{ t('mercariAccounts.autoFetchOff') }}</template>
            </div>
            <div class="card-item"><span>{{ t('mercariAccounts.remarkLabel') }}</span>{{ row.remark || '-' }}</div>
            <div class="card-actions">
              <el-button
                size="small"
                type="primary"
                plain
                :loading="browserLoadingKeys.has(browserKeyFor(row.id))"
                @click="openBrowserForSavedAccount(row)"
              >{{ t('mercariAccounts.openBrowser') }}</el-button>
              <el-tooltip
                :disabled="row.status === 'active' && !syncLockStore.locked"
                :content="row.status !== 'active' ? t('mercariAccounts.syncDataDisabledHint') : syncLockStore.label"
                placement="top"
              >
                <span>
                  <el-button
                    size="small"
                    type="success"
                    :loading="syncDataIds.has(row.id) || syncLockStore.locked"
                    :disabled="row.status !== 'active' || syncLockStore.locked"
                    @click="openSyncDataDialog(row)"
                  >{{ t('mercariAccounts.syncData') }}</el-button>
                </span>
              </el-tooltip>
              <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load"
          background
          size="small"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('mercariAccounts.editDialogTitle') : t('mercariAccounts.addDialogTitle')"
      width="620px"
      top="6vh"
      destroy-on-close
      class="mercari-dialog"
    >
      <p v-if="!form.id" class="form-intro-tip">
        {{ t('mercariAccounts.formIntroTip') }}
      </p>
      <el-form :model="form" :rules="formRules" ref="formRef" label-width="120px" class="mercari-form">
        <el-divider content-position="left">{{ t('mercariAccounts.sectionBasicInfo') }}</el-divider>
        <el-form-item :label="t('mercariAccounts.accountNameLabel')" prop="account_name">
          <el-input v-model="form.account_name" maxlength="60" clearable />
        </el-form-item>
        <el-form-item :label="t('mercariAccounts.sellerId')" prop="seller_id">
          <el-input
            v-model="form.seller_id"
            maxlength="30"
            clearable
            :placeholder="t('mercariAccounts.sellerIdPlaceholder')"
          >
            <template #append>
              <el-button
                :loading="fetchSellerIdLoading"
                @click="fetchSellerIdViaMitm"
              >{{ t('mercariAccounts.fetch') }}</el-button>
            </template>
          </el-input>
          <p class="seller-id-hint">
            {{ t('mercariAccounts.sellerIdHintPrefix') }}
            <a href="https://jp.mercari.com/mypage/listings" target="_blank" rel="noopener">{{ t('mercariAccounts.sellerIdHintLink') }}</a>
            {{ t('mercariAccounts.sellerIdHintMiddle') }}
            <code>api.mercari.jp/items/get_items</code>
            {{ t('mercariAccounts.sellerIdHintSuffix') }}
          </p>
        </el-form-item>
        <el-form-item :label="t('mercariAccounts.accountStatus')" prop="status">
          <el-select v-model="form.status" style="width: 100%">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('common.remark')">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>

        <el-divider content-position="left">{{ t('mercariAccounts.sectionAutoFetch') }}</el-divider>
        <p class="form-section-hint">
          {{ t('mercariAccounts.autoFetchSectionHint') }}
        </p>
        <el-form-item :label="t('mercariAccounts.autoFetch')" prop="is_open">
          <el-select v-model="form.is_open" style="width: 100%" @change="onAutoFetchToggle">
            <el-option v-for="opt in autoFetchSwitchOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <template v-if="form.is_open === 1">
          <el-form-item :label="t('mercariAccounts.syncItems')">
            <div class="af-task-checks">
              <el-checkbox
                v-model="form.auto_fetch_order_list"
                :true-value="1"
                :false-value="0"
                @change="onAutoFetchTaskChange"
              >{{ t('mercariAccounts.taskOrderList') }}</el-checkbox>
              <el-checkbox
                v-model="form.auto_fetch_on_sale"
                :true-value="1"
                :false-value="0"
                @change="onAutoFetchTaskChange"
              >{{ t('mercariAccounts.taskOnSale') }}</el-checkbox>
              <el-checkbox
                v-model="form.auto_fetch_todos"
                :true-value="1"
                :false-value="0"
                @change="onAutoFetchTaskChange"
              >{{ t('mercariAccounts.taskTodos') }}</el-checkbox>
              <el-checkbox
                v-model="form.auto_fetch_notifications"
                :true-value="1"
                :false-value="0"
                @change="onAutoFetchTaskChange"
              >{{ t('mercariAccounts.taskNotifications') }}</el-checkbox>
              <el-checkbox
                v-model="form.auto_fetch_relist"
                :true-value="1"
                :false-value="0"
              >{{ t('mercariAccounts.taskRelist') }}</el-checkbox>
            </div>
            <p class="af-task-hint">{{ t('mercariAccounts.taskRelistHint') }}</p>
          </el-form-item>
          <el-form-item :label="t('mercariAccounts.interval')" prop="fetch_interval">
            <el-select v-model="form.fetch_interval" style="width: 100%" :placeholder="t('mercariAccounts.intervalPlaceholder')" @change="onAutoFetchTaskChange">
              <el-option v-for="opt in fetchIntervalOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('mercariAccounts.pauseRange')" prop="pause_window">
            <div class="af-pause-row">
              <el-time-picker
                v-model="form.pause_start_time"
                :placeholder="t('mercariAccounts.pauseStartPlaceholder')"
                format="HH:mm"
                value-format="HH:mm"
                :clearable="true"
                class="af-pause-picker"
              />
              <span class="af-pause-sep">{{ t('common.to') }}</span>
              <el-time-picker
                v-model="form.pause_end_time"
                :placeholder="t('mercariAccounts.pauseEndPlaceholder')"
                format="HH:mm"
                value-format="HH:mm"
                :clearable="true"
                class="af-pause-picker"
              />
            </div>
            <p class="af-pause-hint">
              {{ t('mercariAccounts.pauseHint') }}
            </p>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <div class="mercari-dialog-footer">
          <el-popconfirm v-if="form.id" :title="t('mercariAccounts.deleteConfirm')" @confirm="removeFromDialog">
            <template #reference>
              <el-button type="danger" plain>{{ t('common.delete') }}</el-button>
            </template>
          </el-popconfirm>
          <div class="mercari-dialog-footer__actions">
            <el-button
              v-if="!form.id"
              plain
              :loading="browserLoadingKeys.has(MERCARI_PREPARE_KEY)"
              @click="openPrepareLoginBrowser"
            >{{ t('mercariAccounts.openLoginBrowser') }}</el-button>
            <el-button v-if="!form.id" plain @click="onFetchUserInfoPlaceholder">{{ t('mercariAccounts.fetchUserInfo') }}</el-button>
            <el-button
              v-if="form.id"
              type="success"
              plain
              :loading="syncingIds.has(form.id)"
              @click="fetchHistoryFromForm"
            >{{ t('mercariAccounts.fetchHistory') }}</el-button>
            <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="syncDataDialogVisible"
      :title="t('mercariAccounts.syncDataDialogTitle')"
      width="420px"
      destroy-on-close
      class="mercari-dialog"
    >
      <p class="form-section-hint">
        {{ t('mercariAccounts.syncDataDialogHint', { name: syncDataRow?.account_name || '' }) }}
      </p>
      <div class="sync-data-checks">
        <el-checkbox
          v-for="def in SYNC_TASK_DEFS"
          :key="def.key"
          v-model="syncDataChecked[def.key]"
        >{{ t(def.labelKey) }}</el-checkbox>
      </div>
      <template #footer>
        <el-button @click="syncDataDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="confirmSyncData">{{ t('mercariAccounts.syncData') }}</el-button>
      </template>
    </el-dialog>

    <SyncOverlay :state="syncOverlay.state" />
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<style src="./style.global.css"></style>
