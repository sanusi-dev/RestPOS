document.addEventListener('alpine:init', () => {
  Alpine.data('orderDetailsDrawer', (returnFocusId) => ({
    open: true,
    returnFocusId,

    init() {
      this.$nextTick(() => this.$refs.closeButton?.focus());
    },

    close() {
      if (!this.open) {
        return;
      }

      this.open = false;
      const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 300;

      window.setTimeout(() => {
        this.$dispatch('order-details-closed');
        this.$root.remove();
        document.getElementById(this.returnFocusId)?.focus();
      }, delay);
    },

    trapFocus(event) {
      if (event.key !== 'Tab') {
        return;
      }

      const focusable = Array.from(
        this.$refs.panel.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );

      if (!focusable.length) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
  }));
});
