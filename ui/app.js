const commandInput = document.getElementById("commandInput");
const micButton = document.getElementById("micButton");
const planButton = document.getElementById("planButton");
const applyButton = document.getElementById("applyButton");
const cancelButton = document.getElementById("cancelButton");
const statusText = document.getElementById("status");
const errorBox = document.getElementById("errorBox");
const welcomePanel = document.getElementById("welcomePanel");
const chatArea = document.getElementById("chatArea");
const wakeNotice = document.getElementById("wakeNotice");
const wakeGreeting = document.getElementById("wakeGreeting");
const chatLog = document.getElementById("chatLog");
const listeningOverlay = document.getElementById("listeningOverlay");

let currentPlan = null;
let isBusy = false;
let pendingMessage = null;
let activeRunId = null;
let runSequence = 0;
let stopRequested = false;
let isRunning = false;

const OUT_OF_SCOPE_MESSAGE =
  "Ben masaüstü işlemlerine odaklı bir sesli asistanım. Klasör oluşturma, uygulama açma, web araması, not, hatırlatıcı ve takvim gibi bilgisayar işlemlerinde yardımcı olabilirim.";

const sendIcon = `
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M5 12h13" />
    <path d="m13 6 6 6-6 6" />
  </svg>
`;

const stopIcon = `
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M8 8h8v8H8z" />
  </svg>
`;

function hasCommandText() {
  return commandInput.value.trim().length > 0;
}

function setListeningVisual(active) {
  listeningOverlay?.classList.toggle("hidden", !active);
  document.body.classList.toggle("is-voice-listening", !!active);
}

function setStatus(text) {
  statusText.textContent = text;
  const stateMap = {
    Hazır: "ready",
    Dinleniyor: "listening",
    Çalışıyor: "working",
    Yanıtlıyor: "speaking",
    "Düşünüyor": "thinking",
    Bekliyor: "waiting",
    Tamamlandı: "done",
    Engellendi: "blocked",
    Durduruldu: "stopped",
  };
  statusText.dataset.state = stateMap[text] || "ready";
}

function resizeCommandInput() {
  commandInput.style.height = "auto";
  const nextHeight = Math.min(commandInput.scrollHeight, 150);
  commandInput.style.height = `${Math.max(nextHeight, 52)}px`;
}

function updateSendButton() {
  if (isBusy) {
    planButton.disabled = false;
    planButton.classList.add("is-active", "is-stop");
    planButton.setAttribute("aria-label", "Durdur");
    planButton.innerHTML = stopIcon;
    return;
  }

  planButton.disabled = !hasCommandText();
  planButton.classList.remove("is-stop");
  planButton.classList.toggle("is-active", !planButton.disabled);
  planButton.setAttribute("aria-label", "Gönder");
  planButton.innerHTML = sendIcon;
}

function setLoading(isLoading, label = "Çalışıyor") {
  isBusy = isLoading;
  isRunning = isLoading && label === "Çalışıyor";
  if (!isLoading) {
    isRunning = false;
  }
  micButton.disabled = isLoading;
  updateSendButton();
  applyButton.disabled = isLoading;
  cancelButton.disabled = isLoading;
  commandInput.disabled = isLoading;
  setStatus(isLoading ? label : "Hazır");
}

function showApprovalButtons(show) {
  applyButton.classList.toggle("hidden", !show);
  cancelButton.classList.toggle("hidden", !show);
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function clearError() {
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}

function resetTransientState() {
  currentPlan = null;
  showApprovalButtons(false);
  clearError();
}

function clearCommandInput() {
  commandInput.value = "";
  resizeCommandInput();
  updateSendButton();
}

function addChatMessage(role, text, variant = "") {
  if (!chatLog || !text) {
    return;
  }

  if (welcomePanel) {
    welcomePanel.classList.add("hidden");
  }
  chatArea?.classList.remove("hidden");
  chatLog.innerHTML = "";

  const row = document.createElement("div");
  const bubble = document.createElement("div");

  row.className = `message-row ${role}${variant ? ` ${variant}` : ""}`;
  bubble.className = "message-bubble";
  appendTextWithLinks(bubble, text);

  row.appendChild(bubble);
  chatLog.appendChild(row);
  chatLog.scrollTop = chatLog.scrollHeight;
  return row;
}

function appendTextWithLinks(container, text) {
  const value = String(text || "");
  const urlPattern = /(https?:\/\/[^\s)]+)/g;
  let lastIndex = 0;
  for (const match of value.matchAll(urlPattern)) {
    const url = match[0];
    const index = match.index || 0;
    if (index > lastIndex) {
      container.appendChild(document.createTextNode(value.slice(lastIndex, index)));
    }
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.textContent = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    container.appendChild(anchor);
    lastIndex = index + url.length;
  }
  if (lastIndex < value.length) {
    container.appendChild(document.createTextNode(value.slice(lastIndex)));
  }
}

