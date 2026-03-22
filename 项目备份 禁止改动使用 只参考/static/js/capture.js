/**
 * 淘宝商品信息采集系统前端控制器
 * 基于Layui框架实现
 */

// 全局变量
let currentTask = null;
let statusInterval = null;
let isCapturing = false;
let currentResult = null;

// 初始化layui
layui.use(['layer', 'form', 'element', 'table'], function() {
    const layer = layui.layer;
    const form = layui.form;
    const element = layui.element;
    const table = layui.table;
    
    // 初始化系统
    initSystem(layer, form, element, table);
});

/**
 * 初始化系统
 */
function initSystem(layer, form, element, table) {
    console.log('初始化淘宝商品信息采集系统...');
    
    // 绑定事件
    bindEvents(layer, form, element, table);
    
    // 加载历史记录
    loadHistory();
    
    // 检查服务状态
    checkServiceStatus();
    
    console.log('系统初始化完成');
}

/**
 * 绑定事件
 */
function bindEvents(layer, form, element, table) {
    // 开始采集按钮
    $('#start-capture').click(function() {
        startCapture(layer, form, element);
    });
    
    // 清空输入按钮
    $('#clear-input').click(function() {
        clearInput(layer);
    });
    
    // 查看历史按钮
    $('#view-history-btn, #nav-history, #view-history').click(function() {
        showHistory(layer, table);
    });
    
    // 取消采集按钮
    $('#cancel-capture').click(function() {
        cancelCapture(layer);
    });
    
    // 最小化状态按钮
    $('#minimize-status').click(function() {
        minimizeStatus();
    });
    
    // 导入数据按钮
    $('#import-results').click(function() {
        importResults(layer);
    });
    
    // 编辑结果按钮
    $('#edit-results').click(function() {
        editResults(layer);
    });
    
    // 下载图片按钮
    $('#download-images').click(function() {
        downloadImages(layer);
    });
    
    // 输入框回车事件
    $('#product-url').keypress(function(e) {
        if (e.which === 13) {
            startCapture(layer, form, element);
        }
    });
    
    // 导航菜单事件
    $('#nav-capture').click(function() {
        $('html, body').animate({
            scrollTop: 0
        }, 500);
    });
    
    // 拖拽上传功能
    setupDragAndDrop();
}

/**
 * 开始采集
 */
async function startCapture(layer, form, element) {
    const url = $('#product-url').val().trim();
    
    if (!url) {
        layer.msg('请输入商品链接', {icon: 2, time: 2000});
        return;
    }
    
    if (!validateTaobaoUrl(url)) {
        layer.msg('请输入有效的淘宝/天猫商品链接', {icon: 2, time: 3000});
        return;
    }
    
    // 获取采集选项
    const options = {
        download_images: $('input[name="download-images"]').is(':checked'),
        extract_sku: $('input[name="extract-sku"]').is(':checked'),
        extract_params: $('input[name="extract-params"]').is(':checked')
    };
    
    isCapturing = true;
    showStatus(element);
    updateStatus(element, 0, '正在启动采集任务...');
    
    try {
        // 调用后端API开始采集
        const response = await fetch('/api/product/capture/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                options: options
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentTask = data.task_id;
            $('#current-task-id').text('任务ID: ' + currentTask);
            startStatusPolling(layer, element);
            layer.msg('采集任务已启动', {icon: 1, time: 2000});
        } else {
            handleCaptureError(layer, data.message);
        }
        
    } catch (error) {
        console.error('启动采集任务失败:', error);
        handleCaptureError(layer, '启动采集任务失败: ' + error.message);
    }
}

/**
 * 验证淘宝/天猫链接
 */
function validateTaobaoUrl(url) {
    const patterns = [
        /detail\.tmall\.com\/item\.htm/,
        /item\.taobao\.com\/item\.htm/,
        /detail\.taobao\.com\/item\.htm/,
        /detail\.tmall\.hk\/item\.htm/
    ];
    
    return patterns.some(pattern => pattern.test(url)) && url.includes('id=');
}

/**
 * 显示状态区域
 */
function showStatus(element) {
    $('#capture-status-container').show();
    $('#capture-results-container').hide();
    element.progress('capture-progress', '0%');
}

/**
 * 更新状态
 */
function updateStatus(element, percent, message) {
    element.progress('capture-progress', percent + '%');
    $('#status-message').text(message);
}

