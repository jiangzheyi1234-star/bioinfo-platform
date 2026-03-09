let bridge = null;
let allTools = [];
let selectedToolId = null;

console.log('=== Detection Page Web - JavaScript 启动 ===');

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    console.log('✓ QWebChannel 连接成功');
    bridge = channel.objects.bridge;
    console.log('✓ Bridge 对象获取成功:', bridge);

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('Tool selected from Python:', tool_id);
    });

    // 加载工具列表
    console.log('开始加载工具列表...');
    loadTools();

    // 搜索功能
    document.getElementById('search').addEventListener('input', function(e) {
        filterTools(e.target.value);
    });
});

function loadTools() {
    console.log('调用 bridge.get_tools()...');
    bridge.get_tools(function(json) {
        console.log('收到工具列表 JSON:', json);
        try {
            allTools = JSON.parse(json);
            console.log(`✓ 解析成功，共 ${allTools.length} 个工具`);
            console.log('工具列表:', allTools);
            renderCards(allTools);
            updateCount(allTools.length, allTools.length);
        } catch (e) {
            console.error('解析 JSON 失败:', e);
        }
    });
}

function renderCards(tools) {
    console.log(`渲染 ${tools.length} 个卡片...`);
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
    console.log('✓ 卡片渲染完成');
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
        <div class="card-description">${tool.description}</div>
    `;

    card.addEventListener('click', function() {
        console.log('点击卡片:', tool.id);
        selectCard(tool.id);
        bridge.select_tool(tool.id);
    });

    return card;
}

function selectCard(toolId) {
    console.log('选中工具:', toolId);
    // 移除之前的选中状态
    document.querySelectorAll('.card').forEach(c => c.classList.remove('selected'));

    // 添加新的选中状态
    const card = document.querySelector(`[data-tool-id="${toolId}"]`);
    if (card) {
        card.classList.add('selected');
        selectedToolId = toolId;
        console.log('✓ 卡片已选中');
    } else {
        console.error('找不到卡片:', toolId);
    }
}

function filterTools(query) {
    console.log('搜索:', query);
    const filtered = allTools.filter(tool => {
        const searchText = `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase();
        return searchText.includes(query.toLowerCase());
    });

    console.log(`搜索结果: ${filtered.length} / ${allTools.length}`);
    renderCards(filtered);
    updateCount(filtered.length, allTools.length);
}

function updateCount(visible, total) {
    document.getElementById('count').textContent = `${visible} / ${total} 个工具`;
}

console.log('=== JavaScript 初始化完成 ===');
