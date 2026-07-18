import Swal from 'sweetalert2';

document.addEventListener('htmx:confirm', function (e) {
  const message = e.target.dataset.confirmMessage;
  if (!message) return;

  e.preventDefault();

  Swal.fire({
    title: e.target.dataset.confirmTitle || 'Are you sure?',
    html: message,
    icon: e.target.dataset.confirmIcon || 'question',
    showCancelButton: true,
    confirmButtonColor: e.target.dataset.confirmColor || undefined,
    confirmButtonText: e.target.dataset.confirmBtn || 'Confirm',
    cancelButtonText: 'Cancel',
  }).then(function (result) {
    if (result.isConfirmed) {
      e.detail.issueRequest(true);
    }
  });
});
