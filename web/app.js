const $ = (id) => document.getElementById(id);
const PROVIDERS = ["gpt", "claude", "gemini", "grok"];
const ACCOUNTS = ["user", "friend", "member3", "member4"];
const LABELS = {gpt:"GPT",claude:"Claude",gemini:"Gemini",grok:"Grok",user:"1415",friend:"1314",member3:"1410",member4:"1411"};
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
let csrfToken = "";
let latestState = null;
let overviewSignature = "";
let overviewBusy = false;
let overviewLastAttempt = 0;

$('logoutBtn').addEventListener('click', async () => {
  const response = await fetch('/logout', {method:'POST',headers:{'X-RE-Lab-CSRF':csrfToken}});
  if (response.ok) location.replace('/login');
  else toast('로그아웃하지 못했습니다. 다시 시도하세요.', true);
});

function openTab(name) {
  for (const section of ["chat", "overview", "activity", "files", "settings"]) $(section + "Panel").hidden = section !== name;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  if (name === "overview") void refreshOverview(true);
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
  const response = await fetch(path, {method:"POST",headers:{"Content-Type":"application/json","X-RE-Lab-CSRF":csrfToken},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "요청에 실패했습니다.");
  return result;
}

function setSelect(provider, options, preferred, fallback) {
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
    el.value = options.includes(preferred) ? preferred : options.includes(fallback) ? fallback : options[0];
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
    const options = [...availableFor(state, account, provider)];
    if (state.assignments?.[provider] && preferred && !options.includes(preferred)) options.push(preferred);
    setSelect(provider, options, preferred, state.defaults?.[provider]);
  }
}

function displayName(message) {
  if (message.actor === selfActor) return "나";
  if (message.actor === "system") return "연구실";
  if (message.actor === "model") return LABELS[message.provider] || message.provider;
  return LABELS[message.actor] || message.actor;
}

function phaseName(phase, round) {
  const names = {role_selection:"역할 협의",topic_selection:"주제 선정",topic_proposal:"독립 주제 제안",topic_critique:"후보 비판",
    topic_ballot:"주제 순위 투표",role_trial:"공통 작업 표본",role_review:"역할 적합성 평가",simulation_design:"수식 시뮬레이션 설계",
    topic_proposals:"독립 주제 제안",topic_critiques:"후보 비판",topic_ballots:"주제 순위 투표",role_trials:"공통 작업 표본",role_reviews:"역할 적합성 평가",research:`토론 ${round}라운드`,
    roles:"역할 협의",topic:"주제 선정",plan_discussion:"연구 계획 토론",plan_report:"연구계획보고서",plan_slides:"계획발표 PPT",
    plan_script:"계획발표 대본",plan_review:"계획 자료 검토",experiment_discussion:"실험 설계 토론",experiment_cases:"실험 사례 생성",
    experiment_run:"실제 모델 실험",experiment_analysis:"실험 결과 분석",middle_slides:"중간발표 PPT",middle_script:"중간발표 대본",
    middle_review:"중간 자료 검토",final_discussion:"최종 검증 토론",final_report:"최종보고서",final_slides:"최종발표 PPT",
    final_script:"최종발표 대본",final_review:"최종 자료 검토",completed:"연구 완료"};
  return names[phase] || "";
}

function overviewElement(tag, content, className = "") {
  const element = document.createElement(tag);
  element.textContent = content;
  if (className) element.className = className;
  return element;
}

function overviewTime(value) {
  if (!value) return "";
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString("ko-KR", {timeZone:"Asia/Seoul", dateStyle:"medium", timeStyle:"short"});
}

function overviewList(target, items, empty) {
  target.replaceChildren();
  if (!items.length) { target.append(overviewElement("p", empty, "overview-empty")); return; }
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "overview-event";
    row.append(overviewElement("span", [item.actor ? LABELS[item.actor] || item.actor : "연구실", overviewTime(item.at)].filter(Boolean).join(" · "), "overview-event-meta"));
    row.append(overviewElement("p", item.text));
    target.append(row);
  }
}

