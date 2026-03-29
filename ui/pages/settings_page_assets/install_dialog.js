let bridge = null;
let hasUserLogPreference = false;

new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.installBridge;
    bridge.toolInfoReady.connect(applyToolInfo);
    bridge.snapshotUpdated.connect(applySnapshot);

    document.getElementById("btn-install").addEventListener("click", onPrimaryClick);
    document.getElementById("btn-cancel").addEventListener("click", onSecondaryClick);
    document.getElementById("log-details").addEventListener("toggle", onLogToggled);

    bridge.requestToolInfo();
});

function applyToolInfo(raw) {
    const info = parsePayload(raw);
    document.getElementById("tool-name").textContent = info.name || "";
    document.getElementById("conda-env").textContent = info.conda_env || "";
    document.getElementById("install-cmd").textContent = info.install_cmd || "（未配置）";

    if (Array.isArray(info.databases) && info.databases.length) {
        const dbText = info.databases
            .map((db) => String(db && db.id ? db.id : "").trim())
            .filter(Boolean)
            .join("、");
        document.getElementById("db-info").innerHTML =
            `<span class="db-warn">⚠ ${escapeHtml(dbText)}（安装后请配置数据库路径）</span>`;
    }
}

function applySnapshot(raw) {
    const snapshot = parsePayload(raw);
    const status = String(snapshot.status || "IDLE").toUpperCase();
    const dot = document.getElementById("status-dot");
    const progressBar = document.getElementById("progress-bar");
    const progressPct = document.getElementById("progress-pct");
    const phaseText = document.getElementById("phase-text");
    const speedText = document.getElementById("speed-text");
    const statusRow = document.getElementById("status-row");
    const logDetails = document.getElementById("log-details");
    const logArea = document.getElementById("log-area");
    const btnInstall = document.getElementById("btn-install");
    const btnCancel = document.getElementById("btn-cancel");

    dot.className = "dot " + statusToDot(status);
    phaseText.textContent = snapshot.phase_text || "";
    speedText.textContent = snapshot.speed ? String(snapshot.speed) : "";

    const progressValue = Number(snapshot.progress || 0);
    if (progressValue > 0) {
        progressBar.value = progressValue;
        progressPct.textContent = snapshot.progress_text || `${progressValue}%`;
    } else {
        progressBar.value = status === "DONE" ? 100 : 0;
        progressPct.textContent = status === "DONE" ? "100%" : "";
    }

    logArea.textContent = snapshot.log_text || "";
    logArea.scrollTop = logArea.scrollHeight;
    if (!hasUserLogPreference) {
        logDetails.open = Boolean(snapshot.log_auto_expand);
    }

    statusRow.textContent = snapshot.message || "";
    statusRow.className = "status-row";
    if (status === "DONE") {
        statusRow.classList.add("success");
    } else if (status === "FAILED") {
        statusRow.classList.add("error");
    }

    btnInstall.textContent = snapshot.primary_label || "开始安装";
    btnInstall.dataset.action = snapshot.primary_action || "install";
    btnInstall.disabled = !Boolean(snapshot.primary_enabled);

    btnCancel.textContent = snapshot.secondary_label || "关闭";
    btnCancel.style.display = snapshot.secondary_visible === false ? "none" : "";
}

function onPrimaryClick() {
    if (!bridge) {
        return;
    }
    const btnInstall = document.getElementById("btn-install");
    const action = btnInstall.dataset.action || "install";
    if (action === "close") {
        bridge.requestClose();
        return;
    }
    bridge.requestInstall();
}

function onSecondaryClick() {
    if (!bridge) {
        return;
    }
    bridge.requestClose();
}

function onLogToggled() {
    hasUserLogPreference = true;
}

function statusToDot(status) {
    if (status === "SUBMITTING" || status === "RUNNING") {
        return "running";
    }
    if (status === "DONE") {
        return "done";
    }
    if (status === "FAILED") {
        return "failed";
    }
    return "idle";
}

function parsePayload(raw) {
    if (typeof raw === "string") {
        return JSON.parse(raw);
    }
    return raw || {};
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
