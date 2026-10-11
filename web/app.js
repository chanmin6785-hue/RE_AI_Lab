const $ = (id) => document.getElementById(id);
const PROVIDERS = ["gpt", "claude", "gemini", "grok"];
const ACCOUNTS = ["user", "friend", "member3", "member4"];
const LABELS = {gpt:"GPT",claude:"Claude",gemini:"Gemini",grok:"Grok",user:"연구자",friend:"친구",member3:"참여자 3",member4:"참여자 4"};
let lastMessageId = "";
let lastAccountSignature = "";
let lastRoleSignature = "";
let lastActivitySignature = "";
let selectedTurn = 0;
let selectedTurnStatus = "";
let toastTimer;
let requestBusy = false;
let lastError = "";
let selfActor = "user";

function openTab(name) {
  for (const section of ["chat", "activity", "files", "settings"]) $(section + "Panel").hidden = section !== name;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
}
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => openTab(tab.dataset.tab)));
document.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => openTab(button.dataset.open)));

function toast(message, error = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", error);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

async function post(path, data = {}) {
  const response = await fetch(path, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "요청에 실패했습니다.");
  return result;
}

function setSelect(provider, options, preferred) {
  const el = $("model-" + provider);
  el.replaceChildren();
  if (!options.length) {
    const option = document.createElement("option");
    option.textContent = "담당자 연결 후 선택";
    option.value = "";
    el.append(option);
  } else {
    for (const id of options) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      el.append(option);
    }
    el.value = options.includes(preferred) ? preferred : options[0];
  }
  el.disabled = !options.length;
}

function availableFor(state, account, provider) {
  return state.accounts?.[account]?.available?.[provider] || [];
}

function assignmentValid(state, assignment) {
  if (!state.connected) return false;
  if (new Set(PROVIDERS.map((provider) => assignment[provider])).size !== ACCOUNTS.length) return false;
  if (!ACCOUNTS.every((actor) => PROVIDERS.some((provider) => assignment[provider] === actor))) return false;
  return PROVIDERS.every((provider) => availableFor(state, assignment[provider], provider).length > 0);
}

function currentAssignment() {
  return Object.fromEntries(PROVIDERS.map((provider) => [provider, $("account-" + provider).value]));
}

function chooseAssignment(state) {
  const current = currentAssignment();
  if (assignmentValid(state, current)) return current;
  function find(index, remaining, candidate) {
    if (index === PROVIDERS.length) return assignmentValid(state, candidate) ? {...candidate} : null;
    const provider = PROVIDERS[index];
    for (const actor of remaining) {
      if (!availableFor(state, actor, provider).length) continue;
      candidate[provider] = actor;
      const found = find(index + 1, remaining.filter((item) => item !== actor), candidate);
      if (found) return found;
    }
    return null;
  }
  const found = find(0, ACCOUNTS, {});
  if (found) return found;
  return current;
}

function updateModelChoices(state) {
  for (const provider of PROVIDERS) {
    const account = $("account-" + provider).value;
    const preferred = state.assignments?.[provider] ? state.models?.[provider] : $("model-" + provider).value;
    setSelect(provider, availableFor(state, account, provider), preferred);
  }
}

function displayName(message) {
  if (message.actor === selfActor) return "나";
  if (message.actor === "system") return "연구실";
  if (message.actor === "model") return LABELS[message.provider] || message.provider;
  return LABELS[message.actor] || message.actor;
}

function phaseName(phase, round) {
  if (phase === "role_selection") return "역할 협의";
  if (phase === "topic_selection") return "주제 선정";
  if (phase === "research") return `토론 ${round}라운드`;
  return "";
}

function makeMessage(message) {
  const article = document.createElement("article");
  article.className = "message " + (message.provider || message.actor) + (message.actor === selfActor ? " mine" : "");
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = message.actor === "system" ? "✳" : displayName(message).slice(0, 1);
  const body = document.createElement("div");
  body.className = "message-body";
  const head = document.createElement("div");
  head.className = "message-head";
  const title = document.createElement("strong");
  title.textContent = displayName(message);
  const time = document.createElement("span");
  time.textContent = [message.model, phaseName(message.phase, message.round), new Date(message.at).toLocaleTimeString("ko-KR", {hour:"2-digit",minute:"2-digit"})].filter(Boolean).join(" · ");
  head.append(title, time);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = message.content;
  body.append(head, bubble);
  if (message.warning) {
    const warning = document.createElement("div");
    warning.className = "warning";
    warning.textContent = message.warning;
    body.append(warning);
  }
  article.append(avatar, body);
  return article;
}

