// assets/biopar-ui.js
/* global Chart, L */
import {
  // Common utilities from ndvi-utils.js
  textColor, fetchJSON, fetchWithTimeout, showError, showProgress,
  NoDataError, APIError
} from "./ndvi-utils.js";

/* ==============================
   Leaflet safety pin for module
   ============================== */
const Lf = (window.__Leaflet || window.L);
if (!Lf || !Lf.Map || !Lf.Control || !Lf.tileLayer) {
  console.error('Leaflet API not ready inside biopar-ui.js', {
    L: window.L, __Leaflet: window.__Leaflet
  });
}

/** Регистрируем zoom-плагин Chart.js, если ещё не зарегистрирован */
(function ensureChartZoomRegistered(){
  try {
    const reg = Chart?.registry?.plugins;
    const already = reg && Object.keys(reg.items || {}).some(k => k.includes("zoom"));
    const plugin = window && window["chartjs-plugin-zoom"];
    if (!already && plugin) {
      Chart.register(plugin);
    }
  } catch (e) {
    console.warn('Failed to register Chart.js zoom plugin:', e);
  }
})();

/* ===================================
   BIOPAR утилиты (цвет, формат, шкалы)
   =================================== */

/**
 * Нормализует тип BIOPAR к верхнему регистру
 * @param {string} t - Тип параметра
 * @returns {string} Нормализованный тип
 */
export function normalizeType(t) {
  return (t || "FAPAR").toString().trim().toUpperCase();
}

/**
 * Форматирует значение BIOPAR в зависимости от типа
 * @param {string} type - Тип параметра
 * @param {number} v - Значение
 * @returns {string} Отформатированное значение
 */
export function formatBIOPARValue(type, v) {
  if (v == null || Number.isNaN(v)) return "—";
  const T = normalizeType(type);
  
  if (T === "FAPAR" || T === "FCOVER") {
    return Number(v).toFixed(3);
  }
  if (T === "LAI") {
    return Number(v).toFixed(2);
  }
  // CCC/CWC — значения зависят от культуры/единиц (г/м²)
  if (T === "CCC" || T === "CWC") {
    return `${Number(v).toFixed(1)} г/м²`;
  }
  return Number(v).toFixed(2);
}

/**
 * Возвращает цвет для значения BIOPAR
 * @param {string} type - Тип параметра
 * @param {number} v - Значение
 * @returns {string} HEX цвет
 */
export function getBIOPARColor(type, v) {
  const T = normalizeType(type);
  if (v == null || Number.isNaN(v)) return "#cccccc";

  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  // FAPAR/FCOVER: 0..1 (красный -> жёлтый -> зелёный)
  if (T === "FAPAR" || T === "FCOVER") {
    const x = clamp(v, 0, 1);
    if (x < 0.1) return "#8b0000";      // Тёмно-красный
    if (x < 0.25) return "#d2691e";     // Шоколадный
    if (x < 0.5) return "#daa520";      // Золотой
    if (x < 0.7) return "#90ee90";      // Светло-зелёный
    return "#228b22";                    // Лесной зелёный
  }
  
  // LAI: 0..6 (бледно-жёлтый -> зелёный -> тёмно-зелёный)
  if (T === "LAI") {
    const x = clamp(v / 6, 0, 1);
    if (x < 0.1) return "#8b0000";
    if (x < 0.25) return "#d2691e";
    if (x < 0.45) return "#daa520";
    if (x < 0.75) return "#90ee90";
    return "#2e8b57";                    // Морской зелёный
  }
  
  // CCC: содержание хлорофилла (г/м²)
  if (T === "CCC") {
    const x = clamp(v / 300, 0, 1);     // Нормализуем к ~300 г/м² max
    if (x < 0.17) return "#8b0000";
    if (x < 0.33) return "#d2691e";
    if (x < 0.67) return "#90ee90";
    return "#228b22";
  }
  
  // CWC: содержание воды (г/м²)
  if (T === "CWC") {
    const x = clamp(v / 600, 0, 1);     // Нормализуем к ~600 г/м² max
    if (x < 0.17) return "#8b0000";
    if (x < 0.33) return "#d2691e";
    if (x < 0.67) return "#4682b4";     // Стальной синий
    return "#1e90ff";                    // Dodger синий
  }
  
  // Fallback для неизвестных типов
  return "#6c757d";
}

/**
 * Определяет статус растительности по среднему значению BIOPAR
 * @param {string} type - Тип параметра
 * @param {number} mean - Среднее значение
 * @returns {object} Статус с уровнем и описанием
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
  
  // Fallback для неизвестных типов
  return { 
    level: "Нет шкалы", 
    status: "neutral", 
    description: "Статус зависит от культуры и фазы развития" 
  };
}

/* ================================
   Сводная карточка по /biopar/stats
   ================================ */

