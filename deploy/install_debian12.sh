#!/usr/bin/env bash
# Установка и запуск бота на чистом Debian 12. Запускать из папки проекта: sudo bash deploy/install_debian12.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Запустите через sudo: sudo bash deploy/install_debian12.sh" >&2
    exit 1
fi

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
    echo ">>> Устанавливаю Docker"
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi

if [[ ! -f .env ]]; then
    cp .env.example .env
    read -r -p "Введите DISCORD_TOKEN: " token
    sed -i "s|^DISCORD_TOKEN=.*|DISCORD_TOKEN=${token}|" .env
    chmod 600 .env
fi

mkdir -p data
chown -R 1000:1000 data

echo ">>> Собираю и запускаю"
docker compose up -d --build

echo ">>> Готово. Логи: docker compose logs -f bot | Проверка: curl http://localhost/health"
