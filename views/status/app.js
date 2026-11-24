const bridge = window.AstrBotPluginView;

const els = {
  site: document.getElementById("site-label"),
  updated: document.getElementById("updated-label"),
  connection: document.getElementById("connection-pill"),
  refresh: document.getElementById("refresh-button"),
  retry: document.getElementById("retry-button"),
  autoRefresh: document.getElementById("auto-refresh"),
  errorBanner: document.getElementById("error-banner"),
  errorText: document.getElementById("error-text"),
  empty: document.getElementById("empty-state"),
  emptyMessage: document.getElementById("empty-message"),
  summaryGrid: document.getElementById("summary-grid"),
  summaryProjects: document.getElementById("summary-projects"),
  summaryMonitors: document.getElementById("summary-monitors"),
  summaryUp: document.getElementById("summary-up"),
  summaryDown: document.getElementById("summary-down"),
  summaryPending: document.getElementById("summary-pending"),
  summaryMaintenance: document.getElementById("summary-maintenance"),
  summaryUnknown: document.getElementById("summary-unknown"),
  toolbar: document.getElementById("toolbar"),
  projectFilter: document.getElementById("project-filter"),
  loadingHint: document.getElementById("loading-hint"),
  skeleton: document.getElementById("skeleton"),
  projectList: document.getElementById("project-list"),
  settings: document.getElementById("settings-content"),
};

const state = {
  data: null,
  selectedProjects: "",
  autoTimer: null,
  loading: false,
};

const MODE_LABELS = {
  text: "文本",
  image: "图片",
};

const ACCESS_LABELS = {
  whitelist: "白名单模式",
  blacklist: "黑名单模式",
};

const SCOPE_LABELS = {
  all: "全局生效",
  include: "仅指定聊天流生效",
  exclude: "指定聊天流不生效",
  none: "全局不生效",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined && text !== null) {
    element.textContent = String(text);
  }
  return element;
}

function clear(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
}

function setConnection(kind, text) {
  els.connection.className = `pill pill--${kind}`;
  els.connection.textContent = text;
}

function showError(message) {
  els.errorText.textContent = message;
  els.errorBanner.hidden = false;
}

function hideError() {
  els.errorBanner.hidden = true;
  els.errorText.textContent = "";
}

function renderSummary(summary) {
  const value = summary || {};
  els.summaryProjects.textContent = String(value.projects ?? 0);
  els.summaryMonitors.textContent = String(value.monitors ?? 0);
  els.summaryUp.textContent = String(value.up ?? 0);
  els.summaryDown.textContent = String(value.down ?? 0);
  els.summaryPending.textContent = String(value.pending ?? 0);
  els.summaryMaintenance.textContent = String(value.maintenance ?? 0);
  els.summaryUnknown.textContent = String(value.unknown ?? 0);
}

function renderMonitor(monitor) {
  const row = node("div", "monitor");
  row.appendChild(
    node("span", `status-dot ${monitor.status_class || "unknown"}`),
  );

  const name = node("span", "monitor-name");
  if (monitor.tag) {
    name.appendChild(node("span", "tag", monitor.tag));
  }
  name.appendChild(document.createTextNode(String(monitor.name || "")));
  row.appendChild(name);

  const stateText = [monitor.icon, monitor.label].filter(Boolean).join(" ");
  row.appendChild(
    node(
      "span",
      `monitor-state ${monitor.status_class || "unknown"}`,
      stateText || "未知",
    ),
  );
  if (monitor.ping) {
    row.appendChild(node("span", "monitor-ping", monitor.ping));
  }
  return row;
}

function renderGroup(group) {
  const section = node("section", "group");
  if (group.name) {
    section.appendChild(node("h3", "group-title", group.name));
  }
  const list = node("div", "monitor-list");
  for (const monitor of group.monitors || []) {
    list.appendChild(renderMonitor(monitor));
  }
  section.appendChild(list);
  return section;
}

function renderIncident(incident) {
  const item = node(
    "div",
    `notice-item ${incident.status_class || "info"}`,
  );
  const head = node("div", "notice-head");
  head.appendChild(
    node("span", "notice-badge", incident.label || "通知"),
  );
  head.appendChild(
    node("span", "notice-title", incident.title || "无标题"),
  );
  item.appendChild(head);
  if (incident.content) {
    item.appendChild(node("div", "notice-content", incident.content));
  }
  if (incident.updated) {
    item.appendChild(
      node("div", "notice-time", `更新于 ${incident.updated}`),
    );
  }
  return item;
}

