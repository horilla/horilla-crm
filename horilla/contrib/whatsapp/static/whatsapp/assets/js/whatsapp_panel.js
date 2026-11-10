/**
 * WhatsApp conversation panel (Activity tab > WhatsApp).
 *
 * Loaded by templates/whatsapp_inbox/conversation_panel.html. Settings come
 * from data attributes on the panel root (#tab-whatsapp-content):
 *   data-conversation-id  data-item-url (ends in /0/)  data-sync-url
 * The script re-runs every time the panel is (re)rendered, so everything is
 * looked up fresh from this render's root.
 */
(function () {
  var script = document.currentScript;
  var root =
    (script && script.closest && script.closest('#tab-whatsapp-content')) ||
    document.getElementById('tab-whatsapp-content');
  if (!root || !root.dataset.conversationId) { return; }

  var HEADERS = { 'HX-Request': 'true', 'X-Requested-With': 'XMLHttpRequest' };
  var NEAR_BOTTOM_PX = 80;

  function getList() { return document.getElementById('whatsapp-message-list'); }

  function nearBottom(list) {
    return list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_BOTTOM_PX;
  }

  // Stay pinned to the bottom while a bubble's images load
  // (template headers / attachments change the height late).
  function pinBottom(list, node) {
    list.scrollTop = list.scrollHeight;
    node.querySelectorAll('img').forEach(function (img) {
      if (!img.complete) {
        img.addEventListener('load', function () { list.scrollTop = list.scrollHeight; });
      }
    });
  }

  function removeEmptyState() {
    var empty = document.getElementById('whatsapp-empty-state');
    if (empty) { empty.remove(); }
  }

  // ---------------------------------------------------------------- account switcher
  // The account select is a select2, which raises a jQuery "change" rather than a
  // native one, and can raise it more than once for a single pick. A second swap into
  // the already-replaced panel breaks the page, so act only on a real change, once.
  function initAccountSwitcher() {
    var select = document.getElementById('whatsapp-account-select');
    if (!select || !window.jQuery) { return; }
    var current = select.value;
    var switching = false;
    window.jQuery(select).off('change.waaccount').on('change.waaccount', function () {
      if (switching || select.value === current) { return; }
      switching = true;
      htmx.ajax('GET', select.dataset.panelUrl + '?account=' + encodeURIComponent(select.value), {
        target: '#tab-whatsapp-content',
        swap: 'outerHTML'
      });
    });
  }

  // ---------------------------------------------------------------- realtime updates
  // The server pushes the id of a message that was added or changed over a
  // WebSocket; we fetch just that bubble and append / replace it, so the list
  // is never reloaded or re-scrolled.
  function initRealtime() {
    var convId = root.dataset.conversationId;
    var itemUrl = root.dataset.itemUrl;
    var syncUrl = root.dataset.syncUrl;
    var delay = 1000;

    if (window.__waConvSocket) {
      window.__waConvSocket.__stop = true;
      window.__waConvSocket.close();
    }

    function applyMessage(messageId) {
      var list = getList();
      if (!list || !messageId) { return; }
      fetch(itemUrl.replace(/\/0\/$/, '/' + messageId + '/'), { headers: HEADERS, credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) {
          if (!html) { return; }
          list = getList();
          if (!list) { return; }
          var tpl = document.createElement('template');
          tpl.innerHTML = html.trim();
          var node = tpl.content.firstElementChild;
          if (!node) { return; }
          var existing = document.getElementById(node.id);
          var atBottom = nearBottom(list);
          if (existing) {
            var oldMeta = existing.querySelector('[data-role="meta"]');
            var newMeta = node.querySelector('[data-role="meta"]');
            var sameMedia =
              existing.querySelectorAll('img, a[target]').length === node.querySelectorAll('img, a[target]').length;
            if (oldMeta && newMeta && sameMedia) {
              // Only a status tick changed: swap just that row so the bubble
              // (and any image in it) is never re-created.
              oldMeta.replaceWith(newMeta);
              return;
            }
            var top = list.scrollTop;
            existing.replaceWith(node); // attachment arrived: swap the whole bubble
            if (atBottom) { pinBottom(list, node); } else { list.scrollTop = top; }
            return;
          }
          removeEmptyState();
          list.appendChild(node);
          if (atBottom || node.dataset.direction === 'out') { pinBottom(list, node); }
        });
    }

    // Catch-up: load any messages newer than the last one on screen
    // (after a send, and when the socket (re)connects).
    function syncNew() {
      var list = getList();
      if (!list) { return; }
      var last = 0;
      list.querySelectorAll('[id^="wa-msg-"]').forEach(function (el) {
        var id = parseInt(el.id.slice(7), 10);
        if (id > last) { last = id; }
      });
      fetch(syncUrl + '?after=' + last, { headers: HEADERS, credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.text() : ''; })
        .then(function (html) {
          if (!html || !html.trim()) { return; }
          list = getList();
          if (!list) { return; }
          var atBottom = nearBottom(list);
          var tpl = document.createElement('template');
          tpl.innerHTML = html.trim();
          Array.prototype.slice.call(tpl.content.children).forEach(function (node) {
            if (!node.id || document.getElementById(node.id)) { return; }
            removeEmptyState();
            list.appendChild(node);
            if (atBottom || node.dataset.direction === 'out') { pinBottom(list, node); }
          });
        });
    }
    window.__waSyncNew = syncNew;

    // Also covers the template modal, which lives outside the panel.
    if (window.__waAfterRequest) {
      document.body.removeEventListener('htmx:afterRequest', window.__waAfterRequest);
    }
    window.__waAfterRequest = function (evt) {
      var cfg = evt.detail.requestConfig || {};
      var path = cfg.path || '';
      if (cfg.verb === 'post' && path.indexOf('/whatsapp/whatsapp-send-') === 0) {
        setTimeout(syncNew, 300);
      }
    };
    document.body.addEventListener('htmx:afterRequest', window.__waAfterRequest);

    function connect() {
      var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
      var ws = new WebSocket(proto + location.host + '/ws/whatsapp/conversation/' + convId + '/');
      window.__waConvSocket = ws;
      ws.onopen = function () { delay = 1000; syncNew(); };
      ws.onmessage = function (e) {
        try { applyMessage(JSON.parse(e.data).message_id); } catch (err) { /* ignore */ }
      };
      ws.onclose = function () {
        if (ws.__stop || !document.getElementById('whatsapp-message-list-container')) { return; }
        setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30000);
      };
    }
    connect();
  }

  // ---------------------------------------------------------------- keep scroll on layout changes
  // The Expand / Collapse button above the tabs hides or shows the record header and
  // re-fits the page height. The browser then resets the list's scroll position to the
  // top, so remember where it was just before that click and put it back afterwards:
  // pinned to the bottom if it was at the bottom, otherwise at the same offset.
  function initScrollKeeper() {
    var container = document.getElementById('whatsapp-message-list-container');
    if (!container || !window.ResizeObserver) { return; }
    if (window.__waScrollKeeper) { window.__waScrollKeeper(); } // drop the previous render's hooks

    var snapshot = null;
    function onClick(evt) {
      var button = evt.target.closest && evt.target.closest('.detail-tab-expand-btn');
      var list = getList();
      if (!button || !list) { return; }
      snapshot = {
        top: list.scrollTop,
        atBottom: list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_BOTTOM_PX,
        until: Date.now() + 2500
      };
    }
    var observer = new ResizeObserver(function () {
      var list = getList();
      if (!snapshot || !list || Date.now() > snapshot.until) { return; }
      list.scrollTop = snapshot.atBottom ? list.scrollHeight : snapshot.top;
    });
    document.addEventListener('click', onClick, true);
    observer.observe(container);
    window.__waScrollKeeper = function () {
      document.removeEventListener('click', onClick, true);
      observer.disconnect();
      window.__waScrollKeeper = null;
    };
  }

  // ---------------------------------------------------------------- message box
  function initComposer() {
    var form = document.getElementById('whatsapp-send-message-form');
    if (!form) { return; } // the user can't send messages on this record
    var box = form.querySelector('textarea[name="body"]');
    var fileInput = document.getElementById('whatsapp-attachment-input');
    var preview = document.getElementById('whatsapp-attachment-preview');
    var fileName = document.getElementById('whatsapp-attachment-name');
    var saved = null;

    function showPreview(file) {
      if (file) {
        fileName.textContent = file.name;
        preview.classList.remove('hidden');
        preview.classList.add('flex');
      } else {
        preview.classList.add('hidden');
        preview.classList.remove('flex');
      }
    }

    fileInput.addEventListener('change', function (evt) { showPreview(evt.target.files[0]); });

    // Feel instant: clear the box the moment a send starts (the request already
    // has its text / file), show the new bubble straight away, and put everything
    // back if the send fails.
    form.addEventListener('htmx:beforeSend', function (evt) {
      if (evt.target !== form) { return; }
      saved = { text: box.value, files: Array.prototype.slice.call(fileInput.files || []) };
      box.value = '';
      fileInput.value = '';
      showPreview(null);
      setTimeout(function () { if (window.__waSyncNew) { window.__waSyncNew(); } }, 250);
    });

    form.addEventListener('htmx:afterRequest', function (evt) {
      if (evt.target !== form) { return; }
      if (evt.detail.successful) {
        form.reset();
        showPreview(null);
      } else if (saved) {
        box.value = saved.text;
        if (saved.files.length) {
          var transfer = new DataTransfer();
          saved.files.forEach(function (f) { transfer.items.add(f); });
          fileInput.files = transfer.files;
          fileInput.dispatchEvent(new Event('change'));
        }
      }
      saved = null;
    });

    // Enter sends, Shift+Enter inserts a new line (like WhatsApp). Ignored while an
    // input method is composing, and for an empty message.
    box.addEventListener('keydown', function (evt) {
      if (evt.key !== 'Enter' || evt.shiftKey || evt.isComposing) { return; }
      evt.preventDefault();
      if (box.value.trim() || (fileInput.files && fileInput.files.length)) {
        form.requestSubmit();
      }
    });
  }

  initAccountSwitcher();
  initRealtime();
  initScrollKeeper();
  initComposer();
})();