/**
 * Отображает сводную статистику BIOPAR
 * @param {object} params - Параметры запроса
 * @param {string} params.apiBase - Базовый URL API
 * @param {array} params.bbox - Bbox координаты
 * @param {string} params.start - Начальная дата
 * @param {string} params.end - Конечная дата
 * @param {string} params.bioparType - Тип параметра
 * @param {HTMLElement} params.container - Контейнер для отображения
 */
export async function renderBIOPARSummary({
  apiBase, bbox, start, end, bioparType, container
}) {
  const T = normalizeType(bioparType);
  
  container.innerHTML = `
    <div style="padding:12px;background:#f8f9fa;border:1px solid #e9ecef;border-radius:6px;font-size:12px">
      <div style="display:flex;align-items:center;gap:8px;">
        <div class="spinner-border spinner-border-sm" role="status" style="width:16px;height:16px;border-width:2px"></div>
        <span>Загрузка статистики ${T}…</span>
      </div>
    </div>`;

  try {
    const url = `${apiBase}/biopar/stats?bbox=${bbox.join(",")}&start=${start}&end=${end}&biopar_type=${encodeURIComponent(T)}`;
    const js = await fetchJSON(url, { maxRetries: 1, timeout: 60000 });

    if (!js || js.status !== "success" || !js.statistics) {
      throw new Error("Invalid /biopar/stats response");
    }

    const s = js.statistics || {};
    const mean = s.mean;
    const cls  = statusBIOPAR(T, mean);
    const color = getBIOPARColor(T, mean);
    const txt = textColor(color);

    const pct = s.percentiles || {};
    const pList = [
      ["p10", pct.p10], ["p25", pct.p25], ["p50", pct.p50],
      ["p75", pct.p75], ["p90", pct.p90]
    ].map(([k, v]) => `
      <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0">
        <span style="color:#666">${k.toUpperCase()}</span>
        <strong>${formatBIOPARValue(T, v)}</strong>
      </div>`).join("");

    container.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <!-- Левая колонка -->
        <div>
          <div style="font-size:11px;color:#666;margin-bottom:6px;font-weight:600;">📅 Период</div>
          <div style="font-size:12px;font-weight:bold;margin-bottom:12px;">${start} — ${end}</div>

          <div style="font-size:11px;color:#666;margin-bottom:6px;font-weight:600;">📊 Среднее ${T}</div>
          <div style="padding:16px;border-radius:6px;text-align:center;font-size:22px;font-weight:bold;background:${color};color:${txt};box-shadow:0 2px 4px rgba(0,0,0,0.1)">
            ${formatBIOPARValue(T, mean)}
          </div>

          <div style="margin-top:12px;padding:8px;background:#f8f9fa;border-radius:4px;border-left:3px solid ${color}">
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
              <strong>${formatBIOPARValue(T, s.min)}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
              <span style="color:#666">Медиана</span>
              <strong>${formatBIOPARValue(T, s.median)}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
              <span style="color:#666">Максимум</span>
              <strong>${formatBIOPARValue(T, s.max)}</strong>
            </div>
            
            ${s.std != null ? `
              <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0;border-bottom:1px solid #f1f3f5">
                <span style="color:#666">Ст. откл.</span>
                <strong>${formatBIOPARValue(T, s.std)}</strong>
              </div>
            ` : ""}
            
            <div style="height:1px;background:#e9ecef;margin:4px 0"></div>
            <div style="font-size:10px;color:#888;margin-bottom:4px;font-weight:600;">Перцентили</div>
            ${pList}
            
            ${s.pixels ? `
              <div style="height:1px;background:#e9ecef;margin:8px 0 4px"></div>
              <div style="display:flex;justify-content:space-between;font-size:11px;padding:4px 0">
                <span style="color:#666">Пикселей</span>
                <strong>${s.pixels.toLocaleString()}</strong>
              </div>
            ` : ""}
          </div>
        </div>
      </div>`;
      
  } catch (e) {
    console.warn("BIOPAR /stats error:", e);
    
    const message = e instanceof NoDataError
      ? "Нет данных для построения статистики"
      : "Статистика недоступна";
    
    container.innerHTML = `
      <div style="padding:16px;text-align:center;color:#666;font-size:12px;background:#f8f9fa;border-radius:6px;border:1px solid #e9ecef;">
        <div style="font-size:24px;margin-bottom:8px;">📊</div>
        <div style="font-weight:600;margin-bottom:4px;">${message}</div>
        <div style="font-size:11px;color:#999;line-height:1.4">${e.message || "Эндпоинт /biopar/stats не отвечает"}</div>
      </div>`;
  }
}

/* =====================================
   График временного ряда /biopar/timeseries
   ===================================== */

/**
 * Строит график временного ряда BIOPAR
 * @param {object} params - Параметры графика
 * @param {HTMLCanvasElement} params.canvas - Canvas элемент
 * @param {array} params.timeline - Массив данных временного ряда
 * @param {string} params.bioparType - Тип параметра
 */
export function buildBIOPARChart({ canvas, timeline, bioparType }) {
  const T = normalizeType(bioparType);

  // Уничтожаем старый график
  if (canvas._chart) {
    canvas._chart.destroy();
    canvas._chart = null;
  }
  
  if (!timeline || timeline.length === 0) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const labels = timeline.map(i => i.date);
  const dsMean = timeline.map(i => i.mean ?? null);
  const dsMax  = timeline.map(i => i.max ?? null);
  const dsMin  = timeline.map(i => i.min ?? null);
  const dsStd  = timeline.map(i => i.std ?? null);

  // Проверяем наличие стандартного отклонения
  const hasStd = dsStd.some(v => v != null && v > 0);

  const datasets = [
    {
      label: `Средний ${T}`,
      data: dsMean,
      borderColor: "#007cba",
      backgroundColor: "rgba(0,124,186,0.10)",
      tension: 0.35,
      fill: true,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: "#007cba",
      pointBorderColor: "#fff",
      pointBorderWidth: 2
    },
    {
      label: `Макс ${T}`,
      data: dsMax,
      borderColor: "#28a745",
      borderDash: [5, 5],
      fill: false,
      pointRadius: 2,
      pointHoverRadius: 4,
      pointBackgroundColor: "#28a745"
    },
    {
      label: `Мин ${T}`,
      data: dsMin,
      borderColor: "#dc3545",
      borderDash: [5, 5],
      fill: false,
      pointRadius: 2,
      pointHoverRadius: 4,
      pointBackgroundColor: "#dc3545"
    }
  ];

  // Определяем конфигурацию оси Y в зависимости от типа
  const yCfg = (() => {
    if (T === "FAPAR" || T === "FCOVER") {
      return { beginAtZero: true, max: 1, title: { display: true, text: T } };
    }
    if (T === "LAI") {
      return { beginAtZero: true, max: 6, title: { display: true, text: `${T} (м²/м²)` } };
    }
    if (T === "CCC") {
      return { beginAtZero: true, title: { display: true, text: `${T} (г/м²)` } };
    }
    if (T === "CWC") {
      return { beginAtZero: true, title: { display: true, text: `${T} (г/м²)` } };
    }
    return { beginAtZero: true };
  })();

  canvas._chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: {
          position: "bottom",
          labels: { 
            boxWidth: 12, 
            font: { size: 10 }, 
            padding: 8,
            usePointStyle: true
          }
        },
        title: {
          display: true,
          text: `Динамика ${T} за период`,
          font: { size: 13, weight: "bold" },
          padding: { top: 5, bottom: 12 }
        },
        tooltip: {
          backgroundColor: "rgba(0, 0, 0, 0.85)",
          padding: 12,
          bodyFont: { size: 11 },
          titleFont: { size: 12, weight: "bold" },
          callbacks: {
            label: (ctx) => {
              const label = ctx.dataset.label || "";
              const value = ctx.parsed.y;
              if (value == null) return `${label}: нет данных`;
              return `${label}: ${formatBIOPARValue(T, value)}`;
            }
          }
        },
        zoom: {
          pan: { enabled: true, mode: "x" },
          zoom: {
            wheel: { enabled: true },
            drag: { enabled: false },
            pinch: { enabled: true },
            mode: "x"
          }
        }
      },
      scales: {
        y: {
          ...yCfg,
          ticks: { 
            font: { size: 10 },
            callback: function(value) {
              return formatBIOPARValue(T, value);
            }
          },
          grid: { color: "rgba(0, 0, 0, 0.05)" }
        },
        x: {
          ticks: { 
            font: { size: 9 }, 
            maxRotation: 45, 
            minRotation: 45,
            autoSkip: true,
            maxTicksLimit: 12
          },
          grid: { display: false }
        }
      }
    }
  });

  // Двойной клик — сброс масштаба
  canvas.ondblclick = () => {
    try { 
      canvas._chart.resetZoom(); 
    } catch (e) {
      console.warn('Failed to reset zoom:', e);
    }
  };
}

/* ==============
   Экспорт в CSV
   ============== */

/**
 * Экспортирует временной ряд в CSV файл
 * @param {array} timeline - Данные временного ряда
 * @param {string} bioparType - Тип параметра
 */
export function exportBIOPARCSV(timeline, bioparType) {
  const T = normalizeType(bioparType);
  
  if (!timeline || timeline.length === 0) {
    alert("Нет данных для экспорта");
    return;
  }

  // Определяем доступные поля
  const firstItem = timeline[0];
  const hasStd = 'std' in firstItem;
  const hasPercentiles = firstItem.percentiles != null;

  // Формируем заголовок
  let header = "date,mean,min,max";
  if (hasStd) header += ",std";
  if (hasPercentiles) header += ",p10,p25,p50,p75,p90";

  // Формируем строки
  const lines = [header];
  
  for (const row of timeline) {
    let line = `${row.date},${row.mean ?? ""},${row.min ?? ""},${row.max ?? ""}`;
    if (hasStd) line += `,${row.std ?? ""}`;
    if (hasPercentiles && row.percentiles) {
      const p = row.percentiles;
      line += `,${p.p10 ?? ""},${p.p25 ?? ""},${p.p50 ?? ""},${p.p75 ?? ""},${p.p90 ?? ""}`;
    }
    lines.push(line);
  }

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  
  const startDate = timeline[0]?.date || "period";
  const endDate = timeline[timeline.length - 1]?.date || "period";
  a.download = `biopar_${T.toLowerCase()}_${startDate}_to_${endDate}.csv`;
  
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ======================
   Тайм-слайдер / анимация
   ====================== */

/**
 * Настраивает слайдер временной линии
 * @param {object} params - Параметры слайдера
 */
export function setupTimelineSlider({
  rowEl, sliderEl, labelEl, timeline, onChange
}) {
  if (!timeline || timeline.length === 0) {
    rowEl.style.display = "none";
    return;
  }
  
  rowEl.style.display = "flex";
  sliderEl.min = 0;
  sliderEl.max = timeline.length - 1;
  sliderEl.value = timeline.length - 1;
  labelEl.textContent = timeline[timeline.length - 1].date;

  sliderEl.oninput = (e) => {
    const i = parseInt(e.target.value, 10);
    if (!timeline[i]) return;
    labelEl.textContent = timeline[i].date;
    onChange(i, timeline[i]);
  };
}

/**
 * Запускает/останавливает анимацию временного ряда
 * @param {object} params - Параметры анимации
 */
export function runAnimation({
  btnEl, timeline, onTick, getIndex, setIndex
}) {
  // Остановка анимации
  if (btnEl._timer) {
    clearInterval(btnEl._timer);
    btnEl._timer = null;
    btnEl.classList.add("muted");
    btnEl.textContent = "▶️ Анимация";
    return;
  }
  
  if (!timeline || timeline.length === 0) {
    alert("Нет данных для анимации");
    return;
  }
  
  // Получаем скорость из слайдера
  const speedSlider = document.getElementById("animation-speed");
  const interval = speedSlider ? parseInt(speedSlider.value, 10) : 1000;
  
  btnEl.classList.remove("muted");
  btnEl.textContent = "⏸ Пауза";
  
  btnEl._timer = setInterval(async () => {
    const i = getIndex();
    
    try {
      await onTick(i, timeline[i]);
    } catch (e) {
      console.error("Animation error:", e);
      // При критической ошибке останавливаем
      if (e?.status >= 500) {
        clearInterval(btnEl._timer);
        btnEl._timer = null;
        btnEl.classList.add("muted");
        btnEl.textContent = "▶️ Анимация";
        showError("Анимация остановлена из-за ошибки сервера");
        return;
      }
    }
    
    setIndex((i + 1) % timeline.length);
  }, interval);
}

/* ======
   Пины
   ====== */

/**
 * Класс для управления сохранёнными точками
 */
export class BIOPARPins {
  constructor(storageKey = "biopar_pins") {
    this.storageKey = storageKey;
    this.items = JSON.parse(localStorage.getItem(storageKey) || "[]");
  }
  
  save() { 
    localStorage.setItem(this.storageKey, JSON.stringify(this.items)); 
  }
  
  add({ lat, lng, name }) {
    this.items.push({ 
      lat, 
      lng, 
      name: name || "Точка", 
      created: new Date().toISOString() 
    });
    this.save();
  }
  
  remove(i) { 
    this.items.splice(i, 1); 
    this.save(); 
  }
  
  clear() {
    this.items = [];
    this.save();
  }

  /**
   * Отображает список точек
   * @param {HTMLElement} container - Контейнер для списка
   * @param {object} map - Leaflet карта
   * @param {object} api - API параметры для графиков
   */
  renderList(container, map, api) {
    if (!this.items.length) {
      container.innerHTML = `
        <div style="color:#777;font-size:12px;padding:12px;text-align:center;background:#f8f9fa;border-radius:4px;border:1px dashed #dee2e6">
          <div style="font-size:24px;margin-bottom:4px">📍</div>
          <div>Нет сохранённых точек</div>
          <div style="font-size:10px;color:#999;margin-top:4px">Нажмите на карту для добавления</div>
        </div>`;
      return;
    }
    
    container.innerHTML = this.items.map((p, i) => `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding:8px;background:#f8f9fa;border-radius:4px;border-left:3px solid #007cba;transition:background 0.2s" onmouseover="this.style.background='#e9ecef'" onmouseout="this.style.background='#f8f9fa'">
        <div style="flex:1;min-width:0;">
          <div style="font-size:11px;font-weight:bold;margin-bottom:3px;color:#212529">${p.name}</div>
          <div style="font-size:10px;color:#6c757d">${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}</div>
        </div>
        <span style="display:flex;gap:4px;flex-shrink:0;">
          <button data-i="${i}" class="go" title="Перейти" style="font-size:11px;padding:4px 8px;background:#007cba;color:white;border:none;border-radius:3px;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='#006ba6'" onmouseout="this.style.background='#007cba'">🔍</button>
          <button data-i="${i}" class="plot" title="График" style="font-size:11px;padding:4px 8px;background:#28a745;color:white;border:none;border-radius:3px;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='#218838'" onmouseout="this.style.background='#28a745'">📈</button>
          <button data-i="${i}" class="rm" title="Удалить" style="font-size:11px;padding:4px 8px;background:#dc3545;color:white;border:none;border-radius:3px;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='#c82333'" onmouseout="this.style.background='#dc3545'">✕</button>
        </span>
      </div>`).join("");

    // Кнопка "перейти"
    container.querySelectorAll("button.go").forEach(b => {
      b.onclick = () => {
        const p = this.items[b.dataset.i];
        map.setView([p.lat, p.lng], 13);
        
        // Добавляем временный маркер с анимацией
        const marker = Lf.circleMarker([p.lat, p.lng], {
          radius: 8,
          color: "#007cba",
          fillColor: "#ffd54f",
          fillOpacity: 0.9,
          weight: 3
        }).addTo(map);
        
        // Анимация маркера
        let scale = 1;
        const animation = setInterval(() => {
          scale = scale === 1 ? 1.3 : 1;
          marker.setRadius(8 * scale);
        }, 300);
        
        setTimeout(() => {
          clearInterval(animation);
          marker.remove();
        }, 3000);
      };
    });

    // Кнопка "удалить"
    container.querySelectorAll("button.rm").forEach(b => {
      b.onclick = () => {
        if (confirm(`Удалить точку "${this.items[b.dataset.i].name}"?`)) {
          this.remove(b.dataset.i);
          this.renderList(container, map, api);
        }
      };
    });

    // Кнопка "график"
    container.querySelectorAll("button.plot").forEach(b => {
      b.onclick = () => this.plotSeries(this.items[b.dataset.i], map, api);
    });
  }

  /**
   * Отображает график временного ряда для точки
   * @param {object} pin - Данные точки
   * @param {object} map - Leaflet карта
   * @param {object} api - API параметры
   */
  async plotSeries(pin, map, { apiBase, bbox, start, end, bioparType }) {
    const T = normalizeType(bioparType);
    
    try {
      // Показываем индикатор загрузки на карте
      const loader = Lf.popup({ maxWidth: 200, closeButton: false })
        .setLatLng([pin.lat, pin.lng])
        .setContent(`
          <div style="text-align:center;padding:8px">
            <div class="spinner-border spinner-border-sm" role="status"></div>
            <div style="font-size:11px;margin-top:8px">Загрузка данных...</div>
          </div>`)
        .openOn(map);

      const url = `${apiBase}/biopar/timeseries?lon=${pin.lng}&lat=${pin.lat}&bbox=${bbox.join(",")}&start=${start}&end=${end}&biopar_type=${encodeURIComponent(T)}&max_dates=20`;
      const ts = await fetchJSON(url, { maxRetries: 1, timeout: 60000 });

      loader.remove();

      if (!ts || ts.status !== "success" || !Array.isArray(ts.series) || ts.series.length === 0) {
        alert(`Нет данных ${T} по точке за выбранный период`);
        return;
      }

      const cId = `pin-mini-${Math.random().toString(36).slice(2)}`;
      const popupHtml = `
        <div style="width:320px">
          <h4 style="margin:0 0 8px 0;font-size:13px;font-weight:bold">📍 ${pin.name || "Точка"}</h4>
          <div style="font-size:10px;color:#666;margin-bottom:8px;display:flex;justify-content:space-between">
            <span>${pin.lat.toFixed(4)}, ${pin.lng.toFixed(4)}</span>
            <span>${T}</span>
          </div>
          <div style="height:160px;margin-bottom:8px"><canvas id="${cId}"></canvas></div>
          <div style="font-size:10px;color:#666;text-align:center;padding:6px;background:#f8f9fa;border-radius:3px">
            ${ts.series.length} наблюдений • ${start} - ${end}
          </div>
        </div>`;
        
      Lf.popup({ maxWidth: 360, maxHeight: 320 })
        .setLatLng([pin.lat, pin.lng])
        .setContent(popupHtml)
        .openOn(map);

      const canvas = document.getElementById(cId);
      if (!canvas) return;

      if (canvas._chart) canvas._chart.destroy();
      
      canvas._chart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
          labels: ts.series.map(i => i.date),
          datasets: [{
            label: T,
            data: ts.series.map(i => i.mean ?? i.value ?? i[T.toLowerCase()]),
            borderColor: "#007cba",
            backgroundColor: "rgba(0,124,186,0.1)",
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 5,
            pointBackgroundColor: "#007cba",
            pointBorderColor: "#fff",
            pointBorderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { 
            legend: { display: false },
            title: { 
              display: true, 
              text: `Временной ряд ${T}`, 
              font: { size: 11, weight: 'bold' }
            },
            tooltip: {
              backgroundColor: 'rgba(0, 0, 0, 0.85)',
              padding: 10,
              callbacks: {
                label: (context) => `${T}: ${formatBIOPARValue(T, context.parsed.y)}`
              }
            }
          },
          scales: {
            y: { 
              beginAtZero: T === "FAPAR" || T === "FCOVER",
              max: T === "FAPAR" || T === "FCOVER" ? 1 : (T === "LAI" ? 6 : undefined),
              ticks: { 
                font: { size: 9 },
                callback: function(value) {
                  return formatBIOPARValue(T, value);
                }
              },
              grid: { color: 'rgba(0, 0, 0, 0.05)' }
            },
            x: { 
              ticks: { 
                font: { size: 9 }, 
                maxRotation: 45,
                autoSkip: true,
                maxTicksLimit: 8
              },
              grid: { display: false }
            }
          }
        }
      });
    } catch (err) {
      console.error("plotSeries error:", err);
      
      if (err instanceof NoDataError) {
        alert(`Нет спутниковых данных ${T} для этой точки за выбранный период`);
      } else {
        alert("Ошибка загрузки тайм-серии точки. Попробуйте позже.");
      }
    }
  }
}

/* ==================
   Инспектор клика
   ================== */

/**
 * Подключает инспектор точек на карту
 * @param {object} params - Параметры инспектора
 */
export async function attachBIOPARPointInspector({
  map, tiffUrl, start, end, bioparType, apiBase, bbox, pins
}) {
  const T = normalizeType(bioparType);

  const handler = async (e) => {
    // Режим добавления пинов
    if (map._pinning) {
      const name = prompt("Название точки (опционально):", "Поле");
      if (name !== null) {
        pins.add({ lat: e.latlng.lat, lng: e.latlng.lng, name: name || "Точка" });
        
        Lf.circleMarker(e.latlng, { 
          radius: 6, 
          color: "#111", 
          fillColor: "#ffd54f", 
          fillOpacity: 0.9, 
          weight: 2 
        })
        .addTo(map)
        .bindPopup(`<strong>${name || "Точка"}</strong><br>${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`)
        .openPopup();
      }
      
      map._pinning = false;
      document.getElementById("btn-pin")?.classList.add("muted");
      map.getContainer().style.cursor = "";
      return;
    }

    // Request pixel value via Titiler
    try {
      // For Titiler, use host.docker.internal
      const tiffUrlForTitiler = tiffUrl.replace('localhost', 'host.docker.internal');
      const pointUrl = `http://localhost:8008/cog/point/${e.latlng.lng},${e.latlng.lat}?url=${encodeURIComponent(tiffUrlForTitiler)}`;
      const resp = await fetchWithTimeout(pointUrl);

      if (!resp.ok) {
        console.warn("Titiler /point failed:", resp.status);
        return;
      }

      const js = await resp.json();
      const value = js?.values?.[0];

      if (value == null || Number.isNaN(value)) {
        // Click on nodata pixel
        return;
      }

      const color = getBIOPARColor(T, Number(value));
      const txt = textColor(color);
      
      Lf.popup({ maxWidth: 320 })
        .setLatLng(e.latlng)
        .setContent(`
          <div class="popup-content">
            <h4 style="margin:0 0 8px 0;font-weight:bold">${T} значение</h4>
            <div style="background:${color};color:${txt};padding:14px;border-radius:6px;text-align:center;font-size:22px;font-weight:bold;margin-bottom:10px;box-shadow:0 2px 4px rgba(0,0,0,0.1)">
              ${formatBIOPARValue(T, Number(value))}
            </div>
            <div style="font-size:11px;margin:4px 0;color:#666">📅 Период: ${start} — ${end}</div>
            <div style="font-size:11px;margin:4px 0;color:#666">📍 ${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}</div>
            <div style="margin-top:10px">
              <button id="pin-here" style="padding:8px 12px;font-size:11px;background:#007cba;color:white;border:none;border-radius:4px;cursor:pointer;width:100%;font-weight:600;transition:background 0.2s" onmouseover="this.style.background='#006ba6'" onmouseout="this.style.background='#007cba'">
                📍 Сохранить точку
              </button>
            </div>
            <div style="width:280px;height:100px;margin-top:12px"><canvas id="px-mini"></canvas></div>
          </div>`)
        .openOn(map);

      // Обработчик сохранения точки
      document.getElementById("pin-here")?.addEventListener("click", () => {
        const name = prompt("Название точки (опционально):", "Поле");
        if (name !== null) {
          pins.add({ lat: e.latlng.lat, lng: e.latlng.lng, name: name || "Точка" });
          map.closePopup();
        }
      });

      // Мини-серия по точке в попапе
      try {
        const tsUrl = `${apiBase}/biopar/timeseries?lon=${e.latlng.lng}&lat=${e.latlng.lat}&bbox=${bbox.join(",")}&start=${start}&end=${end}&biopar_type=${encodeURIComponent(T)}&max_dates=15`;
        const ts = await fetchJSON(tsUrl, { maxRetries: 1, timeout: 30000 });
        
        const canvas = document.getElementById("px-mini");
        if (ts?.status === "success" && canvas && ts.series && ts.series.length > 0) {
          new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
              labels: ts.series.map(i => i.date),
              datasets: [{
                label: T,
                data: ts.series.map(i => i.mean ?? i.value ?? i[T.toLowerCase()]),
                borderColor: "#007cba",
                backgroundColor: "rgba(0,124,186,0.08)",
                tension: 0.35,
                pointRadius: 2,
                pointHoverRadius: 4
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                y: { 
                  beginAtZero: T === "FAPAR" || T === "FCOVER",
                  max: T === "FAPAR" || T === "FCOVER" ? 1 : (T === "LAI" ? 6 : undefined),
                  ticks: { display: false }, 
                  grid: { display: false } 
                },
                x: { 
                  ticks: { display: false }, 
                  grid: { display: false } 
                }
              }
            }
          });
        }
      } catch (err) {
        console.warn("Mini timeseries failed:", err);
        // Не показываем ошибку пользователю, просто нет графика
      }
    } catch (err) {
      console.error("BIOPAR point inspector error:", err);
    }
  };

  map.on("click", handler);
  return () => map.off("click", handler);
}

