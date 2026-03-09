let bridge = null;
let allTools = [];
let selectedToolId = null;
let selectedDescriptor = null;

console.log('=== Detection Page Full - 初始化 ===');

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('✓ QWebChannel 连接成功');
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('收到 Python 信号: tool_selected', tool_id);
    });

    // 加载工具列表
    loadTools();

    // 搜索功能
    document.getElementById('search').addEventListener('input', function(e) {
        filterTools(e.target.value);
    });

    // 运行按钮
    document.getElementById('run-btn').addEventListener('click', runTool);

    // 清空按钮
    document.getElementById('clear-btn').addEventListener('click', clearForm);
});

function loadTools() {
    console.log('加载工具列表...');
    bridge.get_tools(function(json) {
        try {
            allTools = JSON.parse(json);
            console.log(`✓ 加载了 ${allTools.length} 个工具`);
            renderCards(allTools);
            updateCount(allTools.length, allTools.length);
        } catch (e) {
            console.error('解析工具列表失败:', e);
        }
    });
}

function renderCards(tools) {
    const container = document.getElementById('cards');
    container.innerHTML = '';

    if (tools.length === 0) {
        container.innerHTML = '<div style="padding: 40px; text-align: center; color: #999;">没有找到工具</div>';
        return;
    }

    tools.forEach(tool => {
        const card = createCard(tool);
        container.appendChild(card);
    });
}

function createCard(tool) {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.toolId = tool.id;

    card.innerHTML = `
        <div class="card-header">
            <span class="card-title">${tool.name}</span>
            <span class="card-version">v${tool.version}</span>
        </div>
        <div class="card-subtitle">${tool.id} · ${tool.category}</div>
        <div class="card-chips">
            <span class="chip category">${tool.category}</span>
            <span class="chip input">${tool.inputs_count} 输入</span>
            <span class="chip param">${tool.params_count} 参数</span>
            ${tool.db_count > 0 ? `<span class="chip database">${tool.db_count} 数据库</span>` : ''}
        </div>
        <div class="card-description">${tool.description || '暂无描述'}</div>
    `;

    card.addEventListener('click', function() {
        selectTool(tool.id);
    });

    return card;
}

function selectTool(toolId) {
    console.log('选择工具:', toolId);
    selectedToolId = toolId;

    // 更新卡片选中状态
    document.querySelectorAll('.card').forEach(c => c.classList.remove('selected'));
    const card = document.querySelector(`[data-tool-id="${toolId}"]`);
    if (card) {
        card.classList.add('selected');
    }

    // 通知 Python
    bridge.select_tool(toolId);

    // 获取工具详细信息
    bridge.get_tool_descriptor(toolId, function(json) {
        try {
            selectedDescriptor = JSON.parse(json);
            console.log('工具描述符:', selectedDescriptor);
            showToolPanel(selectedDescriptor);
        } catch (e) {
            console.error('解析工具描述符失败:', e);
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
    document.getElementById('tool-category').textContent = descriptor.category || 'unknown';

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
                       placeholder="${input.description || '选择文件...'}"
                       readonly>
                <button class="btn-browse" onclick="browseFile('input-${input.name}')">浏览...</button>
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
        container.innerHTML = '<div style="color: #999; font-size: 12px;">此工具无需配置参数</div>';
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
                    <option value="true" ${defaultValue === true ? 'selected' : ''}>是</option>
                    <option value="false" ${defaultValue === false ? 'selected' : ''}>否</option>
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
                       placeholder="${db.description || '数据库路径...'}"
                       readonly>
                <button class="btn-browse" onclick="browseFile('db-${db.name}')">浏览...</button>
            </div>
            ${db.description ? `<div class="form-help">${db.description}</div>` : ''}
        `;

        container.appendChild(group);
    });
}

function browseFile(inputId) {
    console.log('浏览文件:', inputId);
    bridge.browse_file(inputId, function(filePath) {
        if (filePath) {
            document.getElementById(inputId).value = filePath;
        }
    });
}

function runTool() {
    if (!selectedToolId || !selectedDescriptor) {
        alert('请先选择一个工具');
        return;
    }

    console.log('运行工具:', selectedToolId);

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

    console.log('参数:', params);

    // 调用 Python 执行
    bridge.run_tool(selectedToolId, JSON.stringify(params));

    alert('工具已提交执行！');
}

function clearForm() {
    // 清空所有输入
    document.querySelectorAll('.form-input').forEach(input => {
        if (!input.readOnly) {
            input.value = '';
        }
    });
}

function filterTools(query) {
    const filtered = allTools.filter(tool => {
        const searchText = `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase();
        return searchText.includes(query.toLowerCase());
    });

    renderCards(filtered);
    updateCount(filtered.length, allTools.length);
}

function updateCount(visible, total) {
    document.getElementById('count').textContent = `${visible} / ${total} 个工具`;
}
