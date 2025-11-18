#!/usr/bin/env bash
set -euo pipefail

# === Config ===
PROJ_ROOT="/mnt/c/Users/admin/Documents/project"
BACKEND_DIR="$PROJ_ROOT/backend"
VENV_DIR="$BACKEND_DIR/venv"
COMPOSE_FILE="$PROJ_ROOT/docker-compose.yml"

# === Порты ===
DEFAULT_FASTAPI_PORT=8000
DEFAULT_TITILER_PORT=8008

# === Helpers ===
log()  { printf "\033[1;32m[%s]\033[0m %s\n" "$(date +'%H:%M:%S')" "$*"; }
warn() { printf "\033[1;33m[%s]\033[0m %s\n" "$(date +'%H:%M:%S')" "$*"; }
err()  { printf "\033[1;31m[%s]\033[0m %s\n" "$(date +'%H:%M:%S')" "$*" >&2; }
die()  { err "$1"; exit 1; }

# === Проверка зависимостей ===
check_deps() {
  for cmd in docker curl python3; do
    command -v "$cmd" >/dev/null 2>&1 || die "Требуется $cmd"
  done

  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
  else
    die "Docker Compose не найден"
  fi
}

# === Очистка ===
PIDS=()
cleanup() {
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    log "Останавливаем сервисы (PIDs: ${PIDS[*]})..."
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
  log "Остановлено."
}
trap cleanup EXIT INT TERM

# === Поиск свободного порта ===
find_free_port() {
  local start=$1 port=$1
  while lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; do
    ((port++))
    [[ $port -gt $((start + 100)) ]] && die "Нет свободных портов от $start"
  done
  echo "$port"
}

# === Освобождение порта ===
free_port() {
  local port=$1
  log "Освобождаем порт :$port..."

  # Локальные процессы
  local pids=$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || echo "")
  [[ -n "$pids" ]] && warn "Убиваем PIDs: $pids" && kill $pids 2>/dev/null || true

  # Docker контейнеры
  local containers=$($DOCKER_COMPOSE ps --filter "publish=$port" -q 2>/dev/null || echo "")
  [[ -n "$containers" ]] && warn "Останавливаем контейнеры: $containers" && docker stop $containers >/dev/null 2>&1 || true

  sleep 0.3
}

# === Ожидание сервиса ===
wait_for() {
  local url=$1 name=$2 timeout=${3:-30}
  log "Ожидаем $name: $url ..."
  for i in $(seq 1 $timeout); do
    if curl -sf "$url" >/dev/null 2>&1; then
      log "$name готов: $url"
      return 0
    fi
    sleep 0.5
  done
  die "$name не отвечает: $url"
}

# === Cache busting для ndvi-ui.js ===
bust_cache() {
  local html_file="$PROJ_ROOT/frontend/ndvi.html"
  [[ ! -f "$html_file" ]] && return 0

  local ts=$(date +%s)
  sed -i -E "s|(src=\"/assets/ndvi-ui.js)(\?v=[0-9]+)?|\1?v=$ts|g" "$html_file"
  log "Cache busting: ndvi-ui.js → ?v=$ts"
}

# === Основная функция ===
main() {
  check_deps

  # === Проверка .env файла ===
  if [[ ! -f "$PROJ_ROOT/.env" ]]; then
    warn ".env файл не найден. Создайте его из .env.example:"
    warn "  cp .env.example .env"
    warn "  nano .env  # Добавьте CDSE_CLIENT_ID и CDSE_CLIENT_SECRET"
    die "Отсутствует файл .env"
  fi

  # === Активация venv ===
  [[ -f "$VENV_DIR/bin/activate" ]] || die "Виртуальное окружение не найдено: $VENV_DIR"
  source "$VENV_DIR/bin/activate"

  # === Проверка Python зависимостей ===
  log "Проверяем Python пакеты..."
  python3 -c "import fastapi, uvicorn, pydantic, httpx" 2>/dev/null || {
    warn "Некоторые пакеты не установлены. Устанавливаем..."
    pip install -q -r "$PROJ_ROOT/requirements.txt" || die "Не удалось установить зависимости"
  }

  # === Порты ===
  FASTAPI_PORT=$(find_free_port $DEFAULT_FASTAPI_PORT)
  TITILER_PORT=$(find_free_port $DEFAULT_TITILER_PORT)

  log "Порты: FastAPI → $FASTAPI_PORT | TiTiler → $TITILER_PORT"

  # === Освобождаем порты ===
  free_port "$FASTAPI_PORT"
  free_port "$TITILER_PORT"

  # === Запуск TiTiler ===
  log "Запускаем TiTiler в Docker..."
  export TITILER_PORT
  $DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d titiler --remove-orphans || die "Не удалось запустить TiTiler"

  wait_for "http://127.0.0.1:$TITILER_PORT/healthz" "TiTiler" 40

  # === Переход в корень + PYTHONPATH ===
  cd "$PROJ_ROOT"
  export PYTHONPATH="$PROJ_ROOT:${PYTHONPATH:-}"

  # === Переменные окружения ===
  export TITILER_URL="http://127.0.0.1:$TITILER_PORT"
  export PORT="$FASTAPI_PORT"
  export HOST="0.0.0.0"

  # === Cache busting ===
  bust_cache

  # === Запуск FastAPI ===
  log "Запускаем FastAPI на :$FASTAPI_PORT..."
  uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$FASTAPI_PORT" \
    --reload \
    --log-level info &
  PIDS+=($!)

  wait_for "http://127.0.0.1:$FASTAPI_PORT/healthz" "FastAPI"

  # === Запуск Celery (опционально) ===
  if [[ -f "$BACKEND_DIR/tasks/celery_app.py" ]] && command -v celery >/dev/null 2>&1; then
    log "Запускаем Celery worker..."
    celery -A backend.tasks.celery_app worker -l info &
    PIDS+=($!)
  else
    warn "Celery не настроен (опционально, пропускаем)"
  fi

  # === Проверка здоровья ===
  log "Проверяем здоровье сервисов..."
  if curl -sf "http://127.0.0.1:$FASTAPI_PORT/health" >/dev/null 2>&1; then
    log "✓ Все сервисы работают"
  else
    warn "⚠ Некоторые сервисы могут быть недоступны (проверьте /health)"
  fi

  # === Финал ===
  log "ВСЁ ЗАПУЩЕНО!"
  echo
  echo "   🌐 Главная:    http://localhost:$FASTAPI_PORT/"
  echo "   📊 NDVI:       http://localhost:$FASTAPI_PORT/ndvi"
  echo "   🌱 BIOPAR:     http://localhost:$FASTAPI_PORT/biopar"
  echo
  echo "   📚 API Docs:   http://localhost:$FASTAPI_PORT/docs"
  echo "   ❤️  Health:     http://localhost:$FASTAPI_PORT/health"
  echo "   📈 Metrics:    http://localhost:$FASTAPI_PORT/metrics"
  echo "   💾 Cache:      http://localhost:$FASTAPI_PORT/cache/status"
  echo "   🔧 Jobs:       http://localhost:$FASTAPI_PORT/jobs"
  echo
  echo "   🗺️  TiTiler:    $TITILER_URL"
  echo
  echo "   📝 Нажмите Ctrl+C для остановки"
  echo

  wait
}

# === Запуск ===
main