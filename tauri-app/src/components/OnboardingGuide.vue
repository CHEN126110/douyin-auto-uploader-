<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';

const emit = defineEmits<{
  (e: 'complete'): void;
}>();

const showGuide = ref(false);
const currentStep = ref(0);

// 引导步骤
const steps = [
  {
    title: '欢迎使用抖音袜子发布工具 🎉',
    description: '这是一款帮助您快速发布商品到抖音电商平台的工具。接下来让我们快速了解主要功能。',
    icon: '👋',
    image: null
  },
  {
    title: '第一步：采集商品 🔗',
    description: '在顶部输入淘宝/天猫商品链接，点击"开始采集"，系统会自动采集商品信息、图片和SKU数据。',
    icon: '📥',
    tips: ['支持淘宝、天猫链接', '自动提取标题、价格、规格', '自动下载商品图片']
  },
  {
    title: '第二步：编辑商品 ✏️',
    description: '采集完成后，您可以在列表中编辑商品信息，包括标题、价格、SKU等。',
    icon: '📝',
    tips: ['智能定价：根据成本自动计算售价', '批量编辑：高效处理多个商品', '图片管理：调整主图和详情图']
  },
  {
    title: '第三步：一键上传 🚀',
    description: '选择要上传的商品，点击"上传"按钮，系统会自动打开浏览器并完成商品发布。',
    icon: '☁️',
    tips: ['自动填写商品信息', '自动选择类目和属性', '自动上传图片']
  },
  {
    title: '开始前的准备 ⚙️',
    description: '使用前请确保：',
    icon: '✅',
    tips: [
      '已安装 Google Chrome 浏览器',
      '已登录抖音商家后台',
      '在设置中配置好运费模板'
    ]
  },
  {
    title: '准备就绪！ 🎊',
    description: '现在您可以开始使用了！如有问题，随时点击右上角的设置按钮查看帮助。',
    icon: '🎯',
    tips: null
  }
];

const totalSteps = computed(() => steps.length);
const currentStepData = computed(() => steps[currentStep.value]);
const isLastStep = computed(() => currentStep.value === totalSteps.value - 1);
const progress = computed(() => ((currentStep.value + 1) / totalSteps.value) * 100);

onMounted(() => {
  // 检查是否首次启动
  const hasSeenGuide = localStorage.getItem('onboarding_completed');
  if (!hasSeenGuide) {
    showGuide.value = true;
  }
});

function nextStep() {
  if (currentStep.value < totalSteps.value - 1) {
    currentStep.value++;
  } else {
    completeGuide();
  }
}

function prevStep() {
  if (currentStep.value > 0) {
    currentStep.value--;
  }
}

function skipGuide() {
  completeGuide();
}

function completeGuide() {
  localStorage.setItem('onboarding_completed', 'true');
  localStorage.setItem('onboarding_completed_at', new Date().toISOString());
  showGuide.value = false;
  emit('complete');
}

// 重新显示引导（供外部调用）
function showOnboarding() {
  currentStep.value = 0;
  showGuide.value = true;
}

defineExpose({ showOnboarding });
</script>

<template>
  <Teleport to="body">
    <Transition name="guide-fade">
      <div v-if="showGuide" class="onboarding-overlay">
        <div class="onboarding-modal">
          <!-- 进度条 -->
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
          </div>
          
          <!-- 步骤指示器 -->
          <div class="step-indicator">
            <span 
              v-for="(_, index) in steps" 
              :key="index"
              class="step-dot"
              :class="{ 
                active: index === currentStep,
                completed: index < currentStep 
              }"
              @click="currentStep = index"
            ></span>
          </div>

          <!-- 内容区域 -->
          <div class="guide-content">
            <Transition name="slide-fade" mode="out-in">
              <div :key="currentStep" class="step-content">
                <!-- 图标 -->
                <div class="step-icon">{{ currentStepData.icon }}</div>
                
                <!-- 标题 -->
                <h2 class="step-title">{{ currentStepData.title }}</h2>
                
                <!-- 描述 -->
                <p class="step-description">{{ currentStepData.description }}</p>
                
                <!-- 提示列表 -->
                <ul v-if="currentStepData.tips" class="tips-list">
                  <li v-for="(tip, index) in currentStepData.tips" :key="index">
                    <span class="tip-icon">✓</span>
                    <span>{{ tip }}</span>
                  </li>
                </ul>
              </div>
            </Transition>
          </div>

          <!-- 底部按钮 -->
          <div class="guide-footer">
            <button 
              v-if="currentStep > 0" 
              class="btn btn-secondary"
              @click="prevStep"
            >
              上一步
            </button>
            <button 
              v-else 
              class="btn btn-text"
              @click="skipGuide"
            >
              跳过引导
            </button>
            
            <button 
              class="btn btn-primary"
              @click="nextStep"
            >
              {{ isLastStep ? '开始使用' : '下一步' }}
            </button>
          </div>

          <!-- 关闭按钮 -->
          <button class="close-btn" @click="skipGuide">
            ✕
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style lang="scss" scoped>
.onboarding-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 99999;
}

