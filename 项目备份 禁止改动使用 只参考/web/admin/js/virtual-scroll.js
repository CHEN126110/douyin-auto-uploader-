/**
 * 虚拟滚动组件 - 优化大数据量列表渲染性能
 * 
 * 功能特性：
 * - 只渲染可视区域内的元素
 * - 支持动态高度计算
 * - 内存优化和性能监控
 * - 平滑滚动体验
 * 
 * @author Frontend Performance Team
 * @version 1.0.0
 */

window.VirtualScroll = (function() {
    'use strict';

    /**
     * 虚拟滚动类
     */
    function VirtualScrollContainer(options) {
        this.container = options.container;
        this.itemHeight = options.itemHeight || 80;
        this.bufferSize = options.bufferSize || 5;
        this.data = options.data || [];
        this.renderItem = options.renderItem;
        this.onScroll = options.onScroll;
        
        // 性能相关属性
        this.visibleStart = 0;
        this.visibleEnd = 0;
        this.scrollTop = 0;
        this.containerHeight = 0;
        this.totalHeight = 0;
        this.renderedItems = new Map();
        
        // 节流控制
        this.scrollTimer = null;
        this.resizeTimer = null;
        
        this.init();
    }

    VirtualScrollContainer.prototype = {
        /**
         * 初始化虚拟滚动容器
         */
        init: function() {
            this.setupContainer();
            this.bindEvents();
            this.calculateDimensions();
            this.render();
            
            console.log('🚀 虚拟滚动容器初始化完成');
        },

        /**
         * 设置容器结构
         */
        setupContainer: function() {
            const container = typeof this.container === 'string' 
                ? document.querySelector(this.container) 
                : this.container;
                
            if (!container) {
                console.error('❌ 虚拟滚动容器未找到');
                return;
            }

            this.containerEl = container;
            
            // 设置容器样式
            this.containerEl.style.position = 'relative';
            this.containerEl.style.overflow = 'auto';
            this.containerEl.style.height = this.containerEl.style.height || '400px';
            
            // 创建虚拟滚动区域
            this.scrollArea = document.createElement('div');
            this.scrollArea.className = 'virtual-scroll-area';
            this.scrollArea.style.position = 'relative';
            this.scrollArea.style.width = '100%';
            
            // 创建可视区域
            this.viewport = document.createElement('div');
            this.viewport.className = 'virtual-scroll-viewport';
            this.viewport.style.position = 'absolute';
            this.viewport.style.top = '0';
            this.viewport.style.left = '0';
            this.viewport.style.width = '100%';
            
            this.scrollArea.appendChild(this.viewport);
            this.containerEl.appendChild(this.scrollArea);
        },

        /**
         * 绑定事件监听器
         */
        bindEvents: function() {
            const self = this;
            
            // 滚动事件（节流处理）
            this.containerEl.addEventListener('scroll', function(e) {
                if (self.scrollTimer) {
                    clearTimeout(self.scrollTimer);
                }
                
                self.scrollTimer = setTimeout(function() {
                    self.handleScroll(e);
                }, 16); // 约60fps
            });
            
            // 窗口大小变化事件
            window.addEventListener('resize', function() {
                if (self.resizeTimer) {
                    clearTimeout(self.resizeTimer);
                }
                
                self.resizeTimer = setTimeout(function() {
                    self.handleResize();
                }, 100);
            });
        },

        /**
         * 计算容器尺寸
         */
        calculateDimensions: function() {
            this.containerHeight = this.containerEl.clientHeight;
            this.totalHeight = this.data.length * this.itemHeight;
            this.scrollArea.style.height = this.totalHeight + 'px';
            
            // 计算可视区域能显示的项目数量
            this.visibleCount = Math.ceil(this.containerHeight / this.itemHeight);
        },

        /**
         * 处理滚动事件
         */
        handleScroll: function(e) {
            this.scrollTop = this.containerEl.scrollTop;
            this.updateVisibleRange();
            this.render();
            
            // 触发自定义滚动回调
            if (this.onScroll) {
                this.onScroll({
                    scrollTop: this.scrollTop,
                    visibleStart: this.visibleStart,
                    visibleEnd: this.visibleEnd
                });
            }
        },

        /**
         * 处理窗口大小变化
         */
        handleResize: function() {
            this.calculateDimensions();
            this.updateVisibleRange();
            this.render();
        },

        /**
         * 更新可视范围
         */
        updateVisibleRange: function() {
            const start = Math.floor(this.scrollTop / this.itemHeight);
            const end = Math.min(
                start + this.visibleCount + this.bufferSize * 2,
                this.data.length
            );
            
            this.visibleStart = Math.max(0, start - this.bufferSize);
            this.visibleEnd = end;
        },

        /**
         * 渲染可视区域内的项目
         */
        render: function() {
            // 清理不在可视范围内的元素
            this.cleanupInvisibleItems();
            
            // 渲染可视范围内的元素
            for (let i = this.visibleStart; i < this.visibleEnd; i++) {
                if (!this.renderedItems.has(i)) {
                    this.renderItemAt(i);
                }
            }
            
            // 更新视口位置
            this.viewport.style.transform = `translateY(${this.visibleStart * this.itemHeight}px)`;
        },

        /**
         * 渲染指定索引的项目
         */
        renderItemAt: function(index) {
            if (index >= this.data.length) return;
            
            const item = this.data[index];
            const element = document.createElement('div');
            element.className = 'virtual-scroll-item';
            element.style.height = this.itemHeight + 'px';
            element.style.position = 'relative';
            element.dataset.index = index;
            
            // 调用自定义渲染函数
            if (this.renderItem) {
                const content = this.renderItem(item, index);
                if (typeof content === 'string') {
                    element.innerHTML = content;
                } else if (content instanceof HTMLElement) {
                    element.appendChild(content);
                }
            }
            
            this.viewport.appendChild(element);
            this.renderedItems.set(index, element);
        },

        /**
         * 清理不可见的项目
         */
        cleanupInvisibleItems: function() {
            const toRemove = [];
            
            this.renderedItems.forEach((element, index) => {
                if (index < this.visibleStart || index >= this.visibleEnd) {
                    toRemove.push(index);
                }
            });
            
            toRemove.forEach(index => {
                const element = this.renderedItems.get(index);
                if (element && element.parentNode) {
                    element.parentNode.removeChild(element);
                }
                this.renderedItems.delete(index);
            });
        },

        /**
         * 更新数据
         */
        updateData: function(newData) {
            this.data = newData;
            this.calculateDimensions();
            this.renderedItems.clear();
            this.viewport.innerHTML = '';
            this.updateVisibleRange();
            this.render();
        },

        /**
         * 滚动到指定项目
         */
        scrollToItem: function(index) {
            if (index < 0 || index >= this.data.length) return;
            
            const targetScrollTop = index * this.itemHeight;
            this.containerEl.scrollTop = targetScrollTop;
        },

        /**
         * 获取性能统计信息
         */
        getStats: function() {
            return {
                totalItems: this.data.length,
                renderedItems: this.renderedItems.size,
                visibleRange: [this.visibleStart, this.visibleEnd],
                memoryUsage: this.renderedItems.size * this.itemHeight
            };
        },

        /**
         * 销毁虚拟滚动容器
         */
        destroy: function() {
            if (this.scrollTimer) {
                clearTimeout(this.scrollTimer);
            }
            if (this.resizeTimer) {
                clearTimeout(this.resizeTimer);
            }
            
            this.renderedItems.clear();
            if (this.containerEl && this.scrollArea) {
                this.containerEl.removeChild(this.scrollArea);
            }
            
            console.log('🗑️ 虚拟滚动容器已销毁');
        }
    };

    /**
     * SKU列表虚拟滚动适配器
     */
    function SKUVirtualScroll(options) {
        this.container = options.container || '#attr_box';
        this.onItemClick = options.onItemClick;
        this.onItemDelete = options.onItemDelete;
        this.virtualScroll = null;
        this.originalData = [];
    }

    SKUVirtualScroll.prototype = {
        /**
         * 初始化SKU虚拟滚动
         */
        init: function(skuData) {
            this.originalData = skuData || [];
            
            if (this.originalData.length < 50) {
                // 数据量较小时，不使用虚拟滚动
                console.log('📊 SKU数量较少，使用常规渲染');
                return false;
            }
            
            console.log('🚀 启用SKU虚拟滚动，数据量:', this.originalData.length);
            
            this.setupVirtualScroll();
            return true;
        },

        /**
         * 设置虚拟滚动
         */
        setupVirtualScroll: function() {
            const self = this;
            
            this.virtualScroll = new VirtualScrollContainer({
                container: this.container,
                itemHeight: 90, // SKU项目高度
                bufferSize: 3,
                data: this.originalData,
                renderItem: function(item, index) {
                    return self.renderSKUItem(item, index);
                },
                onScroll: function(info) {
                    // 滚动时的回调处理
                    self.handleVirtualScroll(info);
                }
            });
        },

        /**
         * 渲染SKU项目
         */
        renderSKUItem: function(item, index) {
            const skuHtml = `
                <div class="ipt_box virtual-sku-item" data-index="${index}">
                    <img data-src="${item.url}" 
                         src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='50' height='50' viewBox='0 0 50 50'%3E%3Crect width='50' height='50' fill='%23f5f5f5'/%3E%3Ctext x='25' y='25' font-family='Arial' font-size='10' fill='%23999' text-anchor='middle' dy='.3em'%3ELoading%3C/text%3E%3C/svg%3E" 
                         class="sku-thumbnail lazy-optimized" 
                         data-sku-path="${item.path}">
                    <input type="hidden" name="attr_path_${index + 1}" value="${item.path}">
                    <input type="text" name="attr_name_${index + 1}" 
                           placeholder="SKU名称" autocomplete="off" 
                           class="layui-input" value="${item.name}">
                    <input type="number" name="attr_price_${index + 1}" 
                           placeholder="价格" autocomplete="off" 
                           class="layui-input" step="0.01" value="${item.price}">
                    <button type="button" 
                            class="layui-btn layui-btn-danger layui-btn-sm delete-sku-btn optimized-interactive" 
                            data-index="${index}">删除</button>
                </div>
            `;
            
            return skuHtml;
        },

        /**
         * 处理虚拟滚动事件
         */
        handleVirtualScroll: function(info) {
            // 懒加载图片
            if (window.LazyLoader) {
                window.LazyLoader.scanNewImages();
            }
            
            // 重新绑定事件
            this.bindItemEvents();
        },

        /**
         * 绑定项目事件
         */
        bindItemEvents: function() {
            const self = this;
            const container = document.querySelector(this.container);
            
            if (!container) return;
            
            // 绑定缩略图点击事件
            container.querySelectorAll('.sku-thumbnail').forEach(function(thumb) {
                thumb.onclick = function(e) {
                    e.preventDefault();
                    if (self.onItemClick) {
                        const index = parseInt(this.closest('.virtual-sku-item').dataset.index);
                        self.onItemClick(self.originalData[index], index);
                    }
                };
            });
            
            // 绑定删除按钮事件
            container.querySelectorAll('.delete-sku-btn').forEach(function(btn) {
                btn.onclick = function(e) {
                    e.preventDefault();
                    if (self.onItemDelete) {
                        const index = parseInt(this.dataset.index);
                        self.onItemDelete(index);
                    }
                };
            });
        },

        /**
         * 更新SKU数据
         */
        updateData: function(newData) {
            this.originalData = newData;
            if (this.virtualScroll) {
                this.virtualScroll.updateData(newData);
                this.bindItemEvents();
            }
        },

        /**
         * 获取统计信息
         */
        getStats: function() {
            if (this.virtualScroll) {
                return this.virtualScroll.getStats();
            }
            return null;
        },

        /**
         * 销毁虚拟滚动
         */
        destroy: function() {
            if (this.virtualScroll) {
                this.virtualScroll.destroy();
                this.virtualScroll = null;
            }
        }
    };

    // 公开API
    return {
        VirtualScrollContainer: VirtualScrollContainer,
        SKUVirtualScroll: SKUVirtualScroll,
        
        /**
         * 创建虚拟滚动容器
         */
        create: function(options) {
            return new VirtualScrollContainer(options);
        },
        
        /**
         * 创建SKU虚拟滚动
         */
        createSKUScroll: function(options) {
            return new SKUVirtualScroll(options);
        }
    };
})();

// 初始化日志
console.log('📦 虚拟滚动组件加载完成');