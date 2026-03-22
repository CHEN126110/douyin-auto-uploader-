/**
 * 历史记录管理器
 */

let currentHistoryData = [];
let tableInstance = null;

// 初始化layui
layui.use(['layer', 'table', 'laydate'], function() {
    const layer = layui.layer;
    const table = layui.table;
    const laydate = layui.laydate;
    
    // 初始化历史记录页面
    initHistoryPage(layer, table, laydate);
});

/**
 * 初始化历史记录页面
 */
function initHistoryPage(layer, table, laydate) {
    console.log('初始化历史记录页面...');
    
    // 初始化日期选择器
    initDatePickers(laydate);
    
    // 绑定事件
    bindHistoryEvents(layer, table);
    
    // 加载历史记录
    loadHistoryData(layer, table);
    
    console.log('历史记录页面初始化完成');
}

/**
 * 初始化日期选择器
 */
function initDatePickers(laydate) {
    // 开始日期
    laydate.render({
        elem: '#start-date',
        type: 'date',
        format: 'yyyy-MM-dd',
        done: function(value, date) {
            console.log('开始日期选择:', value);
        }
    });
    
    // 结束日期
    laydate.render({
        elem: '#end-date',
        type: 'date',
        format: 'yyyy-MM-dd',
        done: function(value, date) {
            console.log('结束日期选择:', value);
        }
    });
}

/**
 * 绑定历史记录事件
 */
function bindHistoryEvents(layer, table) {
    // 搜索按钮
    $('#search-btn').click(function() {
        searchHistory(layer, table);
    });
    
    // 日期筛选
    $('#filter-date').click(function() {
        filterByDate(layer, table);
    });
    
    // 批量删除
    $('#batch-delete').click(function() {
        batchDelete(layer, table);
    });
    
    // 导出数据
    $('#export-data').click(function() {
        exportHistoryData(layer);
    });
    
    // 清空历史
    $('#clear-all').click(function() {
        clearAllHistory(layer, table);
    });
    
    // 搜索框回车事件
    const debouncedSearch = debounce(function() { searchHistory(layer, table); }, 300);
    $('#search-keyword').on('keyup', debouncedSearch);
    $('#search-keyword').keypress(function(e) {
        if (e.which === 13) {
            searchHistory(layer, table);
        }
    });
    
    // 表格工具栏事件
    table.on('tool(history-table)', function(obj) {
        const data = obj.data;
        const event = obj.event;
        
        switch(event) {
            case 'view':
                viewHistoryItem(layer, data);
                break;
            case 'reuse':
                reuseHistoryItem(layer, data);
                break;
            case 'delete':
                deleteHistoryItem(layer, table, data);
                break;
        }
    });
    
    // 表格复选框事件
    table.on('checkbox(history-table)', function(obj) {
        console.log('复选框状态改变:', obj);
    });
}

/**
 * 加载历史记录数据
 */
async function loadHistoryData(layer, table) {
    try {
        const response = await fetch('/api/product/capture/history');
        const data = await response.json();
        
        if (data.success) {
            currentHistoryData = data.history || [];
            renderHistoryTable(table, currentHistoryData);
            updateStatistics();
            
            if (currentHistoryData.length === 0) {
                $('#empty-history').show();
            } else {
                $('#empty-history').hide();
            }
        } else {
            layer.msg('加载历史记录失败: ' + data.message, {icon: 2, time: 3000});
        }
        
    } catch (error) {
        console.error('加载历史记录失败:', error);
        layer.msg('加载历史记录失败: ' + error.message, {icon: 2, time: 3000});
    }
}

/**
 * 渲染历史记录表格
 */