function removePendingMessage() {
  if (pendingMessage) {
    pendingMessage.remove();
    pendingMessage = null;
  }
}

function getResponseView(response) {
  if (!response || !response.ok) {
    return {
      message: "İşlem sırasında hata oluştu.",
      variant: "error",
      status: "Hazır",
      error: response?.error || "İşlem sırasında hata oluştu.",
      speak: true,
    };
  }

  const data = response.data;

  if (data.blocked || data.status === "blocked") {
    return {
      message: "Bu işlem güvenlik nedeniyle uygulanmadı.",
      spokenMessage: data.spoken_message || "Bu işlem güvenlik nedeniyle uygulanmadı.",
      variant: "blocked",
      status: "Engellendi",
      speak: true,
    };
  }

  if (data.needs_clarification || data.status === "needs_clarification") {
    return {
      message: data.message || "Biraz daha bilgi verir misiniz?",
      spokenMessage: data.spoken_message || data.message || "Biraz daha bilgi verir misiniz?",
      variant: "success",
      status: "Hazır",
      speak: true,
    };
  }

  if (data.out_of_scope || data.status === "out_of_scope") {
    return {
      message: data.message || OUT_OF_SCOPE_MESSAGE,
      spokenMessage: data.spoken_message || data.message || OUT_OF_SCOPE_MESSAGE,
      variant: "stopped",
      status: "Hazır",
      speak: true,
    };
  }

  if (data.unclear || data.status === "unclear") {
    return {
      message: data.message || "Komutu net anlayamadım, tekrar söyleyebilir misiniz?",
      spokenMessage: data.spoken_message || data.message || "Komutu net anlayamadım, tekrar söyleyebilir misiniz?",
      variant: "error",
      status: "Hazır",
      speak: true,
    };
  }

  if (data.stopped || data.status === "stopped") {
    return {
      message: "İşlem durduruldu.",
      variant: "stopped",
      status: "Durduruldu",
      speak: false,
    };
  }

  if (data.success) {
    const firstResult = Array.isArray(data.results) ? data.results[0] : null;
    const directMessageActions = [
      "ANSWER_ONLY",
      "DATE_TIME_ANSWER",
      "LIST_REMINDERS",
      "LIST_TODOS",
      "SEARCH_FILES",
      "SYSTEM_INFO",
      "WEB_RESEARCH_SUMMARY",
      "ACADEMIC_SEARCH",
      "SUMMARIZE_URL",
      "LATEST_NEWS_BY_TOPIC",
      "OFFICIAL_INFO_SEARCH",
      "GENERAL_AI_ANSWER",
      "RESEARCH_AND_EXPLAIN",
      "PRACTICAL_GUIDE",
      "LOCATION_INFO",
      "UNSAFE_OR_BLOCKED"
    ];
    const actionMessages = {
      CREATE_CALENDAR_EVENT: "Takvim etkinliği oluşturuldu.",
      CREATE_REMINDER: "Hatırlatıcı oluşturuldu.",
      ADD_TODO: "Yapılacaklara eklendi.",
      COMPLETE_TODO: "Yapılacak tamamlandı.",
      CREATE_FOLDER: "Klasör oluşturuldu.",
      OPEN_FOLDER: "Klasör açıldı.",
      OPEN_SPECIAL_FOLDER: "Klasör açıldı.",
      OPEN_COMMON_APP: "Uygulama açıldı.",
      OPEN_APP: "Uygulama açıldı.",
      OPEN_WEBSITE: "Web sitesi açıldı.",
      WEB_SEARCH: "Web araması açıldı.",
      CREATE_NOTE: "Not oluşturuldu.",
      APPEND_TO_NOTE: "Nota metin eklendi.",
      CREATE_PROJECT_STRUCTURE: "Proje yapısı oluşturuldu.",
      TAKE_SCREENSHOT: "Ekran görüntüsü kaydedildi.",
      WEB_RESEARCH_SAVE: "Araştırma raporu kaydedildi.",
      COPY_TEXT_TO_CLIPBOARD: "Metin panoya kopyalandı.",
      VOLUME_UP: "Ses artırıldı.",
      VOLUME_DOWN: "Ses kısıldı.",
      MUTE_VOLUME: "Ses kapatıldı.",
      UNMUTE_VOLUME: "Ses açıldı.",
      PLAY_PAUSE_MEDIA: "Medya oynatma durumu değiştirildi.",
    };
    const message = directMessageActions.includes(firstResult?.action)
      ? firstResult?.message || "İşlem tamamlandı."
      : actionMessages[firstResult?.action] || "İşlem tamamlandı.";
    return {
      message,
      spokenMessage: data.spoken_message || firstResult?.spoken_message || message,
      variant: "success",
      status: "Tamamlandı",
      speak: true,
    };
  }

  if (data.message) {
    return {
      message: data.message,
      spokenMessage: data.spoken_message || data.message,
      variant: "stopped",
      status: "Hazır",
      speak: true,
    };
  }

  return {
    message: "İşlem sırasında hata oluştu.",
    variant: "error",
    status: "Hazır",
    speak: true,
  };
}

