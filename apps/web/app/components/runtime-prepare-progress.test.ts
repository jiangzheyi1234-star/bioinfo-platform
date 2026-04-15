import assert from "node:assert/strict";
import test from "node:test";

type RuntimeDecisionOption =
  | "use_docker"
  | "use_podman"
  | "self_install_docker"
  | "assistant_install_docker"
  | "fallback_conda";

type InstallSnapshot = {
  job_id: string;
  status: string;
  done: boolean;
  ok: boolean;
  message: string;
  log_text: string;
  progress?: {
    steps?: Array<{
      key: string;
      label: string;
      status: "pending" | "running" | "done" | "failed";
      message?: string;
    }>;
  };
};

type PrepareStep = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  message?: string;
};

async function loadModule() {
  const url = new URL(import.meta.url);
  url.pathname = url.pathname.replace(/\.test\.ts$/, ".ts");
  return import(url.href);
}

async function buildView(selectedDecision: RuntimeDecisionOption, snapshot: InstallSnapshot | null = null) {
  const { buildRuntimePrepareView } = await loadModule();
  return buildRuntimePrepareView({
    selectedDecision,
    installTarget: selectedDecision === "assistant_install_docker" ? "docker_runtime" : "workflow_runtime",
    snapshot,
    installRunning: false,
  });
}

test("docker workflow runtime shows docker-specific progress without micromamba", async () => {
  const view = await buildView("use_docker");
  assert.deepEqual(
    view.steps.map((step: PrepareStep) => step.label),
    ["校验 Java 17-24", "验证 Docker", "准备 Nextflow", "创建运行目录", "验证安装"]
  );
  assert.equal(view.steps.some((step: PrepareStep) => /Micromamba/.test(step.label)), false);
});

test("conda workflow runtime keeps conda-specific progress", async () => {
  const view = await buildView("fallback_conda");
  assert.deepEqual(
    view.steps.map((step: PrepareStep) => step.label),
    ["校验 Java", "安装 Nextflow", "安装 Micromamba", "创建运行目录", "验证安装"]
  );
});

test("docker assistant install uses its own install flow", async () => {
  const view = await buildView("assistant_install_docker");
  assert.deepEqual(
    view.steps.map((step: PrepareStep) => step.label),
    ["校验 sudo / root 权限", "下载 Docker 安装脚本", "安装 Docker", "启动 Docker 服务", "验证 Docker 并提示重新检测"]
  );
});

test("backend-provided steps override local defaults", async () => {
  const snapshot: InstallSnapshot = {
    job_id: "job",
    status: "running",
    done: false,
    ok: false,
    message: "",
    log_text: "",
    progress: {
      steps: [
        { key: "docker", label: "验证 Docker", status: "done" },
        { key: "nextflow", label: "准备 Nextflow", status: "running", message: "nextflow bootstrap running" },
      ],
    },
  };
  const view = await buildView("use_docker", snapshot);
  assert.deepEqual(view.steps, snapshot.progress?.steps);
});

test("workflow runtime shows first step as running immediately after start", async () => {
  const { buildRuntimePrepareView } = await loadModule();
  const view = buildRuntimePrepareView({
    selectedDecision: "use_docker",
    installTarget: "workflow_runtime",
    snapshot: null,
    installRunning: true,
  });
  assert.equal(view.steps[0].status, "running");
  assert.equal(view.steps[1].status, "pending");
});

test("workflow runtime stays pending before start", async () => {
  const { buildRuntimePrepareView } = await loadModule();
  const view = buildRuntimePrepareView({
    selectedDecision: "use_docker",
    installTarget: "workflow_runtime",
    snapshot: null,
    installRunning: false,
  });
  assert.equal(view.steps[0].status, "pending");
});

test("polling snapshot promotes the next pending step to running", async () => {
  const { buildRuntimePrepareView } = await loadModule();
  const snapshot: InstallSnapshot = {
    job_id: "job",
    status: "running",
    done: false,
    ok: false,
    message: "",
    log_text: "STEP=java:running",
    progress: {
      steps: [
        { key: "java", label: "校验 Java 17-24", status: "pending" },
        { key: "docker", label: "验证 Docker", status: "pending" },
        { key: "nextflow", label: "准备 Nextflow", status: "pending" },
      ],
    },
  };
  const view = buildRuntimePrepareView({
    selectedDecision: "use_docker",
    installTarget: "workflow_runtime",
    snapshot,
    installRunning: true,
  });
  assert.equal(view.steps[0].status, "running");
  assert.equal(view.steps[1].status, "pending");
});
