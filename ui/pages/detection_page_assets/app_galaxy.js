let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;

console.log('=== Galaxy Style Detection Page ===');

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('✓ QWebChannel connected');
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('Tool selected from Python:', tool_id);
    });

    // 标签切换
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });

    // 加载工具列表
    loadTools();

    // 搜索功能
    document.getElementById('search').addEventListener('input', function(e) {
        renderToolsList(e.target.value);
    });

    // 刷新历史按钮
    document.getElementById('btn-refresh').addEventListener('click', loadHistory);

    // 运行按钮
    document.getElementById('run-btn').addEventListener('click', runTool);

    // 清空按钮
    document.getElementById('clear-btn').addEventListener('click', clearForm);
});

function switchTab(tab) {
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // 更新内容区状态
    document.querySelectorAll('.tab-content').forEach(function(content) {
        content.classList.remove('active');
    });
    const target = document.getElementById('tab-' + tab);
    if (target) {
        target.classList.add('active');
    }

    // 切换到历史标签时加载数据
    if (tab === 'history') {
        loadHistory();
    }
}

function loadTools() {
    console.log('Loading tools...');
    bridge.get_tools(function(json) {
        try {
            allTools = JSON.parse(json);
            console.log(`✓ Loaded ${allTools.length} tools`);
            renderToolsList();
        } catch (e) {
            console.error('Failed to parse tools:', e);
        }
    });
}

function renderToolsList(searchQuery = '') {
    const container = document.getElementById('tools-list');
    container.innerHTML = '';

    // 过滤工具
    let filtered = allTools;

    // 按搜索词过滤
    if (searchQuery) {
        const query = searchQuery.toLowerCase();
        filtered = filtered.filter(tool => {
            const searchText = `${tool.id} ${tool.name} ${tool.description}`.toLowerCase();
            return searchText.includes(query);
        });
    }

    // 更新计数
    document.getElementById('count').textContent = `${filtered.length} tools`;

    if (filtered.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #6c757d; font-size: 12px;">No tools found</div>';
        return;
    }

    // 按分类分组
    const grouped = {};
    filtered.forEach(tool => {
        const category = tool.category || 'unknown';
        if (!grouped[category]) {
            grouped[category] = [];
        }
        grouped[category].push(tool);
    });

    // 渲染分类组
    Object.keys(grouped).sort().forEach(category => {
        const group = createCategoryGroup(category, grouped[category]);
        container.appendChild(group);
    });
}

function createCategoryGroup(category, tools) {
    const group = document.createElement('div');
    group.className = 'category-group';

    // 分类标题
    const header = document.createElement('div');
    header.className = 'category-header';
    header.innerHTML = `
        <span>${getCategoryName(category)}</span>
        <span class="category-arrow">▼</span>
    `;

    // 点击折叠/展开
    header.addEventListener('click', function() {
        group.classList.toggle('collapsed');
    });

    // 工具列表
    const toolsContainer = document.createElement('div');
    toolsContainer.className = 'category-tools';

    tools.forEach(tool => {
        const item = createToolItem(tool);
        toolsContainer.appendChild(item);
    });

    group.appendChild(header);
    group.appendChild(toolsContainer);

    return group;
}

function createToolItem(tool) {
    const item = document.createElement('div');
    item.className = 'tool-item';
    item.dataset.toolId = tool.id;

    item.innerHTML = `
        <div class="tool-name">${tool.name}</div>
        <div class="tool-desc">${tool.description || 'No description available'}</div>
    `;

    item.addEventListener('click', function() {
        selectTool(tool.id);
    });

    return item;
}

function getCategoryName(category) {
    const names = {
        'qc': '质量控制 (QC)',
        'host_removal': '宿主去除',
        'taxonomy': '物种分类',
        'assembly': '组装',
        'binning': '分箱',
        'quality': '质量评估',
        'annotation': '功能注释',
        'blast': '序列比对',
        'unknown': '其他'
    };
    return names[category] || category.toUpperCase();
}