/**
 * 开始状态轮询
 */
function startStatusPolling(layer, element) {
    if (statusInterval) {
        clearInterval(statusInterval);
    }
    let delay = 1000;
    const maxDelay = 5000;
    const minDelay = 1000;
    async function poll() {
        await checkTaskStatus(layer, element);
        if (isCapturing) {
            delay = Math.min(maxDelay, delay + 500);
        } else {
            delay = minDelay;
        }
        statusInterval = setTimeout(poll, delay);
    }
    poll();
}

/**
 * 检查任务状态
 */
async function checkTaskStatus(layer, element) {
    if (!currentTask) return;
    
    try {
        const response = await fetch('/api/product/capture/status/' + currentTask);
        const data = await response.json();
        
        if (data.success) {
            updateStatus(element, data.progress, data.message);
            
            if (data.status === 'completed') {
                handleCaptureSuccess(layer, data.result);
            } else if (data.status === 'failed') {
                handleCaptureError(layer, data.message);
            } else if (data.status === 'login_required') {
                handleLoginRequired(layer, element);
            }
        } else {
            console.error('检查任务状态失败:', data.message);
        }
        
    } catch (error) {
        console.error('检查任务状态失败:', error);
    }
}

/**
 * 处理采集成功
 */
function handleCaptureSuccess(layer, result) {
    isCapturing = false;
    if (statusInterval) {
        clearInterval(statusInterval);
        statusInterval = null;
    }
    
    currentResult = result;
    displayResults(result);
    
    layer.msg('采集完成！', {icon: 1, time: 2000});
    
    // 保存到历史记录
    saveToHistory(result);
    
    // 显示结果区域
    $('#capture-results-container').show();
}

/**
 * 处理采集错误
 */
function handleCaptureError(layer, message) {
    isCapturing = false;
    if (statusInterval) {
        clearInterval(statusInterval);
        statusInterval = null;
    }
    
    updateStatus(layui.element, 0, '采集失败: ' + message);
    layer.msg('采集失败: ' + message, {icon: 2, time: 5000});
}

/**
 * 处理需要登录
 */
function handleLoginRequired(layer, element) {
    layer.open({
        type: 1,
        title: '需要登录',
        area: ['400px', '250px'],
        content: $('#login-prompt-modal').html(),
        success: function(layero) {
            // 确认登录按钮
            layero.find('#confirm-login-complete').click(function() {
                layer.closeAll();
                updateStatus(element, 20, '检测到登录完成，继续采集...');
                notifyLoginComplete();
            });
            
            // 取消登录按钮
            layero.find('#cancel-login-prompt').click(function() {
                layer.closeAll();
                cancelCapture(layer);
            });
        }
    });
}

/**
 * 通知登录完成
 */
async function notifyLoginComplete() {
    if (!currentTask) return;
    
    try {
        const response = await fetch('/api/product/capture/continue/' + currentTask, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            layui.layer.msg('登录验证成功，继续采集...', {icon: 1, time: 2000});
        }
    } catch (error) {
        console.error('通知登录完成失败:', error);
    }
}

/**
 * 显示结果
 */
function displayResults(result) {
    // 基本信息
    $('#result-main-image').attr('src', result.main_image || '/static/images/no-image.png');
    $('#result-title').text(result.title || '未获取到标题');
    $('#result-price').text('¥' + (result.price.current || 0));
    $('#result-url').attr('href', result.url).text(result.url);
    $('#result-download-path').text(result.download_path || '未下载');
    
    // 显示SKU信息
    displaySKUInfo(result.sku_info);
    
    // 显示商品参数
    displayParameters(result.parameters);
    
    // 显示详情图片
    displayDetailImages(result.detail_images);
    
    // 显示原始数据
    $('#raw-data-container').text(JSON.stringify(result, null, 2));
    
    // 重新渲染标签页
    layui.element.render('capture-results-tab');
}

/**
 * 显示SKU信息
 */
