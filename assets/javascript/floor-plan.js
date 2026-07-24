import Alpine from 'alpinejs';
import { getCsrfToken } from './csrf';

Alpine.data('floorPlanEditor', () => ({
  tables: [],
  zoom: 1,
  dragging: null,
  startX: 0,
  startY: 0,
  startTableX: 0,
  startTableY: 0,

  init() {
    const el = document.getElementById('floor-plan-data');
    this.tables = el ? JSON.parse(el.textContent) : [];
  },

  zoomIn() {
    this.zoom = Math.min(this.zoom + 0.1, 2);
  },
  zoomOut() {
    this.zoom = Math.max(this.zoom - 0.1, 0.3);
  },

  startDrag(event, table) {
    this.dragging = table;
    this.startX = event.clientX;
    this.startY = event.clientY;
    this.startTableX = table.x;
    this.startTableY = table.y;
    event.preventDefault();
  },
  onDrag(event, table) {
    if (this.dragging && this.dragging.id === table.id) {
      const dx = (event.clientX - this.startX) / this.zoom;
      const dy = (event.clientY - this.startY) / this.zoom;
      table.x = this.startTableX + dx;
      table.y = this.startTableY + dy;
    }
  },
  async endDrag(event, table) {
    if (this.dragging && this.dragging.id === table.id) {
      const t = this.dragging;
      this.dragging = null;
      const formData = new FormData();
      formData.append('x', t.x);
      formData.append('y', t.y);
      formData.append('width', t.width);
      formData.append('height', t.height);
      await fetch(`/backoffice/settings/tables/${t.id}/layout/`, {
        method: 'POST',
        body: formData,
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
    }
  },
}));
