// assets/ndvi-ui.js
/* global Chart, L */
import {
  getNDVIColor, textColor, fetchJSON, fetchWithTimeout, showError, showProgress,
  NoDataError, APIError
} from "./ndvi-utils.js";

/* ==============================
   Leaflet safety pin for module
   ============================== */
const Lf = (window.__Leaflet || window.L);
if (!Lf || !Lf.Map || !Lf.Control || !Lf.tileLayer) {
  console.error('Leaflet API not ready inside ndvi-ui.js', { 
    L: window.L, __Leaflet: window.__Leaflet 
  });
}

/** Регистрируем zoom-плагин Chart.js, если подключён через <script> и ещё не зарегистрирован */
(function ensureChartZoomRegistered(){
  try {
    const reg = Chart?.registry?.plugins;
    const already = reg && Object.keys(reg.items || {}).some(k => k.includes("zoom"));
    const plugin = window && window["chartjs-plugin-zoom"];
    if (!already && plugin) {
      Chart.register(plugin);
    }
  } catch (_) {}
})();

/* =========================
   Пирог + таблица по классам
   ========================= */
export async function renderNDVIPie({ 
  apiBase, bbox, start, end, pieCanvas, tableContainer 
}) {
  try {
    const bins = [-1, 0, 0.2, 0.3, 0.6, 1];
    const url = `${apiBase}/ndvi/hist?bbox=${bbox.join(",")}&start=${start}&end=${end}&bins=${bins.join(",")}`;
    
    const js = await fetchJSON(url, { maxRetries: 1, retryDelay: 2000 });
    
    if (!js || js.status !== "success" || !Array.isArray(js.bins)) {
      throw new Error("Invalid histogram response");
    }

    const labels = js.bins.map(b => b.label);
    const data = js.bins.map(b => b.pct);
    const colors = ["#0066cc", "#8b4513", "#daa520", "#90ee90", "#228b22"];

    // Уничтожаем старый график
    if (pieCanvas._chart) {
      pieCanvas._chart.destroy();
      pieCanvas._chart = null;
    }
    
    pieCanvas._chart = new Chart(pieCanvas.getContext("2d"), {
      type: "doughnut",
      data: { 
        labels, 
        datasets: [{ 
          data, 
          backgroundColor: colors,
          borderWidth: 2,
          borderColor: '#fff'
        }] 
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { 
          legend: { 
            position: "bottom", 
            labels: { 
              font: { size: 10 },
              padding: 10
            } 
          },
          tooltip: {
            callbacks: {
              label: (context) => {
                const label = context.label || '';
                const value = context.parsed || 0;
                return `${label}: ${value.toFixed(1)}%`;
              }
            }
          }
        },
        cutout: "55%"
      }
    });

    // Таблица с процентами
    tableContainer.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr auto;gap:4px 10px;font-size:11px;margin-top:8px">
        ${js.bins.map(b => `
          <div style="color:#666">${b.label}</div>
          <div style="font-weight:bold;text-align:right">${b.pct.toFixed(1)}%</div>
        `).join("")}
        ${js.total ? `
          <div style="color:#666;grid-column:1/-1;border-top:1px solid #ddd;padding-top:4px;margin-top:4px">
            Всего пикселей: <strong>${js.total.toLocaleString()}</strong>
          </div>
        ` : ""}
      </div>`;
      
  } catch (e) {
    console.warn("Histogram endpoint error:", e);
    
    // Уничтожаем график при ошибке
    if (pieCanvas._chart) {
      pieCanvas._chart.destroy();
      pieCanvas._chart = null;
    }
    
    const message = e instanceof NoDataError
      ? "Нет данных для построения гистограммы"
      : "Гистограмма недоступна";
    
    tableContainer.innerHTML = `
      <div style="padding:12px;text-align:center;color:#666;font-size:11px;background:#f8f9fa;border-radius:4px;">
        <div style="margin-bottom:6px">📊 ${message}</div>
        <div style="font-size:10px;color:#999">${e.message || "Эндпоинт /api/v1/ndvi/hist не отвечает"}</div>
      </div>`;
  }
}

/* =========================
   График времени + zoom/pan
   ========================= */
export function buildNDVIChart({ canvas, timeline }) {
  if (canvas._chart) {
    canvas._chart.destroy();
    canvas._chart = null;
  }

  if (!timeline || timeline.length === 0) {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const labels = timeline.map(i => i.date);
  const dsMean = timeline.map(i => i.mean_ndvi);
  const dsMax  = timeline.map(i => i.max_ndvi);
  const dsMin  = timeline.map(i => i.min_ndvi);

  // Добавим стандартное отклонение если есть
  const dsStd = timeline.map(i => i.std_ndvi);
  const hasStd = dsStd.some(v => v != null && v > 0);

  const datasets = [
    { 
      label: "Средний NDVI", 
      data: dsMean, 
      borderColor: "#007cba", 
      backgroundColor: "rgba(0,124,186,0.10)", 
      tension: 0.4,
      fill: true,
      pointRadius: 3,
      pointHoverRadius: 5
    },
    { 
      label: "Макс NDVI",    
      data: dsMax,  
      borderColor: "#28a745", 
      borderDash: [5, 5], 
      fill: false,
      pointRadius: 2,
      pointHoverRadius: 4
    },
    { 
      label: "Мин NDVI",     
      data: dsMin,  
      borderColor: "#dc3545", 
      borderDash: [5, 5], 
      fill: false,
      pointRadius: 2,
      pointHoverRadius: 4
    }
  ];

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
            padding: 8
          } 
        },
        title: { 
          display: true, 
          text: "Динамика NDVI за период", 
          font: { size: 12, weight: 'bold' },
          padding: { top: 5, bottom: 10 }
        },
        tooltip: {
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          padding: 10,
          bodyFont: { size: 11 },
          callbacks: {
            label: (context) => {
              const label = context.dataset.label || '';
              const value = context.parsed.y;
              return `${label}: ${value.toFixed(3)}`;
            }
          }
        },
        zoom: {
          pan: { enabled: true, mode: "x" },
          zoom: { 
            wheel: { enabled: true }, 
            drag: { enabled: false }, // Отключаем drag zoom для удобства
            pinch: { enabled: true },
            mode: "x" 
          }
        }
      },
      scales: {
        y: { 
          beginAtZero: true, 
          max: 1, 
          ticks: { font: { size: 10 } },
          grid: { color: 'rgba(0, 0, 0, 0.05)' }
        },
        x: { 
          ticks: { 
            font: { size: 9 }, 
            maxRotation: 45, 
            minRotation: 45 
          },
          grid: { display: false }
        }
      }
    }
  });

  // Двойной клик сбрасывает zoom
  canvas.ondblclick = () => {
    try { 
      canvas._chart.resetZoom(); 
    } catch (_) {}
  };
}

/* ==============
   Экспорт в CSV
   ============== */
export function exportCSV(timeline) {
  if (!timeline || timeline.length === 0) {
    alert("Нет данных для экспорта");
    return;
  }
  
  // Определяем доступные поля
  const firstItem = timeline[0];
  const hasStd = 'std_ndvi' in firstItem;
  const hasPercentiles = firstItem.percentiles != null;
  
  // Формируем заголовок
  let header = "date,mean_ndvi,min_ndvi,max_ndvi";
  if (hasStd) header += ",std_ndvi";
  if (hasPercentiles) header += ",p10,p25,p50,p75,p90";
  
  // Формируем строки
  const lines = [header];
  
  for (const row of timeline) {
    let line = `${row.date},${row.mean_ndvi},${row.min_ndvi},${row.max_ndvi}`;
    if (hasStd) line += `,${row.std_ndvi || ''}`;
    if (hasPercentiles && row.percentiles) {
      line += `,${row.percentiles.p10 || ''},${row.percentiles.p25 || ''},${row.percentiles.p50 || ''},${row.percentiles.p75 || ''},${row.percentiles.p90 || ''}`;
    }
    lines.push(line);
  }
  
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  
  const startDate = timeline[0]?.date || "period";
  const endDate = timeline[timeline.length - 1]?.date || "period";
  a.download = `ndvi_timeline_${startDate}_to_${endDate}.csv`;
  
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ======================
   Тайм-слайдер / анимация
   ====================== */
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
  const interval = speedSlider ? parseInt(speedSlider.value) : 1000;
  
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
        return;
      }
    }
    
    setIndex((i + 1) % timeline.length);
  }, interval);
}

/* ======
   Пины
   ====== */
export class Pins {
  constructor(storageKey = "ndvi_pins") {
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

  renderList(container, map, api) {
    if (!this.items.length) {
      container.innerHTML = '<div style="color:#777;font-size:12px;padding:8px;text-align:center;">📍 Нет сохранённых точек</div>';
      return;
    }
    
    container.innerHTML = this.items.map((p, i) => `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding:6px;background:#f8f9fa;border-radius:3px;border-left:3px solid #007cba">
        <div style="flex:1;min-width:0;">
          <div style="font-size:11px;font-weight:bold;margin-bottom:2px;">${p.name}</div>
          <div style="font-size:10px;color:#666;">${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}</div>
        </div>
        <span style="display:flex;gap:4px;flex-shrink:0;">
          <button data-i="${i}" class="go" title="Перейти" style="font-size:11px;padding:3px 7px;background:#007cba;color:white;border:none;border-radius:3px;cursor:pointer">🔍</button>
          <button data-i="${i}" class="plot" title="График" style="font-size:11px;padding:3px 7px;background:#28a745;color:white;border:none;border-radius:3px;cursor:pointer">📈</button>
          <button data-i="${i}" class="rm" title="Удалить" style="font-size:11px;padding:3px 7px;background:#dc3545;color:white;border:none;border-radius:3px;cursor:pointer">✕</button>
        </span>
      </div>`).join("");

    // Кнопка "перейти"
    container.querySelectorAll("button.go").forEach(b => {
      b.onclick = () => {
        const p = this.items[b.dataset.i];
        map.setView([p.lat, p.lng], 12);
        
        // Добавляем временный маркер
        const marker = Lf.circleMarker([p.lat, p.lng], {
          radius: 8,
          color: "#007cba",
          fillColor: "#ffd54f",
          fillOpacity: 0.9,
          weight: 3
        }).addTo(map);
        
        setTimeout(() => marker.remove(), 3000);
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

  async plotSeries(pin, map, { apiBase, bbox, start, end }) {
    try {
      const url = `${apiBase}/ndvi/timeseries?lon=${pin.lng}&lat=${pin.lat}&bbox=${bbox.join(",")}&start=${start}&end=${end}&max_dates=20`;
      const ts = await fetchJSON(url, { maxRetries: 1 });

      if (!ts || ts.status !== "success" || !Array.isArray(ts.series) || ts.series.length === 0) {
        alert("Нет данных по точке за выбранный период");
        return;
      }

      const cId = `pin-mini-${Math.random().toString(36).slice(2)}`;
      const popupHtml = `
        <div style="width:300px">
          <h4 style="margin:0 0 8px 0;font-size:13px;">📍 ${pin.name || "Точка"}</h4>
          <div style="font-size:10px;color:#666;margin-bottom:8px;">
            ${pin.lat.toFixed(4)}, ${pin.lng.toFixed(4)}
          </div>
          <div style="height:150px"><canvas id="${cId}"></canvas></div>
          <div style="font-size:10px;color:#666;margin-top:6px;text-align:center;">
            ${ts.series.length} наблюдений • ${start} - ${end}
          </div>
        </div>`;
        
      Lf.popup({ maxWidth: 340, maxHeight: 300 })
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
            label: "NDVI",
            data: ts.series.map(i => i.ndvi),
            borderColor: "#007cba",
            backgroundColor: "rgba(0,124,186,0.1)",
            tension: 0.3,
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
              text: "Временной ряд NDVI", 
              font: { size: 11, weight: 'bold' }
            },
            tooltip: {
              backgroundColor: 'rgba(0, 0, 0, 0.8)',
              callbacks: {
                label: (context) => `NDVI: ${context.parsed.y.toFixed(3)}`
              }
            }
          },
          scales: {
            y: { 
              min: 0, 
              max: 1, 
              ticks: { font: { size: 9 } },
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
        alert("Нет спутниковых данных для этой точки за выбранный период");
      } else {
        alert("Ошибка загрузки тайм-серии точки. Попробуйте позже.");
      }
    }
  }
}

/* ==================
   Инспектор клика
   ================== */
export async function attachPointInspector({ 
  map, tiffUrl, start, end, apiBase, bbox, pins 
}) {
  const handler = async (e) => {
    // Режим пинов
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

    // Request pixel value from Titiler
    try {
      const pointUrl = `/titiler/cog/point/${e.latlng.lng},${e.latlng.lat}?url=${encodeURIComponent(tiffUrl)}`;
      const pointResp = await fetchWithTimeout(pointUrl);

      if (!pointResp.ok) {
        console.warn("Point fetch failed:", pointResp.status);
        return;
      }
      
      const pointData = await pointResp.json();
      const value = pointData?.values?.[0];
      
      if (value == null || Number.isNaN(value)) {
        // Клик на nodata пикселе
        return;
      }

      const color = getNDVIColor(Number(value));
      
      Lf.popup({ maxWidth: 300 })
        .setLatLng(e.latlng)
        .setContent(`
          <div class="popup-content">
            <h4 style="margin:0 0 8px 0">NDVI значение</h4>
            <div class="ndvi-value" style="background:${color};color:${textColor(color)};padding:12px;border-radius:4px;text-align:center;font-size:20px;font-weight:bold;margin-bottom:8px">
              ${Number(value).toFixed(3)}
            </div>
            <div class="info-row" style="font-size:11px;margin:4px 0">📅 Период: ${start} — ${end}</div>
            <div class="info-row" style="font-size:11px;margin:4px 0">📍 ${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}</div>
            <div class="info-row" style="margin-top:10px">
              <button id="pin-here" style="padding:6px 10px;font-size:11px;background:#007cba;color:white;border:none;border-radius:3px;cursor:pointer;width:100%">
                📍 Сохранить точку
              </button>
            </div>
            <div style="width:250px;height:100px;margin-top:10px"><canvas id="px-mini"></canvas></div>
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
        const tsUrl = `${apiBase}/ndvi/timeseries?lon=${e.latlng.lng}&lat=${e.latlng.lat}&bbox=${bbox.join(",")}&start=${start}&end=${end}&max_dates=15`;
        const ts = await fetchJSON(tsUrl, { maxRetries: 1, timeout: 30000 });
        
        const canvas = document.getElementById("px-mini");
        if (ts?.status === "success" && canvas && ts.series && ts.series.length > 0) {
          new Chart(canvas.getContext("2d"), {
            type: "line",
            data: {
              labels: ts.series.map(i => i.date),
              datasets: [{
                label: "NDVI",
                data: ts.series.map(i => i.ndvi),
                borderColor: "#007cba",
                backgroundColor: "rgba(0,124,186,0.08)",
                tension: 0.3,
                pointRadius: 2,
                pointHoverRadius: 4
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                y: { min: 0, max: 1, ticks: { display: false }, grid: { display: false } },
                x: { ticks: { display: false }, grid: { display: false } }
              }
            }
          });
        }
      } catch (err) {
        console.warn("Mini timeseries failed:", err);
        // Не показываем ошибку пользователю, просто нет графика
      }
    } catch (err) {
      console.error("Point inspector error:", err);
    }
  };

  map.on("click", handler);
  return () => map.off("click", handler);
}

