#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash deploy/ubuntu/setup_ubuntu_systemd.sh <app_user> <app_dir> [service_name]"
  exit 1
fi

APP_USER="${1:-${SUDO_USER:-}}"
APP_DIR_INPUT="${2:-}"
SERVICE_NAME="${3:-gpt-auto-register}"

if [[ -z "${APP_USER}" ]]; then
  echo "缺少 app_user 参数"
  exit 1
fi

if [[ -z "${APP_DIR_INPUT}" ]]; then
  echo "缺少 app_dir 参数"
  exit 1
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  echo "用户不存在: ${APP_USER}"
  exit 1
fi

APP_DIR="$(realpath "${APP_DIR_INPUT}")"
if [[ ! -d "${APP_DIR}" ]]; then
  echo "目录不存在: ${APP_DIR}"
  exit 1
fi

if [[ ! -f "${APP_DIR}/pyproject.toml" ]]; then
  echo "目录不是项目根目录（缺少 pyproject.toml）: ${APP_DIR}"
  exit 1
fi

echo "[1/6] 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  xauth \
  xvfb \
  fonts-liberation \
  fonts-noto-color-emoji \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libc6 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libexpat1 \
  libfontconfig1 \
  libgbm1 \
  libglib2.0-0 \
  libgtk-3-0 \
  libnspr4 \
  libnss3 \
  libpango-1.0-0 \
  libx11-6 \
  libx11-xcb1 \
  libxcb1 \
  libxcomposite1 \
  libxdamage1 \
  libxext6 \
  libxfixes3 \
  libxrandr2

echo "[2/6] 安装 Google Chrome..."
if ! command -v google-chrome >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
  chmod a+r /etc/apt/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
  apt-get update
  apt-get install -y google-chrome-stable
fi

echo "[3/6] 安装 uv..."
if ! sudo -u "${APP_USER}" bash -lc 'command -v uv >/dev/null 2>&1'; then
  sudo -u "${APP_USER}" bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

echo "[4/6] 同步 Python 与项目依赖..."
sudo -u "${APP_USER}" bash -lc "cd \"${APP_DIR}\" && export PATH=\"\$HOME/.local/bin:\$PATH\" && uv python install 3.13 && uv sync --python 3.13"

if [[ ! -f "${APP_DIR}/config.yaml" && -f "${APP_DIR}/config.example.yaml" ]]; then
  cp "${APP_DIR}/config.example.yaml" "${APP_DIR}/config.yaml"
  chown "${APP_USER}:${APP_USER}" "${APP_DIR}/config.yaml"
  echo "已生成 config.yaml，请先补全配置再正式运行。"
fi

echo "[5/6] 生成并安装 systemd 服务..."
TEMPLATE_FILE="${APP_DIR}/deploy/ubuntu/gpt-auto-register.service.template"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
  echo "模板不存在: ${TEMPLATE_FILE}"
  exit 1
fi

sed \
  -e "s|__APP_USER__|${APP_USER}|g" \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  "${TEMPLATE_FILE}" > "${SERVICE_FILE}"

chmod 0644 "${SERVICE_FILE}"
chown root:root "${SERVICE_FILE}"
chmod +x "${APP_DIR}/deploy/ubuntu/start_server.sh"
chown "${APP_USER}:${APP_USER}" "${APP_DIR}/deploy/ubuntu/start_server.sh"

echo "[6/6] 启动服务..."
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"

echo "部署完成。"
echo "查看状态: sudo systemctl status ${SERVICE_NAME}.service --no-pager"
echo "查看日志: sudo journalctl -u ${SERVICE_NAME}.service -f"
