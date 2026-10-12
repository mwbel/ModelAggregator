const RUNTIME_CONFIG = window.__UMA_RUNTIME_CONFIG__ || {};

const API_BASE =
  RUNTIME_CONFIG.apiBaseUrl ||
  RUNTIME_CONFIG.backendUrl ||
  (window.location.protocol === "file:" ? "http://127.0.0.1:8890" : window.location.origin);

const DEFAULT_SYSTEM_PROMPT = "你是一个严谨、直接的中文助手。回答时优先给出结论，再补充必要解释。";
const MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;
const PROMPT_PRESETS = [
  {
    id: "rigorous",
    label: "严谨助手",
    prompt: DEFAULT_SYSTEM_PROMPT,
  },
  {
    id: "researcher",
    label: "研究者",
    prompt: "你是一位研究者型中文助手。先给结论，再给依据、假设、边界条件和可验证线索；不确定时明确说出不确定点。",
  },
  {
    id: "explainer",
    label: "通俗讲解者",
    prompt: "你是一位通俗讲解者。用清楚、平实、少术语的中文解释问题，优先举直观例子，让没有背景的人也能看懂。",
  },
  {
    id: "editor",
    label: "结构整理者",
    prompt: "你是一位结构整理者。回答时先提炼要点，再按清晰结构展开，适合整理资料、改写内容和生成条理分明的结果。",
  },
];
const MODEL_HINTS = {
  vision_verified: {
    badge: "图像已验证",
    detail: "已验证可接收图片输入，适合 OCR、图表和截图类任务。",
    compareRecommended: true,
    singleRecommended: true,
  },
  vision_possible: {
    badge: "图像未稳定",
    detail: "可能支持图片，但当前服务下结果不稳定，建议作为补充对比。",
    compareRecommended: false,
    singleRecommended: false,
  },
  text_only: {
    badge: "文本优先",
    detail: "更适合纯文本对话，图片任务下可能忽略图像内容。",
    compareRecommended: false,
    singleRecommended: false,
  },
  embedding: {
    badge: "非对话",
    detail: "这是 embedding 类模型，不适合聊天或图片理解测试。",
    compareRecommended: false,
    singleRecommended: false,
  },
};

const state = {
  messages: [],
  defaultModels: [],
  servicePresets: [],
  routerConfig: { taskTypes: [] },
  modelProfiles: [],
  availableModelItems: [],
  attachments: [],
  activeModel: "",
  activeProviderPreset: "openai-compatible",
  selectedModels: [],
  dispatchMode: "manual",
  routePreview: null,
  activePromptPresetId: "rigorous",
  imageSelectionAutoApplied: false,
  imageActiveModelAutoApplied: false,
  pending: false,
  hasBackendKey: false,
};

const els = {};

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function getServicePreset(presetId = state.activeProviderPreset) {
  return state.servicePresets.find((item) => item.id === presetId) || null;
}

function saveManualConnectionState() {
  localStorage.setItem("modelTester.manual.baseUrl", els.baseUrlInput.value.trim());
  localStorage.setItem("modelTester.manual.modelsPath", els.modelsPathInput.value.trim());
  localStorage.setItem("modelTester.manual.chatPath", els.chatPathInput.value.trim());
}

function restoreManualConnectionState(config = null) {
  const baseUrl = localStorage.getItem("modelTester.manual.baseUrl");
  const modelsPath = localStorage.getItem("modelTester.manual.modelsPath");
  const chatPath = localStorage.getItem("modelTester.manual.chatPath");
  els.baseUrlInput.value = baseUrl || els.baseUrlInput.value || config?.baseUrl || "";
  els.modelsPathInput.value = modelsPath || els.modelsPathInput.value || config?.modelsPath || "/models";
  els.chatPathInput.value = chatPath || els.chatPathInput.value || config?.chatPath || "/chat/completions";
}

function setConnectionFieldMode(readOnly) {
  els.baseUrlInput.readOnly = readOnly;
  els.modelsPathInput.readOnly = readOnly;
  els.chatPathInput.readOnly = readOnly;
}

function bindElements() {
  [
    "baseUrlInput",
    "apiKeyInput",
    "toggleKeyButton",
    "keyStatus",
    "activeServiceLabel",
    "servicePresetBar",
    "servicePresetHint",
    "modelSelect",
    "refreshModelsButton",
    "modelStatus",
    "dispatchModeSelect",
    "dispatchModeHint",
    "taskTypeSelect",
    "routePreferSelect",
    "preferredProviderSelect",
    "maxCostTierSelect",
    "requireLocalCheckbox",
    "requireVisionCheckbox",
    "previewRouteButton",
    "modelChecklist",
    "modelChecklistHint",
    "selectOnlineModelsButton",
    "selectAllModelsButton",
    "deselectAllModelsButton",
    "temperatureInput",
    "maxTokensInput",
    "modelsPathInput",
    "chatPathInput",
    "clearButton",
    "messages",
    "chatForm",
    "attachmentInput",
    "attachButton",
    "attachmentList",
    "messageInput",
    "sendButton",
    "compareButton",
    "requestBadge",
    "activeModelTitle",
    "latencyValue",
    "tokensValue",
    "finishValue",
    "pathValue",
    "promptPresetBar",
    "promptPresetStatus",
    "requestSettingsSummary",
    "routeStatus",
    "routeTaskTypeValue",
    "routeSelectedModelValue",
    "routeProviderValue",
    "routeFallbacksValue",
    "routeProfileValue",
    "routeReasonValue",
    "systemPromptInput",
    "resetSystemButton",
    "rawResponse",
    "copyRawButton",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

async function initialize() {
  bindElements();
  bindEvents();
  restoreLocalState();
  renderPromptPresets();
  await loadConfig();
  updateRequestSettingsSummary();
  renderAttachments();
  renderMessages();
}

function bindEvents() {
  els.toggleKeyButton.addEventListener("click", () => {
    const shouldShow = els.apiKeyInput.type === "password";
    els.apiKeyInput.type = shouldShow ? "text" : "password";
    updateKeyVisibilityButton(shouldShow);
  });

  els.refreshModelsButton.addEventListener("click", () => refreshModels({ forceRemote: true }));
  els.selectOnlineModelsButton.addEventListener("click", handleSelectOnlineModels);
  els.selectAllModelsButton.addEventListener("click", handleSelectAllModels);
  els.deselectAllModelsButton.addEventListener("click", handleDeselectAllModels);
  els.previewRouteButton.addEventListener("click", handlePreviewRoute);

  els.modelSelect.addEventListener("change", () => {
    state.activeModel = els.modelSelect.value;
    state.imageActiveModelAutoApplied = false;
    localStorage.setItem("modelTester.model", state.activeModel);
    resetRoutePreview();
    updateActiveModelTitle();
    if (hasImageAttachments(state.attachments) && !getModelHint(state.activeModel).singleRecommended) {
      setImageModelStatus();
      return;
    }
    setModelStatus(state.activeModel ? `当前模型：${state.activeModel}` : "未选择模型", false);
  });

  els.dispatchModeSelect.addEventListener("change", () => {
    state.dispatchMode = els.dispatchModeSelect.value || "manual";
    persistLocalState();
    resetRoutePreview();
    updateDispatchModeUI();
    updateActiveModelTitle();
    updateRequestSettingsSummary();
  });

  els.clearButton.addEventListener("click", () => {
    state.messages = [];
    state.attachments = [];
    resetMetrics();
    renderRaw({});
    resetRoutePreview();
    renderAttachments();
    renderMessages();
    els.messageInput.focus();
  });

  els.resetSystemButton.addEventListener("click", () => {
    els.systemPromptInput.value = DEFAULT_SYSTEM_PROMPT;
    persistLocalState();
    syncPromptPresetState();
    updateRequestSettingsSummary();
  });

  els.copyRawButton.addEventListener("click", async () => {
    await navigator.clipboard.writeText(els.rawResponse.textContent || "{}");
    els.copyRawButton.textContent = "已复制";
    window.setTimeout(() => {
      els.copyRawButton.textContent = "复制";
    }, 1200);
  });

  els.messageInput.addEventListener("input", () => {
    autoResizeComposer();
    updateRequestSettingsSummary();
    resetRoutePreview();
  });
  els.attachButton.addEventListener("click", () => els.attachmentInput.click());
  els.attachmentInput.addEventListener("change", () => handleAttachmentFiles(els.attachmentInput.files));
  els.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      els.chatForm.requestSubmit();
    }
  });

  els.chatForm.addEventListener("submit", handleSubmit);
  els.compareButton.addEventListener("click", handleCompareAll);

  [
    els.baseUrlInput,
    els.modelsPathInput,
    els.chatPathInput,
    els.temperatureInput,
    els.maxTokensInput,
    els.taskTypeSelect,
    els.routePreferSelect,
    els.preferredProviderSelect,
    els.maxCostTierSelect,
  ].forEach((input) => {
    input.addEventListener("change", () => {
      persistLocalState();
      resetRoutePreview();
      updateDispatchModeUI();
      updateRequestSettingsSummary();
    });
  });

  [els.requireLocalCheckbox, els.requireVisionCheckbox].forEach((input) => {
    input.addEventListener("change", () => {
      persistLocalState();
      resetRoutePreview();
      updateDispatchModeUI();
      updateRequestSettingsSummary();
    });
  });

  els.systemPromptInput.addEventListener("input", () => {
    persistLocalState();
    syncPromptPresetState();
    updateRequestSettingsSummary();
  });

}

