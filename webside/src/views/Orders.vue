<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            :placeholder="t('orders.searchKeywordPlaceholder')"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.status"
            :placeholder="t('orders.statusFilterPlaceholder')"
            clearable
            filterable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option v-for="item in orderListStatusFilterOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            :range-separator="t('common.to')"
            :start-placeholder="t('orders.lastTimeStart')"
            :end-placeholder="t('orders.lastTimeEnd')"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.owner_user_id"
            :placeholder="t('orders.ownerFilterPlaceholder')"
            clearable
            filterable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-select
            v-model="globalAccountId"
            :placeholder="t('orders.selectMercariAccount')"
            filterable
            class="sync-account-select"
            :loading="mercariAccountStore.loading"
          >
            <el-option
              v-for="acc in mercariAccountStore.activeAccounts"
              :key="acc.id"
              :label="acc.account_name"
              :value="acc.id"
            />
          </el-select>
          <el-button type="success" :icon="RefreshRight" :loading="syncLoading && syncMode === 'newData'" @click="runSync('newData')">{{ t('orders.updateList') }}</el-button>
          <el-button type="primary" :icon="Refresh" :loading="syncLoading && syncMode === 'statusRefresh'" @click="runSync('statusRefresh')">{{ t('orders.updateStatus') }}</el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 数据分析统计卡片：手机端不展示（与库存管理一致） -->
    <el-card v-if="!isMobile" class="section-card order-stats-wrap" shadow="never" v-loading="statsLoading">
      <el-row :gutter="16" class="stat-row order-stat-row">
        <el-col :xs="12" :sm="12" :md="8" :lg="4" v-for="card in orderStatCards" :key="card.label">
          <div
            class="stat-card order-stat-card"
            :class="card.cardClass"
            :style="{ borderTopColor: card.color }"
          >
            <div class="stat-icon" :style="{ background: card.color + '20', color: card.color }">
              <el-icon size="22"><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value-row">
                <span class="stat-value" :class="card.valueClass">{{ card.display }}</span>
                <span class="stat-today">{{ t('orders.todayAddedSuffix', { count: card.todayDisplay }) }}</span>
              </div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        ref="orderTableRef"
        :data="displayList"
        v-loading="loading"
        stripe
        row-key="id"
        :row-class-name="orderRowClassName"
        @expand-change="onOrderExpandChange"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="order-expand-wrap" v-loading="expandState[row.order_no]?.loading">
              <template v-if="expandState[row.order_no]?.loaded">
                <el-table
                  v-if="(expandState[row.order_no]?.rows || []).length"
                  :data="outboundLinesForExpand(row.order_no)"
                  size="small"
                  border
                  class="order-expand-inner-table"
                  :row-class-name="outboundLineRowClassName"
                >
                  <el-table-column :label="t('common.type')" width="80" align="center">
                    <template #default="{ row: line }">
                      {{ outboundLineKindLabel(line) }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.identifier')" min-width="120" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ formatOutboundManagementId(line) }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.inventoryId')" width="88" align="center">
                    <template #default="{ row: line }">
                      {{ line.inventory_id != null ? line.inventory_id : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.inventoryName')" prop="inventory_name" min-width="140" show-overflow-tooltip />
                  <el-table-column :label="t('orders.ownership')" width="110" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      <span :class="{ 'order-owner-unmatched-text': isOutboundLineOwnerUnmatched(line) }">
                        {{ line.inventory_owner_name || '—' }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.warehouse')" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.warehouse_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.shelf')" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.shelfCode')" width="100" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_code || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.currentStock')" width="96" align="center">
                    <template #default="{ row: line }">
                      {{ line.stock_quantity != null ? line.stock_quantity : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.orderQty')" prop="quantity" width="96" align="center" />
                  <el-table-column :label="t('orders.originalPrice')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line)">{{ orderMoneyField(line.original_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.goodsRatio')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line) && line.goods_ratio != null">{{ formatGoodsRatio(line.goods_ratio) }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.ratioPrice')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line)">{{ orderMoneyField(line.ratio_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.pendingOutbound')" width="88" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        v-if="Number(outboundPendingQty(line)) > 0"
                        type="warning"
                        size="small"
                      >
                        {{ outboundPendingQty(line) }}
                      </el-tag>
                      <span v-else class="cell-dash">0</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.status')" width="90" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        :type="Number(line?.is_stocked_out || 0) === 1 ? 'success' : 'info'"
                        size="small"
                      >
                        {{ Number(line?.is_stocked_out || 0) === 1 ? t('orders.stockedOut') : t('orders.pendingStockOut') }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.operate')" :width="isAdminUser ? 232 : 168" align="center">
                    <template #default="{ row: line }">
                      <div class="order-outbound-actions">
                        <el-button
                          size="small"
                          type="warning"
                          plain
                          @click="openBindOutboundInventoryDialog(row, line)"
                        >
                          {{ t('common.edit') }}
                        </el-button>
                        <el-button
                          v-if="isAdminUser"
                          size="small"
                          type="primary"
                          plain
                          :disabled="!outboundLineHasBoundInventory(line)"
                          @click="openConvertOwnerDialog(row, line)"
                        >
                          {{ t('orders.convertOwner') }}
                        </el-button>
                        <el-popconfirm
                          :title="t('orders.confirmStockOut')"
                          :confirm-button-text="t('common.confirm')"
                          :cancel-button-text="t('common.cancel')"
                          @confirm="stockOutLine(row, line)"
                        >
                          <template #reference>
                            <el-button
                              size="small"
                              type="primary"
                              :loading="lineStockingKey === outboundLineKey(row.order_no, line.id)"
                              :disabled="!canStockOutLine(line)"
                            >
                              {{ t('orders.stockOut') }}
                            </el-button>
                          </template>
                        </el-popconfirm>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-else
                  description=" "
                  class="order-empty-compact"
                >
                  <template #image></template>
                  <template #default>
                    <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
                      <el-button size="small" type="primary" @click="openManualOutboundDialog(row)">
                        {{ t('orders.manualAddOutbound') }}
                      </el-button>
                    </div>
                  </template>
                </el-empty>
                <div class="order-packaging-wrap" v-loading="packagingState[row.order_no]?.loading">
                  <el-table
                    :data="packagingDisplayRows(row.order_no)"
                    size="small"
                    border
                  >
                    <el-table-column :label="t('orders.itemName')" min-width="180" show-overflow-tooltip>
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.item_name || '-') }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.bearer')" min-width="110" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.owner || t('orders.unassigned')) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.quantity')" width="90" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.quantity ?? '-') }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.unitPrice')" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(Number(expense.unit_price || 0)) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.amount')" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(expenseAmount(expense)) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.recordTime')" width="168" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : formatExpenseTs(expense.record_time) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.operate')" width="120" align="center">
                      <template #default="{ row: expense }">
                        <el-button
                          v-if="expense.__placeholder"
                          size="small"
                          type="primary"
                          @click="openPackagingDialog(row)"
                        >
                          {{ t('orders.addPackaging') }}
                        </el-button>
                        <span v-else class="cell-dash">-</span>
                      </template>
                    </el-table-column>
                  </el-table>
                  <div
                    v-if="packagingState[row.order_no]?.loaded"
                    class="order-packaging-total-line"
                  >
                    {{ t('orders.packagingTotal') }}
                    <span class="order-packaging-total-value">
                      {{ Math.round(Number(packagingState[row.order_no]?.total_amount || 0)) }}
                    </span>
                    {{ t('orders.jpy') }}
                  </div>
                </div>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.image')" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="firstThumbUrl(row)"
              class="order-thumb"
              :src="firstThumbUrl(row)"
              :preview-src-list="thumbnailPreviewList(row)"
              preview-teleported
              hide-on-click-modal
              fit="cover"
              referrerpolicy="no-referrer"
              lazy
            >
              <template #error>
                <span class="thumb-fallback">-</span>
              </template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.orderNumber')" prop="order_no" width="150" align="center" header-align="center" />
        <el-table-column :label="t('orders.itemNameCol')" prop="remark" min-width="160" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column :label="t('orders.updateTime')" width="176" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">{{ displayTsLocal(row.order_updated_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('orders.purchaseTime')" width="176" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">{{ displayTsLocal(row.purchase_time) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="110" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.tag || 'info'" size="small" effect="light">
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.amount')" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <span class="amount">{{ Math.round(Number(row.amount || 0)) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.feeShipping')" width="128" align="center" header-align="center">
          <template #default="{ row }">
            <span class="col-fee-ship">{{ formatFeeShippingCell(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.netIncome')" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="orderMoneyField(row.net_income) != null" class="col-net">
              {{ orderMoneyField(row.net_income) }}
            </span>
            <span v-else class="cell-dash">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.operate')" width="156" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="order-row-actions">
              <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
              <el-button
                size="small"
                :loading="refreshingId === row.id"
                @click="refreshOrder(row)"
              >{{ t('common.refresh') }}</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

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
      :title="t('orders.editOrder')"
      width="720px"
      destroy-on-close
      class="order-edit-dialog"
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="140px" class="order-edit-form">
        <el-form-item v-if="form.id != null" :label="t('orders.dbId')">
          <el-input :model-value="String(form.id)" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.orderNumber')" prop="order_no">
          <el-input v-model="form.order_no" :placeholder="t('orders.orderNumberPlaceholder')" maxlength="60" clearable />
        </el-form-item>
        <el-form-item :label="t('orders.orderTime')" prop="order_date">
          <el-date-picker
            v-model="form.order_date"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            :placeholder="t('orders.orderDatePlaceholder')"
            clearable
          />
        </el-form-item>
        <el-form-item :label="t('orders.updateTime')">
          <el-date-picker
            v-model="form.order_updated_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            :placeholder="t('common.optional')"
            clearable
          />
        </el-form-item>
        <el-form-item :label="t('orders.purchaseTime')">
          <el-date-picker
            v-model="form.purchase_time"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            :placeholder="t('common.optional')"
            clearable
          />
        </el-form-item>
        <el-form-item :label="t('orders.sellerId')">
          <el-input v-model="form.data_user" placeholder="data_user（Mercari seller.id）" maxlength="64" clearable />
        </el-form-item>
        <el-form-item :label="t('orders.buyerId')">
          <el-input v-model="form.customer_name" :placeholder="t('orders.buyerIdPlaceholder')" maxlength="30" clearable />
        </el-form-item>
        <el-form-item :label="t('orders.orderStatus')" prop="status">
          <el-select v-model="form.status" filterable style="width: 100%">
            <el-option v-for="item in formOrderStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('orders.amountJpy')" prop="amount">
          <el-input-number v-model="form.amount" :min="1" :precision="0" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('orders.serviceFeeJpy')">
          <el-input-number
            v-model="form.service_fee"
            :precision="0"
            :controls="false"
            style="width: 100%"
            :placeholder="t('orders.optionalInteger')"
          />
        </el-form-item>
        <el-form-item :label="t('orders.netIncomeJpy')">
          <el-input-number
            v-model="form.net_income"
            :precision="0"
            :controls="false"
            style="width: 100%"
            :placeholder="t('orders.optionalInteger')"
          />
        </el-form-item>
        <el-form-item :label="t('orders.carrier')">
          <el-input v-model="form.carrier_display_name" clearable placeholder="carrier_display_name" />
        </el-form-item>
        <el-form-item :label="t('orders.shippingMethod')">
          <el-input v-model="form.request_class_display_name" clearable placeholder="request_class_display_name" />
        </el-form-item>
        <el-form-item :label="t('orders.shippingFeeJpy')">
          <el-input-number
            v-model="form.shipping_fee"
            :precision="0"
            :controls="false"
            style="width: 100%"
            :placeholder="t('orders.optionalInteger')"
          />
        </el-form-item>
        <el-form-item :label="t('orders.trackingNo')">
          <el-input v-model="form.tracking_no" clearable placeholder="tracking_no" />
        </el-form-item>
        <el-form-item :label="t('orders.transactionEvidenceId')">
          <el-input-number
            v-model="form.transaction_evidence_id"
            :precision="0"
            :controls="false"
            style="width: 100%"
            :placeholder="t('orders.transactionEvidenceIdPlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('orders.itemNameCol')">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="remark" />
        </el-form-item>
        <el-form-item :label="t('orders.itemDescription')">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="4000"
            show-word-limit
            placeholder="description（transaction_evidences/get）"
          />
          <div v-if="orderDescriptionMgmtHint" class="form-hint">{{ orderDescriptionMgmtHint }}</div>
        </el-form-item>
        <el-form-item :label="t('orders.thumbnailsJson')">
          <el-input
            v-model="form.thumbnails_text"
            type="textarea"
            :rows="4"
            :placeholder="t('orders.thumbnailsJsonPlaceholder')"
          />
          <div class="form-hint">{{ t('orders.thumbnailsJsonHint') }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="order-dialog-footer">
          <el-popconfirm
            v-if="form.id"
            :title="t('orders.deleteConfirm')"
            @confirm="removeFromDialog"
          >
            <template #reference>
              <el-button type="danger">{{ t('common.delete') }}</el-button>
            </template>
          </el-popconfirm>
          <div class="order-dialog-footer-right">
            <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="manualOutboundDialogVisible"
      :title="t('orders.manualAddOutbound')"
      width="760px"
      destroy-on-close
    >
      <el-form label-width="90px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="manualOutboundForm.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.itemFilter')" class="manual-outbound-inv-filter-item">
          <div class="manual-ob-filter-grid">
            <div class="manual-ob-filter-cell">
              <el-input
                v-model="manualInvFilters.keyword"
                :placeholder="t('orders.searchProductPlaceholder')"
                clearable
                prefix-icon="Search"
                @change="reloadManualInventoryList"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="manualInvFilters.filterCat"
                :placeholder="t('orders.allGameCategories')"
                clearable
                filterable
                style="width: 100%"
                @change="reloadManualInventoryList"
              >
                <el-option v-for="c in manualInvFilters.categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="manualInvFilters.filterWarehousePath"
                :options="manualInvFilters.warehouseCascaderOptions"
                :props="manualInvWarehouseCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.warehouseShelfPlaceholder')"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="manualInvFilters.handleFilterWarehouseChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="manualInvFilters.filterProductTypePath"
                :options="manualInvFilters.productTypeCascaderOptions"
                :props="manualInvProductTypeCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.productType')"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="manualInvFilters.handleFilterProductTypeChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="manualInvFilters.filterOwnerUserId"
                :placeholder="t('orders.allOwners')"
                clearable
                filterable
                style="width: 100%"
                @change="reloadManualInventoryList"
              >
                <el-option
                  v-for="u in manualInvFilters.ownerUsers"
                  :key="u.id"
                  :label="u.display_name || u.username"
                  :value="u.id"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell manual-ob-filter-cell--checkbox">
              <el-checkbox v-model="manualInvFilters.hideNoWarehouseSlot" class="manual-ob-filter-checkbox">
                {{ t('orders.hideNoStock') }}
              </el-checkbox>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('orders.inventoryItem')">
          <div class="manual-ob-line-list" v-loading="manualInventoryLoading">
            <div
              v-for="row in manualOutboundForm.rows"
              :key="row.key"
              class="manual-ob-line-row"
            >
              <el-select
                v-model="row.inventory_id"
                filterable
                clearable
                class="manual-inventory-select"
                style="width: 100%"
                :placeholder="t('orders.selectInventoryProduct')"
                popper-class="manual-inventory-select-popper"
                @change="onManualOutboundRowInventoryChange(row)"
              >
                <el-option
                  v-for="it in rowInventoryOptions(row.key)"
                  :key="it.id"
                  :label="`${it.name || '-'}（${t('orders.ownerLabel')}:${it.owner_user_name || '-'}，${t('orders.stockLabel')}:${Number(it.quantity || 0)}）`"
                  :value="it.id"
                >
                  <div class="manual-option-row">
                    <div
                      v-if="inventoryThumbUrl(it)"
                      class="manual-option-thumb-click"
                      @click.stop
                    >
                      <el-image
                        class="manual-option-thumb"
                        :src="inventoryThumbUrl(it)"
                        :preview-src-list="inventoryPreviewSrcList(it)"
                        :initial-index="0"
                        fit="contain"
                        lazy
                        preview-teleported
                        hide-on-click-modal
                        :z-index="4000"
                        referrerpolicy="no-referrer"
                      />
                    </div>
                    <span v-else class="manual-option-thumb-fallback">-</span>
                    <div class="manual-option-meta">
                      <div class="manual-option-name">{{ it.name || '-' }}</div>
                      <div class="manual-option-sub">{{ t('orders.ownerLabel') }}: {{ it.owner_user_name || '-' }} ｜ {{ t('orders.stockLabel') }}: {{ Number(it.quantity || 0) }}</div>
                    </div>
                  </div>
                </el-option>
              </el-select>
              <el-input-number
                v-model="row.quantity"
                :min="1"
                :max="maxStockForManualRow(row.inventory_id)"
                :precision="0"
                :controls="false"
                class="manual-ob-line-qty"
                :disabled="!row.inventory_id"
              />
              <el-button
                type="danger"
                plain
                circle
                :icon="Minus"
                :title="t('orders.deleteRow')"
                @click="removeManualOutboundRow(row.key)"
              />
            </div>
            <div v-if="!manualOutboundForm.rows.length" class="cell-dash manual-ob-line-empty">
              {{ t('orders.clickAddOutboundHint') }}
            </div>
            <div class="manual-ob-line-add">
              <el-button type="primary" plain :icon="Plus" @click="addManualOutboundRow">
                {{ t('common.add') }}
              </el-button>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualOutboundDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="manualOutboundSaving" @click="submitManualOutbound">
          {{ t('orders.confirmAdd') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="bindOutboundDialogVisible"
      :title="bindOutboundContext.is_stocked_out ? t('orders.bindInventoryEditStockedOut') : t('orders.bindInventory')"
      width="760px"
      destroy-on-close
    >
      <el-alert
        v-if="bindOutboundContext.is_stocked_out"
        type="warning"
        :title="t('orders.bindStockedOutAlert')"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="90px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="bindOutboundContext.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.itemFilter')" class="manual-outbound-inv-filter-item">
          <div class="manual-ob-filter-grid">
            <div class="manual-ob-filter-cell">
              <el-input
                v-model="bindInvFilters.keyword"
                :placeholder="t('orders.searchProductPlaceholder')"
                clearable
                prefix-icon="Search"
                @change="reloadBindInventoryList"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="bindInvFilters.filterCat"
                :placeholder="t('orders.allGameCategories')"
                clearable
                filterable
                style="width: 100%"
                @change="reloadBindInventoryList"
              >
                <el-option v-for="c in bindInvFilters.categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="bindInvFilters.filterWarehousePath"
                :options="bindInvFilters.warehouseCascaderOptions"
                :props="bindInvWarehouseCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.warehouseShelfPlaceholder')"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="bindInvFilters.handleFilterWarehouseChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="bindInvFilters.filterProductTypePath"
                :options="bindInvFilters.productTypeCascaderOptions"
                :props="bindInvProductTypeCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.productType')"
                popper-class="product-type-cascader-popper"
                clearable
                filterable
                @change="bindInvFilters.handleFilterProductTypeChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="bindInvFilters.filterOwnerUserId"
                :placeholder="t('orders.allOwners')"
                clearable
                filterable
                style="width: 100%"
                @change="reloadBindInventoryList"
              >
                <el-option
                  v-for="u in bindInvFilters.ownerUsers"
                  :key="u.id"
                  :label="u.display_name || u.username"
                  :value="u.id"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell manual-ob-filter-cell--checkbox">
              <el-checkbox v-model="bindInvFilters.hideNoWarehouseSlot" class="manual-ob-filter-checkbox">
                {{ t('orders.hideNoStock') }}
              </el-checkbox>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('orders.inventoryItem')">
          <div class="manual-ob-line-list" v-loading="bindInventoryLoading">
            <div class="manual-ob-line-row">
              <el-select
                v-model="bindOutboundForm.inventory_id"
                filterable
                clearable
                class="manual-inventory-select"
                style="width: 100%"
                :placeholder="t('orders.selectInventoryProduct')"
                popper-class="manual-inventory-select-popper"
                @change="onBindOutboundInventoryChange"
              >
                <el-option
                  v-for="it in bindInventoryOptions"
                  :key="it.id"
                  :label="`${it.name || '-'}（${t('orders.ownerLabel')}:${it.owner_user_name || '-'}，${t('orders.stockLabel')}:${Number(it.quantity || 0)}）`"
                  :value="it.id"
                >
                  <div class="manual-option-row">
                <div
                  v-if="inventoryThumbUrl(it)"
                  class="manual-option-thumb-click"
                  @click.stop
                >
                  <el-image
                    class="manual-option-thumb"
                    :src="inventoryThumbUrl(it)"
                    :preview-src-list="inventoryPreviewSrcList(it)"
                    :initial-index="0"
                    fit="contain"
                    lazy
                    preview-teleported
                    hide-on-click-modal
                    :z-index="4000"
                    referrerpolicy="no-referrer"
                  />
                </div>
                <span v-else class="manual-option-thumb-fallback">-</span>
                <div class="manual-option-meta">
                  <div class="manual-option-name">{{ it.name || '-' }}</div>
                  <div class="manual-option-sub">{{ t('orders.ownerLabel') }}: {{ it.owner_user_name || '-' }} ｜ {{ t('orders.stockLabel') }}: {{ Number(it.quantity || 0) }}</div>
                </div>
              </div>
                </el-option>
              </el-select>
              <el-input-number
                v-model="bindOutboundForm.quantity"
                :min="1"
                :max="maxStockForBindRow(bindOutboundForm.inventory_id)"
                :precision="0"
                :controls="false"
                class="manual-ob-line-qty"
                :disabled="!bindOutboundForm.inventory_id"
              />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindOutboundDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="bindOutboundSaving" @click="submitBindOutboundInventory">
          {{ t('orders.confirmBind') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="convertOwnerDialogVisible"
      :title="t('orders.convertOwnerDialogTitle')"
      width="480px"
      destroy-on-close
      append-to-body
    >
      <el-alert
        v-if="convertOwnerContext.is_stocked_out"
        type="info"
        :title="t('orders.convertOwnerStockedOutHint')"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="120px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="convertOwnerContext.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.currentInventory')">
          <el-input
            :model-value="convertOwnerContext.inventory_label || ''"
            disabled
            readonly
          />
        </el-form-item>
        <el-form-item :label="t('orders.currentOwner')">
          <el-input
            :model-value="convertOwnerContext.current_owner_name || '—'"
            disabled
            readonly
          />
        </el-form-item>
        <el-form-item :label="t('inventory.splitQuantity')">
          <el-input :model-value="String(convertOwnerContext.quantity)" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.targetOwner')" required>
          <el-select
            v-model="convertOwnerForm.owner_user_id"
            :placeholder="t('inventory.pleaseSelectOwner')"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
              :disabled="u.id === convertOwnerContext.current_owner_user_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertOwnerDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="convertOwnerSubmitting"
          :disabled="!convertOwnerCanSubmit"
          @click="submitConvertOwner"
        >{{ t('orders.confirmConvertOwner') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="packagingDialogVisible"
      :title="t('orders.addPackagingMaterial')"
      width="520px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="packagingForm.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.packagingName')" required>
          <el-select
            v-model="packagingForm.item_name"
            filterable
            clearable
            style="width: 100%"
            :placeholder="t('orders.packagingItemPlaceholder')"
            @change="onPackagingItemChange"
          >
            <el-option :label="t('orders.noPackaging')" :value="PACKAGING_ITEM_NONE" />
            <el-option
              v-for="item in packagingItemsOptions"
              :key="item.item_name"
              :label="`${item.item_name}（${t('orders.stockLabel')}:${Number(item.quantity || 0)}）`"
              :value="item.item_name"
            />
          </el-select>
        </el-form-item>
        <el-row v-show="isPackagingConcreteItemSelected" :gutter="12">
          <el-col :span="12">
            <el-form-item :label="t('common.quantity')" required>
              <el-input-number
                v-model="packagingForm.quantity"
                :min="1"
                :precision="0"
                :controls="false"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('orders.unitPrice')" required>
              <el-input-number
                v-model="packagingForm.unit_price"
                :min="1"
                :precision="0"
                :controls="false"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item v-show="isPackagingConcreteItemSelected" :label="t('orders.costAmount')">
          <el-input :model-value="String(Math.round(expenseAmount(packagingForm)))" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packagingDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="packagingSubmitting" @click="submitPackagingExpense">
          {{ t('orders.confirmAdd') }}
        </el-button>
      </template>
    </el-dialog>

    <teleport to="body">
      <div
        v-show="syncOverlayVisible"
        class="orders-sync-overlay orders-sync-overlay--dark"
        :class="{ 'orders-sync-overlay--failed': syncOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="orders-sync-overlay__box">
          <el-icon class="is-loading orders-sync-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="orders-sync-overlay__title">{{ syncOverlayTitle }}</div>
          <div class="orders-sync-overlay__step">{{ syncProgressLabel || t('orders.pleaseWait') }}</div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshRight, Refresh, Plus, Minus, Loading } from '@element-plus/icons-vue'
import {
  orderApi,
  mercariApi,
  inventoryApi,
  costExpenseApi,
  costRecordApi,
  authApi,
} from '@/api/index.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'

const { t } = useI18n()
const mercariAccountStore = useMercariAccountStore()
const globalAccountId = computed({
  get: () => mercariAccountStore.selectedId,
  set: (v) => mercariAccountStore.setSelected(v),
})
import {
  useInventoryListApiFilters,
  warehouseCascaderProps,
  productTypeCascaderProps,
} from '@/composables/useInventoryListApiFilters.js'
import {
  localYmdToDayStartTs,
  localYmdToDayEndTs,
  localTodayRangeTs,
} from '@/utils/orderStatsTime.js'
import { decodeMgmtIdCipher, parseMgmtIdsFromDescription } from '@/utils/mgmtIdCipher.js'
import { mercariImageUrlList } from '@/utils/mercariImage.js'

const orderTableRef = ref(null)
/** 当前已展开的主表行（用于筛选变更时折叠，避免展开区与缓存不一致） */
const lastExpandedRows = ref([])
const ownerUsers = ref([])

/** 当前登录用户是否为 admin（仅 admin 可使用「归属转化」） */
const isAdminUser = computed(() => {
  try {
    const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
    return String(u?.username || '').trim() === 'admin'
  } catch {
    return false
  }
})

const loading = ref(false)
const statsLoading = ref(false)
/** 与 Layout / 库存页一致：(max-width: 768px) */
const isMobile = ref(false)
const submitting = ref(false)
/** 正在 Mercari 拉取详情的行 id */
const refreshingId = ref(null)
/** 二级列表：正在执行出库的明细键 order_no:line_id */
const lineStockingKey = ref('')
const manualOutboundDialogVisible = ref(false)
const manualOutboundSaving = ref(false)
const manualInventoryLoading = ref(false)
const manualInventoryOptions = ref([])
const bindOutboundDialogVisible = ref(false)
const bindOutboundSaving = ref(false)
const bindInventoryLoading = ref(false)
const bindInventoryOptions = ref([])
const bindOutboundContext = ref({
  order_no: '',
  line_id: 0,
  is_stocked_out: false,
  original_inventory_id: null,
})
const bindOutboundForm = ref({ inventory_id: null, quantity: 1 })
const convertOwnerDialogVisible = ref(false)
const convertOwnerSubmitting = ref(false)
const convertOwnerContext = ref({
  order_no: '',
  line_id: 0,
  inventory_id: null,
  inventory_label: '',
  current_owner_user_id: null,
  current_owner_name: '',
  quantity: 1,
  is_stocked_out: false,
})
const convertOwnerForm = ref({ owner_user_id: null })
const convertOwnerCanSubmit = computed(() => {
  const oid = convertOwnerForm.value.owner_user_id
  if (oid == null) return false
  if (Number(oid) <= 0) return false
  if (Number(oid) === Number(convertOwnerContext.value.current_owner_user_id)) return false
  return Number(convertOwnerContext.value.line_id || 0) > 0
})
const packagingDialogVisible = ref(false)
const packagingSubmitting = ref(false)
const packagingItemsOptions = ref([])
let _manualObRowKeySeq = 0
function newManualOutboundRowKey() {
  _manualObRowKeySeq += 1
  return `mob-${_manualObRowKeySeq}`
}

const manualOutboundForm = ref({
  order_no: '',
  /** 出库明细行：同一 inventory_id 仅允许一行（与后端 batch 校验一致） */
  rows: [],
})

function scheduleManualInvReload() {
  void reloadManualInventoryList()
}
const manualInvFilters = useInventoryListApiFilters(scheduleManualInvReload)
const manualInvWarehouseCascaderProps = warehouseCascaderProps
const manualInvProductTypeCascaderProps = productTypeCascaderProps

function scheduleBindInvReload() {
  void reloadBindInventoryList()
}
const bindInvFilters = useInventoryListApiFilters(scheduleBindInvReload)
const bindInvWarehouseCascaderProps = warehouseCascaderProps
const bindInvProductTypeCascaderProps = productTypeCascaderProps

async function reloadManualInventoryList() {
  if (!manualOutboundDialogVisible.value) return
  manualInventoryLoading.value = true
  try {
    const res = await inventoryApi.list(
      manualInvFilters.buildInventoryListParams({ in_stock_only: true })
    )
    let next = Array.isArray(res) ? res : []
    const inList = new Set(next.map((x) => Number(x.id)))
    const selectedIds = [
      ...new Set(
        (manualOutboundForm.value.rows || [])
          .map((r) => Number(r?.inventory_id || 0))
          .filter((id) => Number.isFinite(id) && id > 0)
      ),
    ]
    const missing = selectedIds.filter((id) => !inList.has(id))
    if (missing.length) {
      const fetched = await Promise.all(
        missing.map((id) => inventoryApi.get(id).catch(() => null))
      )
      for (const one of fetched) {
        if (one && one.id != null) {
          next.push(one)
          inList.add(Number(one.id))
        }
      }
    }
    manualInventoryOptions.value = next
    const allowed = inList
    for (const row of manualOutboundForm.value.rows || []) {
      const iid = Number(row?.inventory_id || 0)
      if (Number.isFinite(iid) && iid > 0 && !allowed.has(iid)) {
        row.inventory_id = null
        row.quantity = 1
      }
    }
  } finally {
    manualInventoryLoading.value = false
  }
}
async function reloadBindInventoryList() {
  if (!bindOutboundDialogVisible.value) return
  bindInventoryLoading.value = true
  try {
    const res = await inventoryApi.list(
      bindInvFilters.buildInventoryListParams({ in_stock_only: true })
    )
    let next = Array.isArray(res) ? res : []
    const inList = new Set(next.map((x) => Number(x.id)))
    const selectedId = Number(bindOutboundForm.value.inventory_id || 0)
    if (Number.isFinite(selectedId) && selectedId > 0 && !inList.has(selectedId)) {
      const one = await inventoryApi.get(selectedId).catch(() => null)
      if (one && one.id != null) {
        next.push(one)
        inList.add(Number(one.id))
      }
    }
    bindInventoryOptions.value = next
    if (Number.isFinite(selectedId) && selectedId > 0 && !inList.has(selectedId)) {
      bindOutboundForm.value.inventory_id = null
    }
  } finally {
    bindInventoryLoading.value = false
  }
}

const stats = ref({
  total_count: 0,
  sum_amount: 0,
  sum_service_fee: 0,
  sum_shipping_fee: 0,
  sum_net_income: 0,
  sum_packaging: 0,
  today_total_count: 0,
  today_sum_amount: 0,
  today_sum_service_fee: 0,
  today_sum_shipping_fee: 0,
  today_sum_net_income: 0,
  today_sum_packaging: 0,
})

const packagingState = ref({})
/** 包材下拉：与真实库存包材名称隔离，避免重名冲突 */
const PACKAGING_ITEM_NONE = '__PACKAGING_NONE__'
const isPackagingConcreteItemSelected = computed(() => {
  const n = String(packagingForm.value?.item_name || '').trim()
  return Boolean(n && n !== PACKAGING_ITEM_NONE)
})
const packagingForm = ref({
  order_no: '',
  item_name: '',
  quantity: 1,
  unit_price: null,
})

/** 与列表相同条件：keyword、状态、最后时间区间（order_updated_at 优先）；今日副指标为本地当日且仍满足相同 keyword/状态（同上时间口径）。汇总不含 status=cancelled（后端 stats 排除已取消）。 */
const orderStatCards = computed(() => {
  const o = stats.value
  return [
    {
      label: t('dashboard.orderCount'),
      display: o.total_count ?? 0,
      todayDisplay: o.today_total_count ?? 0,
      icon: 'Document',
      color: '#409EFF',
      cardClass: '',
      valueClass: '',
    },
    {
      label: t('dashboard.totalAmount'),
      display: Math.round(Number(o.sum_amount || 0)),
      todayDisplay: Math.round(Number(o.today_sum_amount || 0)),
      icon: 'Money',
      color: '#E6A23C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: t('dashboard.serviceFee'),
      display: Math.round(Number(o.sum_service_fee || 0)),
      todayDisplay: Math.round(Number(o.today_sum_service_fee || 0)),
      icon: 'Histogram',
      color: '#F56C6C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: t('dashboard.shippingFee'),
      display: Math.round(Number(o.sum_shipping_fee || 0)),
      todayDisplay: Math.round(Number(o.today_sum_shipping_fee || 0)),
      icon: 'Box',
      color: '#F56C6C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: t('dashboard.packaging'),
      display: Math.round(Number(o.sum_packaging || 0)),
      todayDisplay: Math.round(Number(o.today_sum_packaging || 0)),
      icon: 'ShoppingCart',
      color: '#909399',
      cardClass: '',
      valueClass: '',
    },
    {
      label: t('dashboard.netIncome'),
      display: Math.round(Number(o.sum_net_income || 0)),
      todayDisplay: Math.round(Number(o.today_sum_net_income || 0)),
      icon: 'TrendCharts',
      color: '#67C23A',
      cardClass: '',
      valueClass: '',
    },
  ]
})

/** 订单行展开：按 order_no 缓存出库明细 */
const expandState = ref({})

const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dateRange = ref([])
const dialogVisible = ref(false)
const formRef = ref()

const filters = ref({ keyword: '', status: '', owner_user_id: null })

/** 与后端 routes.orders ORDER_STATUSES 一致（煤炉） */
const ORDER_STATUS_KEYS = [
  'pending',
  'trading',
  'wait_payment',
  'wait_shipping',
  'wait_review',
  'done',
  'sold_out',
  'cancelled',
  'cancel_request',
]

/** 展示用标签：value 与数据库/API 一致 */
const statusMap = computed(() => ({
  pending:        { label: t('orders.statusPendingHandle'), tag: 'info' },
  trading:        { label: t('orders.statusTrading'), tag: 'warning' },
  wait_payment:   { label: t('orders.statusWaitPayment'), tag: 'warning' },
  wait_shipping:  { label: t('orders.statusPending'), tag: 'warning' },
  wait_review:    { label: t('orders.statusWaitReview'), tag: 'primary' },
  done:           { label: t('orders.statusCompleted'), tag: 'success' },
  sold_out:       { label: t('orders.statusSoldOut'), tag: 'info' },
  cancelled:      { label: t('orders.statusCancelled'), tag: 'info' },
  cancel_request: { label: t('orders.statusCancelRequest'), tag: 'danger' },
}))

/** 列表/统计筛选项：仅四种（与 load 条件一致） */
const LIST_FILTER_STATUS_KEYS = ['wait_shipping', 'wait_review', 'done', 'cancelled']

const orderListStatusFilterOptions = computed(() =>
  LIST_FILTER_STATUS_KEYS.filter((k) => statusMap.value[k]).map((value) => ({
    value,
    label: statusMap.value[value].label,
  }))
)

const orderStatusOptions = computed(() =>
  ORDER_STATUS_KEYS.filter((k) => statusMap.value[k]).map((value) => ({
    value,
    label: statusMap.value[value].label,
  }))
)

/** 编辑弹窗：若库里为旧版手工状态等未在 statusMap 中的值，补一项便于查看与改选 */
const formOrderStatusOptions = computed(() => {
  const base = orderStatusOptions.value
  const cur = form.value?.status
  if (cur && !statusMap.value[cur]) {
    return [...base, { value: cur, label: t('orders.legacyStatusLabel', { status: cur }) }]
  }
  return base
})

// ---- 同步订单（更新列表 / 更新状态 共用，账号选择见工具栏全局下拉）----
const syncLoading = ref(false)
/** newData：增量入库出售中；statusRefresh：库内未完成订单批量刷新（与单行「刷新」相同接口） */
const syncMode = ref('newData')

/** 「更新列表 / 更新状态」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
const syncOverlayVisible = ref(false)
const syncOverlayTitle = ref('')
const syncOverlayFailed = ref(false)
const syncProgressLabel = ref('')
let syncProgressTimer = null

async function runSync(mode = 'newData') {
  if (syncLoading.value) return
  const aid = mercariAccountStore.selectedId
  if (!aid) {
    ElMessage.warning(t('orders.pleaseSelectMercariAccount'))
    return
  }
  const name = mercariAccountStore.selectedAccountName || `#${aid}`
  const actionLabel = mode === 'statusRefresh' ? t('orders.actionBatchUpdateStatus') : t('orders.actionUpdateSellingList')
  try {
    await ElMessageBox.confirm(
      t('orders.confirmSyncMessage', { name, action: actionLabel }),
      t('orders.confirmSyncTitle'),
      { type: 'info', confirmButtonText: t('orders.start'), cancelButtonText: t('common.cancel') },
    )
  } catch {
    return
  }

  const progressJobId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

  let lastConsoleStep = ''
  const consoleTag = mode === 'statusRefresh' ? '[更新状态]' : '[更新列表]'
  async function pollSyncProgress() {
    try {
      const pr = await mercariApi.getSyncProgress(progressJobId)
      const d = pr?.data
      const zh = d?.label_zh
      if (zh) {
        syncProgressLabel.value = zh
        if (zh !== lastConsoleStep) {
          lastConsoleStep = zh
          console.log(consoleTag, zh)
        }
      }
    } catch {
      /* 轮询失败忽略 */
    }
  }

  syncMode.value = mode
  syncOverlayTitle.value = mode === 'statusRefresh' ? t('orders.updatingStatus') : t('orders.updatingList')
  syncOverlayFailed.value = false
  syncProgressLabel.value = t('orders.connectingServer')
  syncOverlayVisible.value = true
  syncLoading.value = true
  await pollSyncProgress()
  syncProgressTimer = setInterval(pollSyncProgress, 400)

  let syncHadError = false
  try {
    const payload = { account_id: aid, progress_job_id: progressJobId }
    if (mode === 'statusRefresh') {
      const res = await mercariApi.batchRefreshInfo(payload)
      const d = res.data || {}
      const failed = d.failed?.length ?? 0
      const msg = t('orders.statusRefreshDoneMsg', {
        total: d.total ?? 0,
        ok: d.ok ?? 0,
        skipped: d.skipped_no_account ?? 0,
        failed,
      })
      if (failed > 0) ElMessage.warning(msg)
      else ElMessage.success(msg)
    } else {
      const res = await mercariApi.syncNewData(payload)
      const d = res.data || {}
      ElMessage.success(
        t('orders.updateDoneMsg', {
          api: d.api_item_count ?? 0,
          pending: d.pending_new ?? 0,
          inserted: d.inserted ?? 0,
          enriched: d.info_enriched ?? 0,
        })
      )
    }
    load()
    loadStats()
  } catch (e) {
    syncHadError = true
    syncOverlayTitle.value = mode === 'statusRefresh' ? t('orders.updateStatusFailed') : t('orders.updateListFailed')
    syncOverlayFailed.value = true
    const msg = e?.response?.data?.detail || e?.message || t('orders.syncFailed')
    syncProgressLabel.value = String(msg)
  } finally {
    if (syncProgressTimer != null) {
      clearInterval(syncProgressTimer)
      syncProgressTimer = null
    }
    if (syncHadError) {
      await new Promise((r) => setTimeout(r, 1200))
    }
    syncOverlayVisible.value = false
    syncOverlayTitle.value = ''
    syncOverlayFailed.value = false
    syncProgressLabel.value = ''
    syncLoading.value = false
  }
}

function formatLocalDatetime(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 旧数据仅 YYYY-MM-DD 时补全为当天 00:00:00（按 UTC 日界） */
function normalizeDatetimeStr(v) {
  if (!v) return ''
  const s = String(v).trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s} 00:00:00`
  return s
}

const pad2 = (n) => String(n).padStart(2, '0')

/**
 * 将服务端存库的 UTC 时间字符串解析为 Date（本地显示用）
 * 格式 YYYY-MM-DD 或 YYYY-MM-DD HH:mm:ss，均按 UTC 理解
 */
function parseUtcDbToDate(v) {
  if (v == null || v === '') return null
  const s = normalizeDatetimeStr(String(v).trim())
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/)
  if (!m) return null
  const y = +m[1]
  const mo = +m[2] - 1
  const d = +m[3]
  const h = m[4] != null ? +m[4] : 0
  const mi = m[5] != null ? +m[5] : 0
  const sec = m[6] != null ? +m[6] : 0
  return new Date(Date.UTC(y, mo, d, h, mi, sec))
}

function formatLocalWallToStr(dt) {
  if (!dt || Number.isNaN(dt.getTime())) return ''
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())} ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}:${pad2(dt.getSeconds())}`
}

/**
 * 存库值：优先 Unix 秒/毫秒时间戳；否则按旧版 UTC 字符串解析（兼容旧数据）
 */
function tsOrLegacyToDate(v) {
  if (v == null || v === '') return null
  if (typeof v === 'number' && Number.isFinite(v)) {
    if (v > 1e11) return new Date(v)
    if (v > 1e8) return new Date(v * 1000)
    return null
  }
  const s = String(v).trim()
  if (/^\d+\.?\d*$/.test(s)) {
    const n = Number(s)
    if (Number.isFinite(n)) {
      if (n > 1e11) return new Date(n)
      if (n > 1e8) return new Date(n * 1000)
    }
  }
  return parseUtcDbToDate(v)
}

/** 表格：Unix 秒或旧串 -> 本地展示 */
function displayTsLocal(v) {
  if (v == null || v === '') return '-'
  const dt = tsOrLegacyToDate(v)
  if (!dt || Number.isNaN(dt.getTime())) return String(v)
  return formatLocalWallToStr(dt)
}

/** 编辑弹窗：存库值 -> 选择器 value-format 串 */
function tsOrLegacyToLocalForm(v) {
  if (v == null || v === '') return ''
  const dt = tsOrLegacyToDate(v)
  if (!dt || Number.isNaN(dt.getTime())) return normalizeDatetimeStr(String(v))
  return formatLocalWallToStr(dt)
}

/** 保存：本地 datetime 串 -> Unix 秒（null 表示清空可选字段） */
function localFormStringToUnixSec(v) {
  if (!v || !String(v).trim()) return null
  const s = String(v).trim()
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/)
  if (!m) return null
  const y = +m[1]
  const mo = +m[2] - 1
  const d = +m[3]
  const h = m[4] != null ? +m[4] : 0
  const mi = m[5] != null ? +m[5] : 0
  const sec = m[6] != null ? +m[6] : 0
  const local = new Date(y, mo, d, h, mi, sec)
  if (Number.isNaN(local.getTime())) return null
  return Math.floor(local.getTime() / 1000)
}

function optionalNumFromRow(v) {
  if (v == null || v === '') return undefined
  const n = Number(v)
  return Number.isNaN(n) ? undefined : n
}

function numOrNull(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? null : n
}

function optionalIntFromRow(v) {
  if (v == null || v === '') return undefined
  const n = Number.parseInt(String(v), 10)
  return Number.isNaN(n) ? undefined : n
}

function intOrNull(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number.parseInt(String(v), 10)
  return Number.isNaN(n) ? null : n
}

function thumbnailsToFormText(row) {
  const t = row.thumbnails
  if (t == null || t === '') return ''
  if (Array.isArray(t)) return JSON.stringify(t, null, 2)
  if (typeof t === 'string') {
    try {
      const o = JSON.parse(t)
      if (Array.isArray(o)) return JSON.stringify(o, null, 2)
    } catch {
      /* 原样展示 */
    }
    return t
  }
  return String(t)
}

/** 解析为 API 所需的 string[]；空串返回 null 表示清空或未传 */
function parseThumbnailsPayload(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (Array.isArray(p)) {
      const urls = p.map((s) => String(s).trim()).filter(Boolean)
      return urls.length ? urls : null
    }
  } catch {
    /* 按行/逗号拆分 */
  }
  const urls = raw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
  return urls.length ? urls : null
}

/** 手续费 / 快递费 / 净收益列：null 表示无数据，单元格显示「-」；展示为整数（四舍五入） */
function orderMoneyField(v) {
  if (v == null || v === '') return null
  const n = Number(v)
  if (Number.isNaN(n)) return null
  return String(Math.round(n))
}

/** 「手续/快递」合并列：手续费/快递费，缺失一侧显示 - */
function formatFeeShippingCell(row) {
  const tax = orderMoneyField(row.service_fee)
  const ship = orderMoneyField(row.shipping_fee)
  const left = tax != null ? tax : '-'
  const right = ship != null ? ship : '-'
  if (left === '-' && right === '-') return '-'
  return `${left}/${right}`
}

/** thumbnails 为 JSON 字符串或数组时解析为 URL 列表（用于预览）；煤炉 CDN URL 经后端代理返回 */
function thumbnailPreviewList(row) {
  const raw = row.thumbnails
  if (raw == null || raw === '') return []
  if (Array.isArray(raw)) {
    return mercariImageUrlList(
      raw.map((u) => (u != null && u !== '' ? String(u) : '')).filter(Boolean)
    )
  }
  if (typeof raw === 'string') {
    try {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr)) {
        return mercariImageUrlList(
          arr.map((u) => (u != null && u !== '' ? String(u) : '')).filter(Boolean)
        )
      }
    } catch {
      return []
    }
  }
  return []
}

/** thumbnails 为 JSON 字符串或数组时取首张图 URL */
function firstThumbUrl(row) {
  const list = thumbnailPreviewList(row)
  return list.length ? list[0] : ''
}

const createDefaultForm = () => ({
  id: null,
  order_no: '',
  order_date: formatLocalDatetime(),
  order_updated_at: '',
  purchase_time: '',
  data_user: '',
  customer_name: '',
  status: 'pending',
  amount: null,
  service_fee: undefined,
  net_income: undefined,
  carrier_display_name: '',
  request_class_display_name: '',
  shipping_fee: undefined,
  tracking_no: '',
  transaction_evidence_id: undefined,
  remark: '',
  description: '',
  thumbnails_text: '',
})

const form = ref(createDefaultForm())

const rules = computed(() => ({
  order_no: [{ required: true, message: t('orders.orderNumberPlaceholder'), trigger: 'blur' }],
  order_date: [{ required: true, message: t('orders.pleaseSelectOrderTime'), trigger: 'change' }],
  status: [{ required: true, message: t('orders.pleaseSelectOrderStatus'), trigger: 'change' }],
  amount: [{ required: true, message: t('orders.pleaseInputOrderAmount'), trigger: 'blur' }],
}))

const LIST_FILTER_STATUS_SET = new Set(LIST_FILTER_STATUS_KEYS)

function listFilterParams() {
  const params = {}
  if (filters.value.keyword) params.keyword = filters.value.keyword
  const st = (filters.value.status || '').trim()
  if (st && LIST_FILTER_STATUS_SET.has(st)) params.status = st
  const ouid = filters.value.owner_user_id
  if (ouid != null && ouid !== '') {
    const n = Number(ouid)
    if (Number.isFinite(n) && n > 0) params.owner_user_id = n
  }
  if (dateRange.value?.length === 2) {
    const start = localYmdToDayStartTs(dateRange.value[0])
    const end = localYmdToDayEndTs(dateRange.value[1])
    if (start != null) params.start_ts = start
    if (end != null) params.end_ts = end
  }
  return params
}

/** 与列表「商品归属」筛选一致：展开区只请求该归属下的出库行（一单多归属时各显示各的） */
function buildOutboundLinesParams(orderNo) {
  const ono = String(orderNo || '').trim()
  const params = { order_no: ono }
  const p = listFilterParams()
  if (p.owner_user_id != null) params.owner_user_id = p.owner_user_id
  return params
}

async function resetExpandAndCollapseRows() {
  const rows = [...(lastExpandedRows.value || [])]
  expandState.value = {}
  await nextTick()
  const tbl = orderTableRef.value
  if (tbl && typeof tbl.toggleRowExpansion === 'function') {
    rows.forEach((r) => {
      try {
        tbl.toggleRowExpansion(r, false)
      } catch (_) {
        /* ignore */
      }
    })
  }
  lastExpandedRows.value = []
}

function updateViewportState() {
  isMobile.value = window.matchMedia('(max-width: 768px)').matches
}

async function loadStats() {
  if (isMobile.value) return
  statsLoading.value = true
  try {
    const { today_start_ts, today_end_ts } = localTodayRangeTs()
    const res = await orderApi.stats({
      ...listFilterParams(),
      today_start_ts,
      today_end_ts,
    })
    stats.value = {
      total_count: res.total_count ?? 0,
      sum_amount: res.sum_amount ?? 0,
      sum_service_fee: res.sum_service_fee ?? 0,
      sum_shipping_fee: res.sum_shipping_fee ?? 0,
      sum_net_income: res.sum_net_income ?? 0,
      sum_packaging: res.sum_packaging ?? 0,
      today_total_count: res.today_total_count ?? 0,
      today_sum_amount: res.today_sum_amount ?? 0,
      today_sum_service_fee: res.today_sum_service_fee ?? 0,
      today_sum_shipping_fee: res.today_sum_shipping_fee ?? 0,
      today_sum_net_income: res.today_sum_net_income ?? 0,
      today_sum_packaging: res.today_sum_packaging ?? 0,
    }
  } finally {
    statsLoading.value = false
  }
}

async function load() {
  loading.value = true
  const params = { page: page.value, page_size: pageSize.value, ...listFilterParams() }
  const res = await orderApi.list(params).finally(() => {
    loading.value = false
  })
  list.value = res.items || []
  total.value = res.total || 0
}

async function onFilterChange() {
  page.value = 1
  await resetExpandAndCollapseRows()
  load()
  loadStats()
}

async function resetFilters() {
  filters.value = { keyword: '', status: '', owner_user_id: null }
  dateRange.value = []
  page.value = 1
  await resetExpandAndCollapseRows()
  load()
  loadStats()
}

function clearOutboundExpandCache(orderNo) {
  const ono = String(orderNo || '').trim()
  if (!ono) return
  const next = { ...expandState.value }
  delete next[ono]
  expandState.value = next
}

const orderDescriptionMgmtHint = computed(() => {
  const ids = parseMgmtIdsFromDescription(form.value.description)
  if (!ids.length) return ''
  return t('orders.mgmtIdsParsedHint', { ids: ids.join('、') })
})

/** 出库明细「标识」列：mgmt_id 行展示数字；暗号 token 尝试解码 */
function formatOutboundManagementId(line) {
  const raw = String(line?.management_id ?? '').trim()
  if (!raw) return '-'
  const k = String(line?.line_kind || '').trim()
  if (k === 'mgmt_id' || k === 'manual') {
    const n = Number(raw)
    if (Number.isFinite(n) && n > 0) return String(Math.floor(n))
  }
  const decoded = decodeMgmtIdCipher(raw)
  if (decoded != null) return String(decoded)
  return raw
}

/** 出库明细行：后端 line_kind 含 mgmt_id | barcode | bundle_title | manual */
function outboundLineKindLabel(line) {
  const k = line?.line_kind
  if (k === 'bundle_title') return t('orders.kindBundleTitle')
  if (k === 'manual') return t('orders.kindManual')
  if (k === 'barcode') return t('orders.kindBarcode')
  return t('orders.kindMgmtId')
}

/** 后端已写入 goods_ratio / ratio_price 时展示（组合标题或按库存价分摊的手动/管理 ID/条码行） */
function outboundLineShowsRatioPricing(line) {
  return line?.goods_ratio != null || line?.ratio_price != null
}

function outboundLineKey(orderNo, lineId) {
  return `${String(orderNo || '').trim()}:${Number(lineId || 0)}`
}

function expenseAmount(line) {
  return Math.max(0, Number(line?.quantity || 0)) * Math.max(0, Number(line?.unit_price || 0))
}

function formatExpenseTs(ts) {
  if (!ts) return '-'
  const dt = new Date(Number(ts) * 1000)
  if (Number.isNaN(dt.getTime())) return '-'
  return formatLocalWallToStr(dt)
}

function outboundPendingQty(line) {
  return Number(line?.is_stocked_out || 0) === 1 ? 0 : Math.max(0, Number(line?.quantity || 0))
}

function formatGoodsRatio(v) {
  const n = Number(v)
  if (v == null || v === '' || Number.isNaN(n)) return '-'
  return `${(n * 100).toFixed(2)}%`
}

function canStockOutLine(line) {
  if (Number(line?.is_stocked_out || 0) === 1) return false
  if (line?.inventory_id == null) return false
  const qty = Math.max(1, Number(line?.quantity || 1))
  // 出库按钮按“是否仍有待出库”判断，不以前端当前库存拦截。
  // 库存/并发等最终校验交由后端接口处理。
  return qty > 0
}

/** 二级明细是否已关联有效库存 ID（有则禁用「修改」） */
function outboundLineHasBoundInventory(line) {
  const id = line?.inventory_id
  if (id == null || id === '') return false
  const n = Number(id)
  return Number.isFinite(n) && n > 0
}

/** 与在售商品页标红口径一致：未关联库存或库存无商品归属 */
function isOutboundLineOwnerUnmatched(line) {
  if (!line || typeof line !== 'object') return false
  if (!outboundLineHasBoundInventory(line)) return true
  const ouid = line.inventory_owner_user_id
  if (ouid == null || ouid === '') return true
  const n = Number(ouid)
  return !Number.isFinite(n) || n <= 0
}

function sortOutboundLinesDisplay(rows) {
  const arr = Array.isArray(rows) ? [...rows] : []
  arr.sort((a, b) => {
    const aa = isOutboundLineOwnerUnmatched(a) ? 0 : 1
    const ba = isOutboundLineOwnerUnmatched(b) ? 0 : 1
    if (aa !== ba) return aa - ba
    const sa = Number(a?.sort_index) || 0
    const sb = Number(b?.sort_index) || 0
    if (sa !== sb) return sa - sb
    return (Number(a?.id) || 0) - (Number(b?.id) || 0)
  })
  return arr
}

function outboundLinesForExpand(orderNo) {
  const ono = String(orderNo || '').trim()
  if (!ono) return []
  const rows = expandState.value[ono]?.rows
  return sortOutboundLinesDisplay(rows)
}

function outboundLineRowClassName({ row }) {
  return isOutboundLineOwnerUnmatched(row) ? 'on-sale-stock-alert-row' : ''
}

/** 主表行标红：与后端 order_needs_alert 一致（出库/包材/待评价待出库等） */
function isOrderAlertRow(row) {
  if (!row || typeof row !== 'object') return false
  if (Number(row.order_needs_alert ?? 0) === 1) return true
  if (Number(row.has_owner_unmatched_outbound || 0) === 1) return true
  if (Number(row.has_no_bound_outbound || 0) === 1) return true
  if (Number(row.has_packaging_pending || 0) === 1) return true
  if (String(row.status || '').trim() === 'wait_review') {
    return Number(row.pending_outbound_qty || 0) > 0
  }
  return false
}

const displayList = computed(() => {
  const arr = Array.isArray(list.value) ? [...list.value] : []
  arr.sort((a, b) => {
    const aa = isOrderAlertRow(a) ? 0 : 1
    const ba = isOrderAlertRow(b) ? 0 : 1
    if (aa !== ba) return aa - ba
    const ta = Number(a.purchase_time || a.order_updated_at || a.order_date || 0)
    const tb = Number(b.purchase_time || b.order_updated_at || b.order_date || 0)
    if (tb !== ta) return tb - ta
    return (Number(b.id) || 0) - (Number(a.id) || 0)
  })
  return arr
})

function orderRowClassName({ row }) {
  return isOrderAlertRow(row) ? 'on-sale-stock-alert-row' : ''
}

async function reloadOutboundLinesExpand(orderNo) {
  const ono = String(orderNo || '').trim()
  if (!ono) return
  const cur = expandState.value[ono]
  if (!cur?.loaded) return
  expandState.value = { ...expandState.value, [ono]: { ...cur, loading: true } }
  try {
    const res = await orderApi.outboundLines(buildOutboundLinesParams(ono))
    const rows = Array.isArray(res?.items) ? res.items : []
    expandState.value = {
      ...expandState.value,
      [ono]: { loading: false, loaded: true, rows },
    }
  } catch {
    expandState.value = {
      ...expandState.value,
      [ono]: { loading: false, loaded: true, rows: cur.rows || [] },
    }
  }
}

function maxStockForBindRow(inventoryId) {
  const id = Number(inventoryId || 0)
  if (!Number.isFinite(id) || id <= 0) return undefined
  const row = (bindInventoryOptions.value || []).find((x) => Number(x.id) === id)
  if (!row) return undefined
  const q = Number(row.quantity ?? 0)
  return Number.isFinite(q) && q >= 1 ? q : 1
}

function onBindOutboundInventoryChange() {
  const max = maxStockForBindRow(bindOutboundForm.value?.inventory_id)
  const n = Math.max(1, Number(bindOutboundForm.value.quantity || 1))
  if (max != null) {
    bindOutboundForm.value.quantity = Math.min(n, max)
  } else {
    bindOutboundForm.value.quantity = n
  }
}

async function openBindOutboundInventoryDialog(orderRow, line) {
  const orderNo = String(orderRow?.order_no || '').trim()
  const lineId = Number(line?.id || 0)
  if (!orderNo || !lineId) return
  bindOutboundContext.value = {
    order_no: orderNo,
    line_id: lineId,
    is_stocked_out: Number(line?.is_stocked_out || 0) === 1,
    original_inventory_id:
      line?.inventory_id != null && Number.isFinite(Number(line.inventory_id))
        ? Number(line.inventory_id)
        : null,
  }
  const currentInvId =
    line?.inventory_id != null && Number.isFinite(Number(line.inventory_id))
      ? Number(line.inventory_id)
      : null
  bindOutboundForm.value = {
    inventory_id: currentInvId,
    quantity: Math.max(1, Number(line?.quantity || 1)),
  }
  bindInvFilters.resetFilters()
  bindOutboundDialogVisible.value = true
  bindInventoryLoading.value = true
  try {
    await bindInvFilters.loadFilterMetadata()
    await reloadBindInventoryList()
  } catch {
    bindInventoryOptions.value = []
  } finally {
    bindInventoryLoading.value = false
  }
}

function openConvertOwnerDialog(orderRow, line) {
  const orderNo = String(orderRow?.order_no || '').trim()
  const lineId = Number(line?.id || 0)
  if (!orderNo || !lineId) return
  if (!outboundLineHasBoundInventory(line)) {
    ElMessage.warning(t('orders.convertOwnerNeedBound'))
    return
  }
  const invId = Number(line?.inventory_id || 0)
  const invName = String(line?.inventory_name || '').trim() || '-'
  convertOwnerContext.value = {
    order_no: orderNo,
    line_id: lineId,
    inventory_id: invId,
    inventory_label: `${invId} · ${invName}`,
    current_owner_user_id:
      line?.inventory_owner_user_id != null
        ? Number(line.inventory_owner_user_id)
        : null,
    current_owner_name: String(line?.inventory_owner_name || '').trim(),
    quantity: Math.max(1, Number(line?.quantity || 1)),
    is_stocked_out: Number(line?.is_stocked_out || 0) === 1,
  }
  convertOwnerForm.value = { owner_user_id: null }
  convertOwnerDialogVisible.value = true
}

async function submitConvertOwner() {
  const orderNo = String(convertOwnerContext.value.order_no || '').trim()
  const lineId = Number(convertOwnerContext.value.line_id || 0)
  const ownerId = Number(convertOwnerForm.value.owner_user_id || 0)
  if (!orderNo || !lineId || ownerId <= 0) return
  convertOwnerSubmitting.value = true
  try {
    const res = await orderApi.convertOutboundLineOwner(lineId, { owner_user_id: ownerId })
    const newInvId = res?.new_inventory_id ?? ''
    ElMessage.success(t('orders.convertOwnerSuccess', { id: newInvId }))
    convertOwnerDialogVisible.value = false
    await reloadOutboundLinesExpand(orderNo)
    await load()
  } finally {
    convertOwnerSubmitting.value = false
  }
}

async function submitBindOutboundInventory() {
  const orderNo = String(bindOutboundContext.value.order_no || '').trim()
  const lineId = Number(bindOutboundContext.value.line_id || 0)
  const invId = Number(bindOutboundForm.value.inventory_id || 0)
  if (!orderNo || !lineId) return
  if (!Number.isFinite(invId) || invId <= 0) {
    ElMessage.warning(t('orders.pleaseSelectInventory'))
    return
  }
  const max = maxStockForBindRow(invId)
  const qty = Math.max(1, Number(bindOutboundForm.value.quantity || 1))
  if (max != null && qty > max) {
    ElMessage.warning(t('orders.outboundQtyExceedStock', { max }))
    return
  }
  bindOutboundSaving.value = true
  try {
    await orderApi.bindOutboundLineInventory(lineId, { inventory_id: invId, quantity: qty })
    ElMessage.success(t('orders.boundInventory'))
    bindOutboundDialogVisible.value = false
    await reloadOutboundLinesExpand(orderNo)
    await load()
  } finally {
    bindOutboundSaving.value = false
  }
}

async function onOrderExpandChange(row, expandedRows) {
  const exp = Array.isArray(expandedRows) ? expandedRows : []
  lastExpandedRows.value = [...exp]
  const ono = String(row?.order_no || '').trim()
  if (!ono) return
  const opened = exp.some((r) => String(r?.order_no || '').trim() === ono)
  if (!opened) return
  if (expandState.value[ono]?.loaded) return
  expandState.value = {
    ...expandState.value,
    [ono]: { loading: true, loaded: false, rows: [] },
  }
  try {
    const res = await orderApi.outboundLines(buildOutboundLinesParams(ono))
    const rows = Array.isArray(res?.items) ? res.items : []
    expandState.value = {
      ...expandState.value,
      [ono]: { loading: false, loaded: true, rows },
    }
  } catch {
    expandState.value = {
      ...expandState.value,
      [ono]: { loading: false, loaded: true, rows: [] },
    }
  }
  await loadPackagingExpenses(ono)
}

async function loadPackagingItemOptions() {
  const res = await costRecordApi.listPackagingItems()
  packagingItemsOptions.value = Array.isArray(res?.items) ? res.items : []
}

function selectedPackagingMeta(itemName) {
  return (packagingItemsOptions.value || []).find((it) => it.item_name === itemName) || null
}

function onPackagingItemChange(itemName) {
  if (itemName === PACKAGING_ITEM_NONE) {
    packagingForm.value.quantity = 1
    packagingForm.value.unit_price = 0
    return
  }
  const meta = selectedPackagingMeta(itemName)
  if (!meta) return
  packagingForm.value.unit_price = Number(meta.amount || 0)
}

function packagingDisplayRows(orderNo) {
  const rows = packagingState.value?.[String(orderNo || '').trim()]?.rows || []
  if (!rows.length) return [{ __placeholder: true }]
  return [...rows, { __placeholder: true }]
}

async function loadPackagingExpenses(orderNo) {
  const ono = String(orderNo || '').trim()
  if (!ono) return
  packagingState.value = {
    ...packagingState.value,
    [ono]: {
      loading: true,
      loaded: false,
      rows: [],
      total_amount: 0,
    },
  }
  try {
    const res = await costExpenseApi.list({
      order_no: ono,
      type: '包装材料',
      page: 1,
      page_size: 200,
    })
    const rows = Array.isArray(res?.items) ? res.items : []
    const totalAmount = rows.reduce((sum, it) => sum + expenseAmount(it), 0)
    packagingState.value = {
      ...packagingState.value,
      [ono]: {
        loading: false,
        loaded: true,
        rows,
        total_amount: totalAmount,
      },
    }
  } catch {
    packagingState.value = {
      ...packagingState.value,
      [ono]: {
        loading: false,
        loaded: true,
        rows: [],
        total_amount: 0,
      },
    }
  }
}

function openPackagingDialog(orderRow) {
  const orderNo = String(orderRow?.order_no || '').trim()
  if (!orderNo) return
  packagingForm.value = {
    order_no: orderNo,
    item_name: '',
    quantity: 1,
    unit_price: null,
  }
  packagingDialogVisible.value = true
}

async function submitPackagingExpense() {
  const orderNo = String(packagingForm.value.order_no || '').trim()
  const itemName = String(packagingForm.value.item_name || '').trim()
  const qty = Math.max(1, Number(packagingForm.value.quantity || 1))
  const unitPrice = Math.max(1, Number(packagingForm.value.unit_price || 0))
  if (!orderNo) return
  if (!itemName) {
    ElMessage.warning(t('orders.pleaseSelectPackaging'))
    return
  }
  if (itemName === PACKAGING_ITEM_NONE) {
    packagingSubmitting.value = true
    try {
      await orderApi.waivePackaging({ order_no: orderNo })
      packagingDialogVisible.value = false
      ElMessage.success(t('orders.confirmedNoPackaging'))
      await loadPackagingExpenses(orderNo)
      await load()
    } finally {
      packagingSubmitting.value = false
    }
    return
  }
  if (unitPrice <= 0) {
    ElMessage.warning(t('orders.pleaseInputUnitPrice'))
    return
  }
  packagingSubmitting.value = true
  try {
    await costExpenseApi.create({
      order_no: orderNo,
      item_name: itemName,
      quantity: qty,
      unit_price: unitPrice,
    })
    ElMessage.success(t('orders.packagingAddedDeducted'))
    packagingDialogVisible.value = false
    await loadPackagingExpenses(orderNo)
    await load()
    await loadStats()
  } finally {
    packagingSubmitting.value = false
  }
}

function addManualOutboundRow() {
  manualOutboundForm.value.rows.push({
    key: newManualOutboundRowKey(),
    inventory_id: null,
    quantity: 1,
  })
}

function removeManualOutboundRow(rowKey) {
  const rows = (manualOutboundForm.value.rows || []).filter((r) => r.key !== rowKey)
  manualOutboundForm.value.rows = rows
}

function rowInventoryOptions(rowKey) {
  const rows = manualOutboundForm.value.rows || []
  const otherIds = new Set(
    rows
      .filter((r) => r.key !== rowKey && r.inventory_id != null && r.inventory_id !== '')
      .map((r) => Number(r.inventory_id))
      .filter((id) => Number.isFinite(id) && id > 0)
  )
  return (manualInventoryOptions.value || []).filter((it) => {
    const id = Number(it.id)
    if (!Number.isFinite(id)) return false
    if (otherIds.has(id)) return false
    return true
  })
}

function maxStockForManualRow(inventoryId) {
  const id = Number(inventoryId || 0)
  if (!Number.isFinite(id) || id <= 0) return undefined
  const row = (manualInventoryOptions.value || []).find((x) => Number(x.id) === id)
  if (!row) return undefined
  const q = Number(row.quantity ?? 0)
  return Number.isFinite(q) && q >= 1 ? q : 1
}

function onManualOutboundRowInventoryChange(row) {
  const max = maxStockForManualRow(row?.inventory_id)
  if (max != null) {
    const n = Math.max(1, Number(row.quantity || 1))
    row.quantity = Math.min(n, max)
  } else {
    row.quantity = Math.max(1, Number(row.quantity || 1))
  }
}

async function openManualOutboundDialog(orderRow) {
  const orderNo = String(orderRow?.order_no || '').trim()
  if (!orderNo) return
  manualOutboundForm.value = {
    order_no: orderNo,
    rows: [{ key: newManualOutboundRowKey(), inventory_id: null, quantity: 1 }],
  }
  manualInvFilters.resetFilters()
  manualOutboundDialogVisible.value = true
  manualInventoryLoading.value = true
  try {
    await manualInvFilters.loadFilterMetadata()
    await reloadManualInventoryList()
  } catch {
    manualInventoryOptions.value = []
  } finally {
    manualInventoryLoading.value = false
  }
}

async function submitManualOutbound() {
  const orderNo = String(manualOutboundForm.value.order_no || '').trim()
  if (!orderNo) return
  const rows = manualOutboundForm.value.rows || []
  const lines = []
  const seen = new Set()
  for (const row of rows) {
    const iid = Number(row?.inventory_id || 0)
    if (!Number.isFinite(iid) || iid <= 0) continue
    if (seen.has(iid)) {
      ElMessage.warning(t('orders.duplicateInventorySelected'))
      return
    }
    seen.add(iid)
    const max = maxStockForManualRow(iid)
    const qty = Math.max(1, Number(row.quantity || 1))
    if (max != null && qty > max) {
      ElMessage.warning(t('orders.outboundQtyExceedStockNamed', { name: inventoryLabelById(iid), max }))
      return
    }
    lines.push({ inventory_id: iid, quantity: qty })
  }
  if (!lines.length) {
    ElMessage.warning(t('orders.pleaseAddAtLeastOneRow'))
    return
  }
  manualOutboundSaving.value = true
  try {
    await orderApi.addManualOutboundLinesBatch({
      order_no: orderNo,
      lines,
    })
    ElMessage.success(t('orders.manualOutboundAdded', { count: lines.length }))
    manualOutboundDialogVisible.value = false
    clearOutboundExpandCache(orderNo)
    await load()
  } finally {
    manualOutboundSaving.value = false
  }
}

function inventoryLabelById(iid) {
  const row = (manualInventoryOptions.value || []).find((x) => Number(x.id) === Number(iid))
  if (!row) return t('orders.inventoryNumberFallback', { id: iid })
  return `${row.name || '-'}（${t('orders.stockLabel')}:${Number(row.quantity || 0)}）`
}

function inventoryThumbUrl(row) {
  const f = String(row?.image_front || '').trim()
  if (f) return f
  const i = String(row?.image || '').trim()
  return i || ''
}

/** 下拉项内点击图片预览：正 / 背（与列表缩略图同源，去重） */
function inventoryPreviewSrcList(row) {
  const front = String(row?.image_front || '').trim()
  const back = String(row?.image_back || '').trim()
  const legacy = String(row?.image || '').trim()
  const primary = front || legacy
  const out = []
  if (primary) out.push(primary)
  if (back && !out.includes(back)) out.push(back)
  return out
}

async function stockOutLine(orderRow, line) {
  const orderNo = String(orderRow?.order_no || '').trim()
  const lineId = Number(line?.id || 0)
  if (!orderNo || !lineId) return
  if (!canStockOutLine(line)) return
  const k = outboundLineKey(orderNo, lineId)
  lineStockingKey.value = k
  try {
    await orderApi.stockOutOutboundLine(lineId, {})
    ElMessage.success(t('inventory.outboundSuccess'))
    const cur = expandState.value[orderNo]
    if (cur?.loaded) {
      const nextRows = (cur.rows || []).map((r) => {
        if (Number(r.id) !== lineId) return r
        const deducted = Number(r.stock_deducted || 0) === 1
        const newStock = deducted
          ? Number(r.stock_quantity || 0)
          : Math.max(0, Number(r.stock_quantity || 0) - Math.max(1, Number(r.quantity || 1)))
        return {
          ...r,
          is_stocked_out: 1,
          stock_quantity: newStock,
        }
      })
      expandState.value = {
        ...expandState.value,
        [orderNo]: { ...cur, rows: nextRows },
      }
    }
    load()
  } finally {
    lineStockingKey.value = ''
  }
}

function openEdit(row) {
  const dbMoney = row._owner_split_money_db
  form.value = {
    id: row.id,
    order_no: row.order_no || '',
    order_date: tsOrLegacyToLocalForm(row.order_date),
    order_updated_at: tsOrLegacyToLocalForm(row.order_updated_at),
    purchase_time: tsOrLegacyToLocalForm(row.purchase_time),
    data_user: row.data_user != null && row.data_user !== '' ? String(row.data_user) : '',
    customer_name: row.customer_name || '',
    status: row.status || 'pending',
    amount: Number((dbMoney ? dbMoney.amount : row.amount) ?? 0),
    service_fee: optionalNumFromRow(dbMoney ? dbMoney.service_fee : row.service_fee),
    net_income: optionalNumFromRow(dbMoney ? dbMoney.net_income : row.net_income),
    carrier_display_name: row.carrier_display_name || '',
    request_class_display_name: row.request_class_display_name || '',
    shipping_fee: optionalNumFromRow(dbMoney ? dbMoney.shipping_fee : row.shipping_fee),
    tracking_no: row.tracking_no || '',
    transaction_evidence_id: optionalIntFromRow(row.transaction_evidence_id),
    remark: row.remark || '',
    description: row.description || '',
    thumbnails_text: thumbnailsToFormText(row),
  }
  dialogVisible.value = true
}

/** 单行拉取 transaction_evidences/get，更新状态、金额、说明、费用等 */
async function refreshOrder(row) {
  if (!row?.id) return
  const orderNo = String(row.order_no || '').trim()
  if (!orderNo) {
    ElMessage.warning(t('orders.missingOrderNo'))
    return
  }
  const dataUser = row.data_user != null && row.data_user !== '' ? String(row.data_user).trim() : ''
  if (!dataUser) {
    ElMessage.warning(t('orders.missingSellerId'))
    return
  }

  const progressJobId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

  let lastConsoleStep = ''
  async function pollSyncProgress() {
    try {
      const pr = await orderApi.getRefreshProgress(progressJobId)
      const d = pr?.data
      const zh = d?.label_zh
      if (zh) {
        syncProgressLabel.value = zh
        if (zh !== lastConsoleStep) {
          lastConsoleStep = zh
          console.log('[订单刷新]', zh)
        }
      }
    } catch {
      /* 轮询失败忽略 */
    }
  }

  syncOverlayTitle.value = t('orders.refreshingOrder')
  syncOverlayFailed.value = false
  syncProgressLabel.value = t('orders.connectingServer')
  syncOverlayVisible.value = true
  refreshingId.value = row.id
  await pollSyncProgress()
  syncProgressTimer = setInterval(pollSyncProgress, 400)

  let hadError = false
  try {
    await orderApi.refreshInfo({
      order_no: orderNo,
      data_user: dataUser,
      progress_job_id: progressJobId,
    })
    ElMessage.success(t('orders.refreshedFromMercari'))
    clearOutboundExpandCache(orderNo)
    load()
    loadStats()
  } catch (e) {
    hadError = true
    syncOverlayTitle.value = t('orders.refreshFailed')
    syncOverlayFailed.value = true
    const msg = e?.response?.data?.detail || e?.message || t('orders.refreshFailed')
    syncProgressLabel.value = String(msg)
  } finally {
    if (syncProgressTimer != null) {
      clearInterval(syncProgressTimer)
      syncProgressTimer = null
    }
    if (hadError) {
      await new Promise((r) => setTimeout(r, 1200))
    }
    syncOverlayVisible.value = false
    syncOverlayTitle.value = ''
    syncOverlayFailed.value = false
    syncProgressLabel.value = ''
    refreshingId.value = null
  }
}

async function submit() {
  await formRef.value?.validate()
  if (!form.value.id) {
    ElMessage.warning(t('orders.noOrderSelected'))
    return
  }
  const orderDateSec = localFormStringToUnixSec(form.value.order_date)
  if (orderDateSec == null) {
    ElMessage.warning(t('orders.orderDateInvalid'))
    return
  }
  submitting.value = true
  const payload = {
    order_no: String(form.value.order_no || '').trim(),
    order_date: orderDateSec,
    order_updated_at: localFormStringToUnixSec(form.value.order_updated_at),
    purchase_time: localFormStringToUnixSec(form.value.purchase_time),
    data_user: String(form.value.data_user || '').trim() || null,
    customer_name: String(form.value.customer_name || '').trim() || null,
    status: form.value.status,
    amount: Number(form.value.amount || 0),
    service_fee: numOrNull(form.value.service_fee),
    net_income: numOrNull(form.value.net_income),
    carrier_display_name: String(form.value.carrier_display_name || '').trim() || null,
    request_class_display_name: String(form.value.request_class_display_name || '').trim() || null,
    shipping_fee: numOrNull(form.value.shipping_fee),
    tracking_no: String(form.value.tracking_no || '').trim() || null,
    transaction_evidence_id: intOrNull(form.value.transaction_evidence_id),
    remark: String(form.value.remark || '').trim() || null,
    description: String(form.value.description || '').trim() || null,
    thumbnails: parseThumbnailsPayload(form.value.thumbnails_text),
  }
  try {
    await orderApi.update(form.value.id, payload)
    ElMessage.success(t('orders.updateSuccess'))
    clearOutboundExpandCache(payload.order_no)
    dialogVisible.value = false
    load()
    loadStats()
  } finally {
    submitting.value = false
  }
}

async function remove(id) {
  await orderApi.remove(id)
  ElMessage.success(t('inventory.deleteSuccess'))
  expandState.value = {}
  if (list.value.length === 1 && page.value > 1) page.value -= 1
  load()
  loadStats()
}

async function removeFromDialog() {
  const id = form.value.id
  if (!id) return
  await remove(id)
  dialogVisible.value = false
}

watch(isMobile, (mobile) => {
  if (!mobile) loadStats()
})

onMounted(async () => {
  updateViewportState()
  window.addEventListener('resize', updateViewportState)
  mercariAccountStore.ensureLoaded()
  try {
    const users = await authApi.listUsers()
    ownerUsers.value = Array.isArray(users) ? users : []
  } catch {
    ownerUsers.value = []
  }
  load()
  loadStats()
  loadPackagingItemOptions()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportState)
  if (syncProgressTimer != null) {
    clearInterval(syncProgressTimer)
    syncProgressTimer = null
  }
})
</script>

<style scoped>
.search-card {
  margin-bottom: 16px;
  border-radius: 8px;
}
.section-card {
  margin-bottom: 20px;
  border-radius: 8px;
}
.order-stats-wrap {
  margin-bottom: 20px;
}
.order-stat-row {
  margin-bottom: 0;
}
.stat-row {
  margin-bottom: 20px;
}
.stat-row .el-col {
  margin-bottom: 16px;
}
.stat-card {
  background: #131c2f;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 14px;
  border-top: 3px solid;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  border: 1px solid #2a3446;
}
.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 2px;
  line-height: 1.25;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: #ecf2ff;
}
.stat-today {
  font-size: 13px;
  color: #7dd87a;
  font-weight: 500;
  white-space: nowrap;
}
.stat-label {
  font-size: 12px;
  color: #9ba8bf;
  margin-top: 4px;
}
.search-row {
  justify-content: space-between;
}
.search-left-group {
  display: flex;
  align-items: center;
  gap: 20px;
}
.search-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}
.sync-account-select {
  width: 180px;
}
.table-card {
  border-radius: 8px;
}
.order-row-actions {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.amount {
  color: #ffffff;
  font-weight: 600;
}
.col-fee {
  color: #f56c6c;
  font-weight: 600;
}
.col-fee-ship {
  color: #f56c6c;
  font-weight: 600;
  white-space: nowrap;
}
.col-net {
  color: #ffffff;
  font-weight: 500;
}
.cell-dash {
  color: #c0c4cc;
}
.order-thumb {
  width: 48px;
  height: 48px;
  border-radius: 4px;
  display: block;
  cursor: pointer;
}
.order-thumb :deep(.el-image__inner) {
  cursor: pointer;
}
.thumb-fallback {
  color: #909399;
  font-size: 12px;
}
.order-expand-wrap {
  padding: 8px 12px 12px 48px;
  min-height: 48px;
}
.order-owner-unmatched-text {
  color: #ff8a8f;
  font-weight: 600;
}
.order-expand-inner-table :deep(.on-sale-stock-alert-row) {
  --el-table-tr-bg-color: #3a1517;
}
.order-expand-inner-table :deep(.on-sale-stock-alert-row td) {
  background-color: #3a1517 !important;
}
.order-expand-inner-table :deep(.on-sale-stock-alert-row:hover > td) {
  background-color: #4a1a1d !important;
}
.order-expand-inner-table :deep(.on-sale-stock-alert-row td .cell) {
  color: #ffd6d9;
  font-weight: 600;
}
.table-card :deep(.on-sale-stock-alert-row) {
  --el-table-tr-bg-color: #3a1517;
}
.table-card :deep(.on-sale-stock-alert-row td) {
  background-color: #3a1517 !important;
}
.table-card :deep(.on-sale-stock-alert-row:hover > td) {
  background-color: #4a1a1d !important;
}
.table-card :deep(.on-sale-stock-alert-row td .cell) {
  color: #ffd6d9;
  font-weight: 600;
}
.order-expand-inner-table {
  max-width: 100%;
}
.order-outbound-actions {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: center;
  align-items: center;
}
.order-empty-compact :deep(.el-empty) {
  padding: 8px 0;
}
.order-empty-compact :deep(.el-empty__image) {
  display: none;
}
.order-empty-compact :deep(.el-empty__description) {
  display: none;
}
.order-packaging-wrap {
  margin-top: 10px;
}
.order-packaging-total-line {
  margin-top: 8px;
  font-size: 13px;
  color: #cfd8e6;
}
.order-packaging-total-value {
  font-weight: 700;
  color: #e6edf8;
}
.order-packaging-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}
.order-packaging-title {
  font-size: 13px;
  color: #cfd8e6;
  font-weight: 600;
}
.form-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}
.order-edit-dialog :deep(.el-dialog__body) {
  max-height: 72vh;
  overflow-y: auto;
  padding-top: 8px;
}
.order-dialog-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.order-dialog-footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}
.manual-outbound-inv-filter-item :deep(.el-form-item__content) {
  flex: 1;
  min-width: 0;
}
.manual-ob-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px 12px;
  width: 100%;
}
.manual-ob-filter-cell {
  min-width: 0;
}
.manual-ob-filter-cell :deep(.el-input),
.manual-ob-filter-cell :deep(.el-select),
.manual-ob-filter-cell :deep(.el-cascader) {
  width: 100%;
}
.manual-ob-filter-cell--checkbox {
  display: flex;
  align-items: center;
}
.manual-ob-filter-checkbox :deep(.el-checkbox__label) {
  padding-left: 6px;
  white-space: nowrap;
}
.manual-ob-line-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 40px;
}
.manual-ob-line-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px 36px;
  gap: 10px;
  align-items: center;
}
.manual-ob-line-qty {
  width: 100%;
}
.manual-ob-line-qty :deep(.el-input__wrapper) {
  padding-left: 8px;
  padding-right: 8px;
}
.manual-ob-line-add {
  display: flex;
  justify-content: flex-start;
}
.manual-ob-line-empty {
  font-size: 13px;
}
.manual-option-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  align-items: start;
  gap: 12px;
  width: 100%;
  min-width: 0;
  min-height: 156px;
  padding: 8px 0;
}
.manual-option-thumb-click {
  flex-shrink: 0;
  cursor: zoom-in;
  border-radius: 4px;
  align-self: start;
}
.manual-option-thumb-click :deep(.el-image) {
  display: block;
}
.manual-option-thumb {
  width: 140px;
  height: 140px;
  border-radius: 4px;
  flex-shrink: 0;
  background: #111a2c;
  border: 1px solid #2f3950;
}
:deep(.manual-option-thumb .el-image__inner) {
  object-fit: contain;
}
.manual-option-thumb-fallback {
  width: 140px;
  height: 140px;
  border-radius: 4px;
  border: 1px solid #3a4250;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #8b96a8;
  flex-shrink: 0;
}
.manual-option-meta {
  flex: 1;
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.manual-option-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: normal;
  color: #e6edf8 !important;
  font-size: 16px;
  font-weight: 500;
  line-height: 1.3;
}
.manual-option-sub {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: normal;
  color: #9fb0c8 !important;
  font-size: 13px;
  line-height: 1.25;
}
:deep(.manual-inventory-select .el-select__wrapper) {
  min-height: 48px;
}
:global(.manual-inventory-select-popper .el-select-dropdown__wrap) {
  max-height: 500px;
}
:global(.manual-inventory-select-popper.el-popper) {
  min-width: 620px !important;
}
:global(.manual-inventory-select-popper .el-select-dropdown__item) {
  min-height: 156px !important;
  height: auto !important;
  line-height: normal !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  display: block !important;
}
:global(.manual-inventory-select-popper .el-select-dropdown__item > span) {
  display: block;
  width: 100%;
}
:global(.manual-inventory-select-popper .el-select-dropdown__item.selected .manual-option-name) {
  color: #ffffff !important;
}
:global(.manual-inventory-select-popper .el-select-dropdown__item.selected .manual-option-sub) {
  color: #dbe7ff !important;
}
</style>