function selectTool(toolId) {
    console.log('Selecting tool:', toolId);
    selectedToolId = toolId;

    // 更新列表选中状态
    document.querySelectorAll('.tool-item').forEach(item => {
        item.classList.remove('selected');
    });
    const item = document.querySelector(`[data-tool-id="${toolId}"]`);
    if (item) {
        item.classList.add('selected');
    }

    // 通知 Python
    bridge.select_tool(toolId);

    // 获取工具详细信息
    bridge.get_tool_descriptor(toolId, function(json) {
        try {
            selectedDescriptor = JSON.parse(json);
            console.log('Tool descriptor:', selectedDescriptor);
            showToolPanel(selectedDescriptor);
        } catch (e) {
            console.error('Failed to parse descriptor:', e);
        }
    });
}

function showToolPanel(descriptor) {
    // 隐藏占位符，显示内容
    document.querySelector('.panel-placeholder').style.display = 'none';
    document.getElementById('panel-content').style.display = 'flex';

    // 更新头部信息
    document.getElementById('tool-name').textContent = descriptor.name || descriptor.id;
    document.getElementById('tool-id').textContent = descriptor.id;
    document.getElementById('tool-version').textContent = 'v' + (descriptor.version || 'unknown');
    document.getElementById('tool-category').textContent = getCategoryName(descriptor.category || 'unknown');

    // 渲染输入文件
    renderInputs(descriptor.inputs || []);

    // 渲染参数
    renderParams(descriptor.parameters || []);

    // 渲染数据库
    if (descriptor.databases && descriptor.databases.length > 0) {
        document.getElementById('databases-section').style.display = 'block';
        renderDatabases(descriptor.databases);
    } else {
        document.getElementById('databases-section').style.display = 'none';
    }
}

