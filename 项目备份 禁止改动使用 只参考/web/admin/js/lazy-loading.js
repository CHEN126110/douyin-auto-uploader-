/**
 * 懒加载组件 - 图片和资源延迟加载优化
 * 提供高性能的图片懒加载、背景图片懒加载和资源预加载功能
 */

const LazyLoader = {
    // 配置选项
    config: {
        // Intersection Observer 配置
        rootMargin: '50px 0px',
        threshold: 0.1,
        
        // 加载状态类名
        loadingClass: 'lazy-loading',
        loadedClass: 'lazy-loaded',
        errorClass: 'lazy-error',
        
        // 占位符配置
        placeholderColor: '#f0f0f0',
        placeholderText: '加载中...',
        
        // 动画配置
        fadeInDuration: 300,
        
        // 重试配置
        maxRetries: 3,
        retryDelay: 1000
    },

    // 内部状态
    observers: new Map(),
    loadingImages: new Set(),
    loadedImages: new Set(),
    errorImages: new Set(),
    retryCount: new Map(),

    /**
     * 初始化懒加载
     */
    init() {
        console.log('🚀 初始化懒加载组件...');
        
        // 检查浏览器支持
        if (!this.isSupported()) {
            console.warn('⚠️ 浏览器不支持 Intersection Observer，使用降级方案');
            this.initFallback();
            return;
        }

        // 创建观察器
        this.createObserver();
        
        // 扫描现有图片
        this.scanExistingImages();
        
        // 监听DOM变化
        this.observeDOM();
        
        console.log('✅ 懒加载组件初始化完成');
    },

    /**
     * 检查浏览器支持
     */
    isSupported() {
        return 'IntersectionObserver' in window && 
               'IntersectionObserverEntry' in window && 
               'intersectionRatio' in window.IntersectionObserverEntry.prototype;
    },

    /**
     * 创建 Intersection Observer
     */
    createObserver() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    this.loadImage(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, {
            rootMargin: this.config.rootMargin,
            threshold: this.config.threshold
        });

        this.observers.set('main', observer);
    },

    /**
     * 扫描现有图片
     */
    scanExistingImages() {
        // 扫描 img 标签
        const images = document.querySelectorAll('img[data-src]');
        images.forEach(img => this.observeImage(img));

        // 扫描背景图片
        const bgImages = document.querySelectorAll('[data-bg-src]');
        bgImages.forEach(el => this.observeImage(el));

        console.log(`📊 发现 ${images.length} 个图片和 ${bgImages.length} 个背景图片需要懒加载`);
    },

    /**
     * 观察图片
     */
    observeImage(element) {
        if (!element || this.loadedImages.has(element)) {
            return;
        }

        // 添加加载状态
        element.classList.add(this.config.loadingClass);
        
        // 设置占位符
        this.setPlaceholder(element);
        
        // 开始观察
        const observer = this.observers.get('main');
        if (observer) {
            observer.observe(element);
        }
    },

    /**
     * 设置占位符
     */
    setPlaceholder(element) {
        if (element.tagName === 'IMG') {
            // 图片占位符
            if (!element.src || element.src === '') {
                element.src = this.generatePlaceholder(
                    element.dataset.width || 300,
                    element.dataset.height || 200
                );
            }
        } else {
            // 背景图片占位符
            element.style.backgroundColor = this.config.placeholderColor;
            
            // 添加加载指示器
            if (!element.querySelector('.lazy-placeholder')) {
                const placeholder = document.createElement('div');
                placeholder.className = 'lazy-placeholder';
                placeholder.innerHTML = `
                    <div class="lazy-spinner"></div>
                    <span>${this.config.placeholderText}</span>
                `;
                element.appendChild(placeholder);
            }
        }
    },

    /**
     * 生成占位符图片
     */
    generatePlaceholder(width, height) {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        
        const ctx = canvas.getContext('2d');
        
        // 绘制占位符
        ctx.fillStyle = this.config.placeholderColor;
        ctx.fillRect(0, 0, width, height);
        
        // 绘制加载文字
        ctx.fillStyle = '#999';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText(this.config.placeholderText, width / 2, height / 2);
        
        return canvas.toDataURL();
    },

    /**
     * 加载图片
     */
    async loadImage(element) {
        if (this.loadingImages.has(element) || this.loadedImages.has(element)) {
            return;
        }

        this.loadingImages.add(element);
        
        try {
            if (element.tagName === 'IMG') {
                await this.loadImageElement(element);
            } else {
                await this.loadBackgroundImage(element);
            }
            
            this.onImageLoaded(element);
            
        } catch (error) {
            console.warn('⚠️ 图片加载失败:', error);
            this.onImageError(element, error);
        }
    },

    /**
     * 加载 img 元素
     */
    loadImageElement(img) {
        return new Promise((resolve, reject) => {
            const src = img.dataset.src;
            if (!src) {
                reject(new Error('没有找到 data-src 属性'));
                return;
            }

            const tempImg = new Image();
            
            tempImg.onload = () => {
                // 预加载完成，设置实际图片
                img.src = src;
                img.removeAttribute('data-src');
                resolve();
            };
            
            tempImg.onerror = () => {
                reject(new Error(`图片加载失败: ${src}`));
            };
            
            // 开始加载
            tempImg.src = src;
        });
    },

    /**
     * 加载背景图片
     */
    loadBackgroundImage(element) {
        return new Promise((resolve, reject) => {
            const src = element.dataset.bgSrc;
            if (!src) {
                reject(new Error('没有找到 data-bg-src 属性'));
                return;
            }

            const tempImg = new Image();
            
            tempImg.onload = () => {
                // 设置背景图片
                element.style.backgroundImage = `url(${src})`;
                element.removeAttribute('data-bg-src');
                
                // 移除占位符
                const placeholder = element.querySelector('.lazy-placeholder');
                if (placeholder) {
                    placeholder.remove();
                }
                
                resolve();
            };
            
            tempImg.onerror = () => {
                reject(new Error(`背景图片加载失败: ${src}`));
            };
            
            // 开始加载
            tempImg.src = src;
        });
    },

    /**
     * 图片加载成功处理
     */
    onImageLoaded(element) {
        this.loadingImages.delete(element);
        this.loadedImages.add(element);
        this.retryCount.delete(element);
        
        // 更新状态类
        element.classList.remove(this.config.loadingClass, this.config.errorClass);
        element.classList.add(this.config.loadedClass);
        
        // 淡入动画
        this.fadeIn(element);
        
        // 触发自定义事件
        element.dispatchEvent(new CustomEvent('lazyLoaded', {
            detail: { element }
        }));
    },

    /**
     * 图片加载失败处理
     */
    onImageError(element, error) {
        this.loadingImages.delete(element);
        this.errorImages.add(element);
        
        // 重试逻辑
        const retries = this.retryCount.get(element) || 0;
        if (retries < this.config.maxRetries) {
            this.retryCount.set(element, retries + 1);
            
            setTimeout(() => {
                this.errorImages.delete(element);
                this.loadImage(element);
            }, this.config.retryDelay * (retries + 1));
            
            return;
        }
        
        // 最终失败处理
        element.classList.remove(this.config.loadingClass);
        element.classList.add(this.config.errorClass);
        
        // 设置错误占位符
        if (element.tagName === 'IMG') {
            element.src = this.generateErrorPlaceholder();
        } else {
            element.style.backgroundColor = '#ffebee';
            const placeholder = element.querySelector('.lazy-placeholder');
            if (placeholder) {
                placeholder.innerHTML = '<span>加载失败</span>';
            }
        }
        
        // 触发错误事件
        element.dispatchEvent(new CustomEvent('lazyError', {
            detail: { element, error }
        }));
    },

    /**
     * 生成错误占位符
     */
    generateErrorPlaceholder() {
        const canvas = document.createElement('canvas');
        canvas.width = 300;
        canvas.height = 200;
        
        const ctx = canvas.getContext('2d');
        
        // 绘制错误背景
        ctx.fillStyle = '#ffebee';
        ctx.fillRect(0, 0, 300, 200);
        
        // 绘制错误文字
        ctx.fillStyle = '#f44336';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('加载失败', 150, 100);
        
        return canvas.toDataURL();
    },

    /**
     * 淡入动画
     */
    fadeIn(element) {
        element.style.opacity = '0';
        element.style.transition = `opacity ${this.config.fadeInDuration}ms ease-in-out`;
        
        // 强制重排
        element.offsetHeight;
        
        element.style.opacity = '1';
        
        // 清理样式
        setTimeout(() => {
            element.style.transition = '';
        }, this.config.fadeInDuration);
    },

    /**
     * 监听DOM变化
     */
    observeDOM() {
        if (!('MutationObserver' in window)) {
            return;
        }

        const observer = new MutationObserver((mutations) => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // 检查新添加的图片
                        if (node.tagName === 'IMG' && node.dataset.src) {
                            this.observeImage(node);
                        }
                        
                        if (node.dataset && node.dataset.bgSrc) {
                            this.observeImage(node);
                        }
                        
                        // 检查子元素
                        const images = node.querySelectorAll && node.querySelectorAll('img[data-src], [data-bg-src]');
                        if (images) {
                            images.forEach(img => this.observeImage(img));
                        }
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    },

    /**
     * 降级方案（不支持 Intersection Observer）
     */
    initFallback() {
        // 立即加载所有图片
        const images = document.querySelectorAll('img[data-src], [data-bg-src]');
        images.forEach(img => {
            setTimeout(() => this.loadImage(img), 100);
        });
    },

    /**
     * 手动触发加载
     */
    loadAll() {
        const images = document.querySelectorAll('img[data-src], [data-bg-src]');
        images.forEach(img => this.loadImage(img));
    },

    /**
     * 获取统计信息
     */
    getStats() {
        return {
            loading: this.loadingImages.size,
            loaded: this.loadedImages.size,
            error: this.errorImages.size,
            total: this.loadingImages.size + this.loadedImages.size + this.errorImages.size
        };
    },

    /**
     * 扫描新添加的图片
     * 重新扫描页面中新添加的图片元素并开始懒加载
     */
    scanNewImages() {
        console.log('🔍 开始扫描新添加的图片...');
        
        let newImageCount = 0;
        let newBgImageCount = 0;
        
        // 扫描新的 img 标签
        const newImages = document.querySelectorAll('img[data-src]');
        newImages.forEach(img => {
            if (!this.loadedImages.has(img) && !this.loadingImages.has(img)) {
                this.observeImage(img);
                newImageCount++;
            }
        });

        // 扫描新的背景图片
        const newBgImages = document.querySelectorAll('[data-bg-src]');
        newBgImages.forEach(el => {
            if (!this.loadedImages.has(el) && !this.loadingImages.has(el)) {
                this.observeImage(el);
                newBgImageCount++;
            }
        });

        // 扫描具有 lazy-optimized 类的图片
        const lazyOptimizedImages = document.querySelectorAll('img.lazy-optimized[data-src]');
        lazyOptimizedImages.forEach(img => {
            if (!this.loadedImages.has(img) && !this.loadingImages.has(img)) {
                this.observeImage(img);
                newImageCount++;
            }
        });

        console.log(`📊 扫描完成: 发现 ${newImageCount} 个新图片和 ${newBgImageCount} 个新背景图片`);
        
        return {
            images: newImageCount,
            backgrounds: newBgImageCount,
            total: newImageCount + newBgImageCount
        };
    },

    /**
     * 销毁懒加载
     */
    destroy() {
        // 断开所有观察器
        this.observers.forEach(observer => observer.disconnect());
        this.observers.clear();
        
        // 清理状态
        this.loadingImages.clear();
        this.loadedImages.clear();
        this.errorImages.clear();
        this.retryCount.clear();
        
        console.log('🗑️ 懒加载组件已销毁');
    }
};

// 自动初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => LazyLoader.init());
} else {
    LazyLoader.init();
}

// 导出到全局
window.LazyLoader = LazyLoader;