function renderHistoryTable(table, data) {
    if (tableInstance) {
        tableInstance.reload({
            data: data
        });
        return;
    }
    
    tableInstance = table.render({
        elem: '#history-table',
        data: data,
        cols: [[
            {type: 'checkbox', width: 50},
            {field: 'task_id', title: '任务ID', width: 120, sort: true, templet: function(d) {
                return '<span style="font-family: monospace; font-size: 12px;">' + d.task_id + '</span>';
            }},
            {field: 'title', title: '商品标题', minWidth: 200, templet: function(d) {
                return '<div class="product-title-cell" title="' + d.title + '">' + d.title + '</div>';
            }},
            {field: 'url', title: '商品链接', minWidth: 200, templet: function(d) {
                return '<div class="product-link-cell" title="' + d.url + '">' + 
                       '<a href="' + d.url + '" target="_blank" style="color: #1890ff;">' + d.url + '</a></div>';
            }},
            {field: 'price', title: '价格', width: 100, sort: true, templet: function(d) {
                return '<span class="price-cell">¥' + (d.price || 0) + '</span>';
            }},
            {field: 'status', title: '状态', width: 80, templet: function(d) {
                if (d.status === 'completed') {
                    return '<span class="layui-badge layui-bg-green">成功</span>';
                } else if (d.status === 'failed') {
                    return '<span class="layui-badge layui-bg-red">失败</span>';
                } else {
                    return '<span class="layui-badge layui-bg-blue">' + d.status + '</span>';
                }
            }},
            {field: 'created_at', title: '采集时间', width: 150, sort: true, templet: function(d) {
                return '<div style="font-size: 12px; color: #666;">' + formatDateTime(d.created_at) + '</div>';
            }},
            {width: 120, title: '操作', toolbar: '#action-tpl'}
        ]],
        page: {
            layout: ['limit', 'count', 'prev', 'page', 'next', 'skip'],
            limits: [10, 20, 50, 100],
            limit: 20,
            groups: 5,
            first: '首页',
            last: '尾页'
        },
        skin: 'line',
        size: 'sm',
        even: true,
        done: function(res, curr, count) {
            console.log('表格渲染完成:', res, curr, count);
        }
    });
}

/**
 * 搜索历史记录
 */
function searchHistory(layer, table) {
    const keyword = $('#search-keyword').val().trim();
    
    if (!keyword) {
        renderHistoryTable(table, currentHistoryData);
        return;
    }
    
    const filteredData = currentHistoryData.filter(item => {
        return item.title.toLowerCase().includes(keyword.toLowerCase()) ||
               item.url.toLowerCase().includes(keyword.toLowerCase());
    });
    
    renderHistoryTable(table, filteredData);
    
    if (filteredData.length === 0) {
        layer.msg('没有找到匹配的历史记录', {icon: 0, time: 2000});
    }
}

/**
 * 按日期筛选
 */
function filterByDate(layer, table) {
    const startDate = $('#start-date').val();
    const endDate = $('#end-date').val();
    
    if (!startDate && !endDate) {
        renderHistoryTable(table, currentHistoryData);
        return;
    }
    
    const filteredData = currentHistoryData.filter(item => {
        const itemDate = new Date(item.created_at);
        
        if (startDate && endDate) {
            const start = new Date(startDate);
            const end = new Date(endDate);
            end.setHours(23, 59, 59, 999);
            return itemDate >= start && itemDate <= end;
        } else if (startDate) {
            const start = new Date(startDate);
            return itemDate >= start;
        } else if (endDate) {
            const end = new Date(endDate);
            end.setHours(23, 59, 59, 999);
            return itemDate <= end;
        }
        
        return true;
    });
    
    renderHistoryTable(table, filteredData);
    
    if (filteredData.length === 0) {
        layer.msg('指定日期范围内没有历史记录', {icon: 0, time: 2000});
    }
}

/**
 * 批量删除
 */
function batchDelete(layer, table) {
    const checkStatus = table.checkStatus('history-table');
    const selectedData = checkStatus.data;
    if (selectedData.length === 0) {
        layer.msg('请选择要删除的历史记录', {icon: 0, time: 2000});
        return;
    }
    layer.confirm(`确定要删除选中的 ${selectedData.length} 条历史记录吗？`, {
        btn: ['确定', '取消'],
        icon: 3
    }, async function() {
        try {
            const taskIds = selectedData.map(item => item.task_id);
            const resp = await fetch('/api/product/capture/history', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: taskIds })
            });
            const data = await resp.json();
            if (data.success) {
                currentHistoryData = currentHistoryData.filter(item => !taskIds.includes(item.task_id));
                renderHistoryTable(table, currentHistoryData);
                updateStatistics();
                layer.msg('批量删除成功', {icon: 1, time: 2000});
            } else {
                layer.msg(data.message || '批量删除失败', {icon: 2, time: 2000});
            }
        } catch (error) {
            layer.msg('批量删除请求失败', {icon: 2, time: 2000});
        }
    });
}

