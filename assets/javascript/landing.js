function setCopyrightYear() {
  const el = document.getElementById('copyright-year');
  if (el) {
    el.textContent = new Date().getFullYear();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setCopyrightYear();
});