/* =========================
   Сравнение (side-by-side)
   ========================= */

// Небольшие утилиты
function _getL(){ return (window.Lf || window.__Leaflet || window.L); }
function _sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
async function _waitLeaflet(maxMs=8000){
  const t0=Date.now();
  while(!(window.L && L.Map)){
    if(Date.now()-t0>maxMs) throw new Error('Leaflet failed to initialize');
    await _sleep(25);
  }
  window.Lf = window.Lf || window.L;
  return window.L;
}

// Плагины Leaflet (минимум): НИЧЕГО не грузим дополнительно
let _pluginsReady=null;
async function ensureLeafletPlugins(){
  if (_pluginsReady) return _pluginsReady;
  _pluginsReady = (async()=>{ await _waitLeaflet(); })();
  return _pluginsReady;
}

// Форсируем фоллбэк: плагин side-by-side не подгружаем
async function ensureSideBySideLoaded(){
  await _waitLeaflet();
  return null; // всегда используем fallback
}

// Фоллбэк-контрол: слайдер на DIV + clip
function createSimpleSideBySide(Lref, map, leftLayer, rightLayer){
  const mapEl=map.getContainer();
  const leftEl  = leftLayer.getContainer ? leftLayer.getContainer() : leftLayer._container;
  const rightEl = rightLayer.getContainer ? rightLayer.getContainer() : rightLayer._container;
  if (!leftEl || !rightEl) throw new Error('Layer containers not found');

  const bar=document.createElement('div');
  bar.style.cssText='position:absolute;top:0;bottom:0;width:3px;cursor:ew-resize;z-index:1000;background:rgba(0,0,0,.35);box-shadow:0 0 0 1px rgba(255,255,255,.6)';
  mapEl.appendChild(bar);

  let x=Math.round(mapEl.clientWidth/2), dragging=false;

  function apply(){
    const w=mapEl.clientWidth, h=mapEl.clientHeight, xr=Math.max(0,Math.min(w,x));
    leftEl .style.clip=`rect(0px, ${xr}px, ${h}px, 0px)`;
    rightEl.style.clip=`rect(0px, ${w}px, ${h}px, ${xr}px)`;
    bar.style.left=`${xr-1}px`;
  }
  function down(e){ dragging=true; e.preventDefault(); }
  function move(e){
    if(!dragging) return;
    const rect=mapEl.getBoundingClientRect();
    x=(e.touches?e.touches[0].clientX:e.clientX)-rect.left;
    apply();
  }
  function up(){ dragging=false; }

  bar.addEventListener('mousedown',down);
  bar.addEventListener('touchstart',down,{passive:false});
  window.addEventListener('mousemove',move);
  window.addEventListener('touchmove',move,{passive:false});
  window.addEventListener('mouseup',up);
  window.addEventListener('touchend',up);

  map.on('resize',apply);
  map.on('move',apply);
  apply();

  return {
    remove(){
      leftEl.style.clip=rightEl.style.clip='';
      bar.remove();
      window.removeEventListener('mousemove',move);
      window.removeEventListener('touchmove',move);
      window.removeEventListener('mouseup',up);
      window.removeEventListener('touchend',up);
      map.off('resize',apply);
      map.off('move',apply);
    }
  };
}