/* =========================
   Сравнение (side-by-side)
   ========================= */

// Утилиты для работы с Leaflet
function _getL() { 
  return (window.Lf || window.__Leaflet || window.L); 
}

function _sleep(ms) { 
  return new Promise(r => setTimeout(r, ms)); 
}

async function _waitLeaflet(maxMs = 8000) {
  const t0 = Date.now();
  while (!(window.L && L.Map)) {
    if (Date.now() - t0 > maxMs) {
      throw new Error('Leaflet failed to initialize');
    }
    await _sleep(25);
  }
  window.Lf = window.Lf || window.L;
  return window.L;
}

// Плагины не загружаем — используем fallback
let _pluginsReady = null;

async function ensureLeafletPlugins() {
  if (_pluginsReady) return _pluginsReady;
  _pluginsReady = (async () => { 
    await _waitLeaflet(); 
  })();
  return _pluginsReady;
}

async function ensureSideBySideLoaded() {
  await _waitLeaflet();
  return null; // всегда используем fallback
}

/**
 * Создаёт простой контрол side-by-side с DIV слайдером
 */
function createSimpleSideBySide(Lref, map, leftLayer, rightLayer) {
  const mapEl = map.getContainer();
  const leftEl = leftLayer.getContainer ? leftLayer.getContainer() : leftLayer._container;
  const rightEl = rightLayer.getContainer ? rightLayer.getContainer() : rightLayer._container;
  
  if (!leftEl || !rightEl) {
    throw new Error('Layer containers not found');
  }

  const bar = document.createElement('div');
  bar.style.cssText = 'position:absolute;top:0;bottom:0;width:4px;cursor:ew-resize;z-index:1000;background:rgba(0,0,0,.4);box-shadow:0 0 4px rgba(255,255,255,.8)';
  mapEl.appendChild(bar);

  let x = Math.round(mapEl.clientWidth / 2);
  let dragging = false;

  function apply() {
    const w = mapEl.clientWidth;
    const h = mapEl.clientHeight;
    const xr = Math.max(0, Math.min(w, x));
    
    leftEl.style.clip = `rect(0px, ${xr}px, ${h}px, 0px)`;
    rightEl.style.clip = `rect(0px, ${w}px, ${h}px, ${xr}px)`;
    bar.style.left = `${xr - 2}px`;
  }

  function down(e) { 
    dragging = true; 
    e.preventDefault(); 
  }
  
  function move(e) {
    if (!dragging) return;
    const rect = mapEl.getBoundingClientRect();
    x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    apply();
  }
  
  function up() { 
    dragging = false; 
  }

  bar.addEventListener('mousedown', down);
  bar.addEventListener('touchstart', down, { passive: false });
  window.addEventListener('mousemove', move);
  window.addEventListener('touchmove', move, { passive: false });
  window.addEventListener('mouseup', up);
  window.addEventListener('touchend', up);

  map.on('resize', apply);
  map.on('move', apply);
  apply();

  return {
    remove() {
      leftEl.style.clip = rightEl.style.clip = '';
      bar.remove();
      window.removeEventListener('mousemove', move);
      window.removeEventListener('touchmove', move);
      window.removeEventListener('mouseup', up);
      window.removeEventListener('touchend', up);
      map.off('resize', apply);
      map.off('move', apply);
    }
  };
}

