// assets/ndvi-utils.js

/**
 * Enhanced fetchJSON with retry logic and detailed error handling
 */
export async function fetchJSON(url, options = {}) {
  const maxRetries = options.maxRetries || 2;
  const retryDelay = options.retryDelay || 3000;
  const timeout = options.timeout || 30000; // 30 seconds default

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

      // Specific status code handling
      if (response.status === 400) {
        const text = await response.text();
        if (text.toLowerCase().includes("no data") ||
            text.toLowerCase().includes("no satellite")) {
          throw new NoDataError("No satellite data available for the selected period and area");
        }
        throw new APIError(`Invalid request parameters: ${text}`, response.status);
      }

      if (response.status === 429) {
        const retryAfter = response.headers.get("Retry-After");
        const delay = retryAfter ? parseInt(retryAfter) * 1000 : retryDelay;

        if (attempt < maxRetries) {
          console.warn(`Rate limit (429), retrying in ${delay}ms...`);
          await sleep(delay);
          continue;
        }
        throw new APIError("Rate limit exceeded", 429);
      }

      if (response.status >= 500) {
        if (attempt < maxRetries) {
          console.warn(`Server error (${response.status}), retry ${attempt + 1}/${maxRetries}...`);
          await sleep(retryDelay);
          continue;
        }
        throw new APIError(`Service temporarily unavailable (${response.status})`, response.status);
      }

      if (!response.ok) {
        throw new APIError(`HTTP ${response.status} for ${url}`, response.status);
      }

      return await response.json();

    } catch (error) {
      lastError = error;

      // Don't retry certain errors
      if (error instanceof NoDataError ||
          error instanceof APIError && error.status === 400) {
        throw error;
      }

      // Timeout or connection error - retry
      if (error.name === 'AbortError' || error.message.includes('Failed to fetch')) {
        if (attempt < maxRetries) {
          console.warn(`Timeout/network error, retry ${attempt + 1}/${maxRetries}...`);
          await sleep(retryDelay);
          continue;
        }
      }

      // Last attempt
      if (attempt >= maxRetries) {
        throw error;
      }
    }
  }

  throw lastError || new Error("Unknown error during request");
}

/**
 * Custom error classes
 */
export class APIError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'APIError';
    this.status = status;
  }
}

export class NoDataError extends Error {
  constructor(message) {
    super(message);
    this.name = 'NoDataError';
  }
}

/**
 * Helper function for delays
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Simple fetch wrapper with timeout support (for non-JSON requests)
 * @param {string} url - The URL to fetch
 * @param {object} options - Fetch options (timeout in ms can be specified)
 * @returns {Promise<Response>}
 */
export async function fetchWithTimeout(url, options = {}) {
  const timeout = options.timeout || 30000; // 30 seconds default
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: options.signal || controller.signal
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
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
    .replaceAll("ё","е")
    .replace(/[^\p{Letter}\p{Number}\s_-]/gu,"")
    .trim();
}