// Публичная точка входа
export async function buildSideBySide({ map, apiBase, bbox, dateA, dateB }) {
  await ensureLeafletPlugins();
  await ensureSideBySideLoaded(); // вернёт null — это ОК (фоллбэк)

  const Lref=_getL();

  const fetchLayer = async (dateStr) => {
    const js = await fetchJSON(
      `${apiBase}/ndvi/geotiff?bbox=${bbox.join(",")}&start=${dateStr}&end=${dateStr}`,
      { maxRetries: 1 }
    );
    let tiffUrl = (js && typeof js === 'object' && js.tiff_url) ? js.tiff_url : (typeof js === 'string' ? js : null);
    if (!tiffUrl) throw new Error('NDVI endpoint returned no tiff_url');

    // УБРАЛ replace — используем относительный путь
    // tiffUrl = tiffUrl.replace('localhost','host.docker.internal');

    const url = `/titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=${encodeURIComponent(tiffUrl)}&bidx=1&rescale=-0.2,1&colormap_name=rdylgn&return_mask=true`;

    return Lref.tileLayer(url, {
      opacity: 0.95,
      maxZoom: 18,
      attribution: `NDVI ${dateStr}`
    });
  };

  try {

    const left  = await fetchLayer(dateA);
    const right = await fetchLayer(dateB);
    left.addTo(map);
    right.addTo(map);

    const simple = createSimpleSideBySide(Lref, map, left, right);
    const cleanup = () => { try{ simple.remove(); left.remove(); right.remove(); }catch(e){} };

    const notice=document.createElement('div');
    notice.style.cssText='position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:1000;background:#fff;padding:10px 16px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,0.2);font-size:12px;font-weight:600';
    notice.innerHTML=`🔄 Сравнение:
      <span style="color:#007cba">${dateA}</span>
      ⟷
      <span style="color:#28a745">${dateB}</span>
      <span style="color:#666;font-weight:normal;font-size:11px;margin-left:8px">
        Нажмите "Сравнить" снова для выхода
      </span>`;
    map.getContainer().appendChild(notice);

    return ()=>{ try{ cleanup(); notice.remove(); }catch(e){} };
  } catch (err) {
    console.error('buildSideBySide error:', err);
    if (err instanceof NoDataError) alert('Нет данных для одной или обеих дат сравнения');
    else alert('Ошибка создания режима сравнения. Проверьте консоль.');
    throw err;
  }
}