function restoreLocalState() {
  state.activeProviderPreset = localStorage.getItem("modelTester.providerPreset") || "openai-compatible";
  state.dispatchMode = localStorage.getItem("modelTester.dispatchMode") || "manual";
  els.baseUrlInput.value = localStorage.getItem("modelTester.baseUrl") || "";
  els.modelsPathInput.value = localStorage.getItem("modelTester.modelsPath") || "/models";
  els.chatPathInput.value = localStorage.getItem("modelTester.chatPath") || "/chat/completions";
  els.temperatureInput.value = localStorage.getItem("modelTester.temperature") || "0.7";
  els.maxTokensInput.value = localStorage.getItem("modelTester.maxTokens") || "";
  els.dispatchModeSelect.value = state.dispatchMode;
  els.routePreferSelect.value = localStorage.getItem("modelTester.routePrefer") || "quality";
  els.maxCostTierSelect.value = localStorage.getItem("modelTester.maxCostTier") || "";
  els.requireLocalCheckbox.checked = localStorage.getItem("modelTester.requireLocal") === "1";
  els.requireVisionCheckbox.checked = localStorage.getItem("modelTester.requireVision") === "1";
  els.apiKeyInput.value = "";
  els.systemPromptInput.value = localStorage.getItem("modelTester.systemPrompt") || DEFAULT_SYSTEM_PROMPT;
  syncPromptPresetState();
  updateKeyVisibilityButton(els.apiKeyInput.type === "text");
}

function persistLocalState() {
  localStorage.setItem("modelTester.baseUrl", els.baseUrlInput.value.trim());
  localStorage.setItem("modelTester.modelsPath", els.modelsPathInput.value.trim());
  localStorage.setItem("modelTester.chatPath", els.chatPathInput.value.trim());
  localStorage.setItem("modelTester.temperature", els.temperatureInput.value);
  localStorage.setItem("modelTester.maxTokens", els.maxTokensInput.value);
  localStorage.setItem("modelTester.dispatchMode", els.dispatchModeSelect.value || "manual");
  localStorage.setItem("modelTester.taskType", els.taskTypeSelect.value || "__auto__");
  localStorage.setItem("modelTester.routePrefer", els.routePreferSelect.value || "quality");
  localStorage.setItem("modelTester.preferredProvider", els.preferredProviderSelect.value || "");
  localStorage.setItem("modelTester.maxCostTier", els.maxCostTierSelect.value || "");
  localStorage.setItem("modelTester.requireLocal", els.requireLocalCheckbox.checked ? "1" : "0");
  localStorage.setItem("modelTester.requireVision", els.requireVisionCheckbox.checked ? "1" : "0");
  localStorage.setItem("modelTester.systemPrompt", els.systemPromptInput.value);
}

async function loadConfig() {
  try {
    const response = await fetch(apiUrl("/api/aggregate/config"));
    const config = await response.json();
    state.servicePresets = Array.isArray(config.presets) ? config.presets : [];
    state.routerConfig = config.router || { taskTypes: [] };
    state.modelProfiles = Array.isArray(config.modelProfiles) ? config.modelProfiles : [];
    if (!state.servicePresets.length) {
      state.servicePresets = [
        {
          id: "openai-compatible",
          label: "OpenAI-compatible",
          description: "兼容 OpenAI 的模型服务",
          baseUrl: config.baseUrl || "",
          modelsPath: config.modelsPath || "/models",
          chatPath: config.chatPath || "/chat/completions",
          defaultModels: Array.isArray(config.defaultModels) ? config.defaultModels : [],
          configured: Boolean(config.baseUrl),
          usesEnvKey: false,
          keyStatusLabel: config.hasApiKey ? "使用后端环境变量 key" : "未配置默认 API key",
        },
      ];
    }
    state.defaultModels = Array.isArray(config.unifiedModels)
      ? config.unifiedModels
      : Array.isArray(config.defaultModels)
        ? config.defaultModels
        : [];
    state.hasBackendKey = Boolean(config.hasApiKey);
    renderRouteTaskTypes();
    renderPreferredProviders();
    renderServicePresets();
    applyServicePreset(state.activeProviderPreset, config, false);
    updateKeyStatus();
    updateDispatchModeUI();
    resetRoutePreview();
    await refreshModels({ forceRemote: true });
  } catch (error) {
    setModelStatus(`配置加载失败：${error.message}`, true);
    renderModelOptions(state.defaultModels);
  }
}

function renderServicePresets() {
  els.servicePresetBar.innerHTML = "";
  state.servicePresets.forEach((preset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "service-chip-button";
    button.textContent = preset.label;
    button.classList.toggle("is-active", preset.id === state.activeProviderPreset);
    button.classList.toggle("is-disabled", !preset.configured);
    button.addEventListener("click", () => {
      applyServicePreset(preset.id, null, true);
    });
    els.servicePresetBar.append(button);
  });
}

function renderRouteTaskTypes() {
  const configuredTaskTypes = Array.isArray(state.routerConfig.taskTypes) ? state.routerConfig.taskTypes : [];
  const items = configuredTaskTypes.length ? configuredTaskTypes : ["general.chat"];
  const savedTaskType = localStorage.getItem("modelTester.taskType") || "__auto__";
  els.taskTypeSelect.innerHTML = "";

  const autoOption = document.createElement("option");
  autoOption.value = "__auto__";
  autoOption.textContent = "自动识别";
  els.taskTypeSelect.append(autoOption);

  items.forEach((taskType) => {
    const option = document.createElement("option");
    option.value = taskType;
    option.textContent = taskType;
    els.taskTypeSelect.append(option);
  });

  els.taskTypeSelect.value = Array.from(els.taskTypeSelect.options).some((option) => option.value === savedTaskType)
    ? savedTaskType
    : "__auto__";
}

function renderPreferredProviders() {
  const providers = [
    { value: "", label: "无偏好" },
    { value: "openai-compatible", label: "local / openai-compatible" },
    { value: "gemini", label: "gemini" },
    { value: "yunwu-gpt55", label: "yunwu" },
    { value: "mathpix", label: "mathpix" },
  ];
  const savedProvider = localStorage.getItem("modelTester.preferredProvider") || "";
  els.preferredProviderSelect.innerHTML = "";
  providers.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    els.preferredProviderSelect.append(option);
  });
  els.preferredProviderSelect.value = savedProvider;
}