.onboarding-modal {
  background: linear-gradient(145deg, #1a1f36, #252b4a);
  border-radius: 24px;
  width: 560px;
  max-width: 90vw;
  max-height: 85vh;
  overflow: hidden;
  box-shadow: 
    0 25px 80px rgba(0, 0, 0, 0.5),
    0 0 0 1px rgba(255, 255, 255, 0.1);
  position: relative;
}

// 进度条
.progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #5c7cfa, #7c5cfa);
    transition: width 0.3s ease;
  }
}

// 步骤指示器
.step-indicator {
  display: flex;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  
  .step-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.2);
    cursor: pointer;
    transition: all 0.3s ease;
    
    &:hover {
      background: rgba(255, 255, 255, 0.4);
      transform: scale(1.2);
    }
    
    &.active {
      background: #5c7cfa;
      box-shadow: 0 0 10px rgba(92, 124, 250, 0.5);
    }
    
    &.completed {
      background: #4ade80;
    }
  }
}

// 内容区域
.guide-content {
  padding: 0 48px 32px;
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-content {
  text-align: center;
}

.step-icon {
  font-size: 72px;
  margin-bottom: 24px;
  animation: bounce 2s ease infinite;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.step-title {
  font-size: 24px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 16px;
  letter-spacing: -0.5px;
}

.step-description {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.6;
  margin-bottom: 24px;
}

// 提示列表
.tips-list {
  list-style: none;
  padding: 0;
  margin: 0;
  text-align: left;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 16px 20px;
  
  li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
    color: rgba(255, 255, 255, 0.85);
    font-size: 14px;
    
    &:not(:last-child) {
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
  }
  
  .tip-icon {
    color: #4ade80;
    font-weight: bold;
  }
}

// 底部按钮
.guide-footer {
  display: flex;
  justify-content: space-between;
  padding: 20px 48px 32px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.btn {
  padding: 12px 32px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  
  &.btn-primary {
    background: linear-gradient(135deg, #5c7cfa, #7c5cfa);
    color: white;
    box-shadow: 0 4px 15px rgba(92, 124, 250, 0.4);
    
    &:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(92, 124, 250, 0.5);
    }
  }
  
  &.btn-secondary {
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.8);
    
    &:hover {
      background: rgba(255, 255, 255, 0.15);
    }
  }
  
  &.btn-text {
    background: transparent;
    color: rgba(255, 255, 255, 0.5);
    
    &:hover {
      color: rgba(255, 255, 255, 0.8);
    }
  }
}

// 关闭按钮
.close-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  
  &:hover {
    background: rgba(255, 255, 255, 0.2);
    color: white;
  }
}

// 动画
.guide-fade-enter-active,
.guide-fade-leave-active {
  transition: opacity 0.3s ease;
}

.guide-fade-enter-from,
.guide-fade-leave-to {
  opacity: 0;
}

.slide-fade-enter-active {
  transition: all 0.3s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.2s ease-in;
}

.slide-fade-enter-from {
  opacity: 0;
  transform: translateX(30px);
}

.slide-fade-leave-to {
  opacity: 0;
  transform: translateX(-30px);
}
</style>