function renderRoles(roles) {
  const signature = JSON.stringify(roles || {});
  if (signature === lastRoleSignature) return;
  lastRoleSignature = signature;
  const list = $("roleList");
  list.replaceChildren();
  if (!Object.keys(roles || {}).length) {
    list.textContent = "연구 시작 후 네 모델이 역할을 협의합니다.";
    return;
  }
  for (const provider of PROVIDERS) {
    const item = document.createElement("div");
    item.className = "role-item";
    const title = document.createElement("strong");
    title.textContent = LABELS[provider];
    const content = document.createElement("span");
    content.textContent = roles[provider] || "아직 결정되지 않음";
    item.append(title, content);
    list.append(item);
  }
}

async function showTurn(turn) {
  try {
    const response = await fetch("/api/turn/" + turn, {cache:"no-store"});
    const detail = await response.json();
    if (!response.ok) throw new Error(detail.error || "호출 내용을 읽지 못했습니다.");
    selectedTurn = turn;
    selectedTurnStatus = detail.status;
    $("activityDetail").hidden = false;
    $("detailTitle").textContent = `${turn}번째 호출 · ${LABELS[detail.provider]} · ${LABELS[detail.account]} 계정`;
    $("detailPrompt").textContent = detail.prompt;
    $("detailResponse").textContent = detail.response || (detail.status === "waiting" ? "모델의 응답을 기다리는 중입니다." : detail.error || "응답 없음");
    $("detailRaw").textContent = detail.raw_response || "원형 응답이 아직 없습니다.";
  } catch (error) { toast(error.message, true); }
}

function renderActivities(activities) {
  const signature = JSON.stringify(activities || []);
  if (signature === lastActivitySignature) return;
  lastActivitySignature = signature;
  const list = $("activityList");
  list.replaceChildren();
  if (!activities.length) {
    list.textContent = "아직 호출 기록이 없습니다.";
    $("activityDetail").hidden = true;
    selectedTurn = 0;
    return;
  }
  for (const activity of [...activities].reverse()) {
    const row = document.createElement("div");
    row.className = "activity-item";
    const title = document.createElement("strong");
    title.textContent = `#${activity.turn} ${LABELS[activity.provider]} · ${phaseName(activity.phase, activity.round)} · ${LABELS[activity.account]} 계정`;
    const status = document.createElement("span");
    status.className = "activity-pill " + activity.status;
    status.textContent = {waiting:"응답 대기",completed:"완료",failed:"실패"}[activity.status] || activity.status;
    title.append(status);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "프롬프트·응답 보기";
    button.addEventListener("click", () => showTurn(activity.turn));
    const meta = document.createElement("small");
    const usage = activity.usage ? ` · 사용량 ${JSON.stringify(activity.usage)}` : "";
    meta.textContent = `${activity.model} · ${activity.started_at}${activity.latency_seconds !== undefined ? " · " + activity.latency_seconds + "초" : ""}${usage}${activity.error ? " · " + activity.error : ""}`;
    row.append(title, button, meta);
    list.append(row);
  }
  const chosen = activities.find((activity) => activity.turn === selectedTurn);
  if (chosen && chosen.status !== selectedTurnStatus) showTurn(selectedTurn);
}