function applyServicePreset(presetId, config = null, shouldRefresh = true) {
  const previousPreset = state.activeProviderPreset;
  if (previousPreset === "openai-compatible" && presetId !== "openai-compatible") {
    saveManualConnectionState();
  }

  const preset = getServicePreset(presetId) || getServicePreset("openai-compatible");
  state.activeProviderPreset = preset?.id || "openai-compatible";
  localStorage.setItem("modelTester.providerPreset", state.activeProviderPreset);
  renderServicePresets();

  const activePreset = getServicePreset(state.activeProviderPreset);
  if (!activePreset) {
    return;
  }

  els.activeServiceLabel.textContent = activePreset.label;
  els.servicePresetHint.textContent = activePreset.id === "openai-compatible"
    ? "由聚合服务后端统一鉴权；Base URL 仅用于本地兼容服务配置。"
    : activePreset.description || "选择一个后端服务预设。";
  els.servicePresetHint.className = `field-note ${activePreset.configured ? "is-ok" : ""}`.trim();

  if (activePreset.id === "openai-compatible") {
    restoreManualConnectionState(config);
    setConnectionFieldMode(false);
    els.apiKeyInput.placeholder = "由聚合服务后端环境变量管理";
    state.hasBackendKey = Boolean(config?.hasApiKey);
  } else {
    els.baseUrlInput.value = activePreset.baseUrl || "";
    els.modelsPathInput.value = activePreset.modelsPath || "";
    els.chatPathInput.value = activePreset.chatPath || "";
    setConnectionFieldMode(true);
    els.apiKeyInput.placeholder = "由聚合服务后端环境变量管理";
    state.hasBackendKey = false;
  }

  els.apiKeyInput.value = "";
  els.apiKeyInput.disabled = true;
  els.toggleKeyButton.disabled = true;
  els.apiKeyInput.type = "password";

  updateKeyVisibilityButton(false);
  updateKeyStatus();
  state.defaultModels = Array.isArray(activePreset.defaultModels) ? activePreset.defaultModels : [];
  state.selectedModels = [];
  renderModelOptions(state.defaultModels);
  updateRequestSettingsSummary();

  if (shouldRefresh) {
    refreshModels({ forceRemote: true });
  }
}

async function refreshModels({ forceRemote = false } = {}) {
  const baseUrl = els.baseUrlInput.value.trim();
  if (!forceRemote && !baseUrl) {
    renderModelOptions(state.defaultModels);
    setModelStatus("使用本地默认模型列表", false);
    return;
  }

  setModelStatus("正在刷新模型列表...", false);
  els.refreshModelsButton.disabled = true;
  persistLocalState();

  try {
    const response = await fetch(apiUrl("/api/aggregate/models"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildUnifiedModelsPayload()),
    });
    const data = await response.json();
    const fallbackItems = data.items || state.defaultModels;
    renderModelOptions(fallbackItems);
    if (data.ok) {
      setModelStatus(`模型来源：${data.source || "service"}`, false);
    } else if (fallbackItems.length) {
      setModelStatus("模型接口暂不可用，已使用内置模型列表。", false);
      console.warn("Model list fallback:", data.error || "模型列表请求失败");
    } else {
      setModelStatus(data.error || "模型列表请求失败", true);
    }
  } catch (error) {
    renderModelOptions(state.defaultModels);
    if (state.defaultModels.length) {
      setModelStatus("模型接口暂不可用，已使用内置模型列表。", false);
      console.warn("Model list fallback:", error);
    } else {
      setModelStatus(`刷新失败：${error.message}`, true);
    }
  } finally {
    els.refreshModelsButton.disabled = false;
  }
}

function renderModelOptions(models) {
  const previous = localStorage.getItem("modelTester.model") || state.activeModel;
  const items = Array.from(new Set((models || []).filter(Boolean)));
  els.modelSelect.innerHTML = "";

  if (!items.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无模型";
    els.modelSelect.append(option);
    state.activeModel = "";
    updateActiveModelTitle();
    return;
  }

  items.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    els.modelSelect.append(option);
  });

  state.activeModel = items.includes(previous) ? previous : items[0];
  els.modelSelect.value = state.activeModel;
  const previousSelection = state.selectedModels.filter((model) => items.includes(model));
  state.selectedModels = previousSelection.length ? previousSelection : getDefaultCompareModels(items);
  syncModelSelectionStrategy(items);
  renderModelChecklist(items);
  updateCompareButtonLabel();
  updateActiveModelTitle();
  if (!els.modelStatus.classList.contains("is-error")) {
    setModelStatus(`当前模型：${state.activeModel}`, false);
  }
}

function buildConnectionPayload() {
  return {
    providerPreset: state.activeProviderPreset,
    baseUrl: els.baseUrlInput.value.trim(),
    modelsPath: els.modelsPathInput.value.trim() || "/models",
    chatPath: els.chatPathInput.value.trim() || "/chat/completions",
  };
}

function buildUnifiedModelsPayload() {
  const payload = buildConnectionPayload();
  const openaiPreset = getServicePreset("openai-compatible") || {};
  const manualBaseUrl = localStorage.getItem("modelTester.manual.baseUrl") || "";
  const manualModelsPath = localStorage.getItem("modelTester.manual.modelsPath") || "";
  const manualChatPath = localStorage.getItem("modelTester.manual.chatPath") || "";
  return {
    ...payload,
    providerPreset: "all",
    baseUrl: manualBaseUrl || (state.activeProviderPreset === "openai-compatible" ? payload.baseUrl : openaiPreset.baseUrl || payload.baseUrl),
    modelsPath: manualModelsPath || openaiPreset.modelsPath || payload.modelsPath,
    chatPath: manualChatPath || openaiPreset.chatPath || payload.chatPath,
  };
}

function buildRequestPayloadForModel(model) {
  const payload = buildConnectionPayload();
  const modelText = String(model || "");
  if (modelText.startsWith("gemini:")) {
    return { ...payload, providerPreset: "gemini", apiKey: "" };
  }
  if (modelText.startsWith("yunwu:")) {
    return { ...payload, providerPreset: "yunwu-gpt55", apiKey: "" };
  }
  if (modelText.startsWith("mathpix:")) {
    return { ...payload, providerPreset: "mathpix", apiKey: "" };
  }
  if (modelText.startsWith("local:")) {
    const openaiPreset = getServicePreset("openai-compatible") || {};
    return {
      ...payload,
      providerPreset: "openai-compatible",
      baseUrl: localStorage.getItem("modelTester.manual.baseUrl") || openaiPreset.baseUrl || payload.baseUrl,
      modelsPath: localStorage.getItem("modelTester.manual.modelsPath") || openaiPreset.modelsPath || payload.modelsPath,
      chatPath: localStorage.getItem("modelTester.manual.chatPath") || openaiPreset.chatPath || payload.chatPath,
    };
  }
  return payload;
}

function buildAutoRouteConnectionPayload() {
  const openaiPreset = getServicePreset("openai-compatible") || {};
  return {
    providerPreset: "openai-compatible",
    baseUrl: localStorage.getItem("modelTester.manual.baseUrl") || openaiPreset.baseUrl || "",
    modelsPath: localStorage.getItem("modelTester.manual.modelsPath") || openaiPreset.modelsPath || "/models",
    chatPath: localStorage.getItem("modelTester.manual.chatPath") || openaiPreset.chatPath || "/chat/completions",
  };
}

function getEffectiveTaskType(text = "", attachments = state.attachments) {
  const selected = els.taskTypeSelect.value || "__auto__";
  if (selected !== "__auto__") {
    return selected;
  }
  if (isImageMarkdownRequest(text, attachments)) {
    return "ocr.image_to_markdown";
  }
  return "";
}

function buildRouteConstraints() {
  const constraints = {
    prefer: els.routePreferSelect.value || "quality",
  };
  if (els.preferredProviderSelect.value) {
    constraints.preferredProvider = els.preferredProviderSelect.value;
  }
  if (els.maxCostTierSelect.value) {
    constraints.maxCostTier = els.maxCostTierSelect.value;
  }
  if (els.requireLocalCheckbox.checked) {
    constraints.requireLocal = true;
  }
  if (els.requireVisionCheckbox.checked) {
    constraints.requireVision = true;
  }
  return constraints;
}