function renderDirect(response, options = {}) {
  removePendingMessage();

  const view = getResponseView(response);
  currentPlan = null;
  showApprovalButtons(false);

  if (view.error) {
    showError(view.error);
  }

  if (view.status) {
    setStatus(view.status);
  }
  addChatMessage("assistant", view.message, view.variant);

  if (options.speak !== false && view.speak) {
    speakText(view.spokenMessage || view.message);
  }

  return view;
}

function renderSimpleAssistantMessage(message, variant = "success", status = "Hazır", shouldSpeak = true, spokenMessage = "") {
  removePendingMessage();
  addChatMessage("assistant", message, variant);
  setStatus(status);
  if (shouldSpeak) {
    speakText(spokenMessage || message);
  }
}

async function runVoiceCommandDirect() {
  resetTransientState();
  clearCommandInput();

  if (
    !window.pywebview?.api?.voice_command_direct
  ) {
    showError("Sesli komut sistemi hazır değil.");
    return;
  }

  const runId = ++runSequence;
  activeRunId = runId;
  stopRequested = false;
  micButton.classList.add("is-listening");
  setListeningVisual(true);
  setLoading(true, "Dinleniyor");

  let finalStatus = "Hazır";
  let thinkingTimer = null;
  let workingTimer = null;

  try {
    thinkingTimer = window.setTimeout(() => {
      if (activeRunId === runId && !stopRequested) {
        micButton.classList.remove("is-listening");
        setStatus("Düşünüyor");
      }
    }, 5200);
    workingTimer = window.setTimeout(() => {
      if (activeRunId === runId && !stopRequested) {
        setStatus("Çalışıyor");
      }
    }, 5800);

    const voiceResponse = await window.pywebview.api.voice_command_direct();
    if (thinkingTimer) {
      window.clearTimeout(thinkingTimer);
      thinkingTimer = null;
    }
    if (workingTimer) {
      window.clearTimeout(workingTimer);
      workingTimer = null;
    }
    micButton.classList.remove("is-listening");

    if (activeRunId !== runId || stopRequested) {
      return;
    }

    if (!voiceResponse || !voiceResponse.ok) {
      const message = voiceResponse?.error || "Ses algılanamadı, tekrar deneyebilirsiniz.";
      renderSimpleAssistantMessage(message, "error", "Hazır");
      return;
    }

    const data = voiceResponse.data || {};
    const message = data.message || "İşlem sırasında hata oluştu.";
    const spokenMessage = data.spoken_message || message;

    if (data.blocked || data.status === "blocked") {
      finalStatus = "Engellendi";
      renderSimpleAssistantMessage(message, "blocked", finalStatus, true, spokenMessage);
      return;
    }

    if (data.out_of_scope) {
      renderSimpleAssistantMessage(message || OUT_OF_SCOPE_MESSAGE, "stopped", "Hazır", true, spokenMessage);
      return;
    }

    if (data.needs_clarification) {
      renderSimpleAssistantMessage(message, "success", "Hazır", true, spokenMessage);
      return;
    }

    if (data.unclear) {
      renderSimpleAssistantMessage(message, "error", "Hazır", true, spokenMessage);
      return;
    }

    finalStatus = data.success ? "Tamamlandı" : "Hazır";
    renderSimpleAssistantMessage(
      message,
      data.success ? "success" : "error",
      finalStatus,
      true,
      spokenMessage
    );
  } catch (error) {
    if (activeRunId !== runId || stopRequested) {
      return;
    }
    const message = String(error || "").includes("Ses algılanamadı")
      ? "Ses algılanamadı, tekrar deneyebilirsiniz."
      : "İşlem sırasında hata oluştu.";
    renderSimpleAssistantMessage(message, "error", "Hazır");
  } finally {
    if (thinkingTimer) {
      window.clearTimeout(thinkingTimer);
    }
    if (workingTimer) {
      window.clearTimeout(workingTimer);
    }
    micButton.classList.remove("is-listening");
    setListeningVisual(false);
    if (activeRunId === runId) {
      setLoading(false);
      activeRunId = null;
      if (!stopRequested) {
        setStatus(finalStatus);
      }
    }
  }
}