/**
 * Определяет параметр rescale для типа BIOPAR
 */
function _rescaleForType(type) {
  const T = normalizeType(type);
  if (T === "FAPAR" || T === "FCOVER") return "0,1";
  if (T === "LAI") return "0,6";
  if (T === "CCC") return "0,300";
  if (T === "CWC") return "0,600";
  return null;
}

/**
 * Создаёт режим сравнения side-by-side для BIOPAR
 * @param {object} params - Параметры сравнения
 */
export async function buildBIOPARSideBySide({
  map, apiBase, bbox, dateA, dateB, bioparType
}) {
  const T = normalizeType(bioparType);
  const rescale = _rescaleForType(T);
  
  if (!rescale) {
    alert(`${T}: side-by-side визуализация пока не поддержана (требуется шкала rescale).`);
    throw new Error("Unsupported bioparType for side-by-side");
  }

  await ensureLeafletPlugins();
  await ensureSideBySideLoaded();

  const Lref = _getL();

  const fetchLayer = async (dateStr) => {
    const js = await fetchJSON(
      `${apiBase}/biopar/geotiff?bbox=${bbox.join(",")}&start=${dateStr}&end=${dateStr}&biopar_type=${encodeURIComponent(T)}`,
      { maxRetries: 1, timeout: 120000 }
    );
    
    let tiffUrl = (js && typeof js === 'object' && js.tiff_url) 
      ? js.tiff_url 
      : (typeof js === 'string' ? js : null);
      
    if (!tiffUrl) {
      throw new Error('BIOPAR geotiff endpoint returned no tiff_url');
    }

    // Если frontend в Docker — заменим localhost
    const tiffUrlForTitiler = tiffUrl.replace('localhost', 'host.docker.internal');

    const url = `/titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=${encodeURIComponent(tiffUrl)}&bidx=1&rescale=${rescale}&colormap_name=rdylgn&return_mask=true`;

    return Lref.tileLayer(url, {
      opacity: 0.95,
      maxZoom: 18,
      attribution: `${T} ${dateStr}`
    });
  };

  try {

    const left = await fetchLayer(dateA);
    const right = await fetchLayer(dateB);
    
    left.addTo(map);
    right.addTo(map);

    const simple = createSimpleSideBySide(Lref, map, left, right);
    const cleanup = () => { 
      try { 
        simple.remove(); 
        left.remove(); 
        right.remove(); 
      } catch(e) {
        console.warn('Cleanup error:', e);
      } 
    };

    const notice = document.createElement('div');
    notice.style.cssText = 'position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:1000;background:#fff;padding:12px 18px;border-radius:6px;box-shadow:0 3px 10px rgba(0,0,0,0.25);font-size:12px;font-weight:600';
    notice.innerHTML = `🔄 Сравнение ${T}:
      <span style="color:#007cba;font-weight:bold">${dateA}</span>
      <span style="margin:0 8px">⟷</span>
      <span style="color:#28a745;font-weight:bold">${dateB}</span>
      <span style="color:#6c757d;font-weight:normal;font-size:11px;margin-left:12px">
        Нажмите "Сравнить" снова для выхода
      </span>`;
    map.getContainer().appendChild(notice);

    return () => { 
      try { 
        cleanup(); 
        notice.remove(); 
      } catch(e) {
        console.warn('Cleanup wrapper error:', e);
      } 
    };
    
  } catch (err) {
    console.error('buildBIOPARSideBySide error:', err);
    
    if (err instanceof NoDataError) {
      alert('Нет данных для одной или обеих дат сравнения');
    } else if (err instanceof APIError) {
      alert(`Ошибка API: ${err.message}`);
    } else {
      alert('Ошибка создания режима сравнения. Проверьте консоль.');
    }
    
    throw err;
  }
}

