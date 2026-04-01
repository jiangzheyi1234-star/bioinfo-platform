let bridge = null;
let allTools = [];
let checkInProgress = false;

console.log('=== Tool Environment Table ===');

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('QWebChannel connected');
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.toolListLoaded.connect(onToolListLoaded);
    bridge.checkStarted.connect(onCheckStarted);
    bridge.toolChecked.connect(onToolChecked);
    bridge.checkFinished.connect(onCheckFinished);
    bridge.installStarted.connect(onInstallStarted);
    bridge.installFinished.connect(onInstallFinished);

    // 绑定事件
    document.getElementById('card-header').addEventListener('click', toggleExpand);
    document.getElementById('btn-check').addEventListener('click', startCheck);

    // 初始化高度（折叠状态）
    updateHeight();

    // 加载工具列表
    loadTools();
});

// 加载工具列表
function loadTools() {
    console.log('Loading tools...');
    bridge.getTools(function(json) {
        try {
            allTools = JSON.parse(json);
            console.log('Loaded ' + allTools.length + ' tools');
            renderToolList(allTools);
        } catch (e) {
            console.error('Failed to parse tools:', e);
            showError('工具列表加载失败');
        }
    });
}

// 渲染工具列表
function renderToolList(tools) {
    const tbody = document.getElementById('tool-tbody');
    tbody.innerHTML = '';

    document.getElementById('tool-count').textContent = tools.length;

    if (tools.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="tool-env-empty-row">未发现任何工具</td></tr>';
        return;
    }

    tools.forEach(function(tool) {
        const row = document.createElement('tr');
        row.id = 'row-' + tool.id;
        row.dataset.toolId = tool.id;

        const envName = tool.conda_env || '(系统路径)';
        const envClass = tool.conda_env ? '' : 'system';

        row.innerHTML =
            '<td class="col-name"><span class="tool-name">' + escapeHtml(tool.name) + '</span></td>' +
            '<td class="col-env"><span class="env-name ' + envClass + '">' + escapeHtml(envName) + '</span></td>' +
            '<td class="col-status status-cell">' +
                '<span class="status-dot">' +
                    '<span class="dot dot-pending"></span>' +
                    '<span class="status-text-dot">待检测</span>' +
                '</span>' +
            '</td>' +
            '<td class="col-action action-cell">' +
                '<button class="ui-button ui-button--primary ui-button--sm ui-button--install is-hidden" data-tool-id="' + tool.id + '">安装</button>' +
            '</td>';

        const btn = row.querySelector('[data-tool-id]');
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            installTool(tool.id);
        });

        tbody.appendChild(row);
    });

    updateSummary('pending', 0, tools.length);
}

// 折叠/展开
function toggleExpand() {
    const header = document.getElementById('card-header');
    const body = document.getElementById('card-body');

    header.classList.toggle('expanded');
    body.classList.toggle('expanded');

    // 通知Python调整WebView高度
    updateHeight();
}

// 更新WebView高度
function updateHeight() {
    const card = document.querySelector('.tool-env-card');
    const body = document.getElementById('card-body');
    if (card && bridge) {
        // 只在展开状态时才使用内容高度，折叠状态使用标题行高度(约45px)
        const height = body.classList.contains('expanded') ? card.offsetHeight : 45;
        bridge.setHeight(height);
    }
}

// 页面加载完成后更新高度
window.addEventListener('load', updateHeight);

// 开始检测
function startCheck() {
    if (checkInProgress) return;

    console.log('Starting check...');
    bridge.startCheck();
}

// Python 信号回调
function onToolListLoaded(json) {
    console.log('toolListLoaded signal received');
    try {
        allTools = JSON.parse(json);
        renderToolList(allTools);
    } catch (e) {
        console.error('Failed to parse tool list:', e);
    }
}

function onCheckStarted() {
    console.log('Check started');
    checkInProgress = true;

    const btn = document.getElementById('btn-check');
    btn.disabled = true;
    btn.textContent = '检测中...';

    document.getElementById('status-text').textContent = '正在检测工具环境...';

    // 重置所有状态为检测中
    allTools.forEach(function(tool) {
        updateToolStatus(tool.id, 'checking');
    });
}

function onToolChecked(toolId, ok) {
    console.log('Tool checked: ' + toolId + ', ok=' + ok);
    updateToolStatus(toolId, ok ? 'ready' : 'missing');
}

function onInstallStarted(toolId) {
    console.log('Install started: ' + toolId);
    updateToolStatus(toolId, 'installing');
}

function onInstallFinished(toolId, success) {
    console.log('Install finished: ' + toolId + ', success=' + success);
    updateToolStatus(toolId, success ? 'ready' : 'missing');
}

function onCheckFinished(resultJson) {
    console.log('Check finished: ' + resultJson);
    checkInProgress = false;

    const btn = document.getElementById('btn-check');
    btn.disabled = false;
    btn.textContent = '一键检测';

    try {
        const result = JSON.parse(resultJson);
        const readyCount = result.ready_count || 0;
        const totalCount = result.total_count || allTools.length;
        const missingCount = totalCount - readyCount;

        updateSummary('checked', readyCount, totalCount);

        if (missingCount === 0) {
            document.getElementById('status-text').textContent = '所有环境就绪';
        } else {
            document.getElementById('status-text').textContent = readyCount + '/' + totalCount + ' 就绪，' + missingCount + ' 个需要安装';
        }
    } catch (e) {
        console.error('Failed to parse check result:', e);
        document.getElementById('status-text').textContent = '检测完成';
    }
}

// 更新单个工具状态
function updateToolStatus(toolId, status) {
    const row = document.getElementById('row-' + toolId);
    if (!row) return;

    const dot = row.querySelector('.dot');
    const text = row.querySelector('.status-text-dot');
    const btn = row.querySelector('.btn-install');

    dot.className = 'dot';

    switch (status) {
        case 'ready':
            dot.classList.add('dot-ready');
            text.textContent = '就绪';
            if (btn) btn.classList.add('is-hidden');
            break;
        case 'missing':
            dot.classList.add('dot-missing');
            text.textContent = '缺失';
            if (btn) btn.classList.remove('is-hidden');
            break;
        case 'checking':
            dot.classList.add('dot-checking');
            text.textContent = '检测中';
            if (btn) btn.classList.add('is-hidden');
            break;
        case 'installing':
            dot.classList.add('dot-installing');
            text.textContent = '安装中';
            if (btn) btn.classList.add('is-hidden');
            break;
        case 'pending':
        default:
            dot.classList.add('dot-pending');
            text.textContent = '待检测';
            if (btn) btn.classList.add('is-hidden');
            break;
    }
}

// 更新摘要
function updateSummary(state, readyCount, totalCount) {
    const summary = document.getElementById('summary-text');
    const missingCount = totalCount - readyCount;

    summary.className = 'summary';

    if (state === 'pending') {
        summary.textContent = '未检测';
    } else if (missingCount === 0) {
        summary.classList.add('ready');
        summary.textContent = '全部就绪';
    } else if (readyCount === 0) {
        summary.classList.add('error');
        summary.textContent = missingCount + ' 个缺失';
    } else {
        summary.classList.add('partial');
        summary.textContent = readyCount + '/' + totalCount + ' 就绪';
    }
}

// 安装工具
function installTool(toolId) {
    console.log('Installing tool: ' + toolId);
    bridge.installTool(toolId);
}

// 显示错误
function showError(message) {
    const tbody = document.getElementById('tool-tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="empty-row" style="color: #cf222e;">' + escapeHtml(message) + '</td></tr>';
}

// HTML 转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