async function runCommandText(text, options = {}) {
  clearError();

  const cleanedText = String(text || "").trim();
  if (!cleanedText) {
    showError("Lütfen bir komut yazın.");
    commandInput.focus();
    return;
  }

  if (!window.pywebview?.api?.run_command_direct) {
    showError("Komut sistemi hazır değil.");
    return;
  }

  const runId = ++runSequence;
  activeRunId = runId;
  stopRequested = false;
  currentPlan = null;
  showApprovalButtons(false);
  clearCommandInput();
  pendingMessage = addChatMessage("assistant", "NOVA işlemi yürütüyor...", "pending");
  setLoading(true, "Çalışıyor");

  let finalStatus = null;
  try {
    const response = await window.pywebview.api.run_command_direct(cleanedText);
    if (activeRunId !== runId || stopRequested) {
      return;
    }
    renderDirect(response, { speak: options.speak !== false });
    if (response?.ok) {
      finalStatus = response.data?.success
        ? "Tamamlandı"
        : response.data?.blocked || response.data?.status === "blocked"
          ? "Engellendi"
          : response.data?.stopped || response.data?.status === "stopped"
            ? "Durduruldu"
          : "Hazır";
    }
  } catch (error) {
    if (activeRunId !== runId || stopRequested) {
      return;
    }
    removePendingMessage();
    showError(`Komut çalıştırılamadı: ${error}`);
    finalStatus = "Hazır";
    addChatMessage("assistant", "İşlem sırasında hata oluştu.", "error");
    speakText("İşlem sırasında hata oluştu.");
  } finally {
    if (activeRunId === runId) {
      setLoading(false);
      activeRunId = null;
    }
    if (finalStatus && activeRunId === null && !stopRequested) {
      setStatus(finalStatus);
    }
  }
}

async function runCommandDirectFromInput() {
  await runCommandText(commandInput.value);
}

async function stopCurrentTask() {
  if (!isBusy) {
    return;
  }

  stopRequested = true;
  activeRunId = null;
  removePendingMessage();
  setLoading(false);
  setStatus("Durduruldu");
  addChatMessage("assistant", "İşlem durduruldu.", "stopped");

  if (!window.pywebview?.api?.stop_current_task) {
    return;
  }

  try {
    await window.pywebview.api.stop_current_task();
  } catch (_error) {
    // Durdurma en iyi çaba modundadır; UI bu yüzden kilitlenmemeli.
  }
}