function renderOverview(data) {
  const counts = data.counts || {};
  const topic = data.topic || "연구 주제 선정 전";
  const question = data.question ? ` 연구 질문은 ‘${data.question}’입니다.` : "";
  const discussion = (data.sections || []).map((section) => `${section.title} ${section.count}건`).join(" · ");
  $("overviewSummary").textContent = `연구 주제: ${topic}.${question} 현재 ${phaseName(data.current?.stage) || "준비"} 단계입니다. 저장된 전체 대화 ${counts.all || 0}건 중 AI 발언 ${counts.models || 0}건과 참여자 발언 ${counts.people || 0}건을 확인했습니다.${discussion ? ` 단계별 AI 발언: ${discussion}.` : ""}`;
  const stats = $("overviewStats");
  stats.replaceChildren();
  for (const [value, label] of [[counts.models || 0,"AI 발언"],[counts.people || 0,"참여자 발언"],[data.call_count || 0,"API 호출"],[data.current?.observation_count || 0,"실제 실험 응답"]]) {
    const box = document.createElement("div");
    box.append(overviewElement("strong", String(value)), overviewElement("span", label));
    stats.append(box);
  }
  $("overviewCoverage").textContent = data.first_at ? `전체 저장 대화 기준 · ${overviewTime(data.first_at)}부터 ${overviewTime(data.last_at)}까지` : "아직 저장된 대화가 없습니다.";
  const current = data.current || {};
  $("overviewStage").textContent = `${phaseName(current.stage) || "준비"} · ${({running:"자동 진행 중",waiting_budget:"크레딧 보충 대기",waiting_retry:"연결 재시도 대기",waiting_review:"참여자 검토 대기",paused:"일시정지",completed:"완료",stopped:"중지",failed:"오류",idle:"대기"})[current.status] || current.status || "대기"}`;
  const next = current.provider ? ` ${LABELS[current.provider]}${current.status === "running" ? "가 담당합니다." : " 차례입니다."}` : "";
  $("overviewTask").textContent = (current.task || "") + next;
  $("overviewReason").textContent = [current.reason, current.status === "waiting_budget" && current.next_due_at ? `다음 잔액 확인: ${overviewTime(current.next_due_at)}` : "", current.status === "waiting_retry" && current.next_due_at ? `다음 연결 재시도 예약: ${overviewTime(current.next_due_at)} 이후 정기 실행` : ""].filter(Boolean).join(" · ");
  const roles = $("overviewRoles");
  roles.replaceChildren();
  for (const role of data.roles || []) {
    const card = document.createElement("article");
    card.className = `overview-role ${role.provider}`;
    const heading = document.createElement("div");
    heading.append(overviewElement("strong", LABELS[role.provider] || role.provider), overviewElement("span", role.state, "overview-role-state"));
    card.append(heading, overviewElement("p", role.role), overviewElement("small", [role.model || "모델 미선택", role.account ? `${role.account} 계정` : "담당 계정 미정"].join(" · ")));
    roles.append(card);
  }
  const sections = $("overviewSections");
  sections.replaceChildren();
  if (!data.sections?.length) sections.append(overviewElement("p", "아직 모델 대화가 없습니다.", "overview-empty"));
  for (const section of data.sections || []) {
    const card = document.createElement("article");
    card.className = "overview-section";
    card.append(overviewElement("h3", `${section.title} · AI 발언 ${section.count}건`));
    if (!section.highlights?.length) card.append(overviewElement("p", "실제 실험 응답은 활동 기록에서 사례별로 확인할 수 있습니다.", "overview-empty"));
    for (const highlight of section.highlights || []) {
      const row = document.createElement("p");
      row.append(overviewElement("strong", `${LABELS[highlight.provider] || highlight.provider} · `), document.createTextNode(highlight.text));
      card.append(row);
    }
    sections.append(card);
  }
  overviewList($("overviewMilestones"), data.milestones || [], "아직 기록된 진행 결정이 없습니다.");
  overviewList($("overviewHuman"), data.human_input || [], "아직 참여자 의견이 없습니다.");
  const reviews = data.reviews || [];
  if (reviews.length) $("overviewHuman").prepend(overviewElement("p", `검토 기록 ${reviews.length}건 · 승인 ${reviews.filter((review) => review.approved).length}건 · 수정 요청 ${reviews.filter((review) => !review.approved).length}건`, "overview-review-count"));
}

