// frontend/assets/app.js

// Global error boundary
window.addEventListener('error', (event) => {
  console.error('Global error caught:', event.error);
  showGlobalError('An unexpected error occurred. Please refresh the page or contact support.');
  event.preventDefault();
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection:', event.reason);
  showGlobalError('An unexpected error occurred. Please try again or refresh the page.');
  event.preventDefault();
});

function showGlobalError(message) {
  const errorDiv = document.getElementById('error-overlay') || createErrorOverlay();
  errorDiv.querySelector('.error-message').textContent = message;
  errorDiv.style.display = 'flex';
}

function createErrorOverlay() {
  const overlay = document.createElement('div');
  overlay.id = 'error-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);display:none;align-items:center;justify-content:center;z-index:10000;';
  overlay.innerHTML = `
    <div style="background:white;padding:2rem;border-radius:8px;max-width:500px;text-align:center;">
      <h2 style="color:#d32f2f;margin-top:0;">Error</h2>
      <p class="error-message" style="margin:1rem 0;"></p>
      <button onclick="location.reload()" style="background:#007cba;color:white;border:none;padding:0.5rem 1.5rem;border-radius:4px;cursor:pointer;">Reload Page</button>
      <button onclick="this.parentElement.parentElement.style.display='none'" style="background:#666;color:white;border:none;padding:0.5rem 1.5rem;border-radius:4px;cursor:pointer;margin-left:0.5rem;">Dismiss</button>
    </div>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

// ====== Utilities ======
const debounce = (fn, delay) => {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
};

/**
 * Fetch with timeout support to prevent hanging requests
 * @param {string} url - The URL to fetch
 * @param {object} options - Fetch options (timeout in ms can be specified)
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options = {}) {
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
 * Request deduplication utility to prevent duplicate concurrent requests
 * Maintains a cache of in-flight requests by key
 */
const requestCache = new Map();

/**
 * Deduplicated fetch - prevents multiple identical requests from running concurrently
 * @param {string} cacheKey - Unique key for this request
 * @param {Function} fetchFn - Async function that performs the fetch
 * @returns {Promise} Result of the fetch operation
 */
async function dedupedFetch(cacheKey, fetchFn) {
  // If request already in flight, return the existing promise
  if (requestCache.has(cacheKey)) {
    console.debug(`Request deduplication: using cached promise for ${cacheKey}`);
    return requestCache.get(cacheKey);
  }

  // Start new request and cache the promise
  const promise = fetchFn();
  requestCache.set(cacheKey, promise);

  try {
    const result = await promise;
    return result;
  } finally {
    // Remove from cache when complete (success or failure)
    requestCache.delete(cacheKey);
  }
}

// ====== RectSelector (выделение області на карте) ======
class RectSelector {
  constructor(map, options = {}) {
    this.map = map;
    this.onSelect = options.onSelect || (() => {});
    this.active = false;
    this.startLatLng = null;
    this.rectangle = null;
    this.hint = null;
    
    this._onMouseDown = this._handleMouseDown.bind(this);
    this._onMouseMove = this._handleMouseMove.bind(this);
    this._onMouseUp = this._handleMouseUp.bind(this);
  }

  enable() {
    if (this.active) return;
    this.active = true;
    this.map.getContainer().style.cursor = 'crosshair';
    this.map.dragging.disable();
    this.map.on('mousedown', this._onMouseDown);
    
    // Показываем подсказку
    this._showHint('Кликните и перетащите для выделения области');
  }

  disable() {
    if (!this.active) return;
    this.active = false;
    this.map.getContainer().style.cursor = '';
    this.map.dragging.enable();
    this.map.off('mousedown', this._onMouseDown);
    this.map.off('mousemove', this._onMouseMove);
    this.map.off('mouseup', this._onMouseUp);
    this._hideHint();
  }

  clear() {
    if (this.rectangle) {
      this.map.removeLayer(this.rectangle);
      this.rectangle = null;
    }
  }

  _handleMouseDown(e) {
    this.startLatLng = e.latlng;
    this.map.on('mousemove', this._onMouseMove);
    this.map.on('mouseup', this._onMouseUp);
    this._updateHint('Отпустите для завершения');
  }

  _handleMouseMove(e) {
    if (!this.startLatLng) return;

    const Lf = window.__Leaflet || window.L;
    const bounds = Lf.latLngBounds(this.startLatLng, e.latlng);

    if (this.rectangle) {
      this.rectangle.setBounds(bounds);
    } else {
      this.rectangle = Lf.rectangle(bounds, {
        color: '#007cba',
        weight: 3,
        fillColor: '#007cba',
        fillOpacity: 0.15,
        dashArray: '8,4',
        className: 'selection-rectangle'
      }).addTo(this.map);
    }
  }

  _handleMouseUp(e) {
    if (!this.startLatLng) return;
    
    const Lf = window.__Leaflet || window.L;
    const bounds = Lf.latLngBounds(this.startLatLng, e.latlng);
    
    this.map.off('mousemove', this._onMouseMove);
    this.map.off('mouseup', this._onMouseUp);
    
    // Делаем прямоугольник более заметным после завершения выделения
    if (this.rectangle) {
      this.rectangle.setStyle({
        color: '#28a745',
        weight: 3,
        fillColor: '#28a745',
        fillOpacity: 0.1,
        dashArray: '5,10'
      });
    }
    
    this.disable();
    this.onSelect(bounds);
  }

  _showHint(text) {
    if (this.hint) return;
    
    const hint = document.createElement('div');
    hint.className = 'selection-hint';
    hint.textContent = text;
    hint.style.position = 'absolute';
    hint.style.top = '20px';
    hint.style.left = '50%';
    hint.style.transform = 'translateX(-50%)';
    
    this.map.getContainer().appendChild(hint);
    this.hint = hint;
  }

  _updateHint(text) {
    if (this.hint) {
      this.hint.textContent = text;
    }
  }

  _hideHint() {
    if (this.hint) {
      this.hint.remove();
      this.hint = null;
    }
  }
}

class AkmolaEventMap {
  constructor() {
    // ====== Настройки/константы ======
    const root = document.body || document.documentElement;

    // bbox из data-атрибута или дефолт
    this.bboxCsv = (root?.dataset?.bbox || '65.0,49.5,76.0,54.0').trim();
    this.bboxArr = this.bboxCsv.split(',').map(parseFloat); // [minLon,minLat,maxLon,maxLat]
    this.bounds = [
      [this.bboxArr[1], this.bboxArr[0]],
      [this.bboxArr[3], this.bboxArr[2]],
    ]; // [[minLat,minLon],[maxLat,maxLon]]



    // База API — приоритет data-api-base
    this.API_BASE = (root?.dataset?.apiBase?.trim()) || (location.origin + '/api/v1');

    // ====== Категории NASA EONET ======
    this.eventCategories = {
      drought:     { title: 'Засуха', icon: '🌵', description: 'Длительное отсутствие осадков', color: '#8b4513' },
      dustHaze:    { title: 'Пыль и дымка', icon: '🌫️', description: 'Пылевые бури и дымка', color: '#a9a9a9' },
      earthquakes: { title: 'Землетрясения', icon: '🌍', description: 'Сейсмическая активность', color: '#ff4500' },
      floods:      { title: 'Наводнения', icon: '🌊', description: 'Затопление территорий', color: '#4682b4' },
      landslides:  { title: 'Оползни', icon: '🪨', description: 'Оползни и сели', color: '#6b8e23' },
      manmade:     { title: 'Техногенные', icon: '🏭', description: 'Техногенные происшествия', color: '#ff69b4' },
      seaLakeIce:  { title: 'Лёд', icon: '❄️', description: 'Ледовые явления', color: '#00b7eb' },
      severeStorms:{ title: 'Штормы', icon: '🌧️', description: 'Сильные штормы и ураганы', color: '#1e90ff' },
      snow:        { title: 'Снег', icon: '🌨️', description: 'Экстремальные снегопады', color: '#e0ffff' },
      tempExtremes:{ title: 'Экстр. температуры', icon: '🌡️', description: 'Аномальные температуры', color: '#ff0000' },
      waterColor:  { title: 'Цвет воды', icon: '💧', description: 'Изменение цвета воды', color: '#20b2aa' },
      wildfires:   { title: 'Пожары', icon: '🔥', description: 'Природные пожары', color: '#ff8c00' },
    };

    // ====== Спутниковые слои (GIBS/WMTS + FIRMS/WMS) ======
    this.satelliteLayers = {
      temperature: {
        title: 'Температура поверхности',
        layers: [
          {
            name: 'MODIS_Terra_Land_Surface_Temp_Day',
            title: 'Температура днём',
            layer: 'MODIS_Terra_Land_Surface_Temp_Day',
            matrix3857: 'GoogleMapsCompatible_Level8',
            format: 'image/png',
          },
          {
            name: 'MODIS_Terra_Land_Surface_Temp_Night',
            title: 'Температура ночью',
            layer: 'MODIS_Terra_Land_Surface_Temp_Night',
            matrix3857: 'GoogleMapsCompatible_Level8',
            format: 'image/png',
          },
        ],
      },

      weather: {
        title: 'Погода и атмосфера',
        layers: [
          {
            name: 'MODIS_Terra_Snow_Cover',
            title: 'Снежный покров',
            layer: 'MODIS_Terra_Snow_Cover',
            matrix3857: 'GoogleMapsCompatible_Level9',
            format: 'image/png',
          },
          {
            name: 'MODIS_Terra_Cloud_Top_Temp_Day',
            title: 'Облачность',
            layer: 'MODIS_Terra_Cloud_Top_Temp_Day',
            matrix3857: 'GoogleMapsCompatible_Level8',
            format: 'image/png',
          },
        ],
      },

      disasters: {
        title: 'Стихийные бедствия',
        layers: [
          {
            name: 'VIIRS_FIRMS_Global',
            title: 'Активные пожары (VIIRS)',
            isWMS: true,
            wmsUrl: 'https://firms.modaps.eosdis.nasa.gov/wms/viirs/',
            wmsLayers: 'NASA_VIIRS_Thermal_Anomalies_375m_Global',
          },
          {
            name: 'MODIS_Terra_Aerosol',
            title: 'Аэрозоли и пыль',
            layer: 'MODIS_Terra_Aerosol',
            matrix3857: 'GoogleMapsCompatible_Level7',
            format: 'image/png',
          },
        ],
      },
    };

    // ====== Состояние ======
    this.allEvents = [];
    this.filteredEvents = [];
    this.activeCategories = new Set();
    this.activeSatelliteLayers = new Map();
    this.eventCounts = {};
    this.refreshInterval = null;
    this.searchTerm = '';
    this._eventsLoading = false;
    this.selectedBounds = null;

    // Группы слоёв
    this.sentinelLayerGroup = L.layerGroup();
    this.osmRegionLayer = L.layerGroup();
    this.osmDistrictsLayer = L.layerGroup();

    // Геометрия области
    this.regionFeature = null;
    this.regionPolygon = null;
    this.useOSMForClip = true;

    // handler для resize
    this._onResize = () => this.map?.invalidateSize();

    // Пуск
    this.init();
  }

  // ====== Жизненный цикл ======
  async init() {

    // Ожидание критичных библиотек
    await this.waitForLibraries();

    this.initMap();
    this.initControls();
    this.createCategoryFilters();
    this.createSatelliteLayers();
    this.createLegend();


    try {
      await this.loadOSMBoundary();
    } catch (e) {
      console.warn('⚠️ OSM boundary failed:', e.message);
      this.useOSMForClip = false;
    }
    try {
      await this.loadOSMDistricts();
    } catch (e) {
      console.warn('⚠️ OSM districs failed:', e.message);
      this.useOSMForClip = false;
    }

    await this.loadEvents();

    this.startAutoRefresh();

    // Делегированный обработчик на кнопку Sentinel в попапе
    document.addEventListener('click', (e) => {
      if (e.target && e.target.classList.contains('sentinel-btn')) {
        const lat = parseFloat(e.target.getAttribute('data-lat'));
        const lon = parseFloat(e.target.getAttribute('data-lon'));
        const pad = 0.2;
        const bbox = [lon - pad, lat - pad, lon + pad, lat + pad].join(',');
        const from = document.getElementById('date-from')?.value || '';
        const to   = document.getElementById('date-to')?.value || '';
        this.fetchSentinel(bbox, from, to);
      }
    });
  }

  // ====== Ожидание библиотек ======
  async waitForLibraries() {
    const maxWait = 10000;
    const t0 = Date.now();
    return new Promise((resolve) => {
      const check = () => {
        const ok = !!(
          window.L && 
          L.Map && 
          L.Control && 
          L.tileLayer && 
          L.markerClusterGroup &&
          window.turf
        );
        
        if (ok) {
          resolve();
        } else if (Date.now() - t0 > maxWait) {
          console.error('❌ Timeout при загрузке библиотек:', {
            Leaflet: !!(window.L && L.Map),
            MarkerCluster: !!L.markerClusterGroup,
            Turf: !!window.turf
          });
          alert('Не удалось загрузить необходимые библиотеки. Проверьте подключение к интернету.');
          resolve();
        } else {
          setTimeout(check, 100);
        }
      };
      check();
    });
  }

  // ====== Автообновление ======
  startAutoRefresh(intervalMs = 15 * 60 * 1000) {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
    this.refreshInterval = setInterval(() => {
      if (!this._eventsLoading) {
        this.loadEvents().catch(() => {});
      }
    }, intervalMs);
  }

  stopAutoRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  destroy() {
    try {
      this.stopAutoRefresh();
      window.removeEventListener('resize', this._onResize);
      try { this.markerCluster?.clearLayers(); } catch {}
      try { this.sentinelLayerGroup?.clearLayers(); } catch {}
      try { this.osmRegionLayer?.clearLayers(); } catch {}
      if (this.map && this.map.remove) this.map.remove();
      this.map = null;
    } catch (e) {
      console.warn('[destroy] cleanup error:', e);
    }
  }

  // ====== Карта ======
  initMap() {
    try {
      const mapEl = document.getElementById('map');
      if (!mapEl) {
        console.error('[initMap] #map not found in DOM');
        return;
      }

      // Локальная ссылка на Leaflet
      const Lf = window.__Leaflet || window.L;
      if (!Lf || !Lf.Map) {
        throw new Error('Leaflet API not ready');
      }

      // Подстраховка высоты
      const h = parseFloat(getComputedStyle(mapEl).height);
      if (!h || h < 50) {
        mapEl.style.height = 'calc(100vh - 160px)';
        mapEl.style.minHeight = '480px';
      }

      this.map = Lf.map('map', {
        center: [51.16, 71.45],
        zoom: 7,
        zoomControl: true
      });

      // Базовые слои
      this.osmLayer = Lf.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '© OpenStreetMap'
      });

      // MODIS TrueColor
      const today = new Date().toISOString().split('T')[0];
      this.modisLayer = Lf.tileLayer(
        `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${today}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`,
        { attribution: '© NASA GIBS', tileSize: 256, maxZoom: 9 }
      );

      this.satelliteLayer = Lf.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, attribution: '© Esri' }
      );

      this.baseLayers = {
        'Карта': this.osmLayer,
        'Спутник': this.satelliteLayer,
        'MODIS Terra': this.modisLayer,
      };

      // База по умолчанию
      this.osmLayer.addTo(this.map);

      // Кластеры событий
      this.markerCluster = Lf.markerClusterGroup({
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        maxClusterRadius: 50,
      });
      this.map.addLayer(this.markerCluster);

      // Группы слоёв
      this.sentinelLayerGroup.addTo(this.map);
      this.osmRegionLayer.addTo(this.map);
      this.osmDistrictsLayer.addTo(this.map);

      // Контрол слоёв
      this.updateLayerControl();

      // bbox и рамка (в отладке)
      const bounds = Lf.latLngBounds(this.bounds);
      if (this.getUrlFlag('bboxDebug')) {
        Lf.rectangle(bounds, {
          color: '#007cba',
          weight: 1,
          dashArray: '8,4',
          fillOpacity: 0.03,
          interactive: false
        }).addTo(this.map);
      }
      this.map.fitBounds(bounds, { padding: [20, 20] });

      setTimeout(() => this.map?.invalidateSize(), 0);
      window.addEventListener('resize', this._onResize);
    } catch (err) {
      console.error('[initMap] failed:', err);
    }
  }

  // ====== Контрол слоёв ======
  updateLayerControl() {
    if (!this.map) return;

    const Lf = window.__Leaflet || window.L;

    const overlays = {
      'Граница (OSM)': this.osmRegionLayer,
      'Районы (OSM)': this.osmDistrictsLayer,
      'Footprints Sentinel': this.sentinelLayerGroup,
    };
    // Добавляем включённые спутниковые слои
    this.activeSatelliteLayers.forEach((layer, name) => {
      const cfg = this.findLayerConfig(name);
      overlays[cfg?.title || name] = layer;
    });

    if (this.layerControl) {
      try { this.map.removeControl(this.layerControl); } catch {}
    }
    this.layerControl = Lf.control.layers(this.baseLayers || {}, overlays, { collapsed: true });
    this.layerControl.addTo(this.map);
  }

  // ====== osmtogeojson helpers ======
  async ensureOsmToGeoJSON() {
    let fn =
      (window.osmtogeojson && (window.osmtogeojson.default || window.osmtogeojson)) ||
      window.osmToGeoJSON;
    if (typeof fn === 'function') return fn;

    const candidates = [
      'https://cdn.jsdelivr.net/gh/tyrasd/osmtogeojson@v3.0.0/osmtogeojson.js',
      'https://rawcdn.githack.com/tyrasd/osmtogeojson/v3.0.0/osmtogeojson.js',
      '/assets/vendor/osmtogeojson.js',
    ];

    for (const url of candidates) {
      try {
        await this.injectScript(url);
        fn =
          (window.osmtogeojson && (window.osmtogeojson.default || window.osmtogeojson)) ||
          window.osmToGeoJSON;
        if (typeof fn === 'function') return fn;
      } catch (e) {
        console.warn('[osmtogeojson] load attempt failed:', url, e?.message || e);
      }
    }
    throw new Error('osmtogeojson не найден после всех попыток загрузки');
  }

  injectScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.crossOrigin = 'anonymous';
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('script load failed: ' + src));
      document.head.appendChild(s);
    });
  }

  // ====== Только OSM: граница области + районы ======

  async loadOSMBoundary() {
    const osm2geo = await this.ensureOsmToGeoJSON().catch(() => null);
    if (!osm2geo) { console.warn('osmtogeojson не подключён — пропускаю слой OSM-границы'); this.useOSMForClip = false; return; }
    const query = `
      [out:json][timeout:25];
      (
        area["name:en"="Akmola Region"];
        area["name"="Aqmola Region"];
        area["name"="Акмолинская область"];
        area["name:ru"="Акмолинская область"];
        area["name:kz"="Ақмола облысы"];
      )->.searchArea;
      relation["boundary"="administrative"]["admin_level"="4"](area.searchArea);
      out geom;
    `;

    const tryOnce = async (url) => {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 28000);
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
          body: 'data=' + encodeURIComponent(query),
          signal: controller.signal
        });
        if (!resp.ok) throw new Error(`Overpass HTTP ${resp.status}`);
        return resp.json();
      } finally {
        clearTimeout(t);
      }
    };

    let osmJson;
    try {
      osmJson = await tryOnce('https://overpass-api.de/api/interpreter');
    } catch (e1) {
      console.warn('[Overpass] primary failed, trying fallback:', e1.message);
      osmJson = await tryOnce('https://overpass.kumi.systems/api/interpreter');
    }



    const gj = osm2geo(osmJson);
    const feats = (gj.type === 'FeatureCollection') ? gj.features : [gj];
    if (!feats?.length) throw new Error('OSM boundary not found');

    const pickLargest = (features) => {
      let best = null, bestArea = -1;
      for (const f of features) {
        if (!f.geometry) continue;
        try {
          const a = turf.area(f);
          if (a > bestArea) { bestArea = a; best = f; }
        } catch {}
      }
      return best;
    };

    const osmFeat = pickLargest(feats);
    if (!osmFeat) throw new Error('OSM feature invalid');

    const Lf = window.__Leaflet || window.L;
    this.osmRegionLayer.clearLayers();
    const osmGeo = Lf.geoJSON(osmFeat, {
      style: { color: '#7c3aed', weight: 2.5, fillOpacity: 0.08, dashArray: '4,3' },
      onEachFeature: (_f, layer) => {
        layer.bindTooltip('OSM граница Акмолинской области', {
          permanent: false, direction: 'auto', className: 'region-label'
        });
      }
    }).addTo(this.osmRegionLayer);

    const bounds = osmGeo.getBounds();
    if (bounds.isValid()) this.map.fitBounds(bounds, { padding: [24, 24] });

    // Текст по границе (если leaflet-textpath подключён)
    this.addTextAlongBoundary(osmGeo, '   EONET   ');

    // Геометрия клипа
    this.regionFeature = osmFeat;
    this.regionPolygon = (osmFeat.geometry.type === 'Polygon')
      ? turf.polygon(osmFeat.geometry.coordinates)
      : turf.multiPolygon(osmFeat.geometry.coordinates);

    this.useOSMForClip = true;

    this.updateLayerControl?.();
  }

  async loadOSMDistricts() {
    const osm2geo = await this.ensureOsmToGeoJSON().catch(() => null);
    if (!osm2geo) { console.warn('osmtogeojson не подключён — пропускаю слой OSM-районы'); return; }

    const query = `
      [out:json][timeout:25];
      (
        area["name:en"="Akmola Region"];
        area["name"="Aqmola Region"];
        area["name"="Акмолинская область"];
        area["name:ru"="Акмолинская область"];
        area["name:kz"="Ақмола облысы"];
      )->.searchArea;

      // Районы области: admin_level 6 (иногда 7)
      relation["boundary"="administrative"]["admin_level"~"^(6|7)$"](area.searchArea);
      out geom;
    `;

    const tryOnce = async (url) => {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), 28000);
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
          body: 'data=' + encodeURIComponent(query),
          signal: controller.signal
        });
        if (!resp.ok) throw new Error(`Overpass HTTP ${resp.status}`);
        return resp.json();
      } finally {
        clearTimeout(t);
      }
    };

    let osmJson;
    try {
      osmJson = await tryOnce('https://overpass-api.de/api/interpreter');
    } catch (e1) {
      console.warn('[Overpass] primary failed, trying fallback:', e1.message);
      osmJson = await tryOnce('https://overpass.kumi.systems/api/interpreter');
    }



    const gj = osm2geo(osmJson);
    let feats = (gj.type === 'FeatureCollection') ? gj.features : [gj];

    // Страхуемся: оставляем только административные границы с названием
    feats = feats.filter(f => {
      const p = f.properties || {};
      const tags = p.tags || p;
      const al = (tags.admin_level || p.admin_level || '').toString();
      const boundary = (tags.boundary || p.boundary);
      const hasName = !!(tags['name:ru'] || tags['name:kz'] || tags.name || p.name);
      return boundary === 'administrative' && /^(6|7)$/.test(al) && hasName && f.geometry;
    });

    const Lf = window.__Leaflet || window.L;
    this.osmDistrictsLayer.clearLayers();

    if (!feats.length) {
      console.warn('OSM: районы не найдены');
      this.updateLayerControl?.();
      return;
    }

    Lf.geoJSON({ type: 'FeatureCollection', features: feats }, {
      style: { color: '#1d4ed8', weight: 1.5, fillOpacity: 0.05 },
      onEachFeature: (f, layer) => {
        const p = f.properties || {};
        const tags = p.tags || p;
        const name = tags['name:ru'] || tags['name:kz'] || tags['name:en'] || tags.name || 'Район';
        layer.bindTooltip(name, { permanent: false, direction: 'auto', className: 'district-label' });
      }
    }).addTo(this.osmDistrictsLayer);

    this.updateLayerControl?.();
  }


  // ====== Контролы UI ======
  initControls() {
    const searchBox = document.getElementById('search-events');
    if (searchBox) {
      const debouncedSearch = debounce((term) => {
        this.searchTerm = term.toLowerCase();
        this.updateMapDisplay();
      }, 250);

      searchBox.addEventListener('input', (e) => {
        debouncedSearch(e.target.value || '');
      });
    }

    document.getElementById('select-all')?.addEventListener('click', () => {
      this.activeCategories = new Set(Object.keys(this.eventCategories));
      document.querySelectorAll('#category-filters input').forEach((cb) => (cb.checked = true));
      this.updateMapDisplay();
    });

    document.getElementById('deselect-all')?.addEventListener('click', () => {
      this.activeCategories.clear();
      document.querySelectorAll('#category-filters input').forEach((cb) => (cb.checked = false));
      this.updateMapDisplay();
    });

    document.getElementById('refresh-data')?.addEventListener('click', () => this.loadEvents());
    document.getElementById('apply-date')?.addEventListener('click', () => this.loadEvents());

    // ====== Выделение области ======
    const selector = new RectSelector(this.map, {
      onSelect: (bounds) => {
        this.selectedBounds = bounds;
        const sw = bounds.getSouthWest(), ne = bounds.getNorthEast();
        document.getElementById('selection-coords').textContent =
          `SW: ${sw.lat.toFixed(4)}, ${sw.lng.toFixed(4)} | NE: ${ne.lat.toFixed(4)}, ${ne.lng.toFixed(4)}`;
        document.getElementById('selection-info').style.display = 'block';
        
        // Автоматически перезагружаем события для выделенной области
        this.loadEvents();
      }
    });

    const selectAreaBtn = document.getElementById('select-area');
    if (selectAreaBtn) {
      selectAreaBtn.addEventListener('click', (e) => {
        const btn = e.currentTarget;
        if (!selector.active) {
          selector.enable();
          btn.style.background = '#28a745';
          btn.style.color = '#fff';
          btn.style.borderColor = '#28a745';
          btn.textContent = '✓ Режим выделения';
        } else {
          selector.disable();
          btn.style.background = '';
          btn.style.color = '';
          btn.style.borderColor = '';
          btn.textContent = '✏️ Выделить область';
        }
      });
    }

    document.getElementById('clear-selection')?.addEventListener('click', () => {
      selector.clear();
      this.selectedBounds = null;
      document.getElementById('selection-info').style.display = 'none';
      
      // Сбрасываем кнопку
      const btn = document.getElementById('select-area');
      if (btn) {
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.textContent = '✏️ Выделить область';
      }
      
      // Перезагружаем события для всей области
      this.loadEvents();
    });

    document.getElementById('layers-all')?.addEventListener('click', () => {
      document.querySelectorAll('#satellite-layers input[type="checkbox"]').forEach((cb) => {
        if (!cb.checked) cb.click();
      });
    });

    document.getElementById('layers-none')?.addEventListener('click', () => {
      document.querySelectorAll('#satellite-layers input[type="checkbox"]').forEach((cb) => {
        if (cb.checked) cb.click();
      });
    });
  }

  getUrlFlag(name) {
    const p = new URLSearchParams(location.search);
    const v = p.get(name);
    return p.has(name) && (v === null || v === '' || v === '1' || v === 'true');
  }

  // ====== Получение bbox для backend ======
  getRequestBbox() {
    if (this.selectedBounds) {
      const sw = this.selectedBounds.getSouthWest();
      const ne = this.selectedBounds.getNorthEast();
      return [sw.lng, sw.lat, ne.lng, ne.lat];
    }
    return this.bboxArr;
  }

  // ====== Генерация UI ======
  createIcon(category) {
    const Lf = window.__Leaflet || window.L;
    const c = this.eventCategories[category] || { icon: '❓' };
    return Lf.divIcon({
      className: 'custom-marker',
      html: `<span class="marker-emoji">${c.icon}</span>`,
      iconSize: [25, 25],
      iconAnchor: [12, 12],
    });
  }

  createCategoryFilters() {
    const container = document.getElementById('category-filters');
    if (!container) return;
    container.innerHTML = '';

    Object.entries(this.eventCategories).forEach(([id, data]) => {
      this.activeCategories.add(id);
      const wrap = document.createElement('div');
      wrap.className = 'category-filter';
      wrap.innerHTML = `
        <input type="checkbox" id="filter-${id}" checked>
        <label for="filter-${id}">
          <span class="category-icon">${data.icon}</span>
          <span>${data.title}</span>
          <span class="event-count" id="count-${id}">0</span>
        </label>
      `;
      wrap.querySelector('input').addEventListener('change', (e) => {
        if (e.target.checked) this.activeCategories.add(id);
        else this.activeCategories.delete(id);
        this.updateMapDisplay();
      });
      container.appendChild(wrap);
    });
  }

  createSatelliteLayers() {
    const container = document.getElementById('satellite-layers');
    if (!container) return;
    container.innerHTML = '';

    Object.entries(this.satelliteLayers).forEach(([groupId, group]) => {
      const groupDiv = document.createElement('div');
      groupDiv.className = 'layer-group';

      const groupTitle = document.createElement('div');
      groupTitle.className = 'layer-group-title';
      groupTitle.textContent = group.title;
      groupDiv.appendChild(groupTitle);

      (group.layers || []).forEach((layerConfig) => {
        const filterDiv = document.createElement('div');
        filterDiv.className = 'layer-filter';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `layer-${layerConfig.name}`;

        const label = document.createElement('label');
        label.setAttribute('for', checkbox.id);
        label.textContent = layerConfig.title || layerConfig.name;

        filterDiv.appendChild(checkbox);
        filterDiv.appendChild(label);

        const opacityDiv = document.createElement('div');
        opacityDiv.className = 'layer-opacity';
        opacityDiv.style.display = 'none';

        const opacitySlider = document.createElement('input');
        opacitySlider.type = 'range';
        opacitySlider.min = '0';
        opacitySlider.max = '1';
        opacitySlider.step = '0.1';
        opacitySlider.value = '0.7';

        const opacityValue = document.createElement('span');
        opacityValue.textContent = '70%';

        const opacityLabel = document.createElement('span');
        opacityLabel.textContent = 'Прозрачность:';

        opacityDiv.appendChild(opacityLabel);
        opacityDiv.appendChild(opacitySlider);
        opacityDiv.appendChild(opacityValue);

        groupDiv.appendChild(filterDiv);
        groupDiv.appendChild(opacityDiv);

        checkbox.addEventListener('change', () => {
          this.toggleSatelliteLayer(layerConfig, checkbox.checked, opacitySlider.value, opacityDiv);
        });

        const debouncedOpacity = debounce(() => {
          const opacity = parseFloat(opacitySlider.value);
          const layer = this.activeSatelliteLayers.get(layerConfig.name);
          if (layer?.setOpacity) layer.setOpacity(opacity);
        }, 80);

        opacitySlider.addEventListener('input', () => {
          const opacity = parseFloat(opacitySlider.value);
          opacityValue.textContent = `${Math.round(opacity * 100)}%`;
          debouncedOpacity();
        });
      });

      container.appendChild(groupDiv);
    });
  }

  createLegend() {
    const legendDiv = document.getElementById('legend');
    if (!legendDiv) return;
    legendDiv.innerHTML = '';
    Object.entries(this.eventCategories).forEach(([id, data]) => {
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML = `
        <span class="legend-icon">${data.icon}</span>
        <div class="legend-text">
          <strong>${data.title}</strong><br>
          <small>${data.description}</small>
        </div>
      `;
      legendDiv.appendChild(item);
    });
  }

  // ====== Спутниковые тайлы ======
  toggleSatelliteLayer(config, enabled, opacity, opacityDiv) {
    const Lf = window.__Leaflet || window.L;

    if (enabled) {
      this.showLoading();
      let layer;
      
      if (config.isWMS) {
        const url = config.wmsUrl || 'https://firms.modaps.eosdis.nasa.gov/wms/viirs/';
        const layers = config.wmsLayers || 'NASA_VIIRS_Thermal_Anomalies_375m_Global';
        layer = Lf.tileLayer.wms(url, {
          layers, transparent: true, format: 'image/png',
          opacity: parseFloat(opacity),
        });
      } else {
        const today = new Date().toISOString().split('T')[0];
        const ext = (config.format || 'image/png').split('/')[1] || 'png';
        const matrix = config.matrix3857 || 'GoogleMapsCompatible_Level9';
        layer = Lf.tileLayer(
          `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${config.layer}/default/${today}/${matrix}/{z}/{y}/{x}.${ext}`,
          { attribution: '© NASA GIBS', opacity: parseFloat(opacity), tileSize: 256, maxZoom: 9 }
        );
      }

      layer.on?.('load', () => this.hideLoading());
      layer.on?.('tileerror', () => this.hideLoading());
      layer.addTo(this.map);

      this.activeSatelliteLayers.set(config.name, layer);
      this.updateLayerControl();
      opacityDiv.style.display = 'flex';
    } else {
      const layer = this.activeSatelliteLayers.get(config.name);
      if (layer) {
        this.map.removeLayer(layer);
        this.activeSatelliteLayers.delete(config.name);
        this.updateLayerControl();
        opacityDiv.style.display = 'none';
      }
    }
  }

  findLayerConfig(name) {
    for (const group of Object.values(this.satelliteLayers)) {
      const config = (group.layers || []).find(l => l.name === name);
      if (config) return config;
    }
    return null;
  }

  // ====== Backend: события ======
  async loadEvents() {
    // Increment request ID to track latest request and prevent race conditions
    if (!this._eventsRequestId) {
      this._eventsRequestId = 0;
    }
    const requestId = ++this._eventsRequestId;

    this.showLoading();

    const from = document.getElementById('date-from')?.value || '';
    const to   = document.getElementById('date-to')?.value || '';
    const params = new URLSearchParams({ status: 'all' });

    // Use selected area or full bbox
    const bbox = this.getRequestBbox();
    params.set('bbox', bbox.join(','));

    if (from) params.set('start', from);
    if (to) params.set('end', to);

    const url = `${this.API_BASE}/events?${params.toString()}`;

    // Create cache key for deduplication
    const cacheKey = `events:${from}:${to}:${bbox.join(',')}`;

    try {
      // Use deduplicated fetch to prevent concurrent duplicate requests
      const response = await dedupedFetch(cacheKey, () => fetchWithTimeout(url));

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      // Fallback: combined endpoint
      if ((!data.events || data.events.length === 0) && !data.debug) {
        try {
          const url2 = `${this.API_BASE}/events/combined?${params.toString()}`;
          const r2 = await fetchWithTimeout(url2);
          if (r2.ok) {
            const d2 = await r2.json();
            if (d2?.events?.length) {
              Object.assign(data, d2);
            }
          }
        } catch (_) {}
      }

      // Only update if this is still the latest request (prevent race conditions)
      if (requestId !== this._eventsRequestId) {
        return; // Discard stale response
      }

      this.allEvents = data.events || [];

      if (this.allEvents.length === 0) {
        console.warn('No events in selected period and region');
        if (data.debug && data.message) {
          this.showError(data.message, 'warning');
        } else if (data.stats) {
          const msg = `No events in ${this.selectedBounds ? 'selected area' : 'region'}. Total processed: ${data.stats.total || 0}, nearby: ${data.stats.nearby || 0}`;
          this.showError(msg, 'info');
        } else {
          this.showError(`No events for ${this.selectedBounds ? 'selected area' : 'region'} and selected period. Try expanding the date range.`, 'info');
        }
      } else {
        if (data.debug) {
          this.showError('DEBUG: Showing nearest events for debugging', 'warning');
        }
      }

      this.updateMapDisplay();
    } catch (e) {
      // Only update UI if this is still the latest request
      if (requestId !== this._eventsRequestId) {
        return;
      }

      console.error('=== ERROR LOADING EVENTS ===');
      console.error('Error:', e);
      this.showError(`Error loading events: ${e.message}`);
      this.allEvents = [];
      this.updateMapDisplay();
    } finally {
      // Only hide loading if this is still the latest request
      if (requestId === this._eventsRequestId) {
        this.hideLoading();
      }
    }
  }

  // ====== Sentinel ======
  async fetchSentinel(bboxCsv, from, to) {
    this.showLoading();
    try {
      const params = new URLSearchParams({
        bbox: bboxCsv, platform: 'Sentinel-2', cloudmax: '40', limit: '20'
      });
      if (from) params.set('start', from);
      if (to) params.set('end', to);

      const url = `${this.API_BASE}/sentinel/search?${params.toString()}`;

      // Create cache key for deduplication
      const cacheKey = `sentinel:${bboxCsv}:${from}:${to}`;

      // Use deduplicated fetch to prevent concurrent duplicate requests
      const resp = await dedupedFetch(cacheKey, () => fetchWithTimeout(url));
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (!data.items || data.items.length === 0) {
        this.showError('No Sentinel imagery found for selected area and period.', 'info');
        return;
      }
      this.drawSentinelFootprints(data.items);
    } catch (e) {
      console.error('Sentinel search error:', e);
      this.showError('Failed to retrieve Sentinel products.');
    } finally {
      this.hideLoading();
    }
  }

  // ====== Отрисовка событий ======
  updateMapDisplay() {
    this.markerCluster.clearLayers();

    this.eventCounts = {};
    let totalEvents = 0;

    this.filteredEvents = (this.allEvents || []).filter((event) => {
      const categoryId = event.categories?.[0]?.id || 'unknown';
      const matchesCategory = this.activeCategories.has(categoryId);
      const matchesSearch = !this.searchTerm || (event.title || '').toLowerCase().includes(this.searchTerm);
      return matchesCategory && matchesSearch;
    });

    const eventListDiv = document.getElementById('event-list');
    if (eventListDiv) eventListDiv.innerHTML = '';

    if (!this.filteredEvents.length) {
      if (eventListDiv) eventListDiv.innerHTML = '<div class="no-events">Нет событий для отображения</div>';
    } else {
      const pointMarkers = [];

      this.filteredEvents.forEach((event) => {
        const categoryId = event.categories?.[0]?.id || 'unknown';
        const categoryData = this.eventCategories[categoryId] || { title: 'Unknown', icon: '❓', color: '#666' };
        this.eventCounts[categoryId] = (this.eventCounts[categoryId] || 0) + 1;

        (event.geometry || []).forEach((geo) => {
          const layer = this.addGeometryToMap(event, categoryId, geo);
          if (!layer) return;

          // В список
          if (eventListDiv) {
            const eventItem = document.createElement('div');
            eventItem.className = 'event-item';
            if (this.searchTerm && (event.title || '').toLowerCase().includes(this.searchTerm)) {
              eventItem.classList.add('highlighted');
            }
            const dateStr = geo.date ? new Date(geo.date).toLocaleDateString('ru-RU') : 'Дата не указана';
            eventItem.innerHTML = `
              <strong>${event.title}</strong>
              <div class="event-meta">
                ${categoryData.icon} ${categoryData.title} • ${dateStr}
              </div>
            `;
            eventItem.onclick = () => {
              if (layer.getBounds) this.map.fitBounds(layer.getBounds(), { maxZoom: 12 });
              else if (layer.getLatLng) this.map.setView(layer.getLatLng(), 12);
            };
            eventListDiv.appendChild(eventItem);
          }

          // На карту
          if (layer.getLatLng) pointMarkers.push(layer);
          else layer.addTo(this.map);

          totalEvents++;
        });
      });

      if (pointMarkers.length) this.markerCluster.addLayers(pointMarkers);
    }

    // Счётчики по категориям
    Object.keys(this.eventCategories).forEach((categoryId) => {
      const el = document.getElementById(`count-${categoryId}`);
      if (el) el.textContent = this.eventCounts[categoryId] || 0;
    });

    this.updateSummary(totalEvents);
  }

  addGeometryToMap(event, categoryId, geo) {
    const Lf = window.__Leaflet || window.L;
    const c = this.eventCategories[categoryId] || { title: 'Unknown', icon: '❓', color: '#666' };

    if (geo.type === 'Point') {
      const [lon, lat] = geo.coordinates;
      const marker = Lf.marker([lat, lon], { icon: this.createIcon(categoryId), title: event.title });
      marker.bindPopup(this.createPopupContent(event, c, geo, lat, lon));
      return marker;
    }

    if (geo.type === 'LineString') {
      const latlngs = geo.coordinates.map(([lon, lat]) => [lat, lon]);
      const polyline = Lf.polyline(latlngs, { color: c.color, weight: 3, opacity: 0.8 });
      polyline.bindPopup(this.createPopupContent(event, c, geo, latlngs[0][0], latlngs[0][1]));
      return polyline;
    }

    if (geo.type === 'Polygon') {
      const rings = geo.coordinates.map((ring) => ring.map(([lon, lat]) => [lat, lon]));
      const polygon = Lf.polygon(rings, { color: c.color, weight: 2, fillOpacity: 0.2 });
      const center = this.getPolygonCenter(rings[0]);
      polygon.bindPopup(this.createPopupContent(event, c, geo, center[0], center[1]));
      return polygon;
    }

    return null;
  }

  getPolygonCenter(latlngs) {
    let sumLat = 0, sumLon = 0;
    latlngs.forEach(([lat, lon]) => { sumLat += lat; sumLon += lon; });
    return [sumLat / latlngs.length, sumLon / latlngs.length];
  }

  createPopupContent(event, c, geo, lat, lon) {
    const sources = (event.sources || []).map((s) => s.id).join(', ') || 'NASA EONET';
    const dateHuman = geo.date
      ? new Date(geo.date).toLocaleDateString('ru-RU', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : 'Не указано';
    const safeTitle = (event.title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `
      <div class="info-popup">
        <h4>${safeTitle}</h4>
        <div class="category">${c.icon} <strong>Категория:</strong> ${c.title}</div>
        <div class="date">📅 <strong>Дата:</strong> ${dateHuman}</div>
        <div class="source">📡 <strong>Источники:</strong> ${sources}</div>
        <div class="popup-note">${c.description}</div>
        <div class="coordinates">📍 ${lat.toFixed(4)}°, ${lon.toFixed(4)}°</div>
        <div class="popup-actions">
          <button class="sentinel-btn" data-lat="${lat}" data-lon="${lon}" data-title="${safeTitle}">🛰️ Снимки Sentinel</button>
        </div>
      </div>
    `;
  }

  // ====== Footprints Sentinel ======
  drawSentinelFootprints(items) {
    const Lf = window.__Leaflet || window.L;

    this.sentinelLayerGroup.clearLayers();
    if (!items.length) {
      this.showError('Нет снимков для выбранной области/дат.', 'info');
      this.updateLayerControl();
      return;
    }

    const group = Lf.layerGroup();
    let valid = 0;

    items.forEach((item, idx) => {
      const wkt = item.footprint_wkt || item.footprint || null;

      if (!wkt) {
        console.warn(`Item ${idx} has no WKT:`, item);
        return;
      }

      const geom = this.wktToLeaflet(wkt);
      if (!geom) return;

      valid++;
      const popup = `
        <div class="info-popup">
          <h4>${(item.title || 'Sentinel-2').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</h4>
          <div>📅 ${item.beginposition ? new Date(item.beginposition).toLocaleString('ru-RU') : 'Дата не указана'}</div>
          <div>☁️ Облачность: ${item.cloudcover != null ? Math.round(item.cloudcover) : '—'}%</div>
          ${item.product_id ? `<div>🆔 ID: ${String(item.product_id).slice(0, 12)}…</div>` : ''}
        </div>
      `;
      geom.setStyle({ color: '#2e7d32', weight: 2, fillOpacity: 0.1 });
      geom.bindPopup(popup);
      group.addLayer(geom);
    });

    if (valid === 0) {
      this.showError('Не удалось отобразить контуры снимков (WKT отсутствует или некорректен).', 'warning');
      return;
    }

    this.sentinelLayerGroup.addLayer(group);
    this.updateLayerControl();

    try {
      const b = group.getBounds();
      if (b.isValid()) this.map.fitBounds(b, { padding: [48, 48] });
    } catch {}

    try { group.bringToFront?.(); } catch {}

  }

  wktToLeaflet(wkt) {
    const Lf = window.__Leaflet || window.L;
    if (!wkt) return null;
    const trim = String(wkt).trim();

    const parseRing = (str) => {
      const cleaned = str.replace(/,/g, ' ');
      const parts = cleaned.trim().split(/\s+/).map(Number);
      const coords = [];
      for (let i = 0; i < parts.length - 1; i += 2) {
        const lon = parts[i];
        const lat = parts[i + 1];
        if (!isNaN(lon) && !isNaN(lat)) {
          coords.push([lat, lon]);
        }
      }
      return coords;
    };

    try {
      // POLYGON
      let m = trim.match(/^POLYGON\s*\(\s*\(\s*(.+?)\s*\)\s*\)\s*$/i);
      if (m) {
        const ring = parseRing(m[1]);
        return ring.length >= 3 ? Lf.polygon([ring]) : null;
      }

      // MULTIPOLYGON
      if (/^MULTIPOLYGON/i.test(trim)) {
        const inner = trim.replace(/^MULTIPOLYGON\s*\(\s*/i, '').replace(/\s*\)\s*$/, '');
        const polys = inner.split(/\)\s*\)\s*,\s*\(\s*\(/).map(s => s.replace(/^\(+|\)+$/g, ''));
        const rings = polys.map(parseRing).filter(r => r.length >= 3);
        return rings.length ? Lf.polygon(rings) : null;
      }
    } catch (e) {
      console.error('Ошибка парсинга WKT:', e, wkt);
    }
    return null;
  }

  // ====== Сводка ======
  updateSummary(totalEvents) {
    const summaryDiv = document.getElementById('summary');
    if (!summaryDiv) return;

    const now = new Date();
    const categoriesWithEvents = Object.entries(this.eventCounts)
      .filter(([, count]) => count > 0)
      .map(([cat, count]) => {
        const catData = this.eventCategories[cat] || { icon: '❓', title: cat };
        return `${catData.icon} ${catData.title}: ${count}`;
      })
      .join(' • ');

    const activeCatCount = Object.values(this.eventCounts).filter((v) => v > 0).length;
    
    const areaInfo = this.selectedBounds 
      ? '📍 Выделенная область' 
      : '🗺️ Вся Акмолинская область';

    summaryDiv.innerHTML = `
      <strong>${areaInfo}</strong>
      <div class="stats-grid">
        <div class="stat-item"><div class="stat-value">${totalEvents}</div><div class="stat-label">Всего событий</div></div>
        <div class="stat-item"><div class="stat-value">${activeCatCount}</div><div class="stat-label">Активных категорий</div></div>
        <div class="stat-item"><div class="stat-value">${this.activeSatelliteLayers.size}</div><div class="stat-label">Спутниковых слоёв</div></div>
        <div class="stat-item"><div class="stat-value">${now.getHours()}:${String(now.getMinutes()).padStart(2,'0')}</div><div class="stat-label">Обновлено</div></div>
      </div>
      <div class="summary-cats"><strong>По категориям:</strong> ${categoriesWithEvents || 'Нет событий'}</div>
      <div class="source-info">
        <strong>Источники данных:</strong><br>
        • События: NASA EONET API (через backend)<br>
        • Спутниковые данные: NASA GIBS (WMTS), VIIRS FIRMS (WMS)<br>
        • Снимки Sentinel: Copernicus Data Space Ecosystem<br>
        • Последнее обновление: ${now.toLocaleTimeString('ru-RU')}
      </div>
      <div class="author-info"><strong>Akmola Sentinel</strong></div>
    `;
  }

  // ====== Сервис ======
  showLoading() { document.getElementById('loading')?.classList.add('active'); }
  hideLoading() { document.getElementById('loading')?.classList.remove('active'); }

  showError(message, type = 'error') {
    const eventList = document.getElementById('event-list');
    const div = document.createElement('div');

    let className = 'alert';
    switch(type) {
      case 'warning':
        className += ' warning';
        break;
      case 'info':
        className += ' info';
        break;
      default:
        className += ' error';
    }

    div.className = className;
    div.textContent = message;
    (eventList || document.body).appendChild(div);

    const timeout = type === 'error' ? 5000 : 10000;
    setTimeout(() => div.remove(), timeout);
  }
}

// ====== Инициализация ======
let app = null;

async function boot() {
  try {
    app = new AkmolaEventMap();
    window.app = app;
  } catch (e) {
    console.error('[AkmolaEventMap] init failed:', e);
    alert('Не удалось инициализировать приложение. Проверьте консоль.');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

window.addEventListener('load', () => {
  try {
    const cat = document.getElementById('category-filters');
    const sat = document.getElementById('satellite-layers');
    if (app && cat && !cat.children.length) app.createCategoryFilters();
    if (app && sat && !sat.children.length) app.createSatelliteLayers();
  } catch (e) {
    console.error('[AkmolaEventMap] late render failed:', e);
  }
});

window.addEventListener('beforeunload', () => app?.destroy());