export function isAkmolaLike(name) {
  const n = normalizeName(name);
  return ["aqmola","akmola","akmolinsk","акмолинская","акмола"].some(v => n.includes(v));
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

// ----- цвета NDVI -----
export function getNDVIColor(v) {
  if (v < 0)   return "#0066cc"; // вода
  if (v < 0.2) return "#8b4513"; // почва
  if (v < 0.3) return "#daa520"; // редкая растительность
  if (v < 0.6) return "#90ee90"; // средняя
  return "#228b22";              // густая
}

export function textColor(bg) {
  const c = bg.replace("#","");
  const r = parseInt(c.substring(0,2),16);
  const g = parseInt(c.substring(2,4),16);
  const b = parseInt(c.substring(4,6),16);
  const lumin = (0.299*r + 0.587*g + 0.114*b) / 255;
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
 * Статус NDVI текстом с эмодзи
 */
export function getNDVIStatusEmoji(status) {
  const emojiMap = {
    water: "💧",
    bare_soil: "🏜️",
    critical_low: "⚠️",
    low: "⚡",
    optimal: "✅",
    high: "🌳"
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
  report(report) {
    const recs = (report.vegetation_status?.recommendations || [])
      .map(r => {
        const emoji = extractEmoji(r);
        const text = r.replace(emoji, "").trim();
        return `<li style="margin:4px 0;list-style:none;"><span style="font-size:14px">${emoji}</span> ${text}</li>`;
      })
      .join("");
    
    const trendHTML = report.vegetation_status?.trend
      ? `<div class="info-row">📈 Тренд: ${report.vegetation_status.trend}</div>` 
      : "";
    
    const areaTypeHTML = report._areaType
      ? `<div class="info-row" style="background:#fff3cd;padding:4px 8px;border-radius:3px;margin:5px 0;">
           📍 Отчет для <strong>${report._areaType}</strong>
         </div>` 
      : "";
    
    const stats = report.ndvi_statistics || {};
    const meanNDVIStr = stats.mean_ndvi != null ? stats.mean_ndvi.toFixed(3) : "—";
    const obsCount = stats.observations_count || 0;
    
    // Статус с эмодзи
    const status = report.vegetation_status || {};
    const statusEmoji = getNDVIStatusEmoji(report.statistics?.status?.status);
    
    return `
      <div class="popup-content" style="max-width:400px;max-height:500px;overflow-y:auto;">
        <h4 style="margin:0 0 10px 0;">📑 Отчет NDVI - ${report.region || "Регион"}</h4>
        ${areaTypeHTML}
        <div class="info-row" style="font-size:11px;margin:3px 0;">📅 Дата: ${report.report_date || "—"}</div>
        <div class="info-row" style="font-size:11px;margin:3px 0;">📊 Период: ${report.period_analyzed || "—"}</div>
        ${trendHTML}
        
        <div style="margin:10px 0;padding:10px;background:#f8f9fa;border-radius:4px;border-left:4px solid ${
          status.overall === 'Оптимальный' ? '#28a745' : 
          status.overall === 'Высокий' ? '#007cba' :
          status.overall === 'Низкий' ? '#ffc107' : '#dc3545'
        };">
          <strong>${statusEmoji} Состояние: ${(status.overall || "N/A").toUpperCase()}</strong><br>
          <span style="font-size:11px;color:#666">${status.description || ""}</span>
        </div>
        
        <div style="margin:10px 0;display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;">
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#007cba">${meanNDVIStr}</div>
            <div style="font-size:10px;color:#666">Средний NDVI</div>
          </div>
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#28a745">${obsCount}</div>
            <div style="font-size:10px;color:#666">Наблюдений</div>
          </div>
          <div style="padding:8px;background:#f8f9fa;border-radius:4px;text-align:center;">
            <div style="font-size:18px;font-weight:bold;color:#6c757d">${(report.agricultural_zones||[]).length}</div>
            <div style="font-size:10px;color:#666">С/х зон</div>
          </div>
        </div>
        
        ${recs ? `<div style="background:#e7f3ff;padding:10px;border-radius:4px;margin-top:10px;border-left:4px solid #007cba;">
          <h4 style="margin:0 0 8px 0;font-size:13px;color:#007cba">💡 Рекомендации:</h4>
          <ul style="margin:0;padding:0;font-size:11px;">${recs}</ul>
        </div>` : ""}
      </div>`;
  },
  
  pixelPopup({value, color, start, end, lat, lng}) {
    return `
      <div class="popup-content">
        <h4 style="margin:0 0 8px 0">NDVI</h4>
        <div class="ndvi-value" style="background:${color};color:${textColor(color)};padding:12px;border-radius:4px;text-align:center;font-size:20px;font-weight:bold;margin-bottom:8px">
          ${Number(value).toFixed(3)}
        </div>
        <div class="info-row" style="font-size:11px;margin:4px 0">📅 Период: ${start} - ${end}</div>
        <div class="info-row" style="font-size:11px;margin:4px 0">📍 ${lat.toFixed(4)}, ${lng.toFixed(4)}</div>
        <div class="info-row" style="margin-top:8px">
          <button id="pin-here" style="padding:6px 10px;font-size:11px;background:#007cba;color:white;border:none;border-radius:3px;cursor:pointer;width:100%">
            📍 Сохранить точку
          </button>
        </div>
        <div style="width:240px;height:90px;margin-top:8px"><canvas id="px-mini"></canvas></div>
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
      titiler_ok: response.titiler_ok === true
    };
  } catch (err) {
    console.error("API health check failed:", err);
    return { ok: false, cdse_ok: false, titiler_ok: false };
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
export function showError(containerEl, message, type = 'error') {
  const classes = {
    error: 'error-message',
    warning: 'warning-message',
    info: 'info-message'
  };
  
  const div = document.createElement('div');
  div.className = classes[type] || classes.error;
  div.innerHTML = `
    <strong>${type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️'} ${
      type === 'error' ? 'Ошибка' : type === 'warning' ? 'Внимание' : 'Информация'
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
export function showProgress(containerEl, message = 'Загрузка...') {
  const div = document.createElement('div');
  div.className = 'progress-container';
  div.innerHTML = `
    <div style="font-size:11px;color:#666;margin-bottom:5px">${message}</div>
    <div class="progress-bar">
      <div class="progress-bar-fill" style="width:0%"></div>
    </div>
  `;
  
  containerEl.appendChild(div);
  
  return {
    update: (percent) => {
      const fill = div.querySelector('.progress-bar-fill');
      if (fill) fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    },
    setText: (text) => {
      const label = div.querySelector('div:first-child');
      if (label) label.textContent = text;
    },
    remove: () => div.remove()
  };
}