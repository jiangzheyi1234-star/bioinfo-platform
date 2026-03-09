let bridge = null;
let allTools = [];
let selectedToolId = null;

// 初始化 QWebChannel
new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.bridge;

    // 监听 Python 信号
    bridge.tool_selected.connect(function(tool_id) {
        console.log('Tool selected from Python:', tool_id);
    });

    // 加载工具列表
    loadTools();

    // 搜索功能
    document.getElementById('search').addEventListener('input', function(e) {
        filterTools(e.target.value);
    });
});

function loadTools() {
    bridge.get_tools(function(json) {
        allTools = JSON.parse(json);
        renderCards(allTools);
        updateCount(allTools.length, allTools.length);
    });
}

function renderCards(tools) {
    const container = document.getElementById('cards');
    container.innerHTML = '';

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
        <div class="card-description">${tool.description}</div>
    `;

    card.addEventListener('click', function() {
        selectCard(tool.id);
        bridge.select_tool(tool.id);
    });

    return card;
}

function selectCard(toolId) {
    // 移除之前的选中状态
    document.querySelectorAll('.card').forEach(c => c.classList.remove('selected'));

    // 添加新的选中状态
    const card = document.querySelector(`[data-tool-id="${toolId}"]`);
    if (card) {
        card.classList.add('selected');
        selectedToolId = toolId;
    }
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