function buildRoutePayload({ requestedModel, content = "", attachments = [], includeHistory = false } = {}) {
  const taskType = getEffectiveTaskType(content, attachments);
  const model = requestedModel || (state.dispatchMode === "auto" ? "auto" : state.activeModel);
  const connectionPayload = model === "auto" ? buildAutoRouteConnectionPayload() : buildRequestPayloadForModel(model);
  const payload = {
    ...connectionPayload,
    model,
    constraints: buildRouteConstraints(),
  };
  if (taskType) {
    payload.taskType = taskType;
  }
  if (attachments.length) {
    payload.attachmentIds = attachments.filter((item) => item.id).map((item) => item.id);
  }
  if (taskType !== "ocr.image_to_markdown") {
    const additionalUserMessage = { role: "user", content: buildUserContent(content, attachments) };
    payload.messages = buildChatMessages({ additionalUserMessage, includeHistory });
  } else if (content.trim()) {
    payload.messages = [{ role: "user", content: content.trim() }];
  }
  return payload;
}

function findModelProfile(modelRef) {
  return state.modelProfiles.find((item) => item.id === modelRef) || null;
}

function getSelectedModels() {
  return state.selectedModels.filter(Boolean);
}

function updateCompareButtonLabel() {
  const count = getSelectedModels().length;
  els.compareButton.textContent = count ? `对比 ${count}` : "对比";
}

function getAllModels() {
  return Array.from(els.modelSelect.options)
    .map((option) => option.value)
    .filter(Boolean);
}

function isChatCapableModel(model) {
  const lowered = String(model || "").toLowerCase();
  return !(
    lowered.includes("embed") ||
    lowered.startsWith("mathpix:") ||
    lowered.includes("-image") ||
    lowered.includes("-tts") ||
    lowered.includes("robotics") ||
    lowered.includes("computer-use")
  );
}

function getDefaultCompareModels(models) {
  const preferred = [
    "local:qwen3.6-27b:latest",
    "gemini:gemini-3.8-flash",
    "yunwu:gpt-5.5",
  ];
  const selected = preferred.filter((model) => models.includes(model));
  return selected.length ? selected : models.filter(isChatCapableModel).slice(0, 3);
}

function hasImageAttachments(attachments) {
  return attachments.some((item) => item.kind === "image");
}

function getModelHintType(model) {
  const lowered = String(model || "").toLowerCase();
  if (!lowered) {
    return "text_only";
  }
  if (lowered.startsWith("gemini:") || lowered.includes("gemini-")) {
    return "vision_verified";
  }
  if (lowered.startsWith("yunwu:") || lowered.includes("gpt-5.5")) {
    return "vision_verified";
  }
  if (lowered.startsWith("mathpix:") || lowered.includes("mathpix")) {
    return "vision_verified";
  }
  if (
    lowered.includes("vl") ||
    lowered.includes("vision") ||
    lowered.includes("qwen-vl") ||
    lowered.includes("llava") ||
    lowered.includes("minicpm-v")
  ) {
    return "vision_verified";
  }
  if (lowered.includes("embed")) {
    return "embedding";
  }
  if (lowered.includes("medgemma") || lowered.includes("gemma4") || lowered.includes("qwen3.6")) {
    return "vision_possible";
  }
  return "text_only";
}

function getModelHint(model) {
  return MODEL_HINTS[getModelHintType(model)] || MODEL_HINTS.text_only;
}

function getRecommendedImageModels(models) {
  return (models || []).filter((model) => {
    return isOnlineOcrModel(model) && getModelHint(model).compareRecommended;
  });
}

function isOnlineOcrModel(model) {
  const text = String(model || "").toLowerCase();
  return text.startsWith("gemini:") || text.startsWith("yunwu:") || text.startsWith("mathpix:");
}

function syncModelSelectionStrategy(models = getAllModels()) {
  const hasImages = hasImageAttachments(state.attachments);
  if (!hasImages) {
    state.imageSelectionAutoApplied = false;
    state.imageActiveModelAutoApplied = false;
    updateModelChecklistHint(models);
    return;
  }

  const recommended = getRecommendedImageModels(models);
  const currentSelection = getSelectedModels();
  const shouldAutoApply =
    !state.imageSelectionAutoApplied &&
    recommended.length &&
    (!currentSelection.length || currentSelection.length === models.length);

  if (shouldAutoApply) {
    state.selectedModels = [...recommended];
    state.imageSelectionAutoApplied = true;
  }
  if (recommended.length && !getModelHint(state.activeModel).singleRecommended) {
    state.activeModel = recommended[0];
    state.imageActiveModelAutoApplied = true;
    els.modelSelect.value = state.activeModel;
    localStorage.setItem("modelTester.model", state.activeModel);
    updateActiveModelTitle();
    setModelStatus(`检测到图片，已切换到更适合图片任务的模型：${state.activeModel}`, false);
  }
  updateModelChecklistHint(models);
}

function renderModelChecklist(models) {
  els.modelChecklist.innerHTML = "";
  models.forEach((model) => {
    const label = document.createElement("label");
    label.className = "model-check-item";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.selectedModels.includes(model);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!state.selectedModels.includes(model)) {
          state.selectedModels.push(model);
        }
      } else {
        state.selectedModels = state.selectedModels.filter((item) => item !== model);
      }
      updateCompareButtonLabel();
      updateModelChecklistHint(models);
    });

    const content = document.createElement("div");
    content.className = "model-check-content";

    const titleRow = document.createElement("div");
    titleRow.className = "model-check-title";

    const text = document.createElement("span");
    text.textContent = model;

    const hint = document.createElement("span");
    hint.className = `model-hint-badge is-${getModelHintType(model).replace(/_/g, "-")}`;
    hint.textContent = getModelHint(model).badge;

    const detail = document.createElement("span");
    detail.className = "model-check-detail";
    detail.textContent = getModelHint(model).detail;

    titleRow.append(text, hint);
    content.append(titleRow, detail);
    label.append(input, content);
    els.modelChecklist.append(label);
  });
  updateModelChecklistHint(models);
}

function handleSelectAllModels() {
  state.selectedModels = getAllModels();
  state.imageSelectionAutoApplied = false;
  renderModelChecklist(getAllModels());
  updateCompareButtonLabel();
}

function handleSelectOnlineModels() {
  state.selectedModels = getAllModels().filter(isOnlineOcrModel);
  state.imageSelectionAutoApplied = true;
  renderModelChecklist(getAllModels());
  updateCompareButtonLabel();
}

function handleDeselectAllModels() {
  state.selectedModels = [];
  state.imageSelectionAutoApplied = false;
  renderModelChecklist(getAllModels());
  updateCompareButtonLabel();
}

function updateModelChecklistHint(models = getAllModels()) {
  const hasImages = hasImageAttachments(state.attachments);
  const selectedCount = getSelectedModels().length;
  const totalCount = models.length;
  if (!hasImages) {
    els.modelChecklistHint.textContent = totalCount
      ? `已选择 ${selectedCount}/${totalCount} 个模型，用于横向对比。`
      : "暂无可用模型。";
    els.modelChecklistHint.className = "field-note";
    return;
  }

  const recommended = getRecommendedImageModels(models);
  if (recommended.length) {
    const autoText = state.imageSelectionAutoApplied ? "已优先勾选更适合图片任务的模型。" : "建议优先勾选更适合图片任务的模型。";
    els.modelChecklistHint.textContent = `${autoText} 当前推荐：${recommended.join("、")}。`;
    els.modelChecklistHint.className = "field-note is-ok";
    return;
  }

  els.modelChecklistHint.textContent = "检测到图片附件，但当前列表里没有已验证的视觉模型；结果可能忽略图片内容。";
  els.modelChecklistHint.className = "field-note";
}

function setImageModelStatus() {
  const recommended = getRecommendedImageModels(getAllModels());
  const recommendedText = recommended.length ? recommended.join("、") : "视觉模型";
  setModelStatus(`已上传图片，${state.activeModel} 可能无法稳定识别图像；推荐优先试 ${recommendedText}`, false);
}

function renderPromptPresets() {
  els.promptPresetBar.innerHTML = "";
  PROMPT_PRESETS.forEach((preset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-chip";
    button.dataset.presetId = preset.id;
    button.textContent = preset.label;
    button.addEventListener("click", () => {
      state.activePromptPresetId = preset.id;
      els.systemPromptInput.value = preset.prompt;
      persistLocalState();
      syncPromptPresetState();
      updateRequestSettingsSummary();
    });
    els.promptPresetBar.append(button);
  });
  syncPromptPresetState();
}