function displaySKUInfo(skuInfo) {
    let html = '';
    
    if (skuInfo && skuInfo.length > 0) {
        skuInfo.forEach(function(sku, index) {
            html += `
                <div class="sku-item">
                    <div class="sku-header">
                        <span class="sku-name">${sku.name || '未命名SKU'}</span>
                        <span class="sku-price">¥${sku.price || 0}</span>
                    </div>
                    <div class="sku-images">
                        ${sku.images.map(img => `<img src="${img}" alt="SKU图片" onclick="viewFullImage('${img}')">`).join('')}
                    </div>
                </div>
            `;
        });
    } else {
        html = '<p style="text-align: center; color: #999; padding: 40px;">未获取到SKU信息</p>';
    }
    
    $('#sku-info-container').html(html);
}

/**
 * 显示商品参数
 */
function displayParameters(parameters) {
    let html = '';
    
    if (parameters && parameters.length > 0) {
        parameters.forEach(function(param) {
            html += `
                <div class="param-item">
                    <span class="param-name">${param.name}</span>
                    <span class="param-value">${param.value}</span>
                </div>
            `;
        });
    } else {
        html = '<p style="text-align: center; color: #999; padding: 40px;">未获取到商品参数</p>';
    }
    
    $('#params-container').html(html);
}

/**
 * 显示详情图片
 */
function displayDetailImages(images) {
    let html = '';
    
    if (images && images.length > 0) {
        images.forEach(function(image, index) {
            html += `<img src="${image}" alt="详情图${index + 1}" onclick="viewFullImage('${image}')">`;
        });
    } else {
        html = '<p style="text-align: center; color: #999; padding: 40px;">未获取到详情图片</p>';
    }
    
    $('#detail-images-container').html(html);
}

/**
 * 查看大图
 */
function viewFullImage(imageUrl) {
    layui.layer.open({
        type: 1,
        title: '查看图片',
        area: ['80%', '80%'],
        content: `<img src="${imageUrl}" style="max-width: 100%; max-height: 100%; display: block; margin: 0 auto;">`
    });
}

/**
 * 导入数据
 */
async function importResults(layer) {
    if (!currentResult) {
        layer.msg('没有可导入的数据', {icon: 2, time: 2000});
        return;
    }
    
    layer.confirm('确定要将采集的数据导入到系统中吗？', {
        btn: ['确定', '取消'],
        icon: 3
    }, async function() {
        try {
            const response = await fetch('/api/product/capture/import', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    task_id: currentResult.task_id,
                    product_data: currentResult
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                layer.msg('数据导入成功！', {icon: 1, time: 2000});
                // 可以跳转到商品管理页面
                setTimeout(() => {
                    // window.location.href = '/view/product/list';
                }, 1500);
            } else {
                layer.msg('导入失败: ' + data.message, {icon: 2, time: 3000});
            }
            
        } catch (error) {
            console.error('导入数据失败:', error);
            layer.msg('导入请求失败: ' + error.message, {icon: 2, time: 3000});
        }
    });
}

/**
 * 编辑结果
 */
function editResults(layer) {
    if (!currentResult) return;
    
    layer.open({
        type: 2,
        title: '编辑采集结果',
        area: ['80%', '80%'],
        content: '/view/capture/editor?task_id=' + currentResult.task_id
    });
}

/**
 * 下载图片
 */
function downloadImages(layer) {
    if (!currentResult || !currentResult.download_path) {
        layer.msg('没有可下载的图片', {icon: 2, time: 2000});
        return;
    }
    
    // 创建下载链接
    const downloadUrl = '/api/product/capture/download/' + currentResult.task_id;
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = 'product_images_' + currentResult.task_id + '.zip';
    link.click();
    
    layer.msg('开始下载图片压缩包...', {icon: 1, time: 2000});
}

/**
 * 取消采集
 */
function cancelCapture(layer) {
    if (!currentTask) return;
    
    layer.confirm('确定要取消当前采集任务吗？', {
        btn: ['确定', '取消'],
        icon: 3
    }, async function() {
        try {
            const response = await fetch('/api/product/capture/cancel/' + currentTask, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                isCapturing = false;
                if (statusInterval) {
                    clearInterval(statusInterval);
                    statusInterval = null;
                }
                updateStatus(layui.element, 0, '采集已取消');
                layer.msg('采集任务已取消', {icon: 1, time: 2000});
            }
            
        } catch (error) {
            console.error('取消采集任务失败:', error);
            layer.msg('取消采集失败: ' + error.message, {icon: 2, time: 3000});
        }
    });
}

/**
 * 清空输入
 */