/**
 * 导出历史数据
 */
function exportHistoryData(layer) {
    if (currentHistoryData.length === 0) {
        layer.msg('没有可导出的历史记录', {icon: 0, time: 2000});
        return;
    }
    
    layer.confirm('确定要导出当前显示的历史记录吗？', {
        btn: ['确定', '取消'],
        icon: 3
    }, function() {
        // 准备导出数据
        const exportData = currentHistoryData.map(item => ({
            '任务ID': item.task_id,
            '商品标题': item.title,
            '商品链接': item.url,
            '价格': '¥' + (item.price || 0),
            '状态': item.status === 'completed' ? '成功' : '失败',
            '采集时间': formatDateTime(item.created_at)
        }));
        
        // 转换为CSV格式
        const csvContent = convertToCSV(exportData);
        
        // 创建下载链接
        const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        
        link.setAttribute('href', url);
        link.setAttribute('download', '商品采集历史_' + formatDate(new Date()) + '.csv');
        link.style.visibility = 'hidden';
        
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        layer.msg('历史记录导出成功', {icon: 1, time: 2000});
    });
}

/**
 * 清空所有历史记录
 */
function clearAllHistory(layer, table) {
    if (currentHistoryData.length === 0) {
        layer.msg('历史记录已经是空的', {icon: 0, time: 2000});
        return;
    }
    layer.confirm('确定要清空所有历史记录吗？此操作不可恢复！', {
        btn: ['确定', '取消'],
        icon: 3
    }, async function() {
        try {
            const resp = await fetch('/api/product/capture/history', { method: 'DELETE' });
            const result = await resp.json();
            if (result.success) {
                currentHistoryData = [];
                renderHistoryTable(table, currentHistoryData);
                updateStatistics();
                $('#empty-history').show();
                layer.msg('历史记录已清空', {icon: 1, time: 2000});
            } else {
                layer.msg(result.message || '清空失败', {icon: 2, time: 2000});
            }
        } catch (error) {
            layer.msg('清空请求失败', {icon: 2, time: 2000});
        }
    });
}

/**
 * 查看历史记录详情
 */
function viewHistoryItem(layer, data) {
    // 获取详细的采集结果
    fetch('/api/product/capture/status/' + data.task_id)
        .then(response => response.json())
        .then(result => {
            if (result.success && result.result) {
                showHistoryDetail(layer, result.result);
            } else {
                layer.msg('无法获取详细的采集结果', {icon: 2, time: 2000});
            }
        })
        .catch(error => {
            console.error('获取采集结果失败:', error);
            layer.msg('获取采集结果失败', {icon: 2, time: 2000});
        });
}

/**
 * 显示历史记录详情
 */
