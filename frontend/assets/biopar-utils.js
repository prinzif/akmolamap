// assets/biopar-utils.js

/**
 * Улучшенный fetchJSON с retry логикой и детальной обработкой ошибок
 * Синхронизирован с ndvi-utils.js
 */
export async function fetchJSON(url, options = {}) {
  const maxRetries = options.maxRetries ?? 2;
  const retryDelay = options.retryDelay ?? 3000;
  const timeout = options.timeout ?? 180000;

  let lastError = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      const response = await fetch(url, {
        cache: "no-cache",
        signal: controller.signal,
        ...options
      });

      clearTimeout(timeoutId);

      // Специфичная обработка статусов
      if (response.status === 400) {
        const text = await response.text();
        const low = text.toLowerCase();
        if (low.includes("no data") || 
            low.includes("no satellite") ||
            low.includes("no scenes") ||
            low.includes("no products")) {
          throw new NoDataError("Нет доступных спутниковых данных для выбранного периода и области");
        }
        throw new APIError(`Неверные параметры запроса: ${text}`, 400);
      }

      if (response.status === 429) {
        const retryAfter = response.headers.get("Retry-After");
        const delay = retryAfter ? parseInt(retryAfter, 10) * 1000 : retryDelay;
        if (attempt < maxRetries) {
          console.warn(`Rate limit (429), повтор через ${delay}ms...`);
          await sleep(delay);
          continue;
        }
        throw new APIError("Превышен лимит запросов", 429);
      }

      if (response.status >= 500) {
        if (attempt < maxRetries) {
          console.warn(`Ошибка сервера (${response.status}), повтор ${attempt + 1}/${maxRetries}...`);
          await sleep(retryDelay);
          continue;
        }
        throw new APIError(`Сервис временно недоступен (${response.status})`, response.status);
      }

      if (!response.ok) {
        throw new APIError(`HTTP ${response.status} for ${url}`, response.status);
      }

      return await response.json();
      
    } catch (error) {
      lastError = error;

      // Не повторяем для некоторых ошибок
      if (error instanceof NoDataError || 
          (error instanceof APIError && error.status === 400)) {
        throw error;
      }

      // Timeout или connection error - пробуем ещё раз
      if (error.name === "AbortError" || 
          (typeof error.message === "string" && error.message.includes("Failed to fetch"))) {
        if (attempt < maxRetries) {
          console.warn(`Таймаут/сетевая ошибка, повтор ${attempt + 1}/${maxRetries}...`);
          await sleep(retryDelay);
          continue;
        }
      }

      // Последняя попытка
      if (attempt >= maxRetries) {
        throw error;
      }
    }
  }

  throw lastError || new Error("Неизвестная ошибка при запросе");
}

/**
 * Пользовательские классы ошибок
 */
export class APIError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "APIError";
    this.status = status;
  }
}

export class NoDataError extends Error {
  constructor(message) {
    super(message);
    this.name = "NoDataError";
  }
}

/**
 * Вспомогательная функция задержки
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Debounce функция для ограничения частоты вызовов
 */
export function debounce(fn, ms = 400) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/**
 * Throttle функция для ограничения частоты выполнения
 */
export function throttle(fn, ms = 400) {
  let lastTime = 0;
  return (...args) => {
    const now = Date.now();
    if (now - lastTime >= ms) {
      lastTime = now;
      fn(...args);
    }
  };
}

// ----- имена/поиск в GADM -----
export function normalizeName(s) {
  if (!s) return "";
  return s.toString().toLowerCase()
    .replaceAll("ё", "е")
    .replace(/[^\p{Letter}\p{Number}\s_-]/gu, "")
    .trim();
}

export function isAkmolaLike(name) {
  const n = normalizeName(name);
  return ["aqmola", "akmola", "akmolinsk", "акмолинская", "акмола"].some(v => n.includes(v));
}

export function pickAkmolaFromLevel1(geojson) {
  const feats = (geojson?.type === "FeatureCollection") ? geojson.features : [];
  let hit = feats.find(f => isAkmolaLike(f?.properties?.NAME_1));
  if (!hit) hit = feats.find(f => isAkmolaLike(f?.properties?.name));
  return hit || null;
}

export function pickDistrictsOfAkmolaFromLevel2(geojson) {
  const feats = (geojson?.type === "FeatureCollection") ? geojson.features : [];
  return feats.filter(f => isAkmolaLike(f?.properties?.NAME_1));
}