<!-- 「更新列表 / 更新状态」全屏等待（teleport 到 body，须无 scoped；黑色主题） -->
<style>
.orders-sync-overlay.orders-sync-overlay--dark {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(6px);
}
.orders-sync-overlay--dark .orders-sync-overlay__box {
  min-width: 280px;
  max-width: min(440px, 92vw);
  padding: 28px 32px;
  background: linear-gradient(165deg, #1c1c1f 0%, #121214 100%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  text-align: center;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.04) inset,
    0 20px 50px rgba(0, 0, 0, 0.65);
}
.orders-sync-overlay--dark .orders-sync-overlay__icon {
  color: #94a3b8;
}
.orders-sync-overlay--dark .orders-sync-overlay__title {
  margin-top: 14px;
  font-size: 17px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: 0.02em;
}
.orders-sync-overlay--dark.orders-sync-overlay--failed .orders-sync-overlay__title {
  color: #f87171;
}
.orders-sync-overlay--dark.orders-sync-overlay--failed .orders-sync-overlay__step {
  color: #cbd5e1;
}
.orders-sync-overlay--dark .orders-sync-overlay__step {
  margin-top: 10px;
  font-size: 14px;
  color: #94a3b8;
  line-height: 1.55;
  word-break: break-word;
}
</style>
