/**
 * settings.js — 密码修改 + 通知设置 + 用户管理
 */
"use strict";

import { api, apiPost, apiPut, escapeHtml, showError, showSuccess, hasPermission, formatDate } from "../api.js";

export async function renderPasswordTab(container) {
  container.innerHTML = `
    <div class="settings-page">
      <h3>修改密码</h3>
      <form id="changePasswordForm" class="settings-form">
        <div class="form-field">
          <label>当前密码</label>
          <input type="password" id="currentPassword" autocomplete="current-password" required>
        </div>
        <div class="form-field">
          <label>新密码</label>
          <input type="password" id="newPassword" autocomplete="new-password" required minlength="6">
        </div>
        <div class="form-field">
          <label>确认新密码</label>
          <input type="password" id="confirmPassword" autocomplete="new-password" required>
        </div>
        <div id="passwordError" class="form-error" style="display:none;"></div>
        <div id="passwordSuccess" class="form-success" style="display:none;"></div>
        <button type="submit" class="btn-primary">修改密码</button>
      </form>
    </div>
  `;

  const form = document.getElementById("changePasswordForm");
  const errEl = document.getElementById("passwordError");
  const successEl = document.getElementById("passwordSuccess");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.style.display = "none";
    successEl.style.display = "none";

    const currentPw = document.getElementById("currentPassword").value;
    const newPw = document.getElementById("newPassword").value;
    const confirmPw = document.getElementById("confirmPassword").value;

    if (newPw !== confirmPw) {
      errEl.textContent = "两次输入的新密码不一致";
      errEl.style.display = "block";
      return;
    }
    if (newPw.length < 6) {
      errEl.textContent = "密码长度至少 6 个字符";
      errEl.style.display = "block";
      return;
    }

    try {
      await apiPost("/api/v1/auth/change-password", {}, {
        current_password: currentPw,
        new_password: newPw,
      });
      successEl.textContent = "密码修改成功";
      successEl.style.display = "block";
      form.reset();
    } catch (err) {
      errEl.textContent = err.message || "密码修改失败";
      errEl.style.display = "block";
    }
  });
}