// ----- BIOPAR утилиты -----

/**
 * Нормализует тип BIOPAR к верхнему регистру
 */
export function normalizeType(t) {
  return (t || "FAPAR").toString().trim().toUpperCase();
}

/**
 * Форматирование значения BIOPAR в зависимости от типа
 */
export function formatBIOPARValue(type, v) {
  if (v == null || Number.isNaN(v)) return "—";
  const T = normalizeType(type);
  
  if (T === "FAPAR" || T === "FCOVER") {
    return Number(v).toFixed(3); // 0..1
  }
  if (T === "LAI") {
    return Number(v).toFixed(2); // 0..6(+)
  }
  if (T === "CCC" || T === "CWC") {
    return `${Number(v).toFixed(1)} г/м²`; // Единицы измерения
  }
  return Number(v).toFixed(2);
}

/**
 * Цветовая шкала для типов BIOPAR
 */
export function getBIOPARColor(type, v) {
  const T = normalizeType(type);
  if (v == null || Number.isNaN(v)) return "#cccccc";

  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  // FAPAR/FCOVER: 0..1 (красный -> жёлтый -> зелёный)
  if (T === "FAPAR" || T === "FCOVER") {
    const x = clamp(v, 0, 1);
    if (x < 0.10) return "#8b0000"; // Тёмно-красный
    if (x < 0.25) return "#d2691e"; // Шоколадный
    if (x < 0.50) return "#daa520"; // Золотой
    if (x < 0.70) return "#90ee90"; // Светло-зелёный
    return "#228b22";                // Лесной зелёный
  }
  
  // LAI: 0..6 (бледно-жёлтый -> зелёный -> тёмно-зелёный)
  if (T === "LAI") {
    const x = clamp(v / 6, 0, 1);
    if (x < 0.10) return "#8b0000";
    if (x < 0.25) return "#d2691e";
    if (x < 0.45) return "#daa520";
    if (x < 0.75) return "#90ee90";
    return "#2e8b57"; // Морской зелёный
  }
  
  // CCC: содержание хлорофилла (г/м²)
  if (T === "CCC") {
    const x = clamp(v / 300, 0, 1); // Нормализуем к ~300 г/м² max
    if (x < 0.17) return "#8b0000";
    if (x < 0.33) return "#d2691e";
    if (x < 0.67) return "#90ee90";
    return "#228b22";
  }
  
  // CWC: содержание воды (г/м²)
  if (T === "CWC") {
    const x = clamp(v / 600, 0, 1); // Нормализуем к ~600 г/м² max
    if (x < 0.17) return "#8b0000";
    if (x < 0.33) return "#d2691e";
    if (x < 0.67) return "#4682b4"; // Стальной синий
    return "#1e90ff";                // Dodger синий
  }
  
  // Fallback для неизвестных типов
  return "#6c757d";
}

/**
 * Классификация статуса по среднему значению BIOPAR
 */