function overviewKey(state) {
  const activities = state.activities || [];
  const last = activities[activities.length - 1];
  return JSON.stringify([state.project,state.status,state.phase,state.current_model,state.topic,state.question,
    state.workflow?.stage,state.workflow?.reason,state.workflow?.next_due_at,state.workflow?.reviews?.length,
    activities.length,last?.status,state.messages?.at(-1)?.id,state.roles]);
}

async function refreshOverview(force = false) {
  if ($("overviewPanel").hidden || !latestState || overviewBusy) return;
  const signature = overviewKey(latestState);
  if (!force && (signature === overviewSignature || Date.now() - overviewLastAttempt < 15000)) return;
  overviewBusy = true;
  overviewLastAttempt = Date.now();
  try {
    const response = await fetch("/api/overview", {cache:"no-store"});
    if (!response.ok) throw new Error("연구 요약을 읽지 못했습니다.");
    renderOverview(await response.json());
    overviewSignature = signature;
  } catch (error) { $("overviewSummary").textContent = error.message; }
  finally { overviewBusy = false; }
}

$("overviewRefreshBtn").addEventListener("click", () => refreshOverview(true));

function renderWorkflow(state) {
  const flow = state.workflow || {};
  $("workflowStatus").textContent = flow.stage ? `${phaseName(flow.stage)} · 실제 BAZE 관찰 ${flow.observation_count || 0}건 · 실험 대기 ${flow.remaining_experiment_calls || 0}건` : "연구 시작 후 계획·실험·중간·최종 발표 단계가 표시됩니다.";
  const checks = flow.daily_checks || [];
  const latest = checks[checks.length - 1];
  $("budgetStatus").textContent = flow.reason || (latest ? `${LABELS[latest.account]} 최근 월간 잔액 ${latest.monthly_remaining} 크레딧 · ${latest.at}` : "모델 호출 전에 담당 계정 잔액을 조회합니다.");
  const review = state.status === "waiting_review";
  $("reviewBox").hidden = !review;
  if (review) $("reviewPrompt").textContent = `${phaseName(flow.stage)}: 공유 자료 탭에서 보고서·PPT·대본을 내려받아 확인하세요. 네 사람 모두 승인하거나 수정 요청을 남길 수 있습니다.`;
  const list = $("deliverableList");
  list.replaceChildren();
  if (!state.deliverables?.length) { list.textContent = "아직 생성된 자료가 없습니다."; return; }
  for (const item of state.deliverables) {
    const link = document.createElement("a");
    link.href = "/api/file?path=" + encodeURIComponent(item.path);
    link.textContent = `${item.label} (${Math.ceil(item.bytes / 1024)} KB)`;
    link.className = "deliverable-link";
    list.append(link);
  }
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
    status.textContent = {waiting:"응답 대기",completed:"완료",failed:"실패",interrupted:"재시작으로 중단"}[activity.status] || activity.status;
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
  latestState = state;
  selfActor = state.self_actor || "user";
  csrfToken = state.csrf_token || "";
  $('logoutBtn').hidden = !state.cloud;
  const active = ["running", "paused", "waiting_review", "waiting_budget", "waiting_retry"].includes(state.status);
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
  const names = {idle:"대기 중",running:"자동 진행 중",paused:"일시정지",waiting_review:"검토 대기",waiting_budget:"잔액 보충 대기",waiting_retry:"연결 재시도 대기",stopping:"중지 중",stopped:"중지됨",completed:"완료",failed:"오류"};
  $("statusBadge").textContent = names[state.status] || state.status;
  $("statusBadge").className = "status-badge " + state.status;
  const connectedCount = ACCOUNTS.filter((actor) => accounts[actor]?.connected).length;
  const keyEditable = !["running", "stopping"].includes(state.status) && !(state.activities || []).some((item) => item.status === "waiting");
  $("connectionStatus").textContent = `● BAZE ${connectedCount}/${ACCOUNTS.length} 연결`;
  $("connectionStatus").className = "connection-status" + (connected ? " ok" : "");
  for (const actor of ACCOUNTS) {
    $(actor + "Connection").textContent = accounts[actor]?.connected ?
      (state.key_storage === "persistent" ? "영구 저장됨 · 키 값은 표시되지 않습니다" : "임시 연결됨 · 서버 재시작 시 사라집니다") : "연결 전";
    $(actor + "Connection").classList.toggle("ready", !!accounts[actor]?.connected);
    $("apiKey-" + actor).disabled = !keyEditable || requestBusy;
  }
  document.querySelectorAll(".connect-key").forEach((button) => button.disabled = !keyEditable || requestBusy);
  document.querySelectorAll(".disconnect-key").forEach((button) => button.disabled = !accounts[button.dataset.slot]?.connected || active || state.status === "stopping" || requestBusy);
  $("keyStorageStatus").textContent = state.key_storage === "persistent" ? "암호화해 외부 저장소에 보관 중 · 서버가 다시 시작되어도 자동 복원됩니다." : "임시 보관 중 · 영구 저장소 설정 전에는 서버 재시작 시 키가 사라집니다.";
  $("keyStorageStatus").classList.toggle("persistent", state.key_storage === "persistent");
  $("topicTitle").textContent = state.topic || "모델들이 연구 주제를 선정합니다";
  $("questionText").textContent = state.question || "AI·물리·수학·정보 후보를 비교하고 주제에 맞는 역할을 검증합니다.";
  $("phaseText").textContent = phaseName(state.phase, state.round) || "준비";
  $("turnText").textContent = `${state.activities?.length || 0}회 기록 · 필요에 따라 계속`;
  const assignment = currentAssignment();
  const countValid = new Set(PROVIDERS.map((provider) => assignment[provider])).size === ACCOUNTS.length;
  const providerValid = assignmentValid(state, assignment);
  const modelsValid = PROVIDERS.every((provider) => !!$("model-" + provider).value);
  $("assignmentStatus").textContent = !connected ? "네 칸에 키를 연결해야 합니다." : !countValid ? "각 칸이 정확히 한 모델을 맡아야 합니다." : !providerValid ? "선택한 계정에서 사용할 수 없는 모델이 있습니다." : "네 칸에 모델 하나씩 배정 완료";
  $("assignmentStatus").className = "assignment-status " + (providerValid && modelsValid ? "valid" : "invalid");
  $("startBtn").disabled = !connected || active || state.status === "stopping" || !providerValid || !modelsValid;
  $("restartBtn").disabled = !connected || !state.project || ["running", "stopping"].includes(state.status) ||
    (state.activities || []).some((item) => item.status === "waiting");
  $("pauseBtn").disabled = state.status !== "running";
  $("resumeBtn").disabled = !["paused", "waiting_retry"].includes(state.status);
  $("stepBtn").disabled = !["running", "waiting_budget", "waiting_retry"].includes(state.status);
  const swapReady = ["paused", "waiting_review", "waiting_budget", "waiting_retry"].includes(state.status) && !(state.activities || []).some((item) => item.status === "waiting");
  $("swapBtn").disabled = !swapReady || requestBusy;
  $("swapCurrent").textContent = `현재 모델: ${state.models?.[$("swapProvider").value] || "연구 시작 후 표시"}`;
  $("swapStatus").textContent = !state.project ? "연구 시작 후 사용할 수 있습니다." :
    state.status === "running" ? "일시정지를 누르고 현재 응답이 끝날 때까지 기다리세요." :
    ["paused", "waiting_review", "waiting_budget", "waiting_retry"].includes(state.status) && !swapReady ? "현재 모델 응답이 끝나면 교체할 수 있습니다." :
    swapReady ? "지금 교체할 수 있습니다. 다음 발언부터 적용됩니다." : "진행 중인 연구가 없습니다.";
  const history = state.model_changes || [];
  $("swapHistory").replaceChildren(...history.map((change) => {
    const item = document.createElement("p");
    item.textContent = `${change.at} · ${LABELS[change.provider]} · ${change.from} → ${change.to} · ${LABELS[change.actor]} · ${change.reason}`;
    return item;
  }));
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
      empty.innerHTML = '<span>✦</span><h1>연구 대화를 시작해 보세요</h1><p>연구 설정에서 네 칸의 BAZE 키를 연결하면 네 모델이 역할과 주제를 정하고 차례로 토론합니다.</p><button class="text-action" data-open="settings">연구 설정 열기 →</button>';
      empty.querySelector("[data-open]").addEventListener("click", () => openTab("settings"));
      timeline.append(empty);
    }
    timeline.scrollTop = timeline.scrollHeight;
    lastMessageId = newest;
  }
  renderRoles(state.roles);
  renderActivities(state.activities || []);
  renderWorkflow(state);
  void refreshOverview();
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