function renderMaintenance(item) {
  const wrapper = node("div", "notice-item maintenance");
  const head = node("div", "notice-head");
  head.appendChild(node("span", "notice-badge", "维护"));
  head.appendChild(node("span", "notice-title", item.title || "无标题"));
  wrapper.appendChild(head);
  if (item.description) {
    wrapper.appendChild(node("div", "notice-content", item.description));
  }
  if (item.time) {
    wrapper.appendChild(node("div", "notice-time", item.time));
  }
  return wrapper;
}

function renderProject(project) {
  const card = node("article", "card project-card");
  const head = node("header", "project-head");

  const titleWrap = node("div", "project-title-wrap");
  titleWrap.appendChild(
    node("h2", "project-title", project.title || project.slug || "未命名项目"),
  );
  titleWrap.appendChild(node("p", "project-slug", project.slug || ""));
  head.appendChild(titleWrap);

  const chips = node("div", "chip-row");
  for (const stat of project.stats || []) {
    chips.appendChild(
      node(
        "span",
        `chip chip--${stat.status_class || "unknown"}`,
        [stat.icon, stat.label, stat.count].filter(Boolean).join(" "),
      ),
    );
  }
  head.appendChild(chips);
  card.appendChild(head);

  if (project.error) {
    card.appendChild(node("p", "project-error", project.error));
    return card;
  }

  for (const group of project.groups || []) {
    card.appendChild(renderGroup(group));
  }

  if ((project.incidents || []).length) {
    const block = node("section", "notice-block");
    block.appendChild(node("h3", null, "置顶通知"));
    for (const incident of project.incidents) {
      block.appendChild(renderIncident(incident));
    }
    card.appendChild(block);
  }

  if ((project.maintenance || []).length) {
    const block = node("section", "notice-block");
    block.appendChild(node("h3", null, "维护公告"));
    for (const item of project.maintenance) {
      block.appendChild(renderMaintenance(item));
    }
    card.appendChild(block);
  }

  return card;
}

function renderProjects(projects) {
  clear(els.projectList);
  if (!projects.length) {
    els.projectList.appendChild(
      node("p", "muted", "没有可展示的项目。"),
    );
    return;
  }
  for (const project of projects) {
    els.projectList.appendChild(renderProject(project));
  }
}

function settingsItem(title, valueBuilder) {
  const item = node("div", "settings-item");
  item.appendChild(node("h3", null, title));
  item.appendChild(valueBuilder());
  return item;
}

function renderSettings(settings) {
  const config = settings || {};
  clear(els.settings);

  els.settings.appendChild(
    settingsItem("默认输出方式", () =>
      node(
        "div",
        "settings-value",
        MODE_LABELS[config.default_output_mode] ||
          config.default_output_mode ||
          "未设置",
      ),
    ),
  );

  els.settings.appendChild(
    settingsItem("黑白名单模式", () =>
      node(
        "div",
        "settings-value",
        ACCESS_LABELS[config.access_mode] || config.access_mode || "未设置",
      ),
    ),
  );

  els.settings.appendChild(
    settingsItem("默认查询项", () => {
      const targets = config.default_targets || [];
      return node(
        "div",
        "settings-value",
        targets.length ? targets.join("、") : "未设置",
      );
    }),
  );

  els.settings.appendChild(
    settingsItem("会话查询项", () => {
      const entries = config.session_targets || [];
      if (!entries.length) {
        return node("div", "settings-value", "未设置");
      }
      const list = node("ul", "settings-list");
      for (const entry of entries) {
        const targets = (entry.targets || []).join("、") || "未设置目标";
        list.appendChild(
          node(
            "li",
            null,
            `${entry.session || "未知会话"} → ${targets}`,
          ),
        );
      }
      return list;
    }),
  );

  els.settings.appendChild(
    settingsItem("关键词规则", () => {
      const rules = config.keyword_rules || [];
      if (!rules.length) {
        return node("div", "settings-value", "未设置");
      }
      const list = node("ul", "settings-list");
      for (const rule of rules) {
        const targets = (rule.targets || []).join("、") || "未设置目标";
        const mode =
          rule.output_mode === "default"
            ? "跟随全局"
            : MODE_LABELS[rule.output_mode] || rule.output_mode;
        const scopeLabel =
          SCOPE_LABELS[rule.scope_mode] || rule.scope_mode || "全局生效";
        const scope =
          rule.scope_mode === "include" || rule.scope_mode === "exclude"
            ? `${scopeLabel}（${rule.scope_count ?? 0} 个）`
            : scopeLabel;
        list.appendChild(
          node(
            "li",
            null,
            `${rule.keyword || "未命名关键词"} → ${targets}（${mode}；${scope}）`,
          ),
        );
      }
      return list;
    }),
  );

  els.settings.appendChild(
    settingsItem("名单数量", () => {
      const parts = [
        `用户白名单 ${config.user_whitelist ?? 0}`,
        `用户黑名单 ${config.user_blacklist ?? 0}`,
        `群聊白名单 ${config.group_whitelist ?? 0}`,
        `群聊黑名单 ${config.group_blacklist ?? 0}`,
      ];
      return node("div", "settings-value", parts.join("\n"));
    }),
  );
}