export function statusBIOPAR(type, mean) {
  const T = normalizeType(type);
  
  if (mean == null) {
    return { 
      level: "Нет данных", 
      status: "no_data", 
      description: "Недостаточно наблюдений" 
    };
  }

  if (T === "FAPAR") {
    if (mean < 0.10) return { 
      level: "Очень низкий", 
      status: "very_low", 
      description: "Слабое поглощение PAR, возможен стресс" 
    };
    if (mean < 0.25) return { 
      level: "Низкий", 
      status: "low", 
      description: "Ниже нормы, ранняя фаза развития" 
    };
    if (mean < 0.50) return { 
      level: "Средний", 
      status: "moderate", 
      description: "Умеренная листовая масса, развитие" 
    };
    if (mean < 0.70) return { 
      level: "Оптимальный", 
      status: "optimal", 
      description: "Здоровая листовая масса, активный рост" 
    };
    return { 
      level: "Высокий", 
      status: "high", 
      description: "Очень плотный покров, насыщенная масса" 
    };
  }
  
  if (T === "LAI") {
    if (mean < 0.5) return { 
      level: "Очень низкий", 
      status: "very_low", 
      description: "Малая площадь зелёной поверхности" 
    };
    if (mean < 1.5) return { 
      level: "Низкий", 
      status: "low", 
      description: "Разреженный покров, начало вегетации" 
    };
    if (mean < 3.0) return { 
      level: "Средний", 
      status: "moderate", 
      description: "Умеренная листовая масса" 
    };
    if (mean < 5.0) return { 
      level: "Оптимальный", 
      status: "optimal", 
      description: "Хорошо развитая листовая масса" 
    };
    return { 
      level: "Высокий", 
      status: "high", 
      description: "Очень густой покров/лесные насаждения" 
    };
  }
  
  if (T === "FCOVER") {
    if (mean < 0.2) return { 
      level: "Очень низкий", 
      status: "very_low", 
      description: "Небольшая доля покрытия растительностью" 
    };
    if (mean < 0.4) return { 
      level: "Низкий", 
      status: "low", 
      description: "Фрагментарное покрытие, видна почва" 
    };
    if (mean < 0.6) return { 
      level: "Средний", 
      status: "moderate", 
      description: "Умеренная доля покрытия" 
    };
    if (mean < 0.8) return { 
      level: "Оптимальный", 
      status: "optimal", 
      description: "Преимущественно покрытая поверхность" 
    };
    return { 
      level: "Высокий", 
      status: "high", 
      description: "Практически сплошное покрытие" 
    };
  }
  
  if (T === "CCC") {
    if (mean < 50) return { 
      level: "Очень низкий", 
      status: "very_low", 
      description: "Критически низкое содержание хлорофилла" 
    };
    if (mean < 100) return { 
      level: "Низкий", 
      status: "low", 
      description: "Пониженное содержание, возможен хлороз" 
    };
    if (mean < 200) return { 
      level: "Средний", 
      status: "moderate", 
      description: "Нормальное содержание для большинства культур" 
    };
    if (mean < 300) return { 
      level: "Оптимальный", 
      status: "optimal", 
      description: "Высокое содержание, активный фотосинтез" 
    };
    return { 
      level: "Высокий", 
      status: "high", 
      description: "Очень высокое содержание хлорофилла" 
    };
  }
  
  if (T === "CWC") {
    if (mean < 100) return { 
      level: "Очень низкий", 
      status: "very_low", 
      description: "Критически низкое содержание воды, стресс" 
    };
    if (mean < 200) return { 
      level: "Низкий", 
      status: "low", 
      description: "Пониженное содержание, водный стресс" 
    };
    if (mean < 400) return { 
      level: "Средний", 
      status: "moderate", 
      description: "Нормальное содержание воды" 
    };
    if (mean < 600) return { 
      level: "Оптимальный", 
      status: "optimal", 
      description: "Хорошая оводнённость" 
    };
    return { 
      level: "Высокий", 
      status: "high", 
      description: "Высокое содержание воды" 
    };
  }
  
  // CCC/CWC — зависят от культуры/фазы
  return { 
    level: "Нет шкалы", 
    status: "neutral", 
    description: "Интерпретация зависит от культуры и фазы развития" 
  };
}

// ----- цвета и форматирование -----

/**
 * Определяет контрастный цвет текста для фона
 */
export function textColor(bg) {
  const c = (bg || "#ffffff").replace("#", "");
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  const lumin = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lumin < 0.55 ? "white" : "black";
}

/**
 * Форматирование числа с разделителями тысяч
 */
export function formatNumber(num, decimals = 0) {
  if (num == null || isNaN(num)) return "—";
  return Number(num).toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/**
 * Форматирование даты
 */
export function formatDate(dateStr) {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("ru-RU", { 
      year: "numeric", 
      month: "long", 
      day: "numeric" 
    });
  } catch {
    return dateStr;
  }
}

/**
 * Статус BIOPAR текстом с эмодзи
 */
export function getBIOPARStatusEmoji(status) {
  const emojiMap = {
    very_low: "⚠️",
    low: "⚡",
    moderate: "📊",
    optimal: "✅",
    high: "🌳",
    no_data: "❓",
    neutral: "ℹ️"
  };
  return emojiMap[status] || "📊";
}

/**
 * Парсинг эмодзи из рекомендации для отображения
 */
export function extractEmoji(text) {
  const match = text.match(/^([\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}])/u);
  return match ? match[0] : "";
}