export async function renderNotificationsTab(container) {
  container.innerHTML = `
    <div class="settings-page">
      <h3>通知设置</h3>
      <div class="loading-spinner"><div class="spinner"></div><p>加载中...</p></div>
    </div>
  `;

  let config;
  try {
    config = await api("/api/v1/settings/notifications");
  } catch (err) {
    showError("加载通知设置失败: " + err.message);
    return;
  }

  const ch = config.channels || {};
  const rules = config.rules || {};
  const qh = rules.quiet_hours || {};

  container.innerHTML = `
    <div class="settings-page">
      <h3>通知设置</h3>

      <div class="notif-section">
        <h4>邮件通知</h4>
        <div class="form-field">
          <label><input type="checkbox" id="emailEnabled" ${ch.email?.enabled ? "checked" : ""}> 启用</label>
        </div>
        <div class="form-field">
          <label>SMTP 服务器</label>
          <input type="text" id="emailSmtpHost" value="${escapeHtml(ch.email?.smtp_host || "")}" placeholder="smtp.gmail.com">
        </div>
        <div class="form-field">
          <label>SMTP 端口</label>
          <input type="number" id="emailSmtpPort" value="${ch.email?.smtp_port || 587}" min="1" max="65535">
        </div>
        <div class="form-field">
          <label>发件地址</label>
          <input type="email" id="emailFrom" value="${escapeHtml(ch.email?.from_address || "")}" placeholder="alerts@example.com">
        </div>
        <div class="form-field">
          <label>收件地址（逗号分隔）</label>
          <input type="text" id="emailTo" value="${escapeHtml((ch.email?.to_addresses || []).join(", "))}" placeholder="editor@example.com">
        </div>
      </div>

      <div class="notif-section">
        <h4>飞书通知</h4>
        <div class="form-field">
          <label><input type="checkbox" id="feishuEnabled" ${ch.feishu?.enabled ? "checked" : ""}> 启用</label>
        </div>
        <div class="form-field">
          <label>Webhook URL</label>
          <input type="url" id="feishuUrl" value="${escapeHtml(ch.feishu?.webhook_url || "")}" placeholder="https://open.feishu.cn/...">
        </div>
      </div>

      <div class="notif-section">
        <h4>通用 Webhook</h4>
        <div class="form-field">
          <label><input type="checkbox" id="webhookEnabled" ${ch.generic_webhook?.enabled ? "checked" : ""}> 启用</label>
        </div>
        <div class="form-field">
          <label>URL</label>
          <input type="url" id="webhookUrl" value="${escapeHtml(ch.generic_webhook?.url || "")}" placeholder="https://example.com/webhook">
        </div>
        <div class="form-field">
          <label>Secret</label>
          <input type="password" id="webhookSecret" value="${escapeHtml(ch.generic_webhook?.secret || "")}">
        </div>
      </div>

      <div class="notif-section">
        <h4>告警规则</h4>
        <div class="form-field">
          <label>最低分数 <span id="minScoreVal">${rules.min_score || 80}</span></label>
          <input type="range" id="ruleMinScore" min="0" max="100" value="${rules.min_score || 80}">
        </div>
        <div class="form-field">
          <label><input type="checkbox" id="quietHoursEnabled" ${qh.enabled ? "checked" : ""}> 静默时段</label>
        </div>
        <div class="form-field quiet-hours-times" style="display:${qh.enabled ? "flex" : "none"};gap:8px;align-items:center;">
          <input type="time" id="quietStart" value="${qh.start || "22:00"}">
          <span>至</span>
          <input type="time" id="quietEnd" value="${qh.end || "07:00"}">
        </div>
      </div>

      <div id="notifSaveStatus" style="margin-top:12px;"></div>
      <button class="btn-primary" id="notifSaveBtn">保存设置</button>
    </div>
  `;

  // 范围滑块实时显示
  container.querySelector("#ruleMinScore").addEventListener("input", (e) => {
    container.querySelector("#minScoreVal").textContent = e.target.value;
  });

  // 静默时段开关
  container.querySelector("#quietHoursEnabled").addEventListener("change", (e) => {
    container.querySelector(".quiet-hours-times").style.display = e.target.checked ? "flex" : "none";
  });

  // 保存
  container.querySelector("#notifSaveBtn").addEventListener("click", async () => {
    const newConfig = {
      channels: {
        email: {
          enabled: container.querySelector("#emailEnabled").checked,
          smtp_host: container.querySelector("#emailSmtpHost").value.trim(),
          smtp_port: parseInt(container.querySelector("#emailSmtpPort").value) || 587,
          from_address: container.querySelector("#emailFrom").value.trim(),
          to_addresses: container.querySelector("#emailTo").value.split(",").map(s => s.trim()).filter(Boolean),
        },
        feishu: {
          enabled: container.querySelector("#feishuEnabled").checked,
          webhook_url: container.querySelector("#feishuUrl").value.trim(),
        },
        generic_webhook: {
          enabled: container.querySelector("#webhookEnabled").checked,
          url: container.querySelector("#webhookUrl").value.trim(),
          secret: container.querySelector("#webhookSecret").value,
        },
      },
      rules: {
        min_score: parseInt(container.querySelector("#ruleMinScore").value) || 80,
        include_classifications: rules.include_classifications || ["L1-breaking", "L2-significant"],
        quiet_hours: {
          enabled: container.querySelector("#quietHoursEnabled").checked,
          start: container.querySelector("#quietStart").value || "22:00",
          end: container.querySelector("#quietEnd").value || "07:00",
        },
      },
    };

    try {
      await apiPut("/api/v1/settings/notifications", newConfig);
      container.querySelector("#notifSaveStatus").innerHTML = '<span class="save-ok">已保存</span>';
      showSuccess("通知设置已保存");
    } catch (err) {
      showError("保存失败: " + err.message);
    }
  });
}

