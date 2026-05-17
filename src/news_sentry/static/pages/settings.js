/**
 * settings.js — 密码修改页
 */
"use strict";

import { apiPost } from "../api.js";

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