document.querySelectorAll(".connect-key").forEach((button) => button.addEventListener("click", async () => {
  if (requestBusy) return;
  const slot = button.dataset.slot;
  const input = $("apiKey-" + slot);
  requestBusy = true;
  button.disabled = true;
  try {
    await post("/api/connect", {slot, key:input.value});
    input.value = "";
    lastAccountSignature = "";
    toast(`${LABELS[slot]} 키를 연결하고 사용 가능한 모델을 확인했습니다.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { requestBusy = false; button.disabled = false; }
}));

document.querySelectorAll(".disconnect-key").forEach((button) => button.addEventListener("click", async () => {
  if (requestBusy) return;
  const slot = button.dataset.slot;
  if (!window.confirm(`${LABELS[slot]} 키를 저장소에서도 삭제할까요?`)) return;
  requestBusy = true;
  button.disabled = true;
  try {
    await post("/api/disconnect", {slot});
    $("apiKey-" + slot).value = "";
    lastAccountSignature = "";
    toast(`${LABELS[slot]} 키를 삭제했습니다.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { requestBusy = false; }
}));

$("startBtn").addEventListener("click", async () => {
  const models = Object.fromEntries(PROVIDERS.map((provider) => [provider, $("model-" + provider).value]));
  try {
    await post("/api/start", {rounds:null,models,assignments:currentAssignment(),step_mode:false});
    toast("역할 협의를 시작했습니다.");
    openTab("chat");
    await refresh();
  } catch (error) { toast(error.message, true); }
});

$("restartBtn").addEventListener("click", async () => {
  if (!window.confirm("이전 연구의 기록과 자료를 보존하고 새 연구를 처음부터 시작할까요? 현재 모델 응답이 진행 중이면 완료 후 다시 시도해야 합니다.")) return;
  try {
    await post("/api/restart", {});
    toast("이전 기록을 보존하고 새 연구를 시작했습니다.");
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

$("stepBtn").addEventListener("click", async () => {
  try { await post("/api/step"); toast("진행 가능한 연구 단계를 확인했습니다."); await refresh(); }
  catch (error) { toast(error.message, true); }
});

for (const [id, approved] of [["approveBtn", true], ["reviseBtn", false]]) $(id).addEventListener("click", async () => {
  const state = await (await fetch("/api/state", {cache:"no-store"})).json();
  try {
    await post("/api/review", {stage:state.workflow?.stage, approved, feedback:$("reviewFeedback").value});
    $("reviewFeedback").value = "";
    toast(approved ? "검토 승인을 기록했습니다." : "수정 요청을 기록했습니다.");
    await refresh();
  } catch (error) { toast(error.message, true); }
});

$("swapProvider").addEventListener("change", refresh);
$("swapBtn").addEventListener("click", async () => {
  try {
    const change = await post("/api/swap-model", {provider:$("swapProvider").value,
      model:$("swapModel").value.trim(),reason:$("swapReason").value.trim()});
    $("swapModel").value = "";
    $("swapReason").value = "";
    toast(`${LABELS[change.provider]} 모델을 ${change.to}로 교체했습니다.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
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