export async function renderUserMgmtTab(container) {
  if (!hasPermission("admin")) {
    container.innerHTML = '<div class="empty-state"><p>需要管理员权限</p></div>';
    return;
  }

  container.innerHTML = `
    <div class="settings-page">
      <h3>用户管理</h3>
      <div class="loading-spinner"><div class="spinner"></div><p>加载中...</p></div>
    </div>
  `;

  let users;
  try {
    const resp = await api("/api/v1/admin/users");
    users = resp.users || [];
  } catch (err) {
    showError("加载用户列表失败: " + err.message);
    return;
  }

  container.innerHTML = `
    <div class="settings-page">
      <h3>用户管理</h3>
      <button class="btn-secondary" id="addUserBtn" style="margin-bottom:16px;">+ 添加用户</button>
      <table class="users-table">
        <thead>
          <tr><th>用户名</th><th>角色</th><th>API Key</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          ${users.map(u => `
            <tr>
              <td>${escapeHtml(u.username)}</td>
              <td><span class="chip ${u.role === "admin" ? "chip-classification" : ""}">${escapeHtml(u.role)}</span></td>
              <td>${u.has_api_key ? "✓" : "—"}</td>
              <td>${u.created_at ? formatDate(u.created_at) : "—"}</td>
              <td>
                <button class="btn-sm" data-reset-user="${escapeHtml(u.username)}">重置密码</button>
                <button class="btn-sm btn-danger" data-delete-user="${escapeHtml(u.username)}" ${u.username === "admin" ? "disabled title='不能删除管理员'" : ""}>删除</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>

      <div id="addUserForm" style="display:none;margin-top:16px;padding:16px;background:var(--bg-tertiary);border-radius:var(--radius-md);">
        <h4>添加新用户</h4>
        <div class="form-field">
          <label>用户名</label>
          <input type="text" id="newUsername" placeholder="username">
        </div>
        <div class="form-field">
          <label>密码</label>
          <input type="password" id="newPassword" placeholder="至少 6 个字符">
        </div>
        <div class="form-field">
          <label>角色</label>
          <select id="newRole">
            <option value="reader">reader</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <div id="addUserError" class="form-error" style="display:none;"></div>
        <div style="margin-top:8px;display:flex;gap:8px;">
          <button class="btn-primary" id="addUserSubmit">创建</button>
          <button class="btn-secondary" id="addUserCancel">取消</button>
        </div>
      </div>
    </div>
  `;

  // 添加用户表单开关
  container.querySelector("#addUserBtn").addEventListener("click", () => {
    container.querySelector("#addUserForm").style.display = "block";
  });
  container.querySelector("#addUserCancel").addEventListener("click", () => {
    container.querySelector("#addUserForm").style.display = "none";
  });

  // 创建用户
  container.querySelector("#addUserSubmit").addEventListener("click", async () => {
    const errEl = container.querySelector("#addUserError");
    const username = container.querySelector("#newUsername").value.trim();
    const password = container.querySelector("#newPassword").value;
    const role = container.querySelector("#newRole").value;
    if (!username || !password) {
      errEl.textContent = "请填写用户名和密码";
      errEl.style.display = "block";
      return;
    }
    try {
      await apiPost("/api/v1/admin/users", {}, { username, password, role });
      showSuccess(`用户 ${username} 创建成功`);
      renderUserMgmtTab(container);
    } catch (err) {
      errEl.textContent = err.message || "创建失败";
      errEl.style.display = "block";
    }
  });

  // 重置密码
  container.querySelectorAll("[data-reset-user]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const username = btn.dataset.resetUser;
      const newPw = prompt(`请输入 ${username} 的新密码（至少 6 个字符）:`);
      if (!newPw || newPw.length < 6) {
        if (newPw !== null) showError("密码至少 6 个字符");
        return;
      }
      try {
        await apiPost(`/api/v1/admin/users/${encodeURIComponent(username)}/reset-password`, {}, { new_password: newPw });
        showSuccess(`${username} 密码已重置`);
      } catch (err) {
        showError(`重置失败: ${err.message}`);
      }
    });
  });

  // 删除用户
  container.querySelectorAll("[data-delete-user]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const username = btn.dataset.deleteUser;
      if (!confirm(`确定要删除用户 ${username} 吗？`)) return;
      try {
        await api(`/api/v1/admin/users/${encodeURIComponent(username)}`, null, "DELETE");
        showSuccess(`用户 ${username} 已删除`);
        renderUserMgmtTab(container);
      } catch (err) {
        showError(`删除失败: ${err.message}`);
      }
    });
  });
}