// ----- шаблоны -----
export const tpl = {
  /**
   * Сводная карточка статистики BIOPAR
   */
  summaryCard({ type, start, end, stats }) {
    const T = normalizeType(type);
    const mean = stats?.mean ?? null;
    const col = getBIOPARColor(T, mean);
    const txt = textColor(col);
    const cls = statusBIOPAR(T, mean);
    const pct = stats?.percentiles || {};

    const pctList = ["p10", "p25", "p50", "p75", "p90"].map(k => `
      <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0">
        <span style="color:#666">${k.toUpperCase()}</span>
        <strong>${formatBIOPARValue(T, pct[k])}</strong>
      </div>`).join("");

    return `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <!-- Левая колонка -->
        <div>
          <div style="font-size:11px;color:#666;margin-bottom:6px;font-weight:600;">📅 Период</div>
          <div style="font-size:12px;font-weight:bold;margin-bottom:12px;">${start} — ${end}</div>

          <div style="font-size:11px;color:#666;margin-bottom:6px;font-weight:600;">📊 Среднее ${T}</div>
          <div style="padding:16px;border-radius:6px;text-align:center;font-size:22px;font-weight:bold;background:${col};color:${txt};box-shadow:0 2px 4px rgba(0,0,0,0.1)">
            ${formatBIOPARValue(T, mean)}
          </div>

          <div style="margin-top:12px;padding:8px;background:#f8f9fa;border-radius:4px;border-left:3px solid ${col}">
            <div style="font-size:11px;color:#666;margin-bottom:4px;">Статус</div>
            <div style="font-weight:bold;font-size:12px;margin-bottom:2px;">${cls.level}</div>
            <div style="font-size:10px;color:#888;line-height:1.4">${cls.description}</div>
          </div>
        </div>

        <!-- Правая колонка -->
        <div>
          <div style="font-size:11px;color:#666;margin-bottom:6px;font-weight:600;">📈 Статистика</div>
          <div style="display:grid;gap:6px;border:1px solid #e9ecef;border-radius:6px;padding:12px;background:#fff">
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
              <span style="color:#666">Минимум</span>
              <strong>${formatBIOPARValue(T, stats?.min)}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
              <span style="color:#666">Медиана</span>
              <strong>${formatBIOPARValue(T, stats?.median)}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
              <span style="color:#666">Максимум</span>
              <strong>${formatBIOPARValue(T, stats?.max)}</strong>
            </div>
            
            <div style="height:1px;background:#e9ecef;margin:4px 0"></div>
            <div style="font-size:10px;color:#888;margin-bottom:4px;font-weight:600;">Перцентили</div>
            ${pctList}
            
            ${stats?.pixels ? `
              <div style="height:1px;background:#e9ecef;margin:8px 0 4px"></div>
              <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0">
                <span style="color:#666">Пикселей</span>
                <strong>${formatNumber(stats.pixels)}</strong>
              </div>
            ` : ""}
          </div>
        </div>
      </div>
    `;
  },

  /**
   * Полный отчёт с рекомендациями
   */
  report(report) {
    const T = normalizeType(report.biopar_type || "FAPAR");
    const recs = (report.recommendations || [])
      .map(r => {
        const emoji = extractEmoji(r);
        const text = r.replace(emoji, "").trim();
        return `<li style="margin:4px 0;list-style:none;"><span style="font-size:14px">${emoji}</span> ${text}</li>`;
      })
      .join("");
    
    const trendHTML = report.summary?.trend?.description
      ? `<div class="info-row">📈 Тренд: ${report.summary.trend.description}</div>` 
      : "";
    
    const stats = report.statistics || {};
    const meanStr = stats.mean != null ? formatBIOPARValue(T, stats.mean) : "—";
    const obsCount = report.total_observations || 0;
    
    // Статус с эмодзи
    const status = report.summary?.status || {};
    const statusEmoji = getBIOPARStatusEmoji(status.status);
    
    return `
      <div class="popup-content" style="max-width:400px;max-height:500px;overflow-y:auto;">
        <h4 style="margin:0 0 10px 0;">📑 Отчет ${T}</h4>
        <div class="info-row" style="font-size:11px;margin:3px 0;">📅 Дата: ${report.report_date || "—"}</div>
        <div class="info-row" style="font-size:11px;margin:3px 0;">📊 Период: ${report.period_analyzed || "—"}</div>
        ${trendHTML}
        
        <div style="margin:10px 0;padding:10px;background:#f8f9fa;border-radius:4px;border-left:4px solid ${
          status.level === 'Оптимальный' ? '#28a745' : 
          status.level === 'Высокий' ? '#007cba' :
          status.level === 'Низкий' ? '#ffc107' : '#dc3545'
        };">
          <strong>${statusEmoji} Состояние: ${(status.level || "N/A").toUpperCase()}</strong><br>
          <span style="font-size:11px;color:#666">${status.description || ""}</span>
        </div>
        
        <div style="margin:10px 0;display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;">
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#007cba">${meanStr}</div>
            <div style="font-size:10px;color:#666">Средний ${T}</div>
          </div>
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#28a745">${obsCount}</div>
            <div style="font-size:10px;color:#666">Наблюдений</div>
          </div>
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#6c757d">${formatNumber(stats.pixels || 0)}</div>
            <div style="font-size:10px;color:#666">Пикселей</div>
          </div>
        </div>
        
        ${recs ? `<div style="background:#e7f3ff;padding:10px;border-radius:4px;margin-top:10px;border-left:4px solid #007cba;">
          <h4 style="margin:0 0 8px 0;font-size:13px;color:#007cba">💡 Рекомендации:</h4>
          <ul style="margin:0;padding:0;font-size:11px;">${recs}</ul>
        </div>` : ""}
      </div>`;
  },

  /**
   * Popup для точки на карте
   */
  pixelPopup({ value, color, start, end, lat, lng, type }) {
    const T = normalizeType(type || "FAPAR");
    return `
      <div class="popup-content">
        <h4 style="margin:0 0 8px 0">${T}</h4>
        <div class="ndvi-value" style="background:${color};color:${textColor(color)};padding:14px;border-radius:6px;text-align:center;font-size:22px;font-weight:bold;margin-bottom:10px;box-shadow:0 2px 4px rgba(0,0,0,0.1)">
          ${formatBIOPARValue(T, Number(value))}
        </div>
        <div class="info-row" style="font-size:11px;margin:4px 0;color:#666">📅 Период: ${start} — ${end}</div>
        <div class="info-row" style="font-size:11px;margin:4px 0;color:#666">📍 ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
        <div class="info-row" style="margin-top:10px">
          <button id="pin-here" style="padding:8px 12px;font-size:11px;background:#007cba;color:white;border:none;border-radius:4px;cursor:pointer;width:100%;font-weight:600">
            📍 Сохранить точку
          </button>
        </div>
        <div style="width:280px;height:100px;margin-top:12px"><canvas id="px-mini"></canvas></div>
      </div>`;
  }
};

