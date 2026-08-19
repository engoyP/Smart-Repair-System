<template>
  <div class="page">
    <!-- 查看模式 -->
    <template v-if="isViewMode && form.work_order_no">
      <el-card shadow="never" class="detail-card">
        <div class="detail-header">
          <h3>{{ form.work_order_no }}</h3>
          <el-tag :type="statusTagType" size="large">{{ statusLabel }}</el-tag>
        </div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="故障描述" :span="2">{{ form.fault_description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="故障码">{{ displayFaultCodes || '-' }}</el-descriptions-item>
          <el-descriptions-item label="设备错误码">{{ form.device_error_code || '-' }}</el-descriptions-item>
          <template v-if="form.device_id">
            <el-descriptions-item label="设备">
              <div style="display:flex;align-items:center;gap:8px">
                <span>{{ deviceName }}</span>
                <el-tag :type="devStatusTagType(selectedDevice?.run_status)" size="small" effect="dark" round>
                  {{ devStatusLabel(selectedDevice?.run_status) }}
                </el-tag>
                <el-tag v-if="selectedDevice?.fault_tags && selectedDevice.fault_tags.length" size="small" type="danger" effect="light">
                  {{ selectedDevice.fault_tags.length }} 项故障标签
                </el-tag>
              </div>
            </el-descriptions-item>
          </template>
          <el-descriptions-item label="设备类型">{{ form.device_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="设备位置">{{ form.location || '-' }}</el-descriptions-item>
          <el-descriptions-item label="故障分类">{{ form.fault_phenomenon_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="技术员">{{ technicianName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="故障现象" :span="2">
            <pre class="detail-pre">{{ form.fault_phenomenon || '-' }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="附件" :span="2">
            <div v-if="!attachments.length">-</div>
            <div v-if="attachments.length" class="attach-gallery">
              <div v-for="(f, i) in attachments" :key="i" class="attach-item">
                <img v-if="f.type === 'image'" :src="f.url" class="attach-thumb" />
                <video v-if="f.type !== 'image'" :src="f.url" class="attach-thumb" controls />
                <span class="attach-name">{{ f.name }}</span>
              </div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="根本原因分类">{{ form.root_cause_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="维修结果">
            <div v-if="form.repair_result">
              <el-tag :type="repairResultTagType" size="small">{{ repairResultLabel }}</el-tag>
            </div>
            <div v-if="!form.repair_result">-</div>
          </el-descriptions-item>
          <el-descriptions-item label="原因分析" :span="2">
            <pre class="detail-pre">{{ form.root_cause || '-' }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="处理步骤" :span="2">
            <pre class="detail-pre">{{ form.solution_steps || '-' }}</pre>
          </el-descriptions-item>
          <template v-if="form.repair_result === 'TEMPORARY_FIX'">
            <el-descriptions-item label="后续计划" :span="2">
              <pre class="detail-pre">{{ form.follow_up_plan || '-' }}</pre>
            </el-descriptions-item>
          </template>
          <el-descriptions-item label="工时（小时）">{{ form.work_hours != null ? form.work_hours.toFixed(1) : '-' }}</el-descriptions-item>
          <el-descriptions-item label="维修时间">
            {{ form.start_time ? dayjs(form.start_time).format('YYYY-MM-DD HH:mm') : '-' }}
            ~ {{ form.end_time ? dayjs(form.end_time).format('YYYY-MM-DD HH:mm') : '-' }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="detail-footer">
          <el-button type="primary" @click="$router.push('/work-orders')">返回列表</el-button>
        </div>
      </el-card>
    </template>

    <!-- 编辑模式 -->
    <template v-if="!isViewMode">
      <div class="form-body">
        <!-- 录入模式切换：标准录入 / 错误码录入 -->
        <div class="mode-switch-bar">
          <span class="mode-switch-label">录入方式</span>
          <div class="mode-switch">
            <span class="mode-tab" :class="{ active: entryMode === 'standard' }" @click="switchEntryMode('standard')">标准录入</span>
            <span class="mode-tab" :class="{ active: entryMode === 'error_code' }" @click="switchEntryMode('error_code')">错误码录入</span>
          </div>
        </div>

        <!-- 错误码录入模式：粘贴日志原文 → 抠码 + 手册情形勾选 + 工单案例预填 -->
        <template v-if="entryMode === 'error_code'">
          <el-card shadow="never" class="section-card error-code-card">
            <template #header>
              <div class="card-header-row">
                <span class="section-title">日志原文检索预填</span>
                <span class="mode-tip">粘贴设备屏幕/日志原文，自动提取报警码并匹配手册标准处理与历史工单案例，一键预填</span>
              </div>
            </template>
            <div class="ec-search">
              <el-input
                v-model="ecQuery"
                type="textarea"
                :rows="6"
                placeholder="粘贴设备屏幕/日志原文，如：2026-08-14 10:32:15 SV0436 X AXIS: EXCESS CURRENT IN SERVO 启动瞬间电流突增报警，电机无法转动"
                style="flex:1"
              />
              <el-button type="primary" :loading="ecSearching" @click="ecSearch">解析匹配</el-button>
            </div>
            <div v-if="ecError" class="ec-error">{{ ecError }}</div>
            <template v-if="ecResults">
              <div class="ec-results">
                <!-- 抠码结果：可增删 tag，最终写入 device_error_code -->
                <div class="ec-codes-row">
                  <span class="ec-codes-label">识别报警码</span>
                  <el-tag
                    v-for="c in extractedCodes"
                    :key="c"
                    closable
                    size="small"
                    class="ec-code-tag"
                    @close="removeExtractedCode(c)"
                  >{{ c }}</el-tag>
                  <el-input
                    v-model="manualCodeInput"
                    size="small"
                    class="ec-code-input"
                    placeholder="手动补码后回车"
                    @keydown.enter="addManualCode"
                  />
                  <span v-if="!extractedCodes.length" class="ec-code-empty">未识别到报警码可手动补充</span>
                </div>
                <div v-if="!ecResults.manual_items.length && !ecResults.case_items.length" class="ec-empty">
                  未检索到相关手册或工单案例
                </div>
                <div v-if="ecResults.manual_items.length" class="ec-group">
                  <div class="ec-group-title">设备手册（权威标准处理）</div>
                  <div v-for="m in ecResults.manual_items" :key="m.manual_code_id" class="ec-item manual">
                    <div class="ec-item-header">
                      <span class="ec-code">{{ m.error_code }}</span>
                      <span class="ec-title">{{ m.title }}</span>
                      <el-tag v-if="m.severity" :type="sevTagType(m.severity)" size="small">{{ sevLabel(m.severity) }}（{{ m.effect || '-' }}）</el-tag>
                      <el-tag v-if="m.manual_name" size="small" type="info">{{ m.manual_name }}</el-tag>
                      <el-tag v-if="m.chapter" size="small" effect="plain">{{ m.chapter }}</el-tag>
                      <el-tag v-if="m.page" size="small" effect="plain">P{{ m.page }}</el-tag>
                    </div>
                    <div v-if="m.message_text" class="ec-msg">{{ m.message_text }}</div>
                    <div v-if="m.description" class="ec-desc">{{ m.description }}</div>
                    <div v-if="m.related_codes?.length" class="ec-block">
                      <span class="ec-block-label">伴随报警</span>
                      <el-tag v-for="rc in m.related_codes" :key="rc" size="small" effect="plain" style="margin-right:4px">{{ rc }}</el-tag>
                    </div>
                    <div v-if="m.conditions?.length" class="ec-cond-list">
                      <div class="ec-cond-head">勾选命中的情形（已按日志信号匹配度排序，可多选）</div>
                      <el-checkbox-group v-model="m._selected" class="ec-cond-group">
                        <el-checkbox v-for="(c, i) in m.conditions" :key="i" :value="i" class="ec-cond">
                          <span class="ec-cond-signal">{{ c.signal }}</span>
                          <span class="ec-cond-cause">{{ c.cause }}</span>
                        </el-checkbox>
                      </el-checkbox-group>
                    </div>
                    <div v-if="!m.conditions?.length && (m.causes || m.solutions)" class="ec-block">
                      <span class="ec-block-label">可能原因</span>{{ m.causes }}
                      <div v-if="m.solutions"><span class="ec-block-label">标准处理</span>{{ m.solutions }}</div>
                    </div>
                    <div class="ec-item-footer">
                      <el-button size="small" type="primary" @click="applyManualItem(m)">选用选中情形</el-button>
                    </div>
                  </div>
                </div>
                <div v-if="ecResults.case_items.length" class="ec-group">
                  <div class="ec-group-title">历史工单案例（真实处理记录）</div>
                  <div v-for="c in ecResults.case_items" :key="c.knowledge_id" class="ec-item case">
                    <div class="ec-item-header">
                      <span class="ec-title">{{ c.title }}</span>
                      <el-tag v-if="c.device_type" size="small" type="info">{{ c.device_type }}</el-tag>
                      <el-tag v-if="c.fault_code" size="small" type="warning">{{ c.fault_code }}</el-tag>
                    </div>
                    <div v-if="c.content" class="ec-desc">{{ c.content }}</div>
                    <div class="ec-item-footer">
                      <el-button size="small" type="primary" plain @click="applyCaseItem(c)">引用此案例</el-button>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </el-card>
        </template>

        <template v-if="analysisResult">
          <el-card shadow="never" class="section-card analysis-card">
            <template #header>
              <div class="card-header-row">
                <span class="section-title">AI 校验结果</span>
                <el-button size="small" text type="primary" @click="analysisResult = null">收起</el-button>
              </div>
            </template>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="完整度">
                <el-progress :percentage="Math.round((analysisResult.completeness_score || 0) * 100)" :stroke-width="16" :status="analysisResult.completeness_score >= 0.8 ? 'success' : 'warning'" style="width:180px" />
              </el-descriptions-item>
              <el-descriptions-item label="置信度">
                <span :style="{ fontWeight:600, color: analysisResult.confidence >= 0.8 ? '#52c41a' : '#faad14' }">
                  {{ Math.round((analysisResult.confidence || 0) * 100) }}%
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="设备类型">{{ analysisResult.device_type || '-' }}</el-descriptions-item>
              <el-descriptions-item label="故障分类">{{ analysisResult.fault_category || '-' }}</el-descriptions-item>
              <el-descriptions-item label="标准化故障码">{{ analysisResult.standardized_fault_code || '-' }}</el-descriptions-item>
              <el-descriptions-item label="缺失字段">
                <div v-if="(analysisResult.missing_fields || []).length" class="missing-fields">
                  <template v-for="f in analysisResult.missing_fields" :key="f">
                  <el-tag type="danger" size="small" style="margin-right:4px">{{ f }}</el-tag>
                </template>
                </div>
                <span v-if="!(analysisResult.missing_fields || []).length" style="color:#52c41a">无</span>
              </el-descriptions-item>
              <el-descriptions-item label="校验说明" :span="2">{{ analysisResult.validation_notes || '-' }}</el-descriptions-item>
              <template v-if="analysisResult.standardized_fault_code">
                <el-descriptions-item label="推荐操作" :span="2">
                  <el-button size="small" type="primary" @click="applyAIFields">一键填充 AI 推荐字段</el-button>
                </el-descriptions-item>
              </template>
            </el-descriptions>
          </el-card>
        </template>

        <template v-if="deviceMaintenance">
          <el-alert
            :title="`设备「${deviceMaintenance.device_name}」近 6 个月维修 ${deviceMaintenance.recent_count} 次`"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom:16px"
          >
            <template #default>
              <span v-if="deviceMaintenance.last_fault">
                最近故障：{{ deviceMaintenance.last_fault }}
                <span v-if="deviceMaintenance.last_date">（{{ dayjs(deviceMaintenance.last_date).format('MM-DD HH:mm') }}）</span>
              </span>
            </template>
          </el-alert>
        </template>

        <el-card shadow="never" class="form-card">
          <el-form :model="form" label-width="110px" class="form-grid">
            <div class="form-section">
              <div class="section-header">基本信息</div>
              <el-form-item label="工单编号">
                <el-input v-model="form.work_order_no" disabled placeholder="系统自动生成" />
              </el-form-item>
              <el-form-item label="关联设备" required>
                <el-select
                  v-model="form.device_id"
                  clearable
                  filterable
                  remote
                  :remote-method="searchDevices"
                  placeholder="输入设备名称检索（会显示实时状态）"
                  style="width:100%"
                  @change="onDeviceChange"
                >
                  <el-option v-for="d in deviceFiltered" :key="d.id" :label="`${d.device_name} (${d.device_code})`" :value="d.id">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%">
                      <div style="display:flex;flex-direction:column;gap:2px;min-width:0">
                        <span style="font-weight:600;color:#1D2129">{{ d.device_name }}</span>
                        <span style="font-size:11px;color:#86909C">{{ d.device_code }} · {{ d.location || '未设置位置' }}</span>
                      </div>
                      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
                        <el-tag v-if="d.fault_tags && d.fault_tags.length" size="small" type="danger" effect="light">
                          {{ d.fault_tags.length }} 故障
                        </el-tag>
                        <el-tag :type="devStatusTagType(d.run_status)" size="small" effect="dark" round>
                          {{ devStatusLabel(d.run_status) }}
                        </el-tag>
                      </div>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="设备类型">
                <el-input v-model="form.device_type" disabled placeholder="选择设备后自动填充" />
              </el-form-item>
              <el-form-item label="设备位置">
                <el-input v-model="form.location" disabled placeholder="选择设备后自动填充" />
              </el-form-item>
              <el-form-item label="技术员" required>
                <el-input :model-value="technicianDisplay" disabled placeholder="当前登录账号" />
              </el-form-item>
            </div>

            <div class="form-section">
              <div class="section-header">
                故障信息
                <el-button size="small" type="warning" style="float:right" @click="askAI('fault')">AI 分析故障</el-button>
              </div>
              <el-form-item label="故障描述" required>
                <el-input v-model="form.fault_description" type="textarea" :rows="3" placeholder="描述故障现象，如：电机启动后出现周期性金属摩擦异响" />
              </el-form-item>
            </div>

            <div class="form-section">
              <div class="section-header">
                诊断与维修
                <el-button size="small" type="warning" style="float:right" @click="askAI('diagnosis')">AI 诊断建议</el-button>
              </div>
              <el-form-item label="处理步骤" required>
                <div class="solution-area">
                  <el-input v-model="form.solution_steps" type="textarea" :rows="4" placeholder="1. 停机断电&#10;2. 拆除端盖检查轴承&#10;3. 更换同型号轴承并加注润滑脂" />
                  <el-button size="small" type="primary" plain style="margin-top:8px" @click="openKnowledgeRef">
                    从知识库引用
                  </el-button>
                </div>
              </el-form-item>
              <el-form-item label="维修时间" required>
                <el-date-picker
                  v-model="timeRange"
                  type="datetimerange"
                  start-placeholder="开始"
                  end-placeholder="结束"
                  style="width:100%"
                  :disabled-date="disabledDate"
                  @change="calcWorkHours"
                />
              </el-form-item>
              <el-form-item label="工时（小时）">
                <el-input :model-value="form.work_hours != null ? form.work_hours.toFixed(1) : ''" disabled placeholder="自动计算">
                  <template #append>小时</template>
                </el-input>
              </el-form-item>
              <el-form-item label="维修结果" required>
                <el-radio-group v-model="form.repair_result" @change="onRepairResultChange">
                  <el-radio value="PERMANENT_FIX">彻底修复</el-radio>
                  <el-radio value="TEMPORARY_FIX">临时措施</el-radio>
                  <el-radio value="UNABLE_FIX">未能修复</el-radio>
                </el-radio-group>
              </el-form-item>
              <template v-if="form.repair_result === 'TEMPORARY_FIX'">
                <el-form-item label="后续计划" required>
                  <el-input v-model="form.follow_up_plan" type="textarea" :rows="2" placeholder="请填写后续处理计划，如：已订购配件，预计 3 天后到货更换" />
                </el-form-item>
              </template>
              <template v-if="form.repair_result === 'UNABLE_FIX'">
                <el-form-item label="未修复原因" required>
                  <el-input v-model="form.follow_up_plan" type="textarea" :rows="2" placeholder="请说明未能修复的原因" />
                </el-form-item>
              </template>
              <el-form-item label="故障码" required>
                <div class="fault-code-row">
                  <el-select
                    v-model="form.fault_code"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入故障码，如 100001"
                    style="flex:1"
                    :reserve-keyword="false"
                    :filter-method="filterFaultCodes"
                  >
                    <el-option
                      v-for="opt in faultCodeFiltered"
                      :key="opt.code"
                      :label="opt.code"
                      :value="opt.code"
                    >
                      <span class="fc-option">
                        <span class="fc-code">{{ opt.code }}</span>
                        <span class="fc-desc">{{ opt.desc }}</span>
                      </span>
                    </el-option>
                  </el-select>
                  <el-button size="small" type="warning" plain @click="faultCodeDialog.visible = true">
                    + 新增
                  </el-button>
                </div>
                <div class="cascader-hint">如故障码不存在可点击「+ 新增」填写描述自动生成</div>
              </el-form-item>
            </div>

            <!-- 补充信息（可选）：次要字段折叠，关键路径 = 设备 + 日志粘贴 + 处理结果 -->
            <div class="form-section">
              <el-collapse v-model="supplementOpen" class="supplement-collapse">
                <el-collapse-item :name="'supplement'">
                  <template #title>
                    <span class="supplement-title">
                      补充信息（可选）
                      <el-badge v-if="supplementFilledCount" :value="supplementFilledCount" type="info" class="supplement-badge" />
                    </span>
                  </template>
                  <div class="supplement-body">
                    <el-form-item label="故障现象">
                      <el-cascader
                        v-model="faultPhenomenonCascader"
                        :options="faultPhenomenaOptions"
                        :props="{ value: 'value', label: 'label', children: 'children', checkStrictly: false }"
                        placeholder="选择故障大类 → 具体现象（也可跳过，直接在下方手动输入）"
                        style="width:100%"
                        clearable
                        filterable
                        @change="onFaultPhenomenonChange"
                      />
                      <div class="cascader-hint">如故障类型不在列表中，可直接在下方文本框自由描述</div>
                    </el-form-item>
                    <el-form-item :label="faultPhenomenonCascader.length ? '补充描述' : '故障现象描述'">
                      <el-input
                        v-model="form.fault_phenomenon"
                        type="textarea"
                        :rows="3"
                        :placeholder="faultPhenomenonCascader.length ? '选填：对故障现象的补充说明' : '请详细描述故障现象，如：电机启动后出现周期性金属摩擦异响，振动值超标，外壳温度偏高等'"
                      />
                    </el-form-item>
                    <el-form-item label="根本原因">
                      <el-cascader
                        v-model="rootCauseCascader"
                        :options="rootCauseOptions"
                        :props="{ value: 'value', label: 'label', children: 'children', checkStrictly: false }"
                        placeholder="选择原因大类 → 具体原因（也可跳过，直接在下方手动输入）"
                        style="width:100%"
                        clearable
                        filterable
                        @change="onRootCauseChange"
                      />
                      <div class="cascader-hint">如原因类型不在列表中，可直接在下方文本框自由描述</div>
                    </el-form-item>
                    <el-form-item :label="rootCauseCascader.length ? '补充说明' : '根本原因描述'">
                      <el-input
                        v-model="form.root_cause"
                        type="textarea"
                        :rows="3"
                        :placeholder="rootCauseCascader.length ? '选填：根本原因的补充说明' : '请描述根本原因，如：电机轴承磨损导致径向间隙增大，长期缺油运行加速老化'"
                      />
                    </el-form-item>
                    <el-form-item label="设备错误码">
                      <el-input
                        v-model="form.device_error_code"
                        placeholder="设备运行日志/屏幕报警的错误码，如 SV0436、6401（多个用逗号分隔）"
                      />
                      <div class="cascader-hint">仅带错误码的机电设备填写，提交后自动沉淀到知识库，后续提问该错误码可被检索</div>
                    </el-form-item>
                    <el-form-item label="现场附件">
                      <el-upload
                        :http-request="uploadFile"
                        :file-list="uploadFileList"
                        list-type="picture-card"
                        :on-remove="removeAttachment"
                        :before-upload="beforeUpload"
                        accept=".jpg,.jpeg,.png,.gif,.mp4,.mov,.avi,.webm"
                        multiple
                      >
                        <el-icon><Plus /></el-icon>
                      </el-upload>
                      <div class="upload-hint">支持 JPG/PNG/GIF/MP4，单文件 ≤ 50MB</div>
                    </el-form-item>
                    <div class="supplement-sub">
                      <div class="section-header">备件记录</div>
                      <div class="parts-list">
                        <div v-for="(part, idx) in usedParts" :key="idx" class="part-row">
                          <el-select
                            v-model="part.code"
                            filterable
                            :filter-method="(q) => filterSpareParts(q)"
                            placeholder="选择备件 (输入编码或名称搜索)"
                            style="width: 280px"
                            @change="(val) => onPartSelected(val, idx)"
                            @visible-change="(visible) => onSelectVisible(visible)"
                            clearable
                          >
                            <el-option
                              v-for="sp in sparePartOptions"
                              :key="sp.part_code"
                              :label="`${sp.part_code} - ${sp.part_name}`"
                              :value="sp.part_code"
                            >
                              <div class="spare-option">
                                <span class="spare-code">{{ sp.part_code }}</span>
                                <span class="spare-name">{{ sp.part_name }}</span>
                                <span v-if="sp.specification" class="spare-spec">{{ sp.specification }}</span>
                              </div>
                              <div class="spare-option-info">
                                <span class="spare-stock" :class="{ 'stock-low': sp.stock_quantity <= sp.safety_stock, 'stock-out': sp.stock_quantity <= 0 }">
                                  库存: {{ sp.stock_quantity }}
                                </span>
                                <span v-if="sp.location" class="spare-location">库位: {{ sp.location }}</span>
                              </div>
                            </el-option>
                          </el-select>
                          <el-input-number
                            v-model="part.qty"
                            :min="1"
                            :max="999"
                            style="width: 100px"
                            :class="{ 'qty-over-stock': part.stock !== undefined && part.qty > part.stock && part.stock >= 0 }"
                          />
                          <span v-if="part.stock !== undefined" class="part-stock-tip" :class="{ 'stock-warning': part.qty > part.stock && part.stock >= 0 }">
                            可用: {{ part.stock }}
                            <span v-if="part.qty > part.stock && part.stock >= 0" class="stock-short">（缺 {{ part.qty - part.stock }}）</span>
                          </span>
                          <div v-if="part.qty > part.stock && part.stock >= 0">
                            <el-button type="warning" size="small" plain @click="handleUrgentOrder(part)">
                              紧急采购
                            </el-button>
                          </div>
                          <el-button type="danger" size="small" @click="usedParts.splice(idx,1)">删除</el-button>
                        </div>
                        <el-button type="primary" size="small" @click="usedParts.push({name:'',code:'',qty:1,stock:0,maxStock:999})">+ 添加备件</el-button>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </el-form>
        </el-card>

        <div class="form-footer">
          <el-button type="info" @click="$router.back()">取消</el-button>
          <el-button type="primary" plain :loading="saving" @click="handleSaveDraft">
            {{ saving ? '保存中...' : '保存草稿' }}
          </el-button>
          <template v-if="form.status === 'ARCHIVING'">
            <el-button type="primary" :loading="archiving" @click="handleArchiveCheck">
              {{ archiving ? '校验中...' : '工单归档' }}
            </el-button>
            <el-button type="success" :loading="archiving" @click="handleArchiveComplete" :disabled="!canArchiveComplete">
              {{ archiving ? '归档中...' : '归档完成' }}
            </el-button>
          </template>
          <template v-else>
            <el-button type="warning" :loading="analyzing" @click="handleAnalyze">
              {{ analyzing ? 'AI 校验中...' : 'AI 校验' }}
            </el-button>
            <el-button type="success" :loading="submitting" @click="handleSubmit" :disabled="!canSubmit">
              {{ submitting ? '提交中...' : '确认提交' }}
            </el-button>
          </template>
        </div>
        <p v-if="!isNew && form.status === 'ARCHIVING'" class="submit-hint">
          {{ archiveCheckResult
              ? (archiveCheckResult.passed
                  ? `归档校验通过（完成度 ${Math.round(archiveCheckResult.completeness * 100)}%），可点击「归档完成」`
                  : `归档完成度不足（${Math.round(archiveCheckResult.completeness * 100)}%），缺失：${(archiveCheckResult.missing_fields || []).join('、')}`)
              : '请先点击「工单归档」完成校验，再点击「归档完成」' }}
        </p>
        <p v-else-if="!canSubmit && !isNew" class="submit-hint">
          {{ entryMode === 'error_code'
              ? '请先通过「错误码检索」选用方案（或填写故障描述），再提交'
              : '请先点击「AI 校验」完成分析后再提交' }}
        </p>
      </div>
    </template>

    <!-- AI 问答弹窗 -->
    <el-dialog v-model="aiDialog.visible" title="AI 助手" width="700px" :close-on-click-modal="false">
      <div class="ai-dialog-body">
        <div class="ai-dialog-msgs" ref="aiMsgRef">
          <div v-for="(m, i) in aiDialog.messages" :key="i" class="ai-msg-row" :class="m.role">
            <div class="ai-msg-bubble">{{ m.content }}</div>
          </div>
          <div v-if="aiDialog.loading" class="ai-msg-row assistant">
            <div class="ai-msg-bubble thinking">AI 思考中...</div>
          </div>
        </div>
        <div class="ai-dialog-input">
          <el-input v-model="aiDialog.input" type="textarea" :rows="2" placeholder="输入你的维修问题..." @keydown.enter.prevent="sendAIMessage" />
          <el-button type="primary" @click="sendAIMessage" :loading="aiDialog.loading" style="margin-top:8px">发送</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 知识库引用弹窗 -->
    <el-dialog v-model="knowledgeDialog.visible" title="从知识库引用处理步骤" width="750px" :close-on-click-modal="false">
      <div class="knowledge-dialog">
        <div class="kd-search">
          <el-input v-model="knowledgeDialog.keyword" placeholder="输入故障现象或设备关键词检索" clearable @keydown.enter="searchSolutions" style="flex:1">
            <template #append>
              <el-button type="primary" @click="searchSolutions" :loading="knowledgeDialog.searching">搜索</el-button>
            </template>
          </el-input>
        </div>
        <div class="kd-results" v-loading="knowledgeDialog.searching">
          <div v-if="knowledgeDialog.results.length === 0 && !knowledgeDialog.searching" class="kd-empty">
            请输入关键词搜索知识库中的处理步骤
          </div>
          <div v-for="item in knowledgeDialog.results" :key="item.knowledge_id" class="kd-item" @click="applySolution(item)">
            <div class="kd-item-header">
              <span class="kd-title">{{ item.title }}</span>
              <el-tag size="small" type="info">{{ item.device_type || '通用' }}</el-tag>
              <template v-if="item.fault_code">
                <el-tag size="small" type="warning">{{ item.fault_code }}</el-tag>
              </template>
            </div>
            <pre class="kd-steps">{{ item.solution_steps }}</pre>
            <div class="kd-item-footer">
              <span class="kd-count">共 {{ item.solution_count }} 个步骤</span>
              <el-button size="small" type="primary">引用此方案</el-button>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 新增故障码弹窗 -->
    <el-dialog v-model="faultCodeDialog.visible" title="新增故障码" width="500px" :close-on-click-modal="false">
      <div class="fc-dialog">
        <el-form label-width="80px">
          <el-form-item label="设备类型">
            <el-input :model-value="form.device_type || '（未选择）'" disabled />
            <div class="cascader-hint">系统根据设备类型自动分配编码前缀</div>
          </el-form-item>
          <el-form-item label="故障描述" required>
            <el-input
              v-model="faultCodeDialog.description"
              type="textarea"
              :rows="4"
              placeholder="请填写故障描述，如：注塑机料筒温度偏高报警"
            />
          </el-form-item>
        </el-form>
        <div v-if="faultCodeDialog.result" class="fc-dialog-result">
          <div v-if="faultCodeDialog.result.is_new">
            <el-alert
              title="新增成功"
              type="success"
              :description="`故障码 ${faultCodeDialog.result.fault_code} 已自动生成并收录`"
              show-icon
              :closable="false"
            />
          </div>
          <div v-if="!faultCodeDialog.result.is_new">
            <el-alert
              title="检测到重复"
              type="warning"
              :description="faultCodeDialog.result.duplicate_hint"
              show-icon
              :closable="false"
            />
          </div>
        </div>
        <div class="fc-dialog-footer">
          <el-button @click="faultCodeDialogClose">取消</el-button>
          <div v-if="!faultCodeDialog.result" style="display:inline">
            <el-button type="primary" :loading="faultCodeDialog.creating" @click="handleCreateFaultCode">
              {{ faultCodeDialog.creating ? '生成中...' : '自动生成故障码' }}
            </el-button>
          </div>
          <div v-if="faultCodeDialog.result" style="display:inline">
            <el-button type="primary" @click="confirmFaultCodeResult">
              确认使用
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import request from '../api'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const isNew = computed(() => !route.params.id || route.path.endsWith('/new'))
const isViewMode = computed(() => !isNew.value && !route.query.edit)

const DEFAULT_DEVICE_TYPES = [
  { label: '注塑机', value: '注塑机' },
  { label: '空压机', value: '空压机' },
  { label: '数控机床', value: '数控机床' },
  { label: '输送设备', value: '输送设备' },
  { label: 'PLC系统', value: 'PLC系统' },
]

const flattenTree = (nodes, result = []) => {
  for (const node of nodes) {
    result.push({ label: node.name, value: node.name })
    if (node.children && node.children.length > 0) flattenTree(node.children, result)
  }
  return result
}

const form = reactive({
  work_order_no: '',
  id: null,
  device_id: null,
  device_type: '',
  location: '',
  technician_id: null,
  technician_name: '',
  fault_description: '',
  fault_category: '',
  fault_phenomenon_type: '',
  fault_phenomenon: '',
  fault_code: [],
  device_error_code: '',
  log_text: '',
  root_cause_category: '',
  root_cause_type: '',
  root_cause: '',
  solution_steps: '',
  solution_ref_knowledge_id: null,
  repair_result: '',
  follow_up_plan: '',
  work_hours: null,
  status: 'DRAFT',
  tags: [],
  fault_tags: [],
})

const faultPhenomenonCascader = ref([])
const faultPhenomenaOptions = ref([])
const rootCauseCascader = ref([])
const rootCauseOptions = ref([])
const attachments = ref([])
const uploadFileList = ref([])
const devices = ref([])
const deviceFiltered = ref([])
const users = ref([])
const timeRange = ref(null)
const usedParts = ref([])
const spareParts = ref([])
const sparePartOptions = ref([])
const analyzing = ref(false)
const submitting = ref(false)
const saving = ref(false)
const analysisResult = ref(null)
const entryMode = ref('standard')          // standard 标准录入 | error_code 错误码录入
const ecQuery = ref('')                    // 日志原文输入
const ecSearching = ref(false)
const ecResults = ref(null)                // { manual_items, case_items, error_codes }
const ecError = ref('')
const extractedCodes = ref([])             // 抠出的报警码 tag 组（写入 device_error_code）
const manualCodeInput = ref('')            // 手动补码输入
const supplementOpen = ref([])             // 补充信息折叠区展开状态
// 错误码录入模式：填了设备 + 故障描述即可提交；标准模式仍需 AI 校验
const canSubmit = computed(() => entryMode.value === 'error_code'
  ? !!(form.device_id && form.fault_description)
  : !!analysisResult.value)

const sevTagType = (s) => ({ EX: 'danger', OH: 'warning', INFO: 'info' }[s] || 'info')
const sevLabel = (s) => ({ EX: 'EX 急停', OH: 'OH 停机', INFO: 'INFO 提示' }[s] || s)

// 补充信息已填项数（折叠区标题徽标）
const supplementFilledCount = computed(() => {
  let n = 0
  if (faultPhenomenonCascader.value.length || form.fault_phenomenon) n++
  if (rootCauseCascader.value.length || form.root_cause) n++
  if (form.device_error_code) n++
  if (attachments.value.length) n++
  if (usedParts.value.length) n++
  return n
})

const isFormDirty = () => {
  return !!(form.device_id || form.device_error_code || form.fault_description ||
    form.fault_phenomenon || form.fault_code.length || form.root_cause ||
    form.solution_steps || form.repair_result || form.follow_up_plan ||
    usedParts.value.length || attachments.value.length || timeRange.value)
}

// 清空工单表单（保留工单编号/状态/技术员等系统字段）
const resetFormFields = () => {
  form.device_id = null
  form.device_type = ''
  form.location = ''
  form.fault_description = ''
  form.fault_category = ''
  form.fault_phenomenon_type = ''
  form.fault_phenomenon = ''
  form.fault_code = []
  form.device_error_code = ''
  form.log_text = ''
  form.root_cause_category = ''
  form.root_cause_type = ''
  form.root_cause = ''
  form.solution_steps = ''
  form.solution_ref_knowledge_id = null
  form.repair_result = ''
  form.follow_up_plan = ''
  form.work_hours = null
  form.tags = []
  form.fault_tags = []
  faultPhenomenonCascader.value = []
  rootCauseCascader.value = []
  timeRange.value = null
  usedParts.value = []
  attachments.value = []
  uploadFileList.value = []
  deviceMaintenance.value = null
  analysisResult.value = null
  archiveCheckResult.value = null
}

const switchEntryMode = (mode) => {
  if (entryMode.value === mode) return
  const confirmSwitch = () => {
    resetFormFields()
    ecResults.value = null
    ecQuery.value = ''
    extractedCodes.value = []
    manualCodeInput.value = ''
    entryMode.value = mode
  }
  if (isFormDirty()) {
    ElMessageBox.confirm('切换录入模式将清空当前已填写的内容，是否继续？', '切换确认', {
      confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning',
    }).then(confirmSwitch).catch(() => {})
  } else {
    confirmSwitch()
  }
}

// 日志原文检索：抠码 + 手册情形匹配 + 工单案例
const ecSearch = async () => {
  const q = ecQuery.value.trim()
  if (!q) {
    ElMessage.warning('请粘贴设备日志/屏幕原文')
    return
  }
  ecSearching.value = true
  ecError.value = ''
  try {
    const res = await request.post('/search/manual-lookup', { query: q, top_k: 5 })
    // 情形勾选初始化：命中情形（signal 带 [命中] 标记）默认勾选
    (res.manual_items || []).forEach(m => {
      m._selected = (m.conditions || [])
        .map((c, i) => (c.signal || '').includes('[命中]') ? i : -1)
        .filter(i => i >= 0)
    })
    ecResults.value = res
    if (res.error_codes?.length) {
      extractedCodes.value = res.error_codes
      form.device_error_code = res.error_codes.join(',')
    }
  } catch (e) {
    ecError.value = '检索失败，请稍后重试'
  } finally {
    ecSearching.value = false
  }
}

const syncExtractedCodes = () => { form.device_error_code = extractedCodes.value.join(',') }
const removeExtractedCode = (c) => { extractedCodes.value = extractedCodes.value.filter(x => x !== c); syncExtractedCodes() }
const addManualCode = () => {
  const c = (manualCodeInput.value || '').trim().toUpperCase()
  if (!c) return
  if (!extractedCodes.value.includes(c)) {
    extractedCodes.value.push(c)
    syncExtractedCodes()
  }
  manualCodeInput.value = ''
}

// 错误码去重累计（逗号分隔）
const addDeviceErrorCode = (code) => {
  const c = (code || '').trim().toUpperCase()
  if (!c) return
  const existing = (form.device_error_code || '').split(',').map(x => x.trim().toUpperCase()).filter(Boolean)
  if (!existing.includes(c)) existing.push(c)
  form.device_error_code = existing.join(',')
}

// 选用手册条目：勾选的情形 → 预填工单（日志原文落库留痕）
const applyManualItem = (m) => {
  addDeviceErrorCode(m.error_code)
  if (m.device_type && !form.device_type) form.device_type = m.device_type
  form.log_text = ecQuery.value.trim()
  const selected = (m._selected || []).map(i => (m.conditions || [])[i]).filter(Boolean)
  if (selected.length) {
    form.fault_description = `${m.title}：${selected[0].cause || m.description || ''}`
    if (m.message_text && !form.fault_phenomenon) form.fault_phenomenon = `日志原文：${m.message_text}`
    form.root_cause = selected.map((c, i) => `${i + 1}）${c.cause}`).filter(Boolean).join('\n')
    form.solution_steps = selected.map(c => c.steps).filter(Boolean).join('\n')
  } else {
    form.fault_description = m.title || m.description || form.fault_description
    if (m.description && !form.fault_phenomenon) form.fault_phenomenon = m.description
    if (m.causes) form.root_cause = m.causes
    if (m.solutions) form.solution_steps = m.solutions
  }
  ElMessage.success(`已选用手册方案：${m.error_code} ${m.title}`)
}

// 引用工单案例：预填故障描述与故障码，处理步骤供参考
const applyCaseItem = (c) => {
  form.fault_description = c.title || form.fault_description
  if (c.device_type && !form.device_type) form.device_type = c.device_type
  if (c.fault_code && !form.fault_code.includes(c.fault_code)) form.fault_code.push(c.fault_code)
  ElMessage.success(`已引用案例：${c.title}`)
}
const archiving = ref(false)
const archiveCheckResult = ref(null)
const canArchiveComplete = computed(() => !!archiveCheckResult.value?.passed)
const deviceMaintenance = ref(null)
const deviceTypeOptions = ref([...DEFAULT_DEVICE_TYPES])
const deviceTypeFiltered = ref([...DEFAULT_DEVICE_TYPES])
const faultCodeOptions = ref([])
const faultCodeFiltered = ref([])
const aiDialog = reactive({ visible: false, input: '', messages: [], loading: false })
const aiMsgRef = ref(null)
const knowledgeDialog = reactive({ visible: false, keyword: '', results: [], searching: false })
const faultCodeDialog = reactive({ visible: false, description: '', creating: false, result: null })

const selectedDevice = computed(() => {
  // form 是 reactive 对象（无 .value），直接用 form.device_id
  if (!form.device_id) return null
  const d = devices.value.find(d => d.id === form.device_id)
  if (d) return d
  // 备选：deviceFiltered（远程检索可能引入 devices.value 之外的新数据）
  return deviceFiltered.value.find(d => d.id === form.device_id) || null
})
const deviceName = computed(() => {
  if (!form.device_id) return '-'
  if (selectedDevice.value) return selectedDevice.value.device_name
  // 兜底：设备不在本地列表时，用后端详情接口返回的设备名称
  return form.device_name || form.device_code || '-'
})
const devStatusLabel = (s) => ({ ONLINE: '正常', OFFLINE: '离线', ALARM: '告警', FAULT: '故障', UNKNOWN: '未知' }[s] || '未知')
const devStatusTagType = (s) => ({ ONLINE: 'success', OFFLINE: 'info', ALARM: 'warning', FAULT: 'danger' }[s] || 'info')

const displayFaultCodes = computed(() => {
  const c = form.fault_code
  if (!c) return ''
  if (Array.isArray(c)) return c.join(', ')
  return c
})

const technicianName = computed(() => {
  // 优先用后端返回的 technician_name（确保个人中心改名字后工单同步）
  if (form.technician_name) return form.technician_name
  if (!form.technician_id) return '-'
  const u = users.value.find(u => u.id === form.technician_id)
  return u ? u.real_name : '-'
})

const currentUserName = computed(() => {
  try {
    const raw = localStorage.getItem('current_user')
    if (raw) {
      const u = JSON.parse(raw)
      return u.name || u.real_name || ''
    }
  } catch {}
  return ''
})

// 新建时显示当前登录用户；查看/编辑时显示工单维修员（=创建者）
const technicianDisplay = computed(() => {
  if (isNew.value) return currentUserName.value
  return form.technician_id ? technicianName.value : '-'
})

const statusMap = {
  DRAFT: '草稿', SUBMITTED: '待派工', ASSIGNED: '已派单', ACCEPTED: '已接单',
  ARRIVED: '已到达', INSPECTING: '检查中', IN_PROGRESS: '维修中',
  ARCHIVING: '待归档', ARCHIVED: '已归档', COMPLETED: '已完成', REJECTED: '已退回'
}
const statusLabel = computed(() => statusMap[form.status] || form.status || '-')
const statusTagType = computed(() => {
  const map = {
    DRAFT: 'info', SUBMITTED: 'info', ASSIGNED: 'primary', ACCEPTED: 'primary',
    ARRIVED: 'primary', INSPECTING: 'warning', IN_PROGRESS: 'warning',
    ARCHIVING: 'warning', ARCHIVED: 'success', COMPLETED: 'success', REJECTED: 'danger'
  }
  return map[form.status] || 'info'
})

const repairResultLabel = computed(() => {
  const map = { PERMANENT_FIX: '彻底修复', TEMPORARY_FIX: '临时措施', UNABLE_FIX: '未能修复' }
  return map[form.repair_result] || form.repair_result || ''
})
const repairResultTagType = computed(() => {
  const map = { PERMANENT_FIX: 'success', TEMPORARY_FIX: 'warning', UNABLE_FIX: 'danger' }
  return map[form.repair_result] || 'info'
})

const loadDeviceTypes = async () => {
  try {
    const res = await request.get('/categories/', { params: { category_type: 'DEVICE_TYPE', page_size: 1000 } })
    const items = flattenTree(res.items || [])
    if (items.length > 0) {
      deviceTypeOptions.value = items
      deviceTypeFiltered.value = items
    }
  } catch { /* ignore */ }
}

const fetchFaultCodes = async () => {
  try {
    const res = await request.get('/fault-codes/', { params: { page_size: 200 } })
    faultCodeOptions.value = (res.items || []).map(item => ({
      code: item.fault_code,
      desc: item.fault_description,
    }))
    faultCodeFiltered.value = faultCodeOptions.value
  } catch { /* ignore */ }
}

// 故障码下拉联合搜索：输入可同时匹配「故障码」或「描述」
const filterFaultCodes = (query) => {
  if (!query) {
    faultCodeFiltered.value = faultCodeOptions.value
    return
  }
  const q = query.trim().toLowerCase()
  faultCodeFiltered.value = faultCodeOptions.value.filter(o =>
    (o.code || '').toLowerCase().includes(q) || (o.desc || '').toLowerCase().includes(q)
  )
}

const fetchFaultPhenomena = async (deviceType) => {
  try {
    const params = {}
    if (deviceType) params.device_type = deviceType
    const res = await request.get('/categories/data/fault-phenomena', { params })
    faultPhenomenaOptions.value = res.data || []
  } catch { faultPhenomenaOptions.value = [] }
}

const fetchRootCauses = async () => {
  try {
    const res = await request.get('/categories/data/root-causes')
    rootCauseOptions.value = res.data || []
  } catch { rootCauseOptions.value = [] }
}

const onDeviceChange = async (deviceId) => {
  if (!deviceId) {
    form.device_type = ''
    form.location = ''
    deviceMaintenance.value = null
    fetchFaultPhenomena()
    return
  }
  const d = devices.value.find(d => d.id === deviceId)
  if (d) {
    form.device_type = d.device_type || ''
    form.location = d.location || ''
    fetchFaultPhenomena(d.device_type)
  }
  try {
    const res = await request.get(`/devices/${deviceId}/maintenance-summary`)
    deviceMaintenance.value = res
  } catch { deviceMaintenance.value = null }
}

const onFaultPhenomenonChange = (val) => {
  if (val && val.length >= 2) {
    form.fault_category = val[0]
    form.fault_phenomenon_type = val.join(' > ')
  } else if (val && val.length === 1) {
    form.fault_category = val[0]
    form.fault_phenomenon_type = val[0]
  } else {
    form.fault_category = ''
    form.fault_phenomenon_type = ''
  }
}

const onRootCauseChange = (val) => {
  if (val && val.length >= 2) {
    form.root_cause_category = val[0]
    form.root_cause_type = val.join(' > ')
  } else if (val && val.length === 1) {
    form.root_cause_category = val[0]
    form.root_cause_type = val[0]
  } else {
    form.root_cause_category = ''
    form.root_cause_type = ''
  }
}

const onRepairResultChange = (val) => {
  if (val !== 'TEMPORARY_FIX' && val !== 'UNABLE_FIX') {
    form.follow_up_plan = ''
  }
}

const calcWorkHours = () => {
  if (timeRange.value && timeRange.value.length === 2 && timeRange.value[0] && timeRange.value[1]) {
    const diff = timeRange.value[1].getTime() - timeRange.value[0].getTime()
    form.work_hours = Math.round((diff / (1000 * 60 * 60)) * 10) / 10
  } else {
    form.work_hours = null
  }
}

const uploadFile = async (option) => {
  const formData = new FormData()
  formData.append('file', option.file)
  try {
    const res = await request.post('/upload/work-order-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    attachments.value.push({ url: res.url, name: res.name, type: res.type })
    option.onSuccess(res)
  } catch (e) {
    option.onError(e)
    ElMessage.error('文件上传失败')
  }
}

const beforeUpload = (file) => {
  const maxSize = 50 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.warning('文件大小不能超过 50MB')
    return false
  }
  return true
}

const removeAttachment = (uploadFile) => {
  const idx = attachments.value.findIndex(f => f.name === uploadFile.name)
  if (idx >= 0) attachments.value.splice(idx, 1)
}

const openKnowledgeRef = () => {
  knowledgeDialog.keyword = [form.fault_description, form.fault_phenomenon_type, form.device_type]
    .filter(Boolean).join(' ')
  knowledgeDialog.results = []
  knowledgeDialog.visible = true
  if (knowledgeDialog.keyword) searchSolutions()
}

const searchSolutions = async () => {
  if (!knowledgeDialog.keyword.trim()) return
  knowledgeDialog.searching = true
  try {
    const params = { keyword: knowledgeDialog.keyword.trim(), top_k: 10 }
    if (form.device_type) params.device_type = form.device_type
    const res = await request.get('/knowledge/solutions', { params })
    knowledgeDialog.results = res.results || []
  } catch {
    ElMessage.error('搜索失败')
    knowledgeDialog.results = []
  } finally {
    knowledgeDialog.searching = false
  }
}

const applySolution = (item) => {
  form.solution_steps = item.solution_steps || ''
  form.solution_ref_knowledge_id = item.knowledge_id
  knowledgeDialog.visible = false
  ElMessage.success(`已引用知识库方案: ${item.title}`)
}

const applyAIFields = () => {
  if (!analysisResult.value) return
  const a = analysisResult.value
  if (a.standardized_fault_code && (!form.fault_code || (Array.isArray(form.fault_code) && form.fault_code.length === 0))) {
    form.fault_code = [a.standardized_fault_code]
  }
  if (a.device_type && !form.device_type) form.device_type = a.device_type
  if (a.standardized_fault_phenomenon && !form.fault_phenomenon_type) {
    form.fault_phenomenon_type = a.standardized_fault_phenomenon
  }
  if (a.standardized_root_cause && !form.root_cause) {
    form.root_cause = a.standardized_root_cause
  }
  if (a.standardized_solution_steps && !form.solution_steps) {
    form.solution_steps = a.standardized_solution_steps
  }
  ElMessage.success('AI 推荐字段已填充')
}

const searchDevices = (query) => {
  if (!query) { deviceFiltered.value = devices.value; return }
  const q = query.toLowerCase()
  deviceFiltered.value = devices.value.filter(d =>
    (d.device_name && d.device_name.toLowerCase().includes(q)) ||
    (d.device_code && d.device_code.toLowerCase().includes(q))
  )
}

let sparePartSearchTimer = null
const filterSpareParts = (query) => {
  if (sparePartSearchTimer) clearTimeout(sparePartSearchTimer)
  if (!query) { sparePartOptions.value = [...spareParts.value]; return }
  
  // 清理关键词：去掉常见干扰词
  const cleanedQuery = query.replace(/(库存|记录|备件|零件|等)/g, '').trim() || query
  
  sparePartSearchTimer = setTimeout(async () => {
    try {
      const res = await request.get('/spare-parts/', { 
        params: { keyword: cleanedQuery, page_size: 50 } 
      })
      sparePartOptions.value = res.items || []
    } catch {
      // 降级为本地过滤
      const q = query.toLowerCase()
      sparePartOptions.value = spareParts.value.filter(sp =>
        sp.part_code.toLowerCase().includes(q) ||
        sp.part_name.toLowerCase().includes(q) ||
        (sp.specification && sp.specification.toLowerCase().includes(q))
      )
    }
  }, 300)
}

const onSelectVisible = (visible) => {
  if (visible) sparePartOptions.value = [...spareParts.value]
}

const onPartSelected = (code, idx) => {
  if (!code) {
    usedParts.value[idx].name = ''
    usedParts.value[idx].stock = 0
    usedParts.value[idx].maxStock = 999
    return
  }
  const sp = spareParts.value.find(s => s.part_code === code)
  if (sp) {
    usedParts.value[idx].name = sp.part_name
    usedParts.value[idx].stock = sp.stock_quantity
    usedParts.value[idx].maxStock = sp.stock_quantity
    if (usedParts.value[idx].qty > sp.stock_quantity) {
      usedParts.value[idx].qty = sp.stock_quantity > 0 ? sp.stock_quantity : 1
    }
  }
}

const handleUrgentOrder = (part) => {
  const sp = spareParts.value.find(s => s.part_code === part.code)
  const name = sp ? `${sp.part_code} - ${sp.part_name}` : part.code
  ElMessageBox.confirm(
    `备件「${name}」库存不足（缺 ${part.qty - part.stock} 个），是否发起紧急采购申请？`,
    '紧急采购',
    { confirmButtonText: '确认申请', cancelButtonText: '取消', type: 'warning' }
  ).then(() => {
    ElMessage.success(`已提交紧急采购申请: ${name}`)
  }).catch(() => {})
}

const disabledDate = (time) => time.getTime() > Date.now()

const saveForm = async () => {
  try {
    const validFields = [
      'device_id','fault_code','fault_description','fault_phenomenon',
      'fault_category','fault_phenomenon_type',
      'root_cause','root_cause_category','root_cause_type',
      'solution_steps','solution_ref_knowledge_id',
      'repair_result','follow_up_plan','work_hours',
      'used_parts','assignee_id',
      'location','status','tags','attachments',
      'device_error_code','log_text',
    ]
    const data = { fault_description: form.fault_description || '' }
    for (const k of validFields) {
      let val = form[k]
      if (val === undefined || val === null) continue
      if (k === 'fault_code') {
        if (Array.isArray(val) && val.length > 0) {
          data[k] = val.join(',')
        }
        continue
      }
      if (val !== '') data[k] = val
    }
    if (timeRange.value) {
      data.start_time = timeRange.value[0]?.toISOString()
      data.end_time = timeRange.value[1]?.toISOString()
    }
    if (usedParts.value.length) data.used_parts = usedParts.value
    if (attachments.value.length) data.attachments = attachments.value

    if (isNew.value) {
      const res = await request.post('/work-orders/', data)
      form.id = res.id
      router.replace(`/work-orders/${res.id}?edit=1`)
      return res
    } else {
      return await request.put(`/work-orders/${route.params.id}`, data)
    }
  } catch (e) {
    ElMessage.error('保存失败')
    throw e
  }
}

const handleArchiveCheck = async () => {
  archiving.value = true
  try {
    const id = route.params.id || form.id
    await saveForm()
    const res = await request.post(`/work-orders/${id}/archive-check`)
    archiveCheckResult.value = res
    if (res.passed) {
      ElMessage.success(`归档校验通过（完成度 ${Math.round(res.completeness * 100)}%）`)
    } else {
      ElMessage.warning(`归档完成度不足（${Math.round(res.completeness * 100)}%），缺失：${(res.missing_fields || []).join('、')}`)
    }
  } catch { /* 错误提示由请求拦截器统一处理 */ }
  finally { archiving.value = false }
}

const handleArchiveComplete = async () => {
  if (!canArchiveComplete.value) return
  archiving.value = true
  try {
    const id = route.params.id || form.id
    await saveForm()
    const res = await request.post(`/work-orders/${id}/archive-complete`, null, { timeout: 120000 })
    ElMessage.success('工单归档完成，知识已收录')
    router.push('/work-orders')
  } catch { /* 错误提示由请求拦截器统一处理 */ }
  finally { archiving.value = false }
}

const handleAnalyze = async () => {
  if (!form.fault_description) {
    ElMessage.warning('请填写故障描述')
    return
  }
  analyzing.value = true
  try {
    try { await saveForm() } catch { analyzing.value = false; return }
    const targetId = route.params.id || form.id
    if (!targetId) {
      ElMessage.warning('请先保存工单基本信息')
      analyzing.value = false
      return
    }
    const res = await request.post(`/work-orders/${targetId}/analyze`)
    analysisResult.value = res
    ElMessage.success('AI 校验完成')
  } catch { ElMessage.error('AI 校验失败') }
  finally { analyzing.value = false }
}

const handleSubmit = async () => {
  if (!canSubmit.value) return
  try {
    await ElMessageBox.confirm(
      '确认提交该工单？提交后系统将自动提取知识并上传到公司知识库。',
      '提交确认',
      { confirmButtonText: '确认提交', cancelButtonText: '取消', type: 'warning', customClass: 'submit-confirm-dialog' }
    )
  } catch { return }
  submitting.value = true
  try {
    const id = route.params.id || form.id
    await saveForm()
    const res = await request.post(`/work-orders/${id}/complete`, null, { timeout: 120000 })
    if (res.knowledge_synced) {
      ElMessage.success('工单已提交完成，知识已自动收录')
    } else {
      ElMessage.info('工单已提交完成（检测到相似知识，未重复收录到知识库）')
    }
    router.push('/work-orders')
  } catch { ElMessage.error('提交失败') }
  finally { submitting.value = false }
}

const handleSaveDraft = async () => {
  saving.value = true
  try {
    await saveForm()
    ElMessage.success('草稿已保存')
  } catch { /* error handled in saveForm */ }
  finally { saving.value = false }
}

const handleCreateFaultCode = async () => {
  if (!faultCodeDialog.description.trim()) {
    ElMessage.warning('请填写故障描述')
    return
  }
  faultCodeDialog.creating = true
  try {
    const res = await request.post('/fault-codes/create', {
      fault_description: faultCodeDialog.description.trim(),
      device_type: form.device_type || undefined,
    })
    faultCodeDialog.result = res
    fetchFaultCodes()
    if (res.is_new) {
      ElMessage.success(`新故障码 ${res.fault_code} 已自动生成`)
    } else {
      ElMessage.info(res.duplicate_hint)
    }
  } catch (e) {
    ElMessage.error('新增故障码失败')
  } finally {
    faultCodeDialog.creating = false
  }
}

const confirmFaultCodeResult = () => {
  if (faultCodeDialog.result && faultCodeDialog.result.fault_code) {
    const code = faultCodeDialog.result.fault_code
    if (!form.fault_code.includes(code)) {
      form.fault_code.push(code)
    }
  }
  faultCodeDialogClose()
}

const faultCodeDialogClose = () => {
  faultCodeDialog.visible = false
  setTimeout(() => {
    faultCodeDialog.description = ''
    faultCodeDialog.result = null
  }, 200)
}

const askAI = async (type) => {
  if (form.fault_description) {
    try { await saveForm() } catch { /* ignore */ }
  }

  let context = `我正在填写维修工单，请帮我分析：\n`
  if (form.device_id) {
    const d = devices.value.find(d => d.id === form.device_id)
    context += `设备：${d?.device_name || '未知'}\n`
  }
  if (form.device_type) context += `设备类型：${form.device_type}\n`
  if (form.location) context += `位置：${form.location}\n`
  context += `故障描述：${form.fault_description || '（未填写）'}\n`
  if (form.fault_phenomenon_type) context += `故障现象分类：${form.fault_phenomenon_type}\n`
  if (form.fault_phenomenon) context += `故障现象补充：${form.fault_phenomenon}\n`

  if (type === 'diagnosis') {
    if (form.root_cause_type) context += `根本原因分类：${form.root_cause_type}\n`
    if (form.root_cause) context += `根本原因说明：${form.root_cause}\n`
    if (form.solution_steps) context += `处理步骤：${form.solution_steps}\n`
    if (form.fault_code && (Array.isArray(form.fault_code) ? form.fault_code.length : form.fault_code)) {
      const codes = Array.isArray(form.fault_code) ? form.fault_code.join(', ') : form.fault_code
      context += `故障码：${codes}\n`
    }
    context += `\n请根据以上信息分析可能的根本原因，并推荐处理方案。`
  } else {
    context += `\n请帮我分析故障分类、可能原因，并给出诊断建议（包括可能的故障码）。`
  }

  aiDialog.messages = [{ role: 'user', content: context }]
  aiDialog.input = ''
  aiDialog.visible = true
  sendAIMessage()
}

const sendAIMessage = async () => {
  const text = aiDialog.input.trim()
  if (!text && aiDialog.messages.length === 1) { /* auto-send */ }
  else if (!text) return

  if (text) {
    aiDialog.messages.push({ role: 'user', content: text })
    aiDialog.input = ''
  }

  const question = aiDialog.messages[aiDialog.messages.length - 1].content
  const aiMsg = { role: 'assistant', content: '' }
  aiDialog.messages.push(aiMsg)
  aiDialog.loading = true

  try {
    const response = await fetch('/api/v1/search/answer/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 5 }),
    })

    if (!response.ok) {
      aiMsg.content = '请求失败，请稍后重试。'
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'answer' && data.content) {
            aiMsg.content += data.content
          }
        } catch { /* skip */ }
      }
      await nextTick()
      if (aiMsgRef.value) aiMsgRef.value.scrollTop = aiMsgRef.value.scrollHeight
    }

    if (!aiMsg.content) aiMsg.content = '抱歉，无法生成回答。'
  } catch (e) {
    console.error('AI 发送失败:', e)
    aiMsg.content = '请求失败，请稍后重试。'
  } finally {
    aiDialog.loading = false
    await nextTick()
    if (aiMsgRef.value) aiMsgRef.value.scrollTop = aiMsgRef.value.scrollHeight
  }
}

onMounted(async () => {
  fetchFaultCodes()
  fetchFaultPhenomena()
  fetchRootCauses()

  try {
    const [dRes, uRes, spRes] = await Promise.all([
      request.get('/devices/', { params: { page_size: 200 } }),
      request.get('/users/', { params: { page_size: 200 } }),
      request.get('/spare-parts/', { params: { page_size: 100 } }),
    ])
    devices.value = dRes.items || []
    deviceFiltered.value = dRes.items || []
    users.value = uRes.items || []
    spareParts.value = spRes.items || []
    sparePartOptions.value = spRes.items || []
    // 维修员由后端强制设为当前登录用户（号主），前端无需设置 technician_id
  } catch { /* ignore */ }

  loadDeviceTypes()

  if (route.params.id && !route.path.endsWith('/new')) {
    try {
      const res = await request.get(`/work-orders/${route.params.id}`)
      Object.assign(form, res)

      if (typeof res.fault_code === 'string' && res.fault_code) {
        form.fault_code = res.fault_code.split(',').map(c => c.trim()).filter(Boolean)
      } else if (!res.fault_code) {
        form.fault_code = []
      }

      if (res.start_time && res.end_time) {
        timeRange.value = [dayjs(res.start_time).toDate(), dayjs(res.end_time).toDate()]
        calcWorkHours()
      }

      usedParts.value = (res.used_parts || []).map(p => {
        const sp = spareParts.value.find(s => s.part_code === p.code)
        return { name: p.name || '', code: p.code || '', qty: p.qty || 1, stock: sp?.stock_quantity ?? 0, maxStock: sp?.stock_quantity ?? 999 }
      })

      if (res.attachments && Array.isArray(res.attachments)) {
        attachments.value = res.attachments
        uploadFileList.value = res.attachments.map((f, i) => ({ uid: i, name: f.name, url: f.url, status: 'success' }))
      }

      if (res.fault_phenomenon_type) {
        faultPhenomenonCascader.value = res.fault_phenomenon_type.split(' > ')
        if (res.device_type) fetchFaultPhenomena(res.device_type)
      }
      if (res.root_cause_type) {
        rootCauseCascader.value = res.root_cause_type.split(' > ')
      }

      analysisResult.value = res.analysis_result || null

      if (res.analysis_result?.device_type && !res.device_type) {
        form.device_type = res.analysis_result.device_type
      } else if (res.device_id && !res.device_type) {
        try {
          const dRes2 = await request.get(`/devices/${res.device_id}`)
          form.device_type = dRes2.device_type || ''
        } catch { /* ignore */ }
      }

      if (res.device_id) onDeviceChange(res.device_id)
    } catch { ElMessage.error('加载工单失败') }
  }
})
</script>

<style scoped>
.form-body { max-width: 860px; margin: 0 auto; }
.form-card { padding: 16px; }
.form-section { margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #E5E6EB; }
.form-section:last-of-type { border-bottom: none; }
.section-header { font-size: 15px; font-weight: 600; color: #1D2129; margin-bottom: 16px; }
.form-grid { max-width: 720px; }
.analysis-card { margin-bottom: 16px; border: 1px solid #FFD666; background: #FFFBE6; }
.analysis-card :deep(.el-card__header) { background: #FFF7D6; border-bottom: 1px solid #FFE58F; padding: 10px 16px; }
.card-header-row { display: flex; justify-content: space-between; align-items: center; }
.section-title { font-size: 14px; font-weight: 600; color: #D48806; }
.form-footer { display: flex; gap: 12px; justify-content: center; margin-top: 24px; padding-bottom: 40px; }
.submit-hint { font-size: 12px; color: #FF7D00; text-align: center; margin-top: 8px; }
.parts-list { display: flex; flex-direction: column; gap: 8px; }
.part-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.part-stock-tip { font-size: 12px; color: #86909C; white-space: nowrap; }
.part-stock-tip.stock-warning { color: #F53F3F; }
.stock-short { font-weight: 600; }
.qty-over-stock :deep(.el-input__inner) { border-color: #F53F3F !important; }
.qty-over-stock :deep(.el-input-number__decrease),
.qty-over-stock :deep(.el-input-number__increase) { border-color: #F53F3F !important; }
.spare-option { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.spare-code { color: #1D2129; font-weight: 600; min-width: 80px; }
.spare-name { color: #4E5969; flex: 1; }
.spare-spec { color: #86909C; font-size: 12px; }
.spare-option-info { display: flex; justify-content: space-between; align-items: center; font-size: 12px; padding-top: 2px; }
.spare-stock { color: #00B42A; }
.spare-stock.stock-low { color: #FF7D00; }
.spare-stock.stock-out { color: #F53F3F; }
.spare-location { color: #86909C; }
.solution-area { width: 100%; display: flex; flex-direction: column; }
.upload-hint { font-size: 12px; color: #86909C; margin-top: 4px; }
.cascader-hint { font-size: 12px; color: #86909C; margin-top: 4px; line-height: 1.4; }
.fault-code-row { display: flex; gap: 8px; align-items: flex-start; width: 100%; }
.fc-option { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.fc-code { font-weight: 600; color: #E6A23C; min-width: 70px; text-align: left; }
.fc-desc { color: #4E5969; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; text-align: right; margin-left: 16px; }
.attach-gallery { display: flex; gap: 8px; flex-wrap: wrap; }
.attach-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.attach-thumb { width: 80px; height: 80px; object-fit: cover; border-radius: 4px; border: 1px solid #E5E6EB; }
.attach-name { font-size: 11px; color: #86909C; max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-dialog-body { display: flex; flex-direction: column; gap: 12px; }
.ai-dialog-msgs { max-height: 400px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 8px; }
.ai-msg-row { max-width: 85%; }
.ai-msg-row.user { align-self: flex-end; }
.ai-msg-row.assistant { align-self: flex-start; }
.ai-msg-bubble { padding: 10px 14px; border-radius: 8px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.ai-msg-row.user .ai-msg-bubble { background: var(--color-primary); color: #fff; }
.ai-msg-row.assistant .ai-msg-bubble { background: #F2F3F5; color: #1D2129; }
.ai-msg-bubble.thinking { color: #C9CDD4; font-style: italic; }
.ai-dialog-input { border-top: 1px solid #E5E6EB; padding-top: 12px; }
.knowledge-dialog { display: flex; flex-direction: column; gap: 12px; }
.kd-search { display: flex; gap: 8px; }
.kd-results { max-height: 420px; overflow-y: auto; }
.kd-empty { text-align: center; color: #C9CDD4; padding: 40px 0; font-size: 14px; }
.kd-item { border: 1px solid #E5E6EB; border-radius: 6px; padding: 12px; margin-bottom: 8px; cursor: pointer; transition: border-color 0.2s; }
.kd-item:hover { border-color: var(--color-primary); }
.kd-item-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.kd-title { font-weight: 600; font-size: 14px; color: #1D2129; flex: 1; }
.kd-steps { margin: 0 0 8px; padding: 8px; background: #F7F8FA; border-radius: 4px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; font-family: inherit; color: #4E5969; }
.kd-item-footer { display: flex; justify-content: space-between; align-items: center; }
.kd-count { font-size: 12px; color: #86909C; }
.detail-card { max-width: 900px; margin: 0 auto; padding: 16px; }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.detail-header h3 { font-size: 18px; font-weight: 600; color: #1D2129; margin: 0; }
.detail-pre { margin: 0; white-space: pre-wrap; font-family: inherit; font-size: 14px; line-height: 1.7; }
.detail-footer { margin-top: 24px; display: flex; justify-content: center; }
.fc-dialog-footer { display: flex; gap: 8px; justify-content: flex-end; }
.submit-confirm-dialog .el-message-box__btns .el-button:not(.el-button--primary) {
  background: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
  color: #fff !important;
}
.submit-confirm-dialog .el-message-box__btns .el-button:not(.el-button--primary):hover {
  background: #0db3af !important;
  border-color: #0db3af !important;
  color: #fff !important;
}
.submit-confirm-dialog .el-message-box__btns .el-button--primary {
  background: #52c41a !important;
  border-color: var(--color-primary) !important;
}
.submit-confirm-dialog .el-message-box__btns .el-button--primary:hover {
  background: #49ad17 !important;
  border-color: #49ad17 !important;
}
/* 录入模式切换 */
.mode-switch-bar { display: flex; align-items: center; gap: 12px; max-width: 860px; margin: 0 auto 16px; }
.mode-switch-label { font-size: 13px; color: #86909C; }
.mode-switch {
  display: flex; gap: 4px; background: #F2F3F5; border-radius: 8px; padding: 3px;
}
.mode-tab {
  padding: 5px 14px; border-radius: 6px; font-size: 13px; cursor: pointer;
  color: #86909C; font-weight: 500; transition: all .2s; white-space: nowrap;
}
.mode-tab:hover { color: #4E5969; }
.mode-tab.active { background: #fff; color: #0FC6C2; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }
/* 错误码检索预填 */
.error-code-card { margin-bottom: 16px; }
.error-code-card :deep(.el-card__header) { padding: 10px 16px; }
.mode-tip { font-size: 12px; color: #86909C; }
.ec-search { display: flex; gap: 8px; margin-bottom: 12px; align-items: flex-start; }
.ec-search .el-button { margin-top: 2px; }
.ec-error { color: #F53F3F; font-size: 13px; margin-bottom: 8px; }
.ec-results { max-height: 480px; overflow-y: auto; }
.ec-group { margin-bottom: 14px; }
.ec-group-title { font-size: 13px; font-weight: 600; color: #4E5969; margin-bottom: 8px; }
.ec-item { border: 1px solid #E5E6EB; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
.ec-item.manual { border-left: 3px solid #FF7D00; background: #FFFDF9; }
.ec-item.case { border-left: 3px solid var(--color-primary); }
.ec-item-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.ec-code { font-weight: 700; color: #E6A23C; font-size: 14px; }
.ec-title { font-weight: 600; font-size: 14px; color: #1D2129; }
.ec-desc { font-size: 13px; color: #4E5969; line-height: 1.6; margin-bottom: 6px; }
.ec-msg {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  color: #1D2129;
  background: #F7F8FA;
  border-left: 3px solid #C9CDD4;
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 6px;
  white-space: pre-wrap;
}
.ec-block { font-size: 13px; color: #4E5969; line-height: 1.7; margin-bottom: 4px; }
.ec-block-label { font-weight: 600; color: #1D2129; margin-right: 6px; }
.ec-item-footer { display: flex; justify-content: flex-end; margin-top: 6px; }
.ec-empty { text-align: center; color: #C9CDD4; padding: 30px 0; font-size: 14px; }
.ec-codes-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.ec-codes-label { font-size: 13px; font-weight: 600; color: #4E5969; }
.ec-code-tag { font-family: Consolas, Monaco, monospace; font-weight: 700; }
.ec-code-input { width: 170px; }
.ec-code-empty { font-size: 12px; color: #86909C; }
.ec-cond-list { margin: 6px 0; }
.ec-cond-head { font-size: 12px; color: #86909C; margin-bottom: 6px; }
.ec-cond-group { display: flex; flex-direction: column; gap: 4px; }
.ec-cond { height: auto; align-items: flex-start; white-space: normal; margin-right: 0; }
.ec-cond :deep(.el-checkbox__label) { white-space: normal; line-height: 1.5; }
.ec-cond-signal { font-weight: 600; color: #FF7D00; font-size: 13px; }
.ec-cond-cause { color: #4E5969; font-size: 12px; margin-left: 6px; }
/* 补充信息折叠区 */
.supplement-collapse { border: none; }
.supplement-collapse :deep(.el-collapse-item__header) { background: #F7F8FA; border-radius: 6px; padding: 0 14px; font-size: 14px; font-weight: 600; }
.supplement-collapse :deep(.el-collapse-item__content) { padding: 14px 4px 0; }
.supplement-badge { margin-left: 8px; }
.supplement-body { padding-left: 4px; }
</style>
