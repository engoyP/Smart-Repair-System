<template>
  <div class="worker-submit">
    <!-- 扫码区 -->
    <div class="scan-area" @click="handleScan">
      <div class="scan-icon">📷</div>
      <div class="scan-text">扫码识别设备</div>
      <div class="scan-code" v-if="form.device_code">{{ form.device_code }}</div>
    </div>

    <!-- 故障描述 -->
    <div class="form-section">
      <label class="form-label">故障描述 *</label>
      <textarea
        v-model="form.fault_description"
        class="fault-input"
        placeholder="请描述故障现象..."
        rows="4"
      ></textarea>
    </div>

    <!-- 快捷选项 -->
    <div class="quick-options">
      <span class="option-label">常见故障：</span>
      <span
        v-for="opt in quickOptions"
        :key="opt"
        class="option-chip"
        @click="form.fault_description = opt"
      >{{ opt }}</span>
    </div>

    <!-- 拍照/录音 -->
    <div class="media-toolbar">
      <div class="media-btn" @click="handleCamera">
        <span>📷</span>
        <span>拍照</span>
      </div>
      <div class="media-btn" @click="handleVoice">
        <span>🎤</span>
        <span>语音</span>
      </div>
      <div class="media-btn" @click="handleGallery">
        <span>🖼</span>
        <span>相册</span>
      </div>
    </div>

    <!-- 媒体预览 -->
    <div class="media-preview" v-if="mediaList.length">
      <img v-for="(url, i) in mediaList" :key="i" :src="url" class="preview-img" />
    </div>

    <!-- 位置 -->
    <div class="form-section">
      <label class="form-label">故障位置</label>
      <input v-model="form.location" class="form-input" placeholder="点击自动定位" @focus="getLocation" />
    </div>

    <!-- 提交按钮 -->
    <button class="submit-btn" @click="handleSubmit" :disabled="submitting || !form.fault_description.trim()">
      {{ submitting ? '提交中...' : '提交工单' }}
    </button>

    <!-- 提交结果 -->
    <div v-if="result" class="result-card">
      <div class="result-icon">✓</div>
      <div class="result-title">上报成功</div>
      <div class="result-no">{{ result.work_order_no }}</div>
      <div class="result-msg">{{ result.message }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import request from '../../api'

const form = reactive({
  device_code: '',
  fault_description: '',
  location: '',
  media: [],
})

const mediaList = ref([])
const submitting = ref(false)
const result = ref(null)

const quickOptions = [
  '设备异响',
  '温度过高',
  '设备不启动',
  '漏油/漏水',
  '精度偏差',
  '显示屏故障',
]

const handleScan = () => {
  // 模拟扫码（实际接入钉钉 JSAPI dd.biz.util.scan）
  const codes = ['EQ-001', 'EQ-002', 'MTR-005', 'PUMP-003', 'CNC-001']
  form.device_code = codes[Math.floor(Math.random() * codes.length)]
}

const handleCamera = () => {
  // 模拟拍照（实际接入钉钉 JSAPI dd.biz.util.uploadImage）
  const url = `https://via.placeholder.com/200x150/1677FF/fff?text=Photo_${Date.now()}`
  mediaList.value.push(url)
  form.media.push(url)
}

const handleVoice = () => {
  // 模拟录音（实际接入钉钉 JSAPI dd.device.audio.startRecord）
  const text = '语音已记录: ' + new Date().toLocaleTimeString()
  mediaList.value.push(text)
  form.media.push(text)
}

const handleGallery = () => {
  // 模拟选图（实际接入钉钉 JSAPI dd.biz.util.chooseImage）
  handleCamera()
}

const getLocation = async () => {
  // 模拟定位
  form.location = '1号车间 A区 3号机位'
}

const handleSubmit = async () => {
  submitting.value = true
  try {
    const payload = {
      device_code: form.device_code,
      fault_description: form.fault_description,
      media: form.media,
      location: form.location,
      reporter_id: 1, // 后续从登录态获取
    }
    const res = await request.post('/dingtalk/report', payload)
    result.value = res
    // 重置表单
    form.device_code = ''
    form.fault_description = ''
    form.location = ''
    form.media = []
    mediaList.value = []
    // 3秒后隐藏结果
    setTimeout(() => { result.value = null }, 3000)
  } catch { /* handled */ }
  finally { submitting.value = false }
}
</script>

<style scoped>
.worker-submit { padding: 16px; }

.scan-area {
  background: linear-gradient(135deg, #1677FF, #4096FF);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
  color: #fff;
  cursor: pointer;
  margin-bottom: 16px;
}
.scan-icon { font-size: 36px; margin-bottom: 8px; }
.scan-text { font-size: 15px; opacity: 0.9; }
.scan-code { margin-top: 8px; font-size: 18px; font-weight: 600; font-family: monospace; }

.form-section { margin-bottom: 14px; }
.form-label { display: block; font-size: 14px; font-weight: 500; color: #1D2129; margin-bottom: 6px; }
.fault-input {
  width: 100%; min-height: 100px; padding: 12px;
  border: 1px solid #D9D9D9; border-radius: 8px;
  font-size: 14px; resize: vertical; box-sizing: border-box;
  outline: none; transition: border-color .2s;
}
.fault-input:focus { border-color: #1677FF; }
.form-input {
  width: 100%; padding: 10px 12px;
  border: 1px solid #D9D9D9; border-radius: 8px;
  font-size: 14px; box-sizing: border-box; outline: none;
}
.form-input:focus { border-color: #1677FF; }

.quick-options { margin-bottom: 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.option-label { font-size: 13px; color: #86909C; }
.option-chip {
  background: #E8F3FF; color: #1677FF; padding: 4px 12px;
  border-radius: 16px; font-size: 13px; cursor: pointer;
}
.option-chip:active { background: #BCD1F0; }

.media-toolbar {
  display: flex; gap: 12px; margin-bottom: 16px;
}
.media-btn {
  flex: 1; text-align: center; padding: 14px 0;
  background: #fff; border: 1px dashed #D9D9D9;
  border-radius: 8px; cursor: pointer; font-size: 13px; color: #4E5969;
}
.media-btn span { display: block; }
.media-btn span:first-child { font-size: 24px; margin-bottom: 4px; }
.media-btn:active { background: #F5F6F8; }

.media-preview { display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto; }
.preview-img { width: 80px; height: 60px; border-radius: 6px; object-fit: cover; flex-shrink: 0; }

.submit-btn {
  width: 100%; padding: 14px; background: #1677FF; color: #fff;
  border: none; border-radius: 8px; font-size: 16px; font-weight: 500;
  cursor: pointer; margin-top: 8px;
}
.submit-btn:disabled { background: #C9CDD4; cursor: not-allowed; }
.submit-btn:active { opacity: 0.9; }

.result-card {
  margin-top: 16px; padding: 24px; background: #E8F8EE;
  border-radius: 12px; text-align: center;
}
.result-icon { font-size: 40px; color: #00B42A; margin-bottom: 8px; }
.result-title { font-size: 18px; font-weight: 600; color: #00B42A; margin-bottom: 8px; }
.result-no { font-size: 16px; font-weight: 600; color: #1D2129; font-family: monospace; }
.result-msg { font-size: 13px; color: #86909C; margin-top: 4px; }
</style>
