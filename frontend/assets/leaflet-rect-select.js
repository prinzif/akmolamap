// assets/leaflet-rect-select.js

// Получаем Leaflet из window (где он был пришпилен в HTML)
const L = window.__Leaflet || window.L;

if (!L || !L.rectangle || !L.latLngBounds) {
  throw new Error('Leaflet API not available in RectSelector module');
}

export class RectSelector {
  constructor(map, { onSelect } = {}) {
    this.map = map;
    this.onSelect = onSelect || (()=>{});
    this.active = false;
    this.drawStart = null;
    this.drawingRectangle = null;
    this.selectionRectangle = null;

    this._onDown = this._onDown.bind(this);
    this._onMove = this._onMove.bind(this);
    this._onUp = this._onUp.bind(this);
  }

  enable() {
    if (this.active) return;
    this.active = true;
    this.map.dragging.disable();
    this.map.on("mousedown", this._onDown);
    this.map.on("mousemove", this._onMove);
    this.map.on("mouseup", this._onUp);
    this.map.getContainer().style.cursor = "crosshair";
  }

  disable() {
    this.active = false;
    this.map.dragging.enable();
    this.map.off("mousedown", this._onDown);
    this.map.off("mousemove", this._onMove);
    this.map.off("mouseup", this._onUp);
    this.map.getContainer().style.cursor = ""; // Исправлена опечатка: было ccursor
    if (this.drawingRectangle) { 
      this.map.removeLayer(this.drawingRectangle); 
      this.drawingRectangle = null; 
    }
  }

  clear() {
    if (this.selectionRectangle) { 
      this.map.removeLayer(this.selectionRectangle); 
      this.selectionRectangle = null; 
    }
  }

  _onDown(e) {
    if (!this.active) return;
    this.drawStart = e.latlng;
    if (this.drawingRectangle) this.map.removeLayer(this.drawingRectangle);
    this.drawingRectangle = L.rectangle([this.drawStart, this.drawStart], {
      color: "#007cba", weight: 2, fillOpacity: 0.2, dashArray: "5, 5"
    }).addTo(this.map);
  }

  _onMove(e) {
    if (!this.active || !this.drawStart || !this.drawingRectangle) return;
    const bounds = L.latLngBounds(this.drawStart, e.latlng);
    this.drawingRectangle.setBounds(bounds);
  }

  _onUp(e) {
    if (!this.active || !this.drawStart) return;
    const bounds = L.latLngBounds(this.drawStart, e.latlng);
    const sw = bounds.getSouthWest(), ne = bounds.getNorthEast();
    const area = Math.abs(ne.lat - sw.lat) * Math.abs(ne.lng - sw.lng);
    
    if (area < 0.001) {
      if (this.drawingRectangle) { 
        this.map.removeLayer(this.drawingRectangle); 
        this.drawingRectangle = null; 
      }
      this.drawStart = null;
      return;
    }
    
    if (this.selectionRectangle) this.map.removeLayer(this.selectionRectangle);
    this.selectionRectangle = L.rectangle(bounds, { 
      color:"#007cba", 
      weight:3, 
      fillOpacity:0.1, 
      interactive:false 
    }).addTo(this.map);
    
    if (this.drawingRectangle) { 
      this.map.removeLayer(this.drawingRectangle); 
      this.drawingRectangle = null; 
    }
    
    this.drawStart = null;
    this.disable();
    this.onSelect(bounds);
  }
}