function renderInputs(inputs) {
    const container = document.getElementById('inputs-container');
    container.innerHTML = '';

    if (inputs.length === 0) {
        container.innerHTML = '<div style="color: #6c757d; font-size: 13px;">No input files required</div>';
        return;
    }

    inputs.forEach(input => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = input.required !== false ? '<span class="required">*</span>' : '';

        group.innerHTML = `
            <label class="form-label">
                ${input.label || input.name}${required}
            </label>
            <div class="input-group">
                <input type="text"
                       class="form-input"
                       id="input-${input.name}"
                       placeholder="${input.description || 'Select file...'}"
                       readonly>
                <button class="btn-browse" onclick="browseFile('input-${input.name}')">Browse...</button>
            </div>
            ${input.description ? `<div class="form-help">${input.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
}

function renderParams(params) {
    const container = document.getElementById('params-container');
    container.innerHTML = '';

    if (params.length === 0) {
        container.innerHTML = '<div style="color: #6c757d; font-size: 13px;">No parameters to configure</div>';
        return;
    }

    params.forEach(param => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = param.required !== false ? '<span class="required">*</span>' : '';
        const defaultValue = param.default !== undefined ? param.default : '';

        let inputHtml = '';
        if (param.type === 'int' || param.type === 'integer') {
            inputHtml = `<input type="number" class="form-input" id="param-${param.name}" value="${defaultValue}" step="1">`;
        } else if (param.type === 'float' || param.type === 'number') {
            inputHtml = `<input type="number" class="form-input" id="param-${param.name}" value="${defaultValue}" step="0.01">`;
        } else if (param.type === 'bool' || param.type === 'boolean') {
            inputHtml = `
                <select class="form-input" id="param-${param.name}">
                    <option value="true" ${defaultValue === true ? 'selected' : ''}>Yes</option>
                    <option value="false" ${defaultValue === false ? 'selected' : ''}>No</option>
                </select>
            `;
        } else {
            inputHtml = `<input type="text" class="form-input" id="param-${param.name}" value="${defaultValue}" placeholder="${param.description || ''}">`;
        }

        group.innerHTML = `
            <label class="form-label">
                ${param.label || param.name}${required}
            </label>
            ${inputHtml}
            ${param.description ? `<div class="form-help">${param.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
}

function renderDatabases(databases) {
    const container = document.getElementById('databases-container');
    container.innerHTML = '';

    databases.forEach(db => {
        const group = document.createElement('div');
        group.className = 'form-group';

        const required = db.required !== false ? '<span class="required">*</span>' : '';

        group.innerHTML = `
            <label class="form-label">
                ${db.label || db.name}${required}
            </label>
            <div class="input-group">
                <input type="text"
                       class="form-input"
                       id="db-${db.name}"
                       placeholder="${db.description || 'Database path...'}"
                       readonly>
                <button class="btn-browse" onclick="browseFile('db-${db.name}')">Browse...</button>
            </div>
            ${db.description ? `<div class="form-help">${db.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
}

function browseFile(inputId) {
    console.log('Browse file:', inputId);
    bridge.browse_file(inputId, function(filePath) {
        if (filePath) {
            document.getElementById(inputId).value = filePath;
        }
    });
}

function runTool() {
    if (!selectedToolId || !selectedDescriptor) {
        alert('Please select a tool first');
        return;
    }

    console.log('Running tool:', selectedToolId);

    // 收集参数
    const params = {};

    // 收集输入文件
    const inputs = selectedDescriptor.inputs || [];
    inputs.forEach(input => {
        const value = document.getElementById(`input-${input.name}`)?.value;
        if (value) {
            params[input.name] = value;
        }
    });

    // 收集参数
    const parameters = selectedDescriptor.parameters || [];
    parameters.forEach(param => {
        const element = document.getElementById(`param-${param.name}`);
        if (element) {
            let value = element.value;
            // 类型转换
            if (param.type === 'int' || param.type === 'integer') {
                value = parseInt(value);
            } else if (param.type === 'float' || param.type === 'number') {
                value = parseFloat(value);
            } else if (param.type === 'bool' || param.type === 'boolean') {
                value = value === 'true';
            }
            params[param.name] = value;
        }
    });

    // 收集数据库
    const databases = selectedDescriptor.databases || [];
    databases.forEach(db => {
        const value = document.getElementById(`db-${db.name}`)?.value;
        if (value) {
            params[db.name] = value;
        }
    });

    console.log('Parameters:', params);

    // 调用 Python 执行
    bridge.run_tool(selectedToolId, JSON.stringify(params));

    alert('Tool submitted for execution!');
}

function clearForm() {
    // 清空所有输入
    document.querySelectorAll('.form-input').forEach(input => {
        if (!input.readOnly) {
            input.value = '';
        }
    });
}

// 加载执行历史
function loadHistory() {
    console.log('Loading execution history...');
    
    // 调用 Python 获取执行历史
    bridge.get_execution_history(function(json) {
        try {
            const history = JSON.parse(json);
            console.log(`✓ Loaded ${history.length} execution records`);
            renderHistory(history);
        } catch (e) {
            console.error('Failed to parse history:', e);
        }
    });
}

// 渲染执行历史
function renderHistory(history) {
    const tbody = document.getElementById('history-tbody');
    tbody.innerHTML = '';

    if (history.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center; color: #6c757d; padding: 20px;">
                    暂无执行记录
                </td>
            </tr>
        `;
        return;
    }

    history.forEach(record => {
        const row = document.createElement('tr');
        
        // 状态样式
        const statusClass = `status-${record.status}`;
        const statusText = getStatusText(record.status);
        
        // 计算耗时
        const duration = record.completed_at 
            ? formatDuration(record.completed_at - record.created_at)
            : '-';

        row.innerHTML = `
            <td>${record.tool_id}</td>
            <td><span class="status-badge ${statusClass}">${statusText}</span></td>
            <td>${record.sample_id || '-'}</td>
            <td>${formatTime(record.created_at)}</td>
            <td>${duration}</td>
        `;

        tbody.appendChild(row);
    });
}

// 获取状态文本
function getStatusText(status) {
    const statusMap = {
        'pending': '等待中',
        'running': '运行中',
        'completed': '已完成',
        'failed': '失败'
    };
    return statusMap[status] || status;
}

// 格式化时间
function formatTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// 格式化时长
function formatDuration(seconds) {
    if (seconds < 60) {
        return `${Math.round(seconds)}秒`;
    } else if (seconds < 3600) {
        return `${Math.round(seconds / 60)}分钟`;
    } else {
        return `${Math.round(seconds / 3600)}小时`;
    }
}