function render(state) {
  selfActor = state.self_actor || "user";
  const active = ["running", "paused"].includes(state.status);
  const connected = state.connected;
  const accounts = state.accounts || {};
  const accountSignature = JSON.stringify(accounts);
  if (accountSignature !== lastAccountSignature || active) {
    if (active && state.assignments) {
      for (const provider of PROVIDERS) $("account-" + provider).value = state.assignments[provider] || $("account-" + provider).value;
    } else if (accountSignature !== lastAccountSignature) {
      const picked = chooseAssignment(state);
      for (const provider of PROVIDERS) $("account-" + provider).value = picked[provider];
    }
    updateModelChoices(state);
    lastAccountSignature = accountSignature;
  }
  for (const provider of PROVIDERS) {
    $("account-" + provider).disabled = active;
    $("model-" + provider).disabled = active || !availableFor(state, $("account-" + provider).value, provider).length;
  }
  const names = {idle:"대기 중",running:"진행 중",paused:"일시정지",stopping:"중지 중",stopped:"중지됨",completed:"완료",failed:"오류"};
  $("statusBadge").textContent = names[state.status] || state.status;
  $("statusBadge").className = "status-badge " + state.status;
  const connectedCount = ACCOUNTS.filter((actor) => accounts[actor]?.connected).length;
  $("connectionStatus").textContent = `● BAZE ${connectedCount}/${ACCOUNTS.length} 연결`;
  $("connectionStatus").className = "connection-status" + (connected ? " ok" : "");
  for (const actor of ACCOUNTS) {
    $(actor + "Connection").textContent = LABELS[actor] + " · " + (accounts[actor]?.connected ? "연결됨" : "연결 전");
    $(actor + "Connection").classList.toggle("ready", !!accounts[actor]?.connected);
  }
  $("keyHelp").textContent = `이 화면에서 연결한 키는 ${LABELS[selfActor]} 계정에만 등록됩니다. 키는 서버 메모리에 보관되며 상대에게 표시되지 않습니다.`;
  $("connectBtn").disabled = active || state.status === "stopping" || requestBusy;
  $("disconnectBtn").disabled = !accounts[selfActor]?.connected || active || state.status === "stopping" || requestBusy;
  $("apiKey").disabled = active || state.status === "stopping";
  $("topicTitle").textContent = state.topic || "모델들이 역할과 연구 주제를 선정합니다";
  $("questionText").textContent = state.question || "네 모델이 먼저 역할을 협의하고 AI 분야의 주제를 선정합니다.";
  $("phaseText").textContent = phaseName(state.phase, state.round) || "준비";
  $("turnText").textContent = `${state.messages.filter((m) => m.actor === "model").length} / ${state.rounds ? 8 + state.rounds * 4 : 0} 발언`;
  const assignment = currentAssignment();
  const countValid = new Set(PROVIDERS.map((provider) => assignment[provider])).size === ACCOUNTS.length;
  const providerValid = assignmentValid(state, assignment);
  const modelsValid = PROVIDERS.every((provider) => !!$("model-" + provider).value);
  $("assignmentStatus").textContent = !connected ? "네 사람이 각자 키를 연결해야 합니다." : !countValid ? "각 사람이 정확히 한 모델을 맡아야 합니다." : !providerValid ? "선택한 계정에서 사용할 수 없는 모델이 있습니다." : "네 사람에게 모델 하나씩 배정 완료";
  $("assignmentStatus").className = "assignment-status " + (providerValid && modelsValid ? "valid" : "invalid");
  $("startBtn").disabled = !connected || active || state.status === "stopping" || !providerValid || !modelsValid;
  $("pauseBtn").disabled = state.status !== "running";
  $("resumeBtn").disabled = state.status !== "paused";
  $("stopBtn").disabled = !active;
  $("messageInput").disabled = !active;
  $("sendBtn").disabled = !active;
  $("projectPath").textContent = state.project || "연구 시작 후 생성됩니다.";
  $("copyPathBtn").disabled = !state.project;
  $("downloadBtn").disabled = !state.project;
  for (const id of ["datasetFile","uploadBtn","sourceTitle","sourceUrl","sourceNote","sourceBtn"]) $(id).disabled = !active;
  const datasets = $("datasetList");
  datasets.replaceChildren();
  if (!state.datasets.length) {
    const item = document.createElement("li"); item.textContent = "아직 추가된 자료가 없습니다."; datasets.append(item);
  } else for (const name of state.datasets) {
    const item = document.createElement("li"); item.textContent = name; datasets.append(item);
  }
  const messages = state.messages;
  const newest = messages.length ? messages[messages.length - 1].id : "";
  if (newest !== lastMessageId || (!newest && !$("timeline").querySelector(".empty-state"))) {
    const timeline = $("timeline");
    timeline.replaceChildren(...messages.map(makeMessage));
    if (!messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = '<span>✦</span><h1>연구 대화를 시작해 보세요</h1><p>연구 설정에서 네 사람이 BAZE 키를 연결하면 네 모델이 역할과 주제를 정하고 차례로 토론합니다.</p><button class="text-action" data-open="settings">연구 설정 열기 →</button>';
      empty.querySelector("[data-open]").addEventListener("click", () => openTab("settings"));
      timeline.append(empty);
    }
    timeline.scrollTop = timeline.scrollHeight;
    lastMessageId = newest;
  }
  renderRoles(state.roles);
  renderActivities(state.activities || []);
  if (state.error && state.error !== lastError) toast(state.error, true);
  lastError = state.error;
}