function syncPromptPresetState() {
  const currentPrompt = els.systemPromptInput.value.trim();
  const matchedPreset = PROMPT_PRESETS.find((preset) => preset.prompt === currentPrompt);
  state.activePromptPresetId = matchedPreset ? matchedPreset.id : "custom";
  els.promptPresetStatus.textContent = matchedPreset ? matchedPreset.label : "自定义";
  els.promptPresetBar.querySelectorAll(".preset-chip").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.presetId === state.activePromptPresetId);
  });
}

function buildAttachmentSummary(attachments) {
  if (!attachments.length) {
    return "";
  }
  return attachments
    .map((item) => `${item.name} (${item.kind}, ${formatBytes(item.size)})`)
    .join("；");
}

function buildUserContent(text, attachments) {
  const cleanText = text.trim();
  if (!attachments.length) {
    return cleanText;
  }

  const parts = [];
  if (cleanText) {
    parts.push({ type: "text", text: cleanText });
  }

  attachments.forEach((item) => {
    if (item.id && (item.kind === "image" || item.kind === "text" || item.kind === "metadata")) {
      parts.push({ type: "model_tester_attachment", attachment_id: item.id });
      return;
    }
    parts.push({
      type: "text",
      text: `\n\n[附件: ${item.name}]\n当前文件类型 ${item.type || "unknown"} 未内联，只提供文件名和大小 ${formatBytes(item.size)}。`,
    });
  });

  return parts;
}

function contentToDisplayText(content) {
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  const textParts = content
    .filter((item) => item.type === "text" && item.text)
    .map((item) => item.text.trim())
    .filter(Boolean);
  const imageCount = content.filter((item) => item.type === "image_url").length;
  if (imageCount) {
    textParts.push(`[${imageCount} 张图片]`);
  }
  return textParts.join("\n\n");
}

function buildChatMessages({ additionalUserMessage = null, includeHistory = true } = {}) {
  const systemPrompt = els.systemPromptInput.value.trim();
  const messages = systemPrompt ? [{ role: "system", content: systemPrompt }] : [];
  if (includeHistory) {
    state.messages.forEach((message) => {
      if (message.role === "user" || message.role === "assistant") {
        messages.push({
          role: message.role,
          content: message.apiContent || message.content,
        });
      }
    });
  }
  if (additionalUserMessage) {
    messages.push(additionalUserMessage);
  }
  return messages;
}

function buildChatRequestPayload(model, messages, content = "", attachments = []) {
  const payload = model === "auto" ? buildAutoRouteConnectionPayload() : buildRequestPayloadForModel(model);
  const taskType = getEffectiveTaskType(content, attachments);
  const request = {
    ...payload,
    model,
    messages,
    temperature: Number(els.temperatureInput.value || 0.7),
    maxTokens: els.maxTokensInput.value.trim(),
    constraints: buildRouteConstraints(),
  };
  if (taskType) {
    request.taskType = taskType;
  }
  return request;
}

