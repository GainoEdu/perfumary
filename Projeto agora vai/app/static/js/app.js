(function () {
  function ready(fn) {
    if (document.readyState !== 'loading') { fn(); } else { document.addEventListener('DOMContentLoaded', fn); }
  }
  ready(function () {
    // menus (mobile)
    document.querySelectorAll('[data-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = document.querySelector(btn.getAttribute('data-toggle'));
        if (target) {
          target.classList.toggle('open');
          btn.setAttribute('aria-expanded', target.classList.contains('open') ? 'true' : 'false');
        }
      });
    });
    // confirmações de exclusão
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!window.confirm(form.getAttribute('data-confirm'))) { e.preventDefault(); }
      });
    });
    // galeria do produto
    var main = document.getElementById('main-photo');
    document.querySelectorAll('.thumb[data-src]').forEach(function (t) {
      t.addEventListener('click', function () { if (main) { main.src = t.getAttribute('data-src'); } });
    });
  });
})();
