<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            placeholder="搜索订单号、备注等"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.status"
            placeholder="待发货 / 待评价 / 已完成 / 已取消"
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
            range-separator="至"
            start-placeholder="购入时间起"
            end-placeholder="购入时间止"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            @change="onFilterChange"
          />
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-button type="success" :icon="RefreshRight" @click="openSyncDialog('newData')">更新列表</el-button>
          <el-button type="primary" :icon="Refresh" @click="openSyncDialog('statusRefresh')">更新状态</el-button>
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
                <span class="stat-today">（今日新增 {{ card.todayDisplay }}）</span>
              </div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        :data="list"
        v-loading="loading"
        stripe
        row-key="id"
        @expand-change="onOrderExpandChange"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="order-expand-wrap" v-loading="expandState[row.order_no]?.loading">
              <template v-if="expandState[row.order_no]?.loaded">
                <el-table
                  v-if="(expandState[row.order_no]?.rows || []).length"
                  :data="expandState[row.order_no].rows"
                  size="small"
                  border
                  class="order-expand-inner-table"
                >
                  <el-table-column label="类型" width="80" align="center">
                    <template #default="{ row: line }">
                      {{ outboundLineKindLabel(line) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="标识" prop="management_id" min-width="120" align="center" show-overflow-tooltip />
                  <el-table-column label="库存ID" width="88" align="center">
                    <template #default="{ row: line }">
                      {{ line.inventory_id != null ? line.inventory_id : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="商品名称" prop="product_name" min-width="140" show-overflow-tooltip />
                  <el-table-column label="商品归属" width="110" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.product_owner_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="仓库" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.warehouse_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="货架" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="货架号" width="100" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_code || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="当前库存" width="96" align="center">
                    <template #default="{ row: line }">
                      {{ line.stock_quantity != null ? line.stock_quantity : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="本单件数" prop="quantity" width="96" align="center" />
                  <el-table-column label="商品原价格" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="line.line_kind === 'bundle_title'">{{ orderMoneyField(line.original_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="货物比例" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="line.line_kind === 'bundle_title' && line.goods_ratio != null">{{ formatGoodsRatio(line.goods_ratio) }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="比例价格" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="line.line_kind === 'bundle_title'">{{ orderMoneyField(line.ratio_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="待出库" width="88" align="center">
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
                  <el-table-column label="状态" width="90" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        :type="Number(line?.is_stocked_out || 0) === 1 ? 'success' : 'info'"
                        size="small"
                      >
                        {{ Number(line?.is_stocked_out || 0) === 1 ? '已出库' : '待出库' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="96" align="center">
                    <template #default="{ row: line }">
                      <el-popconfirm
                        title="确认出库？"
                        confirm-button-text="确认"
                        cancel-button-text="取消"
                        @confirm="stockOutLine(row, line)"
                      >
                        <template #reference>
                          <el-button
                            size="small"
                            type="primary"
                            :loading="lineStockingKey === outboundLineKey(row.order_no, line.id)"
                            :disabled="!canStockOutLine(line)"
                          >
                            出库
                          </el-button>
                        </template>
                      </el-popconfirm>
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
                        手动添加出库
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
                    <el-table-column label="物品名称" min-width="180" show-overflow-tooltip>
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.item_name || '-') }}
                      </template>
                    </el-table-column>
                    <el-table-column label="承担人" min-width="110" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.owner || '未分配') }}
                      </template>
                    </el-table-column>
                    <el-table-column label="数量" prop="quantity" width="90" align="center" />
                    <el-table-column label="单价" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(Number(expense.unit_price || 0)) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="金额" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(expenseAmount(expense)) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="记录时间" width="168" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : formatExpenseTs(expense.record_time) }}
                      </template>
                    </el-table-column>
                    <el-table-column label="操作" width="120" align="center">
                      <template #default="{ row: expense }">
                        <el-button
                          v-if="expense.__placeholder"
                          size="small"
                          type="primary"
                          @click="openPackagingDialog(row)"
                        >
                          添加包装材料
                        </el-button>
                        <span v-else class="cell-dash">-</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="图片" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="firstThumbUrl(row)"
              class="order-thumb"
              :src="firstThumbUrl(row)"
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
        <el-table-column label="订单号" prop="order_no" width="150" align="center" header-align="center" />
        <el-table-column label="商品名称" prop="remark" min-width="160" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column label="最后更新" width="176" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">{{ displayTsLocal(row.order_updated_at) }}</template>
        </el-table-column>
        <el-table-column label="购入时间" width="176" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">{{ displayTsLocal(row.purchase_time) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.tag || 'info'" size="small" effect="light">
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <span class="amount">{{ Math.round(Number(row.amount || 0)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="手续/快递" width="128" align="center" header-align="center">
          <template #default="{ row }">
            <span class="col-fee-ship">{{ formatFeeShippingCell(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="净收益" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="orderMoneyField(row.net_income) != null" class="col-net">
              {{ orderMoneyField(row.net_income) }}
            </span>
            <span v-else class="cell-dash">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="156" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="order-row-actions">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                size="small"
                :loading="refreshingId === row.id"
                @click="refreshOrder(row)"
              >刷新</el-button>
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
          small
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      title="编辑订单"
      width="720px"
      destroy-on-close
      class="order-edit-dialog"
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="140px" class="order-edit-form">
        <el-form-item v-if="form.id != null" label="数据库 ID">
          <el-input :model-value="String(form.id)" disabled />
        </el-form-item>
        <el-form-item label="订单号" prop="order_no">
          <el-input v-model="form.order_no" placeholder="请输入订单号" maxlength="60" clearable />
        </el-form-item>
        <el-form-item label="订单时间" prop="order_date">
          <el-date-picker
            v-model="form.order_date"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            placeholder="order_date（库内 Unix 秒，存库基准）"
            clearable
          />
        </el-form-item>
        <el-form-item label="最后更新">
          <el-date-picker
            v-model="form.order_updated_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            placeholder="可选"
            clearable
          />
        </el-form-item>
        <el-form-item label="购入时间">
          <el-date-picker
            v-model="form.purchase_time"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            style="width: 100%"
            placeholder="可选"
            clearable
          />
        </el-form-item>
        <el-form-item label="卖家ID">
          <el-input v-model="form.data_user" placeholder="data_user（Mercari seller.id）" maxlength="64" clearable />
        </el-form-item>
        <el-form-item label="买家ID">
          <el-input v-model="form.customer_name" placeholder="customer_name（Mercari 买家用户 ID）" maxlength="30" clearable />
        </el-form-item>
        <el-form-item label="订单状态" prop="status">
          <el-select v-model="form.status" filterable style="width: 100%">
            <el-option v-for="item in formOrderStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="订单金额（日元）" prop="amount">
          <el-input-number v-model="form.amount" :min="1" :precision="0" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="手续费（日元）">
          <el-input-number
            v-model="form.service_fee"
            :precision="0"
            :controls="false"
            style="width: 100%"
            placeholder="可选，整数"
          />
        </el-form-item>
        <el-form-item label="净收益（日元）">
          <el-input-number
            v-model="form.net_income"
            :precision="0"
            :controls="false"
            style="width: 100%"
            placeholder="可选，整数"
          />
        </el-form-item>
        <el-form-item label="快递公司">
          <el-input v-model="form.carrier_display_name" clearable placeholder="carrier_display_name" />
        </el-form-item>
        <el-form-item label="寄件方式名">
          <el-input v-model="form.request_class_display_name" clearable placeholder="request_class_display_name" />
        </el-form-item>
        <el-form-item label="快递费（日元）">
          <el-input-number
            v-model="form.shipping_fee"
            :precision="0"
            :controls="false"
            style="width: 100%"
            placeholder="可选，整数"
          />
        </el-form-item>
        <el-form-item label="快递单号">
          <el-input v-model="form.tracking_no" clearable placeholder="tracking_no" />
        </el-form-item>
        <el-form-item label="取引凭证 ID">
          <el-input-number
            v-model="form.transaction_evidence_id"
            :precision="0"
            :controls="false"
            style="width: 100%"
            placeholder="transaction_evidence.id（煤炉）"
          />
        </el-form-item>
        <el-form-item label="商品名称">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="2000" show-word-limit placeholder="remark" />
        </el-form-item>
        <el-form-item label="商品说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="4000"
            show-word-limit
            placeholder="description（transaction_evidences/get）"
          />
        </el-form-item>
        <el-form-item label="缩略图 JSON">
          <el-input
            v-model="form.thumbnails_text"
            type="textarea"
            :rows="4"
            placeholder='JSON 数组，如 ["https://..."]；也可每行一个 URL'
          />
          <div class="form-hint">对应库字段 thumbnails；留空表示不设置（更新时传空可清空）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="order-dialog-footer">
          <el-popconfirm
            v-if="form.id"
            title="确认删除该订单？"
            @confirm="removeFromDialog"
          >
            <template #reference>
              <el-button type="danger">删除</el-button>
            </template>
          </el-popconfirm>
          <div class="order-dialog-footer-right">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 同步订单弹窗 -->
    <el-dialog v-model="syncDialogVisible" :title="syncDialogTitle" width="420px" destroy-on-close>
      <el-form label-width="86px">
        <el-form-item label="煤炉账号">
          <el-select
            v-model="syncAccountId"
            :placeholder="accountOptions.length ? '' : '暂无活跃账号'"
            style="width: 100%"
            :loading="accountsLoading"
          >
            <el-option
              v-for="acc in accountOptions"
              :key="acc.id"
              :label="acc.account_name"
              :value="acc.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="syncDialogVisible = false">取消</el-button>
        <el-button type="success" :loading="syncLoading" @click="confirmSyncDialog">
          {{ syncMode === 'statusRefresh' ? '开始刷新状态' : '开始同步' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="manualOutboundDialogVisible"
      title="手动添加出库"
      width="520px"
      destroy-on-close
    >
      <el-form label-width="90px">
        <el-form-item label="订单号">
          <el-input :model-value="manualOutboundForm.order_no" disabled />
        </el-form-item>
        <el-form-item label="商品归属">
          <el-select
            v-model="manualOwnerFilter"
            clearable
            filterable
            style="width: 100%"
            placeholder="请选择商品归属"
          >
            <el-option
              v-for="owner in manualOwnerOptions"
              :key="owner"
              :label="owner"
              :value="owner"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="库存商品">
          <el-select
            v-model="manualOutboundForm.inventory_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            clearable
            class="manual-inventory-select"
            style="width: 100%"
            placeholder="请选择一个或多个库存商品"
            :loading="manualInventoryLoading"
            popper-class="manual-inventory-select-popper"
          >
            <el-option
              v-for="it in filteredManualInventoryOptions"
              :key="it.id"
              :label="`${it.name || '-'}（归属:${it.owner_user_name || '-'}，库存:${Number(it.quantity || 0)}）`"
              :value="it.id"
            >
              <div class="manual-option-row">
                <el-image
                  v-if="inventoryThumbUrl(it)"
                  class="manual-option-thumb"
                  :src="inventoryThumbUrl(it)"
                  fit="contain"
                  lazy
                  referrerpolicy="no-referrer"
                />
                <span v-else class="manual-option-thumb-fallback">-</span>
                <div class="manual-option-meta">
                  <div class="manual-option-name">{{ it.name || '-' }}</div>
                  <div class="manual-option-sub">归属: {{ it.owner_user_name || '-' }} ｜ 库存: {{ Number(it.quantity || 0) }}</div>
                </div>
              </div>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="各自数量">
          <div style="width:100%; display:flex; flex-direction:column; gap:8px;">
            <div
              v-for="iid in manualOutboundForm.inventory_ids"
              :key="iid"
              style="display:flex; align-items:center; gap:8px;"
            >
              <span style="flex:1; min-width:0; color:#cfd3dc;">
                {{ inventoryLabelById(iid) }}
              </span>
              <el-input-number
                v-model="manualOutboundForm.quantities[iid]"
                :min="1"
                :precision="0"
                :controls="false"
                style="width:120px"
              />
            </div>
            <span v-if="!manualOutboundForm.inventory_ids.length" class="cell-dash">请先选择库存商品</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualOutboundDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="manualOutboundSaving" @click="submitManualOutbound">
          确认添加
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="packagingDialogVisible"
      title="添加包装材料"
      width="520px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="订单号">
          <el-input :model-value="packagingForm.order_no" disabled />
        </el-form-item>
        <el-form-item label="包材名称" required>
          <el-select
            v-model="packagingForm.item_name"
            filterable
            clearable
            style="width: 100%"
            placeholder="请选择库存包材"
            @change="onPackagingItemChange"
          >
            <el-option
              v-for="item in packagingItemsOptions"
              :key="item.item_name"
              :label="`${item.item_name}（库存:${Number(item.quantity || 0)}）`"
              :value="item.item_name"
            />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="数量" required>
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
            <el-form-item label="单价" required>
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
        <el-form-item label="成本金额">
          <el-input :model-value="String(Math.round(expenseAmount(packagingForm)))" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packagingDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="packagingSubmitting" @click="submitPackagingExpense">
          确认添加
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { RefreshRight, Refresh } from '@element-plus/icons-vue'
import { orderApi, mercariApi, meiluAccountApi, inventoryApi, costExpenseApi, costRecordApi } from '@/api/index.js'
import {
  localYmdToDayStartTs,
  localYmdToDayEndTs,
  localTodayRangeTs,
} from '@/utils/orderStatsTime.js'

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
const manualOwnerFilter = ref('')
const packagingDialogVisible = ref(false)
const packagingSubmitting = ref(false)
const packagingItemsOptions = ref([])
const manualOutboundForm = ref({
  order_no: '',
  inventory_ids: [],
  quantities: {},
})
const manualOwnerOptions = computed(() => {
  const out = []
  const seen = new Set()
  for (const it of (manualInventoryOptions.value || [])) {
    const owner = String(it?.owner_user_name || '').trim()
    if (!owner || seen.has(owner)) continue
    seen.add(owner)
    out.push(owner)
  }
  return out.sort((a, b) => a.localeCompare(b, 'zh-CN'))
})
const filteredManualInventoryOptions = computed(() => {
  const owner = String(manualOwnerFilter.value || '').trim()
  if (!owner) return manualInventoryOptions.value || []
  return (manualInventoryOptions.value || []).filter(
    (it) => String(it?.owner_user_name || '').trim() === owner
  )
})
const stats = ref({
  total_count: 0,
  sum_amount: 0,
  sum_service_fee: 0,
  sum_shipping_fee: 0,
  sum_net_income: 0,
  today_total_count: 0,
  today_sum_amount: 0,
  today_sum_service_fee: 0,
  today_sum_shipping_fee: 0,
  today_sum_net_income: 0,
})

const packagingState = ref({})
const packagingForm = ref({
  order_no: '',
  item_name: '',
  quantity: 1,
  unit_price: null,
})

/** 与列表相同条件：keyword、状态、购入时间区间；今日新增为本地当日购入且仍满足相同 keyword/状态。汇总不含 status=cancelled（后端 stats 排除已取消）。 */
const orderStatCards = computed(() => {
  const o = stats.value
  return [
    {
      label: '订单笔数',
      display: o.total_count ?? 0,
      todayDisplay: o.today_total_count ?? 0,
      icon: 'Document',
      color: '#409EFF',
      cardClass: '',
      valueClass: '',
    },
    {
      label: '金额合计',
      display: Math.round(Number(o.sum_amount || 0)),
      todayDisplay: Math.round(Number(o.today_sum_amount || 0)),
      icon: 'Money',
      color: '#E6A23C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: '手续费合计',
      display: Math.round(Number(o.sum_service_fee || 0)),
      todayDisplay: Math.round(Number(o.today_sum_service_fee || 0)),
      icon: 'Histogram',
      color: '#F56C6C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: '快递费合计',
      display: Math.round(Number(o.sum_shipping_fee || 0)),
      todayDisplay: Math.round(Number(o.today_sum_shipping_fee || 0)),
      icon: 'Box',
      color: '#F56C6C',
      cardClass: '',
      valueClass: '',
    },
    {
      label: '净收益合计',
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

const filters = ref({ keyword: '', status: '' })

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
const statusMap = {
  pending:        { label: '待处理', tag: 'info' },
  trading:        { label: '交易中', tag: 'warning' },
  wait_payment:   { label: '待支付', tag: 'warning' },
  wait_shipping:  { label: '待发货', tag: 'warning' },
  wait_review:    { label: '待评价', tag: 'primary' },
  done:           { label: '已完成', tag: 'success' },
  sold_out:       { label: '已售完', tag: 'info' },
  cancelled:      { label: '已取消', tag: 'info' },
  cancel_request: { label: '取消申请中', tag: 'danger' },
}

/** 列表/统计筛选项：仅四种（与 load 条件一致） */
const LIST_FILTER_STATUS_KEYS = ['wait_shipping', 'wait_review', 'done', 'cancelled']

const orderListStatusFilterOptions = computed(() =>
  LIST_FILTER_STATUS_KEYS.filter((k) => statusMap[k]).map((value) => ({
    value,
    label: statusMap[value].label,
  }))
)

const orderStatusOptions = computed(() =>
  ORDER_STATUS_KEYS.filter((k) => statusMap[k]).map((value) => ({
    value,
    label: statusMap[value].label,
  }))
)

/** 编辑弹窗：若库里为旧版手工状态等未在 statusMap 中的值，补一项便于查看与改选 */
const formOrderStatusOptions = computed(() => {
  const base = orderStatusOptions.value
  const cur = form.value?.status
  if (cur && !statusMap[cur]) {
    return [...base, { value: cur, label: `（旧）${cur}` }]
  }
  return base
})

// ---- 同步订单弹窗（更新列表 / 更新状态 共用）----
const syncDialogVisible = ref(false)
const syncLoading = ref(false)
const syncAccountId = ref(null)
/** newData：增量入库出售中；statusRefresh：库内未完成订单批量刷新（与单行「刷新」相同接口） */
const syncMode = ref('newData')
const accountOptions = ref([])
const accountsLoading = ref(false)

const syncDialogTitle = computed(() =>
  syncMode.value === 'statusRefresh'
    ? '批量更新订单状态'
    : '更新出售中列表（增量入库）'
)

async function openSyncDialog(mode = 'newData') {
  syncMode.value = mode
  syncAccountId.value = null
  syncDialogVisible.value = true
  accountsLoading.value = true
  try {
    const res = await meiluAccountApi.list({ page: 1, page_size: 100 })
    accountOptions.value = (res.items || []).filter(a => a.status === 'active')
    const first = accountOptions.value[0]
    syncAccountId.value = first?.id ?? null
  } catch (_) {
    accountOptions.value = []
    syncAccountId.value = null
  } finally {
    accountsLoading.value = false
  }
}

async function confirmSyncDialog() {
  if (syncMode.value === 'statusRefresh') {
    await confirmStatusRefresh()
  } else {
    await confirmSync()
  }
}

async function confirmSync() {
  syncLoading.value = true
  try {
    const payload = {}
    if (syncAccountId.value) payload.account_id = syncAccountId.value
    const res = await mercariApi.syncNewData(payload)
    const d = res.data || {}
    ElMessage.success(
      `更新完成：接口 ${d.api_item_count ?? 0} 条，待入库新单 ${d.pending_new ?? 0} 条，新增 ${d.inserted ?? 0} 条（回填详情 ${d.info_enriched ?? 0} 条）`
    )
    syncDialogVisible.value = false
    load()
    loadStats()
  } finally {
    syncLoading.value = false
  }
}

async function confirmStatusRefresh() {
  syncLoading.value = true
  try {
    const payload = {}
    if (syncAccountId.value) payload.account_id = syncAccountId.value
    const res = await mercariApi.batchRefreshInfo(payload)
    const d = res.data || {}
    const failed = d.failed?.length ?? 0
    const msg = `状态刷新完成：待处理 ${d.total ?? 0} 条，成功 ${d.ok ?? 0}，无对应煤炉账号跳过 ${d.skipped_no_account ?? 0}，失败 ${failed}`
    if (failed > 0) {
      ElMessage.warning(msg)
    } else {
      ElMessage.success(msg)
    }
    syncDialogVisible.value = false
    load()
    loadStats()
  } finally {
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

/** thumbnails 为 JSON 字符串或数组时取首张图 URL */
function firstThumbUrl(row) {
  const raw = row.thumbnails
  if (raw == null || raw === '') return ''
  if (Array.isArray(raw)) {
    const u = raw[0]
    return u ? String(u) : ''
  }
  if (typeof raw === 'string') {
    try {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr) && arr.length > 0 && arr[0]) return String(arr[0])
    } catch {
      return ''
    }
  }
  return ''
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

const rules = {
  order_no: [{ required: true, message: '请输入订单号', trigger: 'blur' }],
  order_date: [{ required: true, message: '请选择订单时间', trigger: 'change' }],
  status: [{ required: true, message: '请选择订单状态', trigger: 'change' }],
  amount: [{ required: true, message: '请输入订单金额', trigger: 'blur' }],
}

const LIST_FILTER_STATUS_SET = new Set(LIST_FILTER_STATUS_KEYS)

function listFilterParams() {
  const params = {}
  if (filters.value.keyword) params.keyword = filters.value.keyword
  const st = (filters.value.status || '').trim()
  if (st && LIST_FILTER_STATUS_SET.has(st)) params.status = st
  if (dateRange.value?.length === 2) {
    const start = localYmdToDayStartTs(dateRange.value[0])
    const end = localYmdToDayEndTs(dateRange.value[1])
    if (start != null) params.start_ts = start
    if (end != null) params.end_ts = end
  }
  return params
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
      today_total_count: res.today_total_count ?? 0,
      today_sum_amount: res.today_sum_amount ?? 0,
      today_sum_service_fee: res.today_sum_service_fee ?? 0,
      today_sum_shipping_fee: res.today_sum_shipping_fee ?? 0,
      today_sum_net_income: res.today_sum_net_income ?? 0,
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

function onFilterChange() {
  page.value = 1
  load()
  loadStats()
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  dateRange.value = []
  page.value = 1
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

/** 出库明细行：后端 line_kind 为 mgmt_id | barcode */
function outboundLineKindLabel(line) {
  const k = line?.line_kind
  if (k === 'bundle_title') return '组合标题'
  if (k === 'barcode') return '条码'
  return '管理ID'
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

async function onOrderExpandChange(row, expandedRows) {
  const ono = String(row?.order_no || '').trim()
  if (!ono) return
  const opened = expandedRows.some((r) => String(r?.order_no || '').trim() === ono)
  if (!opened) return
  if (expandState.value[ono]?.loaded) return
  expandState.value = {
    ...expandState.value,
    [ono]: { loading: true, loaded: false, rows: [] },
  }
  try {
    const res = await orderApi.outboundLines({ order_no: ono })
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
  const meta = selectedPackagingMeta(itemName)
  if (!meta) return
  packagingForm.value.unit_price = Number(meta.amount || 0)
}

function packagingDisplayRows(orderNo) {
  const rows = packagingState.value?.[String(orderNo || '').trim()]?.rows || []
  if (rows.length) return rows
  return [{ __placeholder: true }]
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
    ElMessage.warning('请选择包材物品')
    return
  }
  if (unitPrice <= 0) {
    ElMessage.warning('请填写有效单价')
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
    ElMessage.success('已添加包装材料并扣减库存')
    packagingDialogVisible.value = false
    await loadPackagingExpenses(orderNo)
    await load()
    await loadStats()
  } finally {
    packagingSubmitting.value = false
  }
}

async function openManualOutboundDialog(orderRow) {
  const orderNo = String(orderRow?.order_no || '').trim()
  if (!orderNo) return
  manualOutboundForm.value = {
    order_no: orderNo,
    inventory_ids: [],
    quantities: {},
  }
  manualOwnerFilter.value = ''
  manualOutboundDialogVisible.value = true
  manualInventoryLoading.value = true
  try {
    const res = await inventoryApi.list({ in_stock_only: true })
    manualInventoryOptions.value = Array.isArray(res) ? res : []
  } finally {
    manualInventoryLoading.value = false
  }
}

async function submitManualOutbound() {
  const orderNo = String(manualOutboundForm.value.order_no || '').trim()
  const ids = Array.isArray(manualOutboundForm.value.inventory_ids)
    ? manualOutboundForm.value.inventory_ids.map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)
    : []
  if (!orderNo) return
  if (!ids.length) {
    ElMessage.warning('请至少选择一个库存商品')
    return
  }
  const lines = ids.map((iid) => ({
    inventory_id: iid,
    quantity: Math.max(1, Number((manualOutboundForm.value.quantities || {})[iid] || 1)),
  }))
  manualOutboundSaving.value = true
  try {
    await orderApi.addManualOutboundLinesBatch({
      order_no: orderNo,
      lines,
    })
    ElMessage.success(`已添加 ${lines.length} 条手动出库明细`)
    manualOutboundDialogVisible.value = false
    clearOutboundExpandCache(orderNo)
    await load()
  } finally {
    manualOutboundSaving.value = false
  }
}

function inventoryLabelById(iid) {
  const row = (manualInventoryOptions.value || []).find((x) => Number(x.id) === Number(iid))
  if (!row) return `库存#${iid}`
  return `${row.name || '-'}（库存:${Number(row.quantity || 0)}）`
}

function inventoryThumbUrl(row) {
  const f = String(row?.image_front || '').trim()
  if (f) return f
  const i = String(row?.image || '').trim()
  return i || ''
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
    ElMessage.success('出库成功')
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
  form.value = {
    id: row.id,
    order_no: row.order_no || '',
    order_date: tsOrLegacyToLocalForm(row.order_date),
    order_updated_at: tsOrLegacyToLocalForm(row.order_updated_at),
    purchase_time: tsOrLegacyToLocalForm(row.purchase_time),
    data_user: row.data_user != null && row.data_user !== '' ? String(row.data_user) : '',
    customer_name: row.customer_name || '',
    status: row.status || 'pending',
    amount: Number(row.amount || 0),
    service_fee: optionalNumFromRow(row.service_fee),
    net_income: optionalNumFromRow(row.net_income),
    carrier_display_name: row.carrier_display_name || '',
    request_class_display_name: row.request_class_display_name || '',
    shipping_fee: optionalNumFromRow(row.shipping_fee),
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
    ElMessage.warning('该订单缺少订单号')
    return
  }
  const dataUser = row.data_user != null && row.data_user !== '' ? String(row.data_user).trim() : ''
  if (!dataUser) {
    ElMessage.warning('该订单缺少卖家ID（data_user），无法选择煤炉账号，请先同步或编辑补全')
    return
  }
  refreshingId.value = row.id
  try {
    await orderApi.refreshInfo({ order_no: orderNo, data_user: dataUser })
    ElMessage.success('已从煤炉刷新该订单')
    clearOutboundExpandCache(orderNo)
    load()
    loadStats()
  } finally {
    refreshingId.value = null
  }
}

async function submit() {
  await formRef.value?.validate()
  if (!form.value.id) {
    ElMessage.warning('未选择订单')
    return
  }
  const orderDateSec = localFormStringToUnixSec(form.value.order_date)
  if (orderDateSec == null) {
    ElMessage.warning('订单时间（order_date）无效，请检查「订单时间」')
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
    ElMessage.success('更新成功')
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
  ElMessage.success('删除成功')
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

onMounted(() => {
  updateViewportState()
  window.addEventListener('resize', updateViewportState)
  load()
  loadStats()
  loadPackagingItemOptions()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportState)
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
}
.thumb-fallback {
  color: #909399;
  font-size: 12px;
}
.order-expand-wrap {
  padding: 8px 12px 12px 48px;
  min-height: 48px;
}
.order-expand-inner-table {
  max-width: 100%;
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