async function sendChatRequest(payload) {
  const response = await fetch(apiUrl("/api/aggregate/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function isImageMarkdownRequest(text, attachments) {
  if (!hasImageAttachments(attachments)) {
    return false;
  }
  const cleanText = String(text || "").trim();
  if (!cleanText) {
    return true;
  }
  return /markdown|md|ocr|识别|提取|转换|转为|转成|表格|公式|文字|文本/i.test(cleanText);
}

function buildImageMarkdownRequestPayload(model, prompt, attachments, models = null, options = {}) {
  const attachmentIds = attachments
    .filter((item) => item.kind === "image" && item.id)
    .map((item) => item.id);
  return {
    ...(model === "auto" ? buildAutoRouteConnectionPayload() : buildRequestPayloadForModel(model)),
    model,
    models: Array.isArray(models) && models.length ? models : [model],
    attachmentIds,
    prompt,
    temperature: Number(els.temperatureInput.value || 0),
    maxTokens: els.maxTokensInput.value.trim(),
    ...options,
  };
}

async function sendImageMarkdownRequest(payload) {
  const response = await fetch(apiUrl("/api/aggregate/image-to-markdown"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!data.ok) {
    const attempts = Array.isArray(data.attempts)
      ? data.attempts.map((item) => `${item.modelRef || item.model}: ${item.error || item.status}`).join("；")
      : "";
    throw new Error(`${data.error || "图片转 Markdown 失败"}${attempts ? `（${attempts}）` : ""}`);
  }
  return data;
}

async function requestRoutePreview(payload) {
  const response = await fetch(apiUrl("/api/aggregate/route"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

function summarizeRouteProfile(routeResult) {
  const profile = routeResult?.modelProfile || findModelProfile(routeResult?.selectedModel || routeResult?.resolvedModel || "");
  if (!profile) {
    return "-";
  }
  const summary = [
    `quality ${profile.qualityTier || "-"}`,
    `speed ${profile.speedTier || "-"}`,
    `cost ${profile.costTier || "-"}`,
    `privacy ${profile.privacy || "-"}`,
  ];
  if (routeResult?.taskType === "translation.zh_en" && profile.translationZhEn) {
    summary.push(`${profile.translationZhEn.adapterId}：${profile.translationZhEn.recommendation}`);
  }
  return summary.join(" · ");
}

function updateRoutePreview(routeResult) {
  state.routePreview = routeResult || null;
  if (!routeResult) {
    resetRoutePreview();
    return;
  }
  els.routeStatus.textContent = routeResult.ok ? (routeResult.requestedModel === "auto" ? "auto" : "manual") : "未命中";
  els.routeTaskTypeValue.textContent = routeResult.taskType || "-";
  els.routeSelectedModelValue.textContent = routeResult.selectedModel || routeResult.resolvedModel || "-";
  els.routeProviderValue.textContent = routeResult.provider || "-";
  const fallbacks = Array.isArray(routeResult.fallbacks) ? routeResult.fallbacks.filter(Boolean) : [];
  els.routeFallbacksValue.textContent = fallbacks.length ? fallbacks.join("、") : "-";
  els.routeProfileValue.textContent = summarizeRouteProfile(routeResult);
  els.routeReasonValue.textContent = routeResult.reason || routeResult.error || routeResult.routerDecision?.reason || "-";
  updateActiveModelTitle();
}

function resetRoutePreview() {
  state.routePreview = null;
  els.routeStatus.textContent = "未预览";
  els.routeTaskTypeValue.textContent = "-";
  els.routeSelectedModelValue.textContent = "-";
  els.routeProviderValue.textContent = "-";
  els.routeFallbacksValue.textContent = "-";
  els.routeProfileValue.textContent = "-";
  els.routeReasonValue.textContent = "-";
  updateActiveModelTitle();
}

function updateDispatchModeUI() {
  const autoMode = state.dispatchMode === "auto";
  els.dispatchModeHint.textContent = autoMode
    ? "发送时会带上 taskType 和路由约束，由服务端选择模型。"
    : "发送时会直接使用当前所选模型。";
  els.dispatchModeHint.className = autoMode ? "field-note is-ok" : "field-note";
  els.previewRouteButton.textContent = autoMode ? "预览自动路由" : "预览当前模型";
}

async function handlePreviewRoute() {
  const content = els.messageInput.value.trim();
  const attachments = [...state.attachments];
  const requestedModel = state.dispatchMode === "auto" ? "auto" : state.activeModel;
  if (!requestedModel) {
    updateRoutePreview({ ok: false, error: "请先选择模型。", requestedModel: "", taskType: getEffectiveTaskType(content, attachments) || "general.chat" });
    renderRaw({ ok: false, error: "请先选择模型。" });
    return;
  }
  els.previewRouteButton.disabled = true;
  try {
    const payload = buildRoutePayload({ requestedModel, content, attachments, includeHistory: false });
    const data = await requestRoutePreview(payload);
    updateRoutePreview(data);
    renderRaw(data);
  } catch (error) {
    updateRoutePreview({ ok: false, error: error.message, requestedModel, taskType: getEffectiveTaskType(content, attachments) || "general.chat" });
    renderRaw({ ok: false, error: error.message });
  } finally {
    els.previewRouteButton.disabled = false;
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.pending) {
    return;
  }

  const content = els.messageInput.value.trim();
  const attachments = [...state.attachments];
  if (!content && !attachments.length) {
    return;
  }

  persistLocalState();
  if (hasImageAttachments(attachments)) {
    const modelHint = getModelHint(state.activeModel);
    if (!modelHint.singleRecommended) {
      setImageModelStatus();
    }
  }
  const useImageMarkdown = isImageMarkdownRequest(content, attachments);
  const apiContent = buildUserContent(content, attachments);
  const requestMessages = useImageMarkdown
    ? []
    : buildChatMessages({
        additionalUserMessage: { role: "user", content: apiContent },
        includeHistory: true,
      });
  state.messages.push({
    role: "user",
    content: content || "附件测试",
    apiContent,
    attachments: attachments.map((item) => ({ name: item.name, kind: item.kind, size: item.size })),
    model: state.activeModel,
    createdAt: Date.now(),
  });
  els.messageInput.value = "";
  state.attachments = [];
  renderAttachments();
  autoResizeComposer();
  renderMessages();
  setRequestState("Running", "busy");

  state.pending = true;
  els.sendButton.disabled = true;
  els.compareButton.disabled = true;
  els.refreshModelsButton.disabled = true;
  els.previewRouteButton.disabled = true;

  try {
    let data;
    if (useImageMarkdown) {
      let requestModel = state.activeModel;
      const imageTaskType = getEffectiveTaskType(content, attachments) || "ocr.image_to_markdown";
      if (state.dispatchMode === "auto") {
        const routeData = await requestRoutePreview(
          buildRoutePayload({
            requestedModel: "auto",
            content,
            attachments,
            includeHistory: false,
          })
        );
        updateRoutePreview(routeData);
        if (!routeData.ok || !routeData.selectedModel) {
          throw new Error(routeData.error || routeData.reason || "自动路由没有选出可用模型。");
        }
        requestModel = routeData.selectedModel;
      }
      data = await sendImageMarkdownRequest(
        buildImageMarkdownRequestPayload(requestModel, content, attachments, [requestModel], {
          allowFallback: false,
          taskType: imageTaskType,
          constraints: buildRouteConstraints(),
        })
      );
    } else {
      const requestModel = state.dispatchMode === "auto" ? "auto" : state.activeModel;
      data = await sendChatRequest(buildChatRequestPayload(requestModel, requestMessages, content, attachments));
      if (data.routerDecision) {
        updateRoutePreview({
          ok: Boolean(data.routerDecision.ok),
          requestedModel: data.requestedModel || requestModel,
          selectedModel: data.routerDecision.selectedModel || data.resolvedModel || data.modelRef,
          resolvedModel: data.resolvedModel || data.modelRef,
          provider: data.provider || data.routerDecision.provider,
          model: data.model || data.routerDecision.model,
          taskType: data.routerDecision.taskType || getEffectiveTaskType(content, attachments) || "general.chat",
          fallbacks: data.routerDecision.fallbacks || [],
          reason: data.routerDecision.reason || "",
          routerDecision: data.routerDecision,
          modelProfile: findModelProfile(data.resolvedModel || data.modelRef || ""),
        });
      }
    }
    renderRaw(data.raw || data);

    state.messages.push({
      role: "assistant",
      content: data.markdown || data.answer || "(空响应)",
      reasoning: data.reasoning || "",
      model: data.modelRef || data.model || state.activeModel,
      createdAt: Date.now(),
    });
    updateMetrics(data);
    setRequestState("Ready", "ok");
  } catch (error) {
    state.messages.push({
      role: "assistant",
      content: `请求失败：${error.message}`,
      model: state.activeModel,
      error: true,
      createdAt: Date.now(),
    });
    setRequestState("Error", "error");
  } finally {
    state.pending = false;
    els.sendButton.disabled = false;
    els.compareButton.disabled = false;
    els.refreshModelsButton.disabled = false;
    els.previewRouteButton.disabled = false;
    renderMessages();
  }
}

async function handleCompareAll() {
  if (state.pending) {
    return;
  }

  const content = els.messageInput.value.trim();
  const attachments = [...state.attachments];
  if (!content && !attachments.length) {
    els.messageInput.focus();
    return;
  }

  const models = getSelectedModels();
  if (!models.length) {
    setRequestState("No models", "error");
    return;
  }

  persistLocalState();
  if (hasImageAttachments(attachments) && !models.some((model) => getModelHint(model).compareRecommended)) {
    setModelStatus("已上传图片，但当前对比列表没有已验证视觉模型，结果可能忽略图片内容。", false);
  }
  const useImageMarkdown = isImageMarkdownRequest(content, attachments);
  const apiContent = buildUserContent(content, attachments);
  const requestMessages = useImageMarkdown
    ? []
    : buildChatMessages({
        additionalUserMessage: { role: "user", content: apiContent },
        includeHistory: false,
      });

  state.messages.push({
    role: "user",
    content: content || "附件测试",
    apiContent,
    attachments: attachments.map((item) => ({ name: item.name, kind: item.kind, size: item.size })),
    model: "compare",
    createdAt: Date.now(),
  });

  const comparison = {
    id: `comparison-${Date.now()}`,
    role: "comparison",
    content,
    createdAt: Date.now(),
    settings: {
      temperature: Number(els.temperatureInput.value || 0.7),
      maxTokens: els.maxTokensInput.value.trim() || "auto",
      systemPromptEnabled: Boolean(els.systemPromptInput.value.trim()),
      promptPresetLabel: els.promptPresetStatus.textContent || "自定义",
      taskType: getEffectiveTaskType(content, attachments) || "general.chat",
      attachments: buildAttachmentSummary(attachments),
    },
    results: models.map((model) => ({ model, status: "pending", answer: "", latencyMs: null, usage: null })),
    mode: useImageMarkdown ? "image-to-markdown" : "chat",
  };
  state.messages.push(comparison);

  els.messageInput.value = "";
  state.attachments = [];
  renderAttachments();
  autoResizeComposer();
  renderMessages();

  state.pending = true;
  els.sendButton.disabled = true;
  els.compareButton.disabled = true;
  els.refreshModelsButton.disabled = true;
  els.previewRouteButton.disabled = true;
  const rawResults = [];

  try {
    for (let index = 0; index < comparison.results.length; index += 1) {
      const result = comparison.results[index];
      setRequestState(`${index + 1}/${comparison.results.length}`, "busy");
      renderMessages();
      try {
        const data = useImageMarkdown
          ? await sendImageMarkdownRequest(
              buildImageMarkdownRequestPayload(result.model, content, attachments, [result.model], {
                allowFallback: false,
                taskType: getEffectiveTaskType(content, attachments) || "ocr.image_to_markdown",
                constraints: buildRouteConstraints(),
              })
            )
          : await sendChatRequest(
              buildChatRequestPayload(result.model, requestMessages, content, attachments)
            );
        result.status = "done";
        result.answer = data.markdown || data.answer || "(空响应)";
        result.reasoning = data.reasoning || "";
        result.actualModel = data.modelRef || data.model || result.model;
        result.latencyMs = data.latencyMs;
        result.usage = data.usage;
        result.finishReason = data.finishReason;
        result.path = data.path;
        rawResults.push({
          model: result.model,
          actualModel: result.actualModel,
          ok: true,
          data: data.raw || data,
          attempts: data.attempts,
          routerDecision: data.routerDecision || null,
        });
      } catch (error) {
        result.status = "error";
        result.answer = error.message;
        rawResults.push({ model: result.model, ok: false, error: error.message });
      }
    }
    updateComparisonMetrics(comparison.results);
    renderRaw({ comparison: rawResults });
    setRequestState("Ready", "ok");
  } finally {
    state.pending = false;
    els.sendButton.disabled = false;
    els.compareButton.disabled = false;
    els.refreshModelsButton.disabled = false;
    els.previewRouteButton.disabled = false;
    renderMessages();
  }
}

function renderMessages() {
  els.messages.innerHTML = "";

  if (!state.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-message";
    empty.textContent = "选择模型后发送第一条测试消息。这里会保留上下文，方便比较不同模型的回答质量和速度。";
    els.messages.append(empty);
    return;
  }

  state.messages.forEach((message) => {
    if (message.role === "comparison") {
      els.messages.append(renderComparisonMessage(message));
      return;
    }

    const wrapper = document.createElement("article");
    wrapper.className = `message ${message.role}`;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = `${message.role === "user" ? "你" : message.model || "assistant"} · ${formatTime(message.createdAt)}`;

    const messageNodes = [meta];
    if (Array.isArray(message.attachments) && message.attachments.length) {
      messageNodes.push(renderAttachmentBadges(message.attachments));
    }

    if (message.reasoning) {
      const reasoning = document.createElement("div");
      reasoning.className = "reasoning";
      reasoning.textContent = message.reasoning;
      messageNodes.push(reasoning, bubble(message.content, message.error));
    } else {
      messageNodes.push(bubble(message.content, message.error));
    }
    wrapper.append(...messageNodes);

    els.messages.append(wrapper);
  });

  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderComparisonMessage(message) {
  const wrapper = document.createElement("article");
  wrapper.className = "comparison-message";

  const header = document.createElement("div");
  header.className = "comparison-header";
  const title = document.createElement("div");
  title.innerHTML = `<strong>${message.mode === "image-to-markdown" ? "图片转 Markdown 对比" : "横向对比"}</strong><span>${formatTime(message.createdAt)}</span>`;
  const settings = document.createElement("div");
  settings.className = "comparison-settings";
  settings.textContent = `Task ${message.settings.taskType} · Temperature ${message.settings.temperature} · Max ${message.settings.maxTokens} · 角色 ${message.settings.promptPresetLabel} · System ${message.settings.systemPromptEnabled ? "on" : "off"}${message.settings.attachments ? ` · ${message.settings.attachments}` : ""}`;
  header.append(title, settings);

  const grid = document.createElement("div");
  grid.className = "comparison-grid";
  message.results.forEach((result) => {
    const card = document.createElement("section");
    card.className = `comparison-card ${result.status === "error" ? "is-error" : ""}`;

    const cardHead = document.createElement("div");
    cardHead.className = "comparison-card-head";

    const model = document.createElement("div");
    model.className = "comparison-model";
    model.textContent = result.model;

    const copyButton = document.createElement("button");
    copyButton.className = "text-button compact-button comparison-copy-button";
    copyButton.type = "button";
    copyButton.textContent = "复制";
    copyButton.disabled = result.status === "pending" || !result.answer;
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(normalizeAnswerForDisplay(result.answer || ""));
      copyButton.textContent = "已复制";
      window.setTimeout(() => {
        copyButton.textContent = "复制";
      }, 1200);
    });
    cardHead.append(model, copyButton);

    const hint = document.createElement("div");
    hint.className = `comparison-hint is-${getModelHintType(result.model).replace(/_/g, "-")}`;
    hint.textContent = getModelHint(result.model).badge;

    const meta = document.createElement("div");
    meta.className = "comparison-meta";
    const totalTokens = result.usage?.total_tokens ?? result.usage?.totalTokens;
    if (result.status === "pending") {
      meta.textContent = "等待中";
    } else {
      const actual = result.actualModel && result.actualModel !== result.model ? ` · 命中 ${result.actualModel}` : "";
      meta.textContent = `${result.latencyMs ? `${result.latencyMs} ms` : "-"} · ${totalTokens ? `${totalTokens} tokens` : "tokens -"}${actual}`;
    }

    if (result.reasoning) {
      const reasoning = document.createElement("div");
      reasoning.className = "reasoning";
      reasoning.textContent = result.reasoning;
      card.append(cardHead, hint, meta, reasoning, bubble(result.answer || "等待响应...", result.status === "error"));
    } else {
      card.append(cardHead, hint, meta, bubble(result.answer || "等待响应...", result.status === "error"));
    }
    grid.append(card);
  });

  wrapper.append(header, grid);
  return wrapper;
}

function renderAttachmentBadges(attachments) {
  const list = document.createElement("div");
  list.className = "message-attachments";
  attachments.forEach((item) => {
    const badge = document.createElement("span");
    badge.textContent = `${item.name} · ${item.kind}`;
    list.append(badge);
  });
  return list;
}

function bubble(content, isError = false) {
  const node = document.createElement("div");
  node.className = "bubble markdown-body";
  if (isError) {
    node.style.borderColor = "#ffc9b8";
    node.style.background = "#fff7f3";
    node.textContent = normalizeAnswerForDisplay(content);
    return node;
  }
  node.innerHTML = renderMarkdownHtml(normalizeAnswerForDisplay(content));
  return node;
}

function normalizeAnswerForDisplay(content) {
  return normalizeMathMarkdown(stripMarkdownFence(String(content || "")));
}

function stripMarkdownFence(text) {
  const stripped = text.trim();
  const match = stripped.match(/^```(?:markdown|md)?\s*([\s\S]*?)\s*```$/i);
  return match ? match[1].trim() : text;
}

function normalizeMathMarkdown(text) {
  const inlineMathPattern = /\b([A-Za-z]\s*=\s*[-+]?(?:[A-Za-z]+|\d+(?:\.\d+)?)(?:\s*\^\s*(?:\{[^}\n]+\}|[A-Za-z0-9()+-]+))?)(?=$|[\s,.;:|)\]])/g;
  return text
    .split("\n")
    .map((line) => {
      if (!line.includes("|")) {
        return wrapInlineMathOutsideMathSpans(line, inlineMathPattern);
      }
      return line
        .split("|")
        .map((cell) => {
          const trimmed = cell.trim();
          if (!trimmed || /^:?-{3,}:?$/.test(trimmed)) {
            return cell;
          }
          return cell.replace(trimmed, wrapInlineMathOutsideMathSpans(trimmed, inlineMathPattern));
        })
        .join("|");
    })
    .join("\n");
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function splitMarkdownTableRow(line) {
  const trimmed = line.trim();
  const body = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
  const withoutTrailing = body.endsWith("|") ? body.slice(0, -1) : body;
  return withoutTrailing.split("|").map((cell) => cell.trim());
}

function isMarkdownTableSeparator(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isMarkdownTableStart(lines, index) {
  return (
    typeof lines[index] === "string" &&
    typeof lines[index + 1] === "string" &&
    lines[index].trim().startsWith("|") &&
    lines[index + 1].trim().startsWith("|") &&
    isMarkdownTableSeparator(lines[index + 1])
  );
}

function isCodeFenceStart(line) {
  return /^```/.test(String(line || "").trim());
}

function renderCodeBlock(lines) {
  const opener = lines[0].trim();
  const language = opener.replace(/^```/, "").trim();
  const body = lines.slice(1, -1).join("\n");
  const languageClass = language ? ` class="language-${escapeHtml(language)}"` : "";
  return `<pre><code${languageClass}>${escapeHtml(body)}</code></pre>`;
}

function renderMarkdownTable(lines) {
  const header = splitMarkdownTableRow(lines[0]);
  const bodyRows = lines.slice(2).map(splitMarkdownTableRow);
  const width = Math.max(header.length, ...bodyRows.map((row) => row.length), 1);
  const normalizeRow = (row) => row.concat(Array(Math.max(0, width - row.length)).fill(""));
  const headHtml = normalizeRow(header)
    .map((cell) => `<th>${escapeHtml(cell)}</th>`)
    .join("");
  const bodyHtml = bodyRows
    .map((row) => `<tr>${normalizeRow(row).map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="markdown-table-wrap"><table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
}

function renderParagraph(lines) {
  const text = lines.join("\n").trim();
  if (!text) {
    return "";
  }
  return `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>`;
}

function renderMarkdownHtml(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const parts = [];
  let index = 0;

  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }

    if (isCodeFenceStart(lines[index])) {
      const codeLines = [lines[index]];
      index += 1;
      while (index < lines.length && !isCodeFenceStart(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        codeLines.push(lines[index]);
        index += 1;
      } else {
        codeLines.push("```");
      }
      parts.push(renderCodeBlock(codeLines));
      continue;
    }

    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [lines[index], lines[index + 1]];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      parts.push(renderMarkdownTable(tableLines));
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length && lines[index].trim() && !isMarkdownTableStart(lines, index)) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    parts.push(renderParagraph(paragraphLines));
  }

  return parts.join("");
}