function showHistoryDetail(layer, result) {
    const content = `
        <div style="padding: 20px; max-height: 500px; overflow-y: auto;">
            <div style="margin-bottom: 20px;">
                <h4 style="color: #333; margin-bottom: 10px;">基本信息</h4>
                <div style="background: #f8f9fa; padding: 15px; border-radius: 5px;">
                    <div style="margin-bottom: 10px;">
                        <strong>商品标题：</strong> ${result.title || '未获取到标题'}
                    </div>
                    <div style="margin-bottom: 10px;">
                        <strong>商品价格：</strong> <span style="color: #ff4d4f; font-weight: bold;">¥${result.price.current || 0}</span>
                    </div>
                    <div style="margin-bottom: 10px;">
                        <strong>商品链接：</strong> <a href="${result.url}" target="_blank" style="color: #1890ff;">${result.url}</a>
                    </div>
                    <div>
                        <strong>采集时间：</strong> ${formatDateTime(result.captured_at)}
                    </div>
                </div>
            </div>
            
            <div style="margin-bottom: 20px;">
                <h4 style="color: #333; margin-bottom: 10px;">SKU信息</h4>
                <div style="max-height: 200px; overflow-y: auto;">
                    ${result.sku_info && result.sku_info.length > 0 ? 
                        result.sku_info.map(sku => `
                            <div style="border: 1px solid #e8e8e8; padding: 10px; margin-bottom: 10px; border-radius: 5px;">
                                <div style="font-weight: bold; margin-bottom: 5px;">${sku.name || '未命名SKU'}</div>
                                <div style="color: #ff4d4f;">价格：¥${sku.price || 0}</div>
                                ${sku.images && sku.images.length > 0 ? 
                                    `<div style="margin-top: 5px;">
                                        <img src="${sku.images[0]}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 3px;">
                                    </div>` : ''
                                }
                            </div>
                        `).join('') : 
                        '<div style="color: #999; text-align: center; padding: 20px;">未获取到SKU信息</div>'
                    }
                </div>
            </div>
            
            <div>
                <h4 style="color: #333; margin-bottom: 10px;">商品参数</h4>
                <div style="max-height: 200px; overflow-y: auto;">
                    ${result.parameters && result.parameters.length > 0 ? 
                        result.parameters.map(param => `
                            <div style="display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #f0f0f0;">
                                <span style="color: #666;">${param.name}</span>
                                <span style="font-weight: bold;">${param.value}</span>
                            </div>
                        `).join('') : 
                        '<div style="color: #999; text-align: center; padding: 20px;">未获取到商品参数</div>'
                    }
                </div>
            </div>
        </div>
    `;
    
    layer.open({
        type: 1,
        title: '采集结果详情',
        area: ['600px', '500px'],
        content: content,
        btn: ['关闭']
    });
}

/**
 * 重用历史记录
 */
function reuseHistoryItem(layer, data) {
    // 将URL传递给父窗口
    if (window.parent && window.parent.$) {
        window.parent.$('#product-url').val(data.url);
        layer.msg('链接已填入采集页面', {icon: 1, time: 2000});
        
        // 关闭当前窗口
        setTimeout(() => {
            const index = parent.layer.getFrameIndex(window.name);
            parent.layer.close(index);
        }, 1000);
    } else {
        layer.msg('无法在父窗口中填入链接', {icon: 2, time: 2000});
    }
}

/**
 * 删除历史记录
 */
function deleteHistoryItem(layer, table, data) {
    layer.confirm('确定要删除这条历史记录吗？', {
        btn: ['确定', '取消'],
        icon: 3
    }, async function() {
        try {
            const resp = await fetch('/api/product/capture/history/' + data.task_id, { method: 'DELETE' });
            const result = await resp.json();
            if (result.success) {
                currentHistoryData = currentHistoryData.filter(item => item.task_id !== data.task_id);
                renderHistoryTable(table, currentHistoryData);
                updateStatistics();
                layer.msg('删除成功', {icon: 1, time: 2000});
            } else {
                layer.msg(result.message || '删除失败', {icon: 2, time: 2000});
            }
        } catch (error) {
            layer.msg('删除请求失败', {icon: 2, time: 2000});
        }
    });
}

/**
 * 更新统计信息
 */
function updateStatistics() {
    const total = currentHistoryData.length;
    const success = currentHistoryData.filter(item => item.status === 'completed').length;
    const failed = currentHistoryData.filter(item => item.status === 'failed').length;
    
    $('#total-count').text(total);
    $('#success-count').text(success);
    $('#failed-count').text(failed);
}

/**
 * 格式化日期时间
 */
function formatDateTime(dateString) {
    if (!dateString) return '';
    
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * 格式化日期
 */
function formatDate(date) {
    return date.toISOString().split('T')[0];
}

/**
 * 转换为CSV格式
 */
function convertToCSV(data) {
    if (data.length === 0) return '';
    
    const headers = Object.keys(data[0]);
    const csvContent = [
        headers.join(','),
        ...data.map(row => headers.map(header => {
            const value = row[header];
            return typeof value === 'string' && value.includes(',') ? `"${value}"` : value;
        }).join(','))
    ].join('\n');
    
    return csvContent;
}

/**
 * 跳转到采集页面
 */
function goToCapture() {
    if (window.parent) {
        window.parent.location.href = '/capture.html';
    } else {
        window.location.href = '/capture.html';
    }
}

// 页面加载完成后执行
$(document).ready(function() {
    console.log('历史记录页面加载完成');
});