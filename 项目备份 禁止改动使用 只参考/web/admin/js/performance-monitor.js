/**
 * 性能监控面板 - 实时性能监控工具
 * 
 * 功能特性：
 * - 实时显示关键性能指标
 * - FPS、内存、网络请求监控
 * - 快捷键控制显示/隐藏
 * - 性能数据导出
 * - 可视化图表展示
 * 
 * @author Frontend Performance Team
 * @version 1.0.0
 */

window.PerformanceMonitorPanel = (function() {
    'use strict';

    /**
     * 性能监控面板类
     */
    function MonitorPanel() {
        this.isVisible = false;
        this.isMinimized = false;
        this.panel = null;
        this.charts = {};
        this.updateInterval = null;
        this.dataHistory = {
            fps: [],
            memory: [],
            network: [],
            dom: []
        };
        this.maxHistoryLength = 60; // 保留60个数据点
        
        this.init();
    }

    MonitorPanel.prototype = {
        /**
         * 初始化监控面板
         */
        init: function() {
            this.createPanel();
            this.bindEvents();
            this.startMonitoring();
            
            console.log('🚀 性能监控面板初始化完成');
        },

        /**
         * 创建监控面板DOM结构
         */
        createPanel: function() {
            // 创建面板容器
            this.panel = document.createElement('div');
            this.panel.id = 'performance-monitor-panel';
            this.panel.className = 'performance-monitor-panel hidden';
            
            this.panel.innerHTML = `
                <div class="monitor-header">
                    <div class="monitor-title">
                        <span class="monitor-icon">📊</span>
                        <span class="monitor-text">性能监控</span>
                    </div>
                    <div class="monitor-controls">
                        <button class="monitor-btn minimize-btn" title="最小化">−</button>
                        <button class="monitor-btn export-btn" title="导出数据">📤</button>
                        <button class="monitor-btn close-btn" title="关闭">×</button>
                    </div>
                </div>
                
                <div class="monitor-content">
                    <!-- 实时指标 -->
                    <div class="monitor-section">
                        <h3 class="section-title">实时指标</h3>
                        <div class="metrics-grid">
                            <div class="metric-card">
                                <div class="metric-label">FPS</div>
                                <div class="metric-value" id="fps-value">--</div>
                                <div class="metric-status" id="fps-status">正常</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-label">内存使用</div>
                                <div class="metric-value" id="memory-value">--</div>
                                <div class="metric-status" id="memory-status">正常</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-label">网络请求</div>
                                <div class="metric-value" id="network-value">--</div>
                                <div class="metric-status" id="network-status">正常</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-label">DOM节点</div>
                                <div class="metric-value" id="dom-value">--</div>
                                <div class="metric-status" id="dom-status">正常</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 性能图表 -->
                    <div class="monitor-section">
                        <h3 class="section-title">性能趋势</h3>
                        <div class="charts-container">
                            <div class="chart-wrapper">
                                <canvas id="fps-chart" width="300" height="100"></canvas>
                                <div class="chart-label">FPS 趋势</div>
                            </div>
                            <div class="chart-wrapper">
                                <canvas id="memory-chart" width="300" height="100"></canvas>
                                <div class="chart-label">内存使用趋势</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 优化建议 -->
                    <div class="monitor-section">
                        <h3 class="section-title">优化建议</h3>
                        <div class="suggestions-list" id="suggestions-list">
                            <div class="suggestion-item">
                                <span class="suggestion-icon">💡</span>
                                <span class="suggestion-text">性能监控已启动</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 快捷操作 -->
                    <div class="monitor-section">
                        <h3 class="section-title">快捷操作</h3>
                        <div class="actions-grid">
                            <button class="action-btn" id="clear-cache-btn">清理缓存</button>
                            <button class="action-btn" id="gc-btn">强制GC</button>
                            <button class="action-btn" id="reset-stats-btn">重置统计</button>
                            <button class="action-btn" id="screenshot-btn">截图</button>
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(this.panel);
        },

        /**
         * 绑定事件监听器
         */
        bindEvents: function() {
            const self = this;
            
            // 快捷键控制 (Ctrl+Shift+P)
            document.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.shiftKey && e.key === 'P') {
                    e.preventDefault();
                    self.toggle();
                }
            });
            
            // 面板控制按钮
            this.panel.querySelector('.minimize-btn').addEventListener('click', function() {
                self.toggleMinimize();
            });
            
            this.panel.querySelector('.export-btn').addEventListener('click', function() {
                self.exportData();
            });
            
            this.panel.querySelector('.close-btn').addEventListener('click', function() {
                self.hide();
            });
            
            // 快捷操作按钮
            this.panel.querySelector('#clear-cache-btn').addEventListener('click', function() {
                self.clearCache();
            });
            
            this.panel.querySelector('#gc-btn').addEventListener('click', function() {
                self.forceGC();
            });
            
            this.panel.querySelector('#reset-stats-btn').addEventListener('click', function() {
                self.resetStats();
            });
            
            this.panel.querySelector('#screenshot-btn').addEventListener('click', function() {
                self.takeScreenshot();
            });
            
            // 拖拽功能
            this.makeDraggable();
        },

        /**
         * 使面板可拖拽
         */
        makeDraggable: function() {
            const header = this.panel.querySelector('.monitor-header');
            let isDragging = false;
            let startX, startY, startLeft, startTop;
            
            header.addEventListener('mousedown', function(e) {
                isDragging = true;
                startX = e.clientX;
                startY = e.clientY;
                startLeft = parseInt(window.getComputedStyle(this.parentElement).left, 10);
                startTop = parseInt(window.getComputedStyle(this.parentElement).top, 10);
                
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });
            
            function onMouseMove(e) {
                if (!isDragging) return;
                
                const deltaX = e.clientX - startX;
                const deltaY = e.clientY - startY;
                
                const newLeft = startLeft + deltaX;
                const newTop = startTop + deltaY;
                
                header.parentElement.style.left = newLeft + 'px';
                header.parentElement.style.top = newTop + 'px';
            }
            
            function onMouseUp() {
                isDragging = false;
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            }
        },

        /**
         * 开始性能监控
         */
        startMonitoring: function() {
            const self = this;
            
            this.updateInterval = setInterval(function() {
                self.updateMetrics();
                self.updateCharts();
                self.checkPerformance();
            }, 1000);
        },

        /**
         * 更新性能指标
         */
        updateMetrics: function() {
            // 获取性能数据
            const performanceData = this.getPerformanceData();
            
            // 更新显示
            this.updateMetricDisplay('fps', performanceData.fps, 'fps');
            this.updateMetricDisplay('memory', performanceData.memory, 'MB');
            this.updateMetricDisplay('network', performanceData.networkRequests, '个');
            this.updateMetricDisplay('dom', performanceData.domNodes, '个');
            
            // 保存历史数据
            this.saveHistoryData(performanceData);
        },

        /**
         * 获取性能数据
         */
        getPerformanceData: function() {
            const data = {
                fps: 60,
                memory: 0,
                networkRequests: 0,
                domNodes: document.querySelectorAll('*').length
            };
            
            // 获取FPS数据
            if (window.PerformanceOptimizer && window.PerformanceOptimizer.getMetrics) {
                const metrics = window.PerformanceOptimizer.getMetrics();
                data.fps = metrics.fps || 60;
                data.networkRequests = metrics.networkRequests || 0;
            }
            
            // 获取内存数据
            if (performance.memory) {
                data.memory = Math.round(performance.memory.usedJSHeapSize / 1024 / 1024);
            }
            
            return data;
        },

        /**
         * 更新指标显示
         */
        updateMetricDisplay: function(type, value, unit) {
            const valueEl = document.getElementById(type + '-value');
            const statusEl = document.getElementById(type + '-status');
            
            if (valueEl) {
                valueEl.textContent = value + (unit || '');
            }
            
            if (statusEl) {
                const status = this.getMetricStatus(type, value);
                statusEl.textContent = status.text;
                statusEl.className = 'metric-status ' + status.class;
            }
        },

        /**
         * 获取指标状态
         */
        getMetricStatus: function(type, value) {
            switch (type) {
                case 'fps':
                    if (value >= 55) return { text: '优秀', class: 'excellent' };
                    if (value >= 45) return { text: '良好', class: 'good' };
                    if (value >= 30) return { text: '一般', class: 'fair' };
                    return { text: '较差', class: 'poor' };
                    
                case 'memory':
                    if (value < 50) return { text: '优秀', class: 'excellent' };
                    if (value < 100) return { text: '良好', class: 'good' };
                    if (value < 200) return { text: '一般', class: 'fair' };
                    return { text: '较高', class: 'poor' };
                    
                case 'network':
                    if (value < 5) return { text: '正常', class: 'excellent' };
                    if (value < 10) return { text: '活跃', class: 'good' };
                    if (value < 20) return { text: '繁忙', class: 'fair' };
                    return { text: '过载', class: 'poor' };
                    
                case 'dom':
                    if (value < 1000) return { text: '轻量', class: 'excellent' };
                    if (value < 3000) return { text: '正常', class: 'good' };
                    if (value < 5000) return { text: '较多', class: 'fair' };
                    return { text: '过多', class: 'poor' };
                    
                default:
                    return { text: '正常', class: 'good' };
            }
        },

        /**
         * 保存历史数据
         */
        saveHistoryData: function(data) {
            this.dataHistory.fps.push(data.fps);
            this.dataHistory.memory.push(data.memory);
            this.dataHistory.network.push(data.networkRequests);
            this.dataHistory.dom.push(data.domNodes);
            
            // 限制历史数据长度
            Object.keys(this.dataHistory).forEach(key => {
                if (this.dataHistory[key].length > this.maxHistoryLength) {
                    this.dataHistory[key].shift();
                }
            });
        },

        /**
         * 更新图表
         */
        updateCharts: function() {
            this.updateChart('fps-chart', this.dataHistory.fps, '#4CAF50');
            this.updateChart('memory-chart', this.dataHistory.memory, '#2196F3');
        },

        /**
         * 更新单个图表
         */
        updateChart: function(canvasId, data, color) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            
            const ctx = canvas.getContext('2d');
            const width = canvas.width;
            const height = canvas.height;
            
            // 清空画布
            ctx.clearRect(0, 0, width, height);
            
            if (data.length < 2) return;
            
            // 计算数据范围
            const maxValue = Math.max(...data);
            const minValue = Math.min(...data);
            const range = maxValue - minValue || 1;
            
            // 绘制网格线
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = (height / 4) * i;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(width, y);
                ctx.stroke();
            }
            
            // 绘制数据线
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            
            data.forEach((value, index) => {
                const x = (width / (data.length - 1)) * index;
                const y = height - ((value - minValue) / range) * height;
                
                if (index === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            });
            
            ctx.stroke();
            
            // 绘制数据点
            ctx.fillStyle = color;
            data.forEach((value, index) => {
                const x = (width / (data.length - 1)) * index;
                const y = height - ((value - minValue) / range) * height;
                
                ctx.beginPath();
                ctx.arc(x, y, 2, 0, 2 * Math.PI);
                ctx.fill();
            });
        },

        /**
         * 检查性能并提供建议
         */
        checkPerformance: function() {
            const suggestions = [];
            const data = this.getPerformanceData();
            
            if (data.fps < 30) {
                suggestions.push({
                    icon: '⚠️',
                    text: 'FPS过低，建议减少动画效果或优化渲染'
                });
            }
            
            if (data.memory > 150) {
                suggestions.push({
                    icon: '🔥',
                    text: '内存使用过高，建议清理缓存或重载页面'
                });
            }
            
            if (data.domNodes > 3000) {
                suggestions.push({
                    icon: '📦',
                    text: 'DOM节点过多，建议使用虚拟滚动或分页'
                });
            }
            
            if (data.networkRequests > 15) {
                suggestions.push({
                    icon: '🌐',
                    text: '网络请求频繁，建议合并请求或使用缓存'
                });
            }
            
            this.updateSuggestions(suggestions);
        },

        /**
         * 更新优化建议
         */
        updateSuggestions: function(suggestions) {
            const container = document.getElementById('suggestions-list');
            if (!container) return;
            
            if (suggestions.length === 0) {
                container.innerHTML = `
                    <div class="suggestion-item">
                        <span class="suggestion-icon">✅</span>
                        <span class="suggestion-text">性能表现良好</span>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = suggestions.map(suggestion => `
                <div class="suggestion-item">
                    <span class="suggestion-icon">${suggestion.icon}</span>
                    <span class="suggestion-text">${suggestion.text}</span>
                </div>
            `).join('');
        },

        /**
         * 显示面板
         */
        show: function() {
            this.panel.classList.remove('hidden');
            this.isVisible = true;
        },

        /**
         * 隐藏面板
         */
        hide: function() {
            this.panel.classList.add('hidden');
            this.isVisible = false;
        },

        /**
         * 切换显示状态
         */
        toggle: function() {
            if (this.isVisible) {
                this.hide();
            } else {
                this.show();
            }
        },

        /**
         * 切换最小化状态
         */
        toggleMinimize: function() {
            this.panel.classList.toggle('minimized');
            this.isMinimized = !this.isMinimized;
        },

        /**
         * 导出性能数据
         */
        exportData: function() {
            const data = {
                timestamp: new Date().toISOString(),
                history: this.dataHistory,
                currentMetrics: this.getPerformanceData(),
                userAgent: navigator.userAgent,
                url: window.location.href
            };
            
            const blob = new Blob([JSON.stringify(data, null, 2)], {
                type: 'application/json'
            });
            
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'performance-data-' + Date.now() + '.json';
            a.click();
            
            URL.revokeObjectURL(url);
            
            console.log('📤 性能数据已导出');
        },

        /**
         * 清理缓存
         */
        clearCache: function() {
            if (window.PerformanceOptimizer && window.PerformanceOptimizer.clearCache) {
                window.PerformanceOptimizer.clearCache();
            }
            
            // 清理浏览器缓存
            if ('caches' in window) {
                caches.keys().then(function(names) {
                    names.forEach(function(name) {
                        caches.delete(name);
                    });
                });
            }
            
            console.log('🗑️ 缓存已清理');
        },

        /**
         * 强制垃圾回收
         */
        forceGC: function() {
            if (window.gc) {
                window.gc();
                console.log('🗑️ 强制垃圾回收完成');
            } else {
                console.log('⚠️ 垃圾回收功能不可用');
            }
        },

        /**
         * 重置统计数据
         */
        resetStats: function() {
            this.dataHistory = {
                fps: [],
                memory: [],
                network: [],
                dom: []
            };
            
            if (window.PerformanceOptimizer && window.PerformanceOptimizer.resetStats) {
                window.PerformanceOptimizer.resetStats();
            }
            
            console.log('🔄 统计数据已重置');
        },

        /**
         * 截图功能
         */
        takeScreenshot: function() {
            if (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) {
                navigator.mediaDevices.getDisplayMedia({ video: true })
                    .then(function(stream) {
                        const video = document.createElement('video');
                        video.srcObject = stream;
                        video.play();
                        
                        video.addEventListener('loadedmetadata', function() {
                            const canvas = document.createElement('canvas');
                            canvas.width = video.videoWidth;
                            canvas.height = video.videoHeight;
                            
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(video, 0, 0);
                            
                            canvas.toBlob(function(blob) {
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = 'screenshot-' + Date.now() + '.png';
                                a.click();
                                
                                URL.revokeObjectURL(url);
                                stream.getTracks().forEach(track => track.stop());
                            });
                        });
                    })
                    .catch(function(err) {
                        console.error('截图失败:', err);
                    });
            } else {
                console.log('⚠️ 截图功能不支持');
            }
        },

        /**
         * 销毁监控面板
         */
        destroy: function() {
            if (this.updateInterval) {
                clearInterval(this.updateInterval);
            }
            
            if (this.panel && this.panel.parentNode) {
                this.panel.parentNode.removeChild(this.panel);
            }
            
            console.log('🗑️ 性能监控面板已销毁');
        }
    };

    // 创建全局实例
    let instance = null;

    return {
        /**
         * 获取监控面板实例
         */
        getInstance: function() {
            if (!instance) {
                instance = new MonitorPanel();
            }
            return instance;
        },

        /**
         * 初始化监控面板
         */
        init: function() {
            return this.getInstance();
        },

        /**
         * 显示监控面板
         */
        show: function() {
            this.getInstance().show();
        },

        /**
         * 隐藏监控面板
         */
        hide: function() {
            this.getInstance().hide();
        },

        /**
         * 切换监控面板
         */
        toggle: function() {
            this.getInstance().toggle();
        }
    };
})();

// 自动初始化
document.addEventListener('DOMContentLoaded', function() {
    window.PerformanceMonitorPanel.init();
    console.log('📊 性能监控面板已加载，按 Ctrl+Shift+P 打开');
});