function wrapInlineMathOutsideMathSpans(text, inlineMathPattern) {
  const mathSpanPattern = /(\$\$[\s\S]*?\$\$|\$[^$\n]*?\$)/g;
  return text
    .split(mathSpanPattern)
    .map((part) => {
      if (!part || /^(\$\$[\s\S]*?\$\$|\$[^$\n]*?\$)$/.test(part)) {
        return part;
      }
      return part.replace(inlineMathPattern, (match) => `$${match}$`);
    })
    .join("");
}

async function handleAttachmentFiles(fileList) {
  const files = Array.from(fileList || []);
  els.attachmentInput.value = "";
  for (const file of files) {
    try {
      state.attachments.push(await readAttachment(file));
    } catch (error) {
      state.attachments.push({
        id: `attachment-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        type: file.type,
        size: file.size,
        kind: "error",
        error: error.message,
      });
    }
  }
  syncModelSelectionStrategy();
  renderAttachments();
  updateRequestSettingsSummary();
  resetRoutePreview();
}

function readAttachment(file) {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return Promise.reject(new Error(`文件超过 ${formatBytes(MAX_ATTACHMENT_BYTES)}`));
  }

  if (file.type.startsWith("image/")) {
    return readFileAsDataUrl(file).then((dataUrl) =>
      uploadAttachmentToServer({
        name: file.name,
        mimeType: file.type,
        size: file.size,
        kind: "image",
        dataUrl,
      }).then((uploaded) => ({
        id: uploaded.id,
        name: uploaded.name,
        type: uploaded.mimeType,
        size: uploaded.size,
        kind: uploaded.kind,
      }))
    );
  }

  if (isTextLikeFile(file)) {
    return readFileAsText(file).then((text) =>
      uploadAttachmentToServer({
        name: file.name,
        mimeType: file.type,
        size: file.size,
        kind: "text",
        text,
      }).then((uploaded) => ({
        id: uploaded.id,
        name: uploaded.name,
        type: uploaded.mimeType,
        size: uploaded.size,
        kind: uploaded.kind,
      }))
    );
  }

  return uploadAttachmentToServer({
    name: file.name,
    mimeType: file.type,
    size: file.size,
    kind: "metadata",
  }).then((uploaded) => ({
    id: uploaded.id,
    name: uploaded.name,
    type: uploaded.mimeType,
    size: uploaded.size,
    kind: uploaded.kind,
  }));
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.readAsDataURL(file);
  });
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取文本失败"));
    reader.readAsText(file);
  });
}

function isTextLikeFile(file) {
  const name = file.name.toLowerCase();
  return (
    file.type.startsWith("text/") ||
    [".md", ".json", ".csv", ".tsv", ".txt", ".log", ".xml", ".yaml", ".yml"].some((suffix) => name.endsWith(suffix))
  );
}

async function uploadAttachmentToServer(payload) {
  const response = await fetch(apiUrl("/api/aggregate/upload"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(data.error || "上传附件失败");
  }
  return data;
}

function renderAttachments() {
  els.attachmentList.innerHTML = "";
  if (!state.attachments.length) {
    els.attachmentList.hidden = true;
    return;
  }

  els.attachmentList.hidden = false;
  state.attachments.forEach((item) => {
    const chip = document.createElement("button");
    chip.className = `attachment-chip ${item.kind === "error" ? "is-error" : ""}`;
    chip.type = "button";
    chip.title = item.error ? `${item.name}: ${item.error}` : "点击移除附件";
    chip.textContent = `${item.name} · ${item.kind} · ${formatBytes(item.size)}`;
    chip.addEventListener("click", () => {
      state.attachments = state.attachments.filter((attachment) => attachment.id !== item.id);
      syncModelSelectionStrategy();
      renderAttachments();
      updateRequestSettingsSummary();
      resetRoutePreview();
    });
    els.attachmentList.append(chip);
  });
  updateModelChecklistHint();
}

function updateComparisonMetrics(results) {
  const completed = results.filter((item) => item.status === "done");
  const latencyTotal = completed.reduce((sum, item) => sum + (Number(item.latencyMs) || 0), 0);
  const tokenTotal = completed.reduce((sum, item) => {
    const usage = item.usage || {};
    return sum + Number(usage.total_tokens ?? usage.totalTokens ?? 0);
  }, 0);
  els.latencyValue.textContent = completed.length ? `${Math.round(latencyTotal / completed.length)} ms avg` : "-";
  els.tokensValue.textContent = tokenTotal ? String(tokenTotal) : "-";
  els.finishValue.textContent = `${completed.length}/${results.length}`;
  els.pathValue.textContent = "compare";
}

function updateMetrics(data) {
  els.latencyValue.textContent = data.latencyMs ? `${data.latencyMs} ms` : "-";
  const usage = data.usage || {};
  const total = usage.total_tokens ?? usage.totalTokens;
  els.tokensValue.textContent = total ? String(total) : "-";
  els.finishValue.textContent = data.finishReason || "-";
  els.pathValue.textContent = data.path || "-";
}

function resetMetrics() {
  els.latencyValue.textContent = "-";
  els.tokensValue.textContent = "-";
  els.finishValue.textContent = "-";
  els.pathValue.textContent = "-";
}

function renderRaw(data) {
  els.rawResponse.textContent = JSON.stringify(data || {}, null, 2);
}

function setRequestState(label, stateName = "ok") {
  els.requestBadge.textContent = label;
  els.requestBadge.classList.toggle("is-busy", stateName === "busy");
  els.requestBadge.classList.toggle("is-error", stateName === "error");
}

function setModelStatus(message, isError) {
  els.modelStatus.textContent = message;
  els.modelStatus.classList.toggle("is-error", Boolean(isError));
  els.modelStatus.classList.toggle("is-ok", !isError);
}

function updateKeyStatus() {
  const preset = getServicePreset();
  const configured = Boolean(preset?.configured || state.hasBackendKey);
  els.keyStatus.textContent = configured
    ? "由聚合服务后端环境变量管理"
    : "由聚合服务后端管理，当前未检测到该通道配置";
  els.keyStatus.className = configured ? "field-note is-ok" : "field-note";
}

function updateKeyVisibilityButton(isVisible) {
  els.toggleKeyButton.classList.toggle("is-visible", isVisible);
  els.toggleKeyButton.title = isVisible ? "隐藏 API Key" : "显示 API Key";
  els.toggleKeyButton.setAttribute("aria-label", isVisible ? "隐藏 API Key" : "显示 API Key");
}

function updateActiveModelTitle() {
  if (state.dispatchMode === "auto") {
    const selected = state.routePreview?.selectedModel || state.routePreview?.resolvedModel;
    els.activeModelTitle.textContent = selected ? `自动路由 → ${selected}` : "自动路由";
    return;
  }
  els.activeModelTitle.textContent = state.activeModel || "选择模型后开始测试";
}

function autoResizeComposer() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(els.messageInput.scrollHeight, 180)}px`;
}

function updateRequestSettingsSummary() {
  const temperature = els.temperatureInput.value || "0.7";
  const maxTokens = els.maxTokensInput.value.trim() || "auto";
  const hasSystemPrompt = Boolean(els.systemPromptInput.value.trim());
  const roleLabel = els.promptPresetStatus.textContent || "自定义";
  const preset = getServicePreset();
  const serviceLabel = preset?.label || "OpenAI-compatible";
  const taskType = getEffectiveTaskType(els.messageInput.value || "", state.attachments) || "自动识别";
  const modeLabel = state.dispatchMode === "auto" ? "auto" : "manual";
  els.requestSettingsSummary.textContent = `服务 ${serviceLabel} · 模式 ${modeLabel} · Task ${taskType} · Temperature ${temperature} · Max ${maxTokens} · 角色 ${roleLabel} · System prompt ${hasSystemPrompt ? "已启用" : "关闭"}`;
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${Math.round(value / 1024)} KB`;
  }
  return `${value} B`;
}

function formatTime(timestamp) {
  if (!timestamp) {
    return "-";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
}

initialize();