async function refresh() {
  try {
    const response = await fetch("/api/state", {cache:"no-store"});
    if (!response.ok) throw new Error("서버 상태를 읽지 못했습니다.");
    render(await response.json());
  } catch (error) { toast(error.message, true); }
}

for (const provider of PROVIDERS) $("account-" + provider).addEventListener("change", async () => {
  try {
    const response = await fetch("/api/state", {cache:"no-store"});
    if (response.ok) {
      const state = await response.json();
      updateModelChoices(state);
      render(state);
    }
  } catch { /* 다음 자동 새로고침에서 반영 */ }
});

$("connectBtn").addEventListener("click", async () => {
  if (requestBusy) return;
  requestBusy = true;
  $("connectBtn").disabled = true;
  try {
    await post("/api/connect", {key:$("apiKey").value});
    $("apiKey").value = "";
    lastAccountSignature = "";
    toast("내 키와 사용 가능한 모델을 확인했습니다.");
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { $("connectBtn").disabled = false; requestBusy = false; }
});

$("disconnectBtn").addEventListener("click", async () => {
  if (requestBusy) return;
  requestBusy = true;
  $("disconnectBtn").disabled = true;
  try {
    await post("/api/disconnect");
    $("apiKey").value = "";
    lastAccountSignature = "";
    toast("내 키 연결을 해제했습니다.");
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { requestBusy = false; }
});

$("startBtn").addEventListener("click", async () => {
  const models = Object.fromEntries(PROVIDERS.map((provider) => [provider, $("model-" + provider).value]));
  try {
    await post("/api/start", {rounds:Number($("rounds").value),models,assignments:currentAssignment(),step_mode:$("stepMode").checked});
    toast("역할 협의를 시작했습니다.");
    openTab("chat");
    await refresh();
  } catch (error) { toast(error.message, true); }
});

$("messageForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = $("messageInput").value.trim();
  if (!content) return;
  try { await post("/api/intervene", {content}); $("messageInput").value = ""; await refresh(); }
  catch (error) { toast(error.message, true); }
});
$("messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("messageForm").requestSubmit(); }
});

for (const action of ["pause","resume","stop"]) $(action + "Btn").addEventListener("click", async () => {
  try { await post("/api/" + action); await refresh(); }
  catch (error) { toast(error.message, true); }
});

$("copyPathBtn").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("projectPath").textContent); toast("프로젝트 경로를 복사했습니다."); }
  catch { toast("경로를 선택해 직접 복사하세요.", true); }
});
$("downloadBtn").addEventListener("click", () => window.location.assign("/api/archive"));

$("uploadBtn").addEventListener("click", async () => {
  const file = $("datasetFile").files[0];
  if (!file) { toast("파일을 먼저 선택하세요.", true); return; }
  if (file.size > 2_000_000) { toast("2MB 이하 파일만 올릴 수 있습니다.", true); return; }
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
    });
    await post("/api/upload", {filename:file.name,content:String(dataUrl).split(",",2)[1]});
    $("datasetFile").value = "";
    toast("자료를 저장했습니다. 다음 발언에 반영됩니다."); await refresh();
  } catch (error) { toast(error.message, true); }
});

$("sourceBtn").addEventListener("click", async () => {
  try {
    await post("/api/source", {title:$("sourceTitle").value,url:$("sourceUrl").value,note:$("sourceNote").value});
    for (const id of ["sourceTitle","sourceUrl","sourceNote"]) $(id).value = "";
    toast("출처를 기록했습니다."); await refresh();
  } catch (error) { toast(error.message, true); }
});

refresh();
setInterval(refresh, 1200);