async function applyCurrentPlan() {
  if (!currentPlan || !window.pywebview?.api?.apply_plan) {
    return;
  }

  setLoading(true, "Çalışıyor");
  try {
    const response = await window.pywebview.api.apply_plan(currentPlan);
    renderDirect(response);
  } catch (_error) {
    addChatMessage("assistant", "İşlem sırasında hata oluştu.", "error");
    speakText("İşlem sırasında hata oluştu.");
  } finally {
    setLoading(false);
  }
}

async function speakText(text) {
  if (!window.pywebview?.api?.speak_text) {
    return;
  }

  try {
    await window.pywebview.api.speak_text(text);
  } catch (_error) {
    // Sesli cevap hatası arayüzü veya işlemi durdurmamalı.
  }
}

async function speakTextSync(text) {
  if (!window.pywebview?.api?.speak_text_sync) {
    return;
  }

  try {
    await window.pywebview.api.speak_text_sync(text);
  } catch (_error) {
    // Sesli cevap hatası arayüzü veya işlemi durdurmamalı.
  }
}

async function checkDueReminders() {
  if (!window.pywebview?.api?.check_due_reminders || isBusy) {
    return;
  }

  try {
    const response = await window.pywebview.api.check_due_reminders();
    const reminders = response?.data?.reminders || [];
    for (const reminder of reminders) {
      const message = `Hatırlatma: ${reminder.title || "Bir hatırlatıcınız var."}`;
      addChatMessage("assistant", message, "success");
      speakText(message);
    }
  } catch (_error) {
    // Hatırlatıcı kontrolü arayüzü sessizce rahatsız etmemeli.
  }
}

micButton.addEventListener("click", runVoiceCommandDirect);
planButton.addEventListener("click", () => {
  if (isBusy) {
    stopCurrentTask();
    return;
  }
  runCommandDirectFromInput();
});
applyButton.addEventListener("click", applyCurrentPlan);
cancelButton.addEventListener("click", resetTransientState);

async function handleWakeEvent(event = {}) {
  if (isBusy) {
    return;
  }

  welcomePanel?.classList.add("hidden");
  chatArea?.classList.remove("hidden");
  wakeGreeting?.classList.add("hidden");
  wakeNotice?.classList.add("hidden");

  // Siri benzeri akış: watcher sadece "Hey Nova"yı yakalar.
  // Komut arayüz tarafından ayrıca dinlenir ve sessizlik sonrası otomatik çalıştırılır.
  setStatus("Dinleniyor");
  setListeningVisual(true);
  await new Promise((resolve) => window.setTimeout(resolve, 180));
  await runVoiceCommandDirect();
}

async function consumeWakeEvent() {
  if (!window.pywebview?.api?.consume_wake_event || isBusy) {
    return;
  }

  try {
    const response = await window.pywebview.api.consume_wake_event();
    const event = response?.data?.event;
    if (event) {
      await handleWakeEvent(event);
    }
  } catch (_error) {
    // Wake event yoksa sessiz geçilir.
  }
}

window.addEventListener("nova-wake-opened", () => consumeWakeEvent());

if (window.localStorage.getItem("nova_opened_by_wake") === "1") {
  window.localStorage.removeItem("nova_opened_by_wake");
  consumeWakeEvent();
}

commandInput.addEventListener("input", () => {
  if (currentPlan) {
    currentPlan = null;
    showApprovalButtons(false);
  }
  resizeCommandInput();
  updateSendButton();
});

commandInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!isBusy && hasCommandText()) {
      runCommandDirectFromInput();
    }
  }
});

window.addEventListener("DOMContentLoaded", () => {
  resizeCommandInput();
  updateSendButton();
  window.setInterval(checkDueReminders, 30000);
  window.setInterval(consumeWakeEvent, 1000);
  checkDueReminders();
  consumeWakeEvent();
});

if (document.readyState !== "loading") {
  resizeCommandInput();
  updateSendButton();
  window.setInterval(checkDueReminders, 30000);
  window.setInterval(consumeWakeEvent, 1000);
  checkDueReminders();
  consumeWakeEvent();
}