function populateProjectFilter(available, selected) {
  const select = els.projectFilter;
  const previous = state.selectedProjects;
  clear(select);
  select.appendChild(new Option("全部项目", ""));
  for (const slug of available || []) {
    select.appendChild(new Option(slug, slug));
  }

  let desired = "";
  if ((selected || []).length === 1) {
    desired = selected[0];
  } else if (previous && (available || []).includes(previous)) {
    desired = previous;
  }
  select.value = desired;
  state.selectedProjects = desired;
}

function render(data) {
  els.site.textContent = data.site || "未配置站点";
  els.updated.textContent = data.generated_at
    ? `更新于 ${data.generated_at}`
    : "尚未刷新";
  renderSummary(data.summary);
  renderSettings(data.settings);

  const configured = Boolean(data.configured);
  els.empty.hidden = configured;
  els.summaryGrid.hidden = !configured;
  els.toolbar.hidden = !configured;
  els.projectList.hidden = !configured;

  if (!configured) {
    els.emptyMessage.textContent =
      data.message || "请先在插件配置中填写 Uptime Kuma 地址与项目。";
    els.projectList.hidden = true;
    clear(els.projectList);
    setConnection("idle", "未配置");
    return;
  }

  setConnection("ok", "已连接");
  populateProjectFilter(data.available_projects, data.selected_projects);
  renderProjects(data.projects || []);
}

async function loadOverview() {
  if (state.loading) {
    return;
  }
  state.loading = true;
  els.refresh.disabled = true;
  els.loadingHint.hidden = false;
  if (!state.data) {
    els.skeleton.hidden = false;
  }

  try {
    const params = {};
    if (state.selectedProjects) {
      params.projects = state.selectedProjects;
    }
    const data = await bridge.apiGet("overview", params);
    state.data = data;
    hideError();
    render(data);
  } catch (error) {
    const message =
      error && error.message ? error.message : String(error || "未知错误");
    showError(message);
    setConnection("error", "请求失败");
  } finally {
    state.loading = false;
    els.refresh.disabled = false;
    els.loadingHint.hidden = true;
    els.skeleton.hidden = true;
  }
}

function applyAutoRefresh(seconds) {
  if (state.autoTimer) {
    clearInterval(state.autoTimer);
    state.autoTimer = null;
  }
  if (seconds > 0) {
    state.autoTimer = setInterval(() => {
      if (!document.hidden) {
        loadOverview();
      }
    }, seconds * 1000);
  }
}

function applyContext(context) {
  if (context && context.pageTitle) {
    document.title = context.pageTitle;
  }
}

function bindEvents() {
  els.refresh.addEventListener("click", loadOverview);
  els.retry.addEventListener("click", loadOverview);

  els.projectFilter.addEventListener("change", () => {
    state.selectedProjects = els.projectFilter.value;
    loadOverview();
  });

  els.autoRefresh.addEventListener("change", () => {
    const seconds = Number(els.autoRefresh.value) || 0;
    applyAutoRefresh(seconds);
  });

  window.addEventListener("beforeunload", () => {
    if (state.autoTimer) {
      clearInterval(state.autoTimer);
      state.autoTimer = null;
    }
  });
}

async function init() {
  bindEvents();
  if (!bridge || typeof bridge.apiGet !== "function") {
    showError("Bridge SDK 未加载，请从插件详情页打开本页面。");
    setConnection("error", "未连接");
    return;
  }
  try {
    const context = await bridge.ready();
    applyContext(context);
    if (typeof bridge.onContext === "function") {
      bridge.onContext(applyContext);
    }
  } catch (error) {
    showError("无法连接到 AstrBot WebUI，请刷新页面后重试。");
    setConnection("error", "未连接");
    return;
  }
  await loadOverview();
}

init();