function clearInput(layer) {
    $('#product-url').val('');
    $('#capture-results-container').hide();
    $('#capture-status-container').hide();
    currentResult = null;
    currentTask = null;
    layer.msg('已清空', {icon: 1, time: 1500});
}

/**
 * 最小化状态
 */
function minimizeStatus() {
    $('#capture-status-container').slideUp();
}

/**
 * 显示历史记录
 */
function showHistory(layer, table) {
    layer.open({
        type: 2,
        title: '采集历史记录',
        area: ['90%', '80%'],
        content: '/view/capture/history',
        success: function(layero, index) {
            // 在历史记录页面加载完成后，可以在这里添加额外的逻辑
        }
    });
}

/**
 * 加载历史记录
 */
function loadHistory() {
    // 可以在这里加载本地存储的历史记录
    const history = JSON.parse(localStorage.getItem('captureHistory') || '[]');
    console.log('加载历史记录:', history.length + '条');
}

/**
 * 保存到历史记录
 */
function saveToHistory(result) {
    const history = JSON.parse(localStorage.getItem('captureHistory') || '[]');
    
    // 避免重复添加相同的URL
    const existingIndex = history.findIndex(item => item.url === result.url);
    if (existingIndex !== -1) {
        history.splice(existingIndex, 1);
    }
    
    // 添加新记录到开头
    history.unshift({
        ...result,
        timestamp: new Date().toISOString(),
        id: 'history_' + Date.now()
    });
    
    // 限制历史记录数量
    if (history.length > 50) {
        history.splice(50);
    }
    
    localStorage.setItem('captureHistory', JSON.stringify(history));
}

/**
 * 检查服务状态
 */
async function checkServiceStatus() {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        
        if (data.success) {
            console.log('服务状态正常');
        } else {
            console.warn('服务状态异常:', data.message);
        }
        
    } catch (error) {
        console.error('无法连接服务:', error);
        layui.layer.msg('无法连接到采集服务，请检查服务是否正常运行', {
            icon: 2,
            time: 5000
        });
    }
}

/**
 * 拖拽上传功能
 */
function setupDragAndDrop() {
    const dropZone = document.getElementById('product-url');
    
    if (!dropZone) return;
    
    // 防止默认拖放行为
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });
    
    // 高亮拖放区域
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    // 处理拖放事件
    dropZone.addEventListener('drop', handleDrop, false);
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    function highlight(e) {
        dropZone.classList.add('highlight');
    }
    
    function unhighlight(e) {
        dropZone.classList.remove('highlight');
    }
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        if (files.length > 0) {
            handleFiles(files);
        } else {
            // 检查是否有文本数据
            const text = dt.getData('text');
            if (text && validateTaobaoUrl(text)) {
                $('#product-url').val(text);
                layui.layer.msg('链接已自动填入', {icon: 1, time: 1500});
            }
        }
    }
    
    function handleFiles(files) {
        // 处理文件上传
        Array.from(files).forEach(file => {
            if (file.type.startsWith('image/')) {
                uploadImage(file);
            }
        });
    }
    
    function uploadImage(file) {
        const formData = new FormData();
        formData.append('image', file);
        
        const loadingIndex = layui.layer.msg('上传图片中...', {
            icon: 16,
            shade: 0.3,
            time: 0
        });
        
        fetch('/api/upload/image', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            layui.layer.close(loadingIndex);
            if (data.success) {
                layui.layer.msg('图片上传成功', {icon: 1, time: 2000});
            } else {
                layui.layer.msg('图片上传失败: ' + data.message, {icon: 2, time: 3000});
            }
        })
        .catch(error => {
            layui.layer.close(loadingIndex);
            layui.layer.msg('图片上传请求失败', {icon: 2, time: 3000});
        });
    }
}

/**
 * 工具函数
 */
const Utils = {
    // 格式化文件大小
    formatFileSize: function(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },
    
    // 格式化价格
    formatPrice: function(price) {
        return '¥' + parseFloat(price).toFixed(2);
    },
    
    // 提取商品ID
    extractItemId: function(url) {
        const match = url.match(/[?&]id=(\d+)/);
        return match ? match[1] : null;
    },
    
    // 生成任务ID
    generateTaskId: function() {
        return 'task_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    },
    
    // 防抖函数
    debounce: function(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    // 节流函数
    throttle: function(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
};

// 页面加载完成后执行
$(document).ready(function() {
    console.log('淘宝商品信息采集系统已加载');
});