/**
 * Проверка доступности API
 */
export async function checkAPIHealth(apiBase) {
  try {
    const response = await fetchJSON(`${apiBase}/settings/health`, { 
      timeout: 5000,
      maxRetries: 0 
    });
    return {
      ok: response.ok === true,
      cdse_ok: response.cdse_ok === true,
      titiler_ok: response.titiler_ok === true,
      openeo_ok: response.openeo_ok === true
    };
  } catch (err) {
    console.error("API health check failed:", err);
    return { 
      ok: false, 
      cdse_ok: false, 
      titiler_ok: false,
      openeo_ok: false 
    };
  }
}

/**
 * Вычисление bbox из bounds Leaflet
 */
export function boundsToWGS84Bbox(bounds) {
  return [
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth()
  ];
}

/**
 * Показать сообщение об ошибке в UI
 */
export function showError(containerEl, message, type = "error") {
  const classes = {
    error: "error-message",
    warning: "warning-message",
    info: "info-message"
  };

  const div = document.createElement("div");
  div.className = classes[type] || classes.error;
  div.innerHTML = `
    <strong>${type === "error" ? "❌" : type === "warning" ? "⚠️" : "ℹ️"} ${
      type === "error" ? "Ошибка" : type === "warning" ? "Внимание" : "Информация"
    }</strong><br>
    <span style="font-size:11px">${message}</span>
    <button onclick="this.parentElement.remove()" style="float:right;background:none;border:none;cursor:pointer;font-size:16px">✕</button>
  `;

  if (containerEl) {
    containerEl.insertBefore(div, containerEl.firstChild);
    setTimeout(() => div.remove(), 10000); // Автоудаление через 10 сек
  }

  return div;
}

/**
 * Показать прогресс-бар
 */
export function showProgress(containerEl, message = "Загрузка...") {
  const div = document.createElement("div");
  div.className = "progress-container";
  div.innerHTML = `
    <div style="font-size:11px;color:#666;margin-bottom:5px">${message}</div>
    <div class="progress-bar">
      <div class="progress-bar-fill" style="width:0%"></div>
    </div>
  `;

  containerEl.appendChild(div);

  return {
    update: (percent) => {
      const fill = div.querySelector(".progress-bar-fill");
      if (fill) fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    },
    setText: (text) => {
      const label = div.querySelector("div:first-child");
      if (label) label.textContent = text;
    },
    remove: () => div.remove()
  };
}