/* =========================================
   Вспомогательная загрузка тайм-серии с API
   ========================================= */

/**
 * Загружает временной ряд BIOPAR
 * @param {object} params - Параметры запроса
 * @returns {Promise<object>} Данные временного ряда
 */
export async function loadBIOPARTimeseries({
  apiBase, bbox, start, end, bioparType, aggregationDays = 10
}) {
  const T = normalizeType(bioparType);
  const url = `${apiBase}/biopar/timeseries?bbox=${bbox.join(",")}&start=${start}&end=${end}&biopar_type=${encodeURIComponent(T)}&agg=${aggregationDays}`;
  
  const js = await fetchJSON(url, { maxRetries: 1, timeout: 120000 });
  
  if (!js || js.status !== "success" || !Array.isArray(js.timeline)) {
    throw new Error("Invalid /biopar/timeseries response");
  }
  
  return js;
}

/* =======================================
   Загрузка GeoTIFF URL с API
   ======================================= */

/**
 * Получает URL GeoTIFF для BIOPAR
 * @param {object} params - Параметры запроса
 * @returns {Promise<string>} URL GeoTIFF файла
 */
export async function loadBIOPARGTIFFUrl({
  apiBase, bbox, start, end, bioparType
}) {
  const T = normalizeType(bioparType);
  const js = await fetchJSON(
    `${apiBase}/biopar/geotiff?bbox=${bbox.join(",")}&start=${start}&end=${end}&biopar_type=${encodeURIComponent(T)}`,
    { maxRetries: 1, timeout: 120000 }
  );
  
  const tiffUrl = js?.tiff_url || (typeof js === "string" ? js : null);
  
  if (!tiffUrl) {
    throw new Error("No tiff_url from /biopar/geotiff");
  }
  
  // УБРАТЬ ЭТУ СТРОКУ:
  // return tiffUrl.replace('localhost', 'host.docker.internal');
  
  // Вернуть как есть:
  return tiffUrl;
}