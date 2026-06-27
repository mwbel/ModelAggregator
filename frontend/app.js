const els = {
  status: document.getElementById("serviceStatus"),
  refreshModels: document.getElementById("refreshModels"),
  modelSummary: document.getElementById("modelSummary"),
  modelList: document.getElementById("modelList"),
  modelSelect: document.getElementById("modelSelect"),
  promptInput: document.getElementById("promptInput"),
  sendButton: document.getElementById("sendButton"),
  compareButton: document.getElementById("compareButton"),
  clearButton: document.getElementById("clearButton"),
  resultBox: document.getElementById("resultBox"),
};

let models = [];

function renderJson(value) {
  els.resultBox.textContent = JSON.stringify(value, null, 2);
}

function setStatus(text, mode = "") {
  els.status.textContent = text;
  els.status.className = `status-pill ${mode}`.trim();
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function renderModels(items) {
  models = Array.from(new Set((items || []).filter(Boolean)));
  els.modelSummary.textContent = models.length ? `共 ${models.length} 个模型` : "暂无模型";
  els.modelList.innerHTML = "";
  els.modelSelect.innerHTML = "";

  models.forEach((model) => {
    const row = document.createElement("label");
    row.className = "model-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = model;
    checkbox.checked = ["gemini:gemini-2.5-flash", "yunwu:gpt-5.5", "mathpix:mathpix-text"].includes(model);

    const code = document.createElement("code");
    code.textContent = model;

    row.append(checkbox, code);
    els.modelList.append(row);

    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    els.modelSelect.append(option);
  });
}

function selectedModels() {
  return Array.from(els.modelList.querySelectorAll("input[type='checkbox']:checked")).map((item) => item.value);
}

async function loadHealth() {
  try {
    const data = await requestJson("/api/aggregate/health");
    setStatus(data.ok ? "Ready" : "Error", data.ok ? "ready" : "error");
  } catch (error) {
    setStatus("Error", "error");
    renderJson({ ok: false, error: error.message });
  }
}

async function loadModels() {
  els.refreshModels.disabled = true;
  els.modelSummary.textContent = "正在加载模型...";
  try {
    const data = await requestJson("/api/aggregate/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ providerPreset: "all" }),
    });
    renderModels(data.items || []);
  } catch (error) {
    els.modelSummary.textContent = `加载失败：${error.message}`;
  } finally {
    els.refreshModels.disabled = false;
  }
}

async function sendChat() {
  const model = els.modelSelect.value;
  const prompt = els.promptInput.value.trim();
  if (!model || !prompt) {
    renderJson({ ok: false, error: "请选择模型并输入问题。" });
    return;
  }
  els.sendButton.disabled = true;
  renderJson({ status: "running", model });
  try {
    const data = await requestJson("/api/aggregate/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: prompt }],
        temperature: 0.3,
        maxTokens: 2048,
      }),
    });
    renderJson(data);
  } catch (error) {
    renderJson({ ok: false, error: error.message });
  } finally {
    els.sendButton.disabled = false;
  }
}

async function compareModels() {
  const chosen = selectedModels();
  const prompt = els.promptInput.value.trim();
  if (!chosen.length || !prompt) {
    renderJson({ ok: false, error: "请至少勾选一个模型并输入问题。" });
    return;
  }
  els.compareButton.disabled = true;
  renderJson({ status: "running", models: chosen });
  try {
    const data = await requestJson("/api/aggregate/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        taskType: "chat",
        models: chosen,
        messages: [{ role: "user", content: prompt }],
        temperature: 0.3,
        maxTokens: 2048,
      }),
    });
    renderJson(data);
  } catch (error) {
    renderJson({ ok: false, error: error.message });
  } finally {
    els.compareButton.disabled = false;
  }
}

els.refreshModels.addEventListener("click", loadModels);
els.sendButton.addEventListener("click", sendChat);
els.compareButton.addEventListener("click", compareModels);
els.clearButton.addEventListener("click", () => renderJson({}));

loadHealth();
loadModels();
