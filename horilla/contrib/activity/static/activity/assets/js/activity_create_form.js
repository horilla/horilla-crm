(function () {
  // URLs are passed from the template via data-* attributes on this script tag.
  // currentScript is only set while the script runs, so read it synchronously.
  var scriptData = document.currentScript ? document.currentScript.dataset : {};
  var ADD_EMAIL_URL = scriptData.addEmailUrl;
  var REMOVE_EMAIL_URL = scriptData.removeEmailUrl;

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  }

  function addEmailPill(email, fieldType) {
    if (!email || !isValidEmail(email)) return false;
    htmx.ajax("POST", ADD_EMAIL_URL, {
      values: {
        email: email.trim(),
        field_type: fieldType,
        [fieldType + "_email_list"]: (document.querySelector('[name="' + fieldType + '_email_list"]') || {value: ''}).value,
      },
      target: '#email-input-' + fieldType,
      swap: 'outerHTML',
    });
    return true;
  }

  function handleEmailInput(event, fieldType) {
    if (fieldType !== 'external_participants') return;
    var input = event.target;
    var email = input.value.trim();
    if (event.key === 'Enter' || event.key === 'Tab' || event.key === ',' || event.key === ';') {
      event.preventDefault();
      if (email && isValidEmail(email)) {
        addEmailPill(email, fieldType);
        var sugg = document.getElementById('email-suggestions-' + fieldType);
        if (sugg) sugg.innerHTML = '';
      }
    }
    if (event.key === 'Backspace' && !email) {
      var listInput = document.querySelector('[name="' + fieldType + '_email_list"]');
      if (!listInput) return;
      var emails = listInput.value.split(',').filter(function(e) { return e.trim(); });
      if (emails.length) {
        htmx.ajax("POST", REMOVE_EMAIL_URL, {
          values: {
            email_to_remove: emails[emails.length - 1].trim(),
            field_type: fieldType,
            [fieldType + "_email_list"]: listInput.value,
          },
          target: '#email-input-' + fieldType,
          swap: 'outerHTML',
        });
      }
    }
  }

  function handleEmailBlur(event, fieldType) {
    if (fieldType !== 'external_participants') return;
    var email = event.target.value.trim();
    var sugg = document.getElementById('email-suggestions-' + fieldType);

    // If focus is moving to a suggestion item, let its own click
    // handler add the pill and clear the dropdown; don't race it here.
    if (sugg && sugg.dataset.mousedown === '1') {
      return;
    }

    setTimeout(function() {
      if (email && isValidEmail(email)) {
        addEmailPill(email, fieldType);
      }
      if (sugg) sugg.innerHTML = '';
    }, 100);
  }

  // This file re-runs each time the form fragment is swapped in; bind the
  // document-level listeners only once so they don't stack up.
  var firstRun = !window._activityCreateFormBound;
  window._activityCreateFormBound = true;

  if (firstRun) document.addEventListener('mousedown', function (event) {
    var sugg = event.target.closest('[id^="email-suggestions-"]');
    if (sugg) {
      sugg.dataset.mousedown = '1';
      setTimeout(function () {
        delete sugg.dataset.mousedown;
      }, 300);
    }
  }, true);

  window.handleEmailInput = handleEmailInput;
  window.handleEmailBlur = handleEmailBlur;
  window.addEmailPill = addEmailPill;

  function getFieldRow(selector) {
    var input = document.querySelector(selector);
    // A hidden input (e.g. a field hidden for the current activity type)
    // has no labeled row of its own; treating its outer wrapper as the
    // "row" would hide unrelated sibling content.
    if (!input || input.type === 'hidden') return null;
    var el = input;
    for (var i = 0; i < 6; i++) {
      el = el.parentElement;
      if (!el) break;
      if (el.querySelector('label') && el.querySelector(selector)) return el;
    }
    return input.parentElement;
  }

  function applyVisibility() {
    var cb = document.getElementById('id_is_online');
    // Not a meeting-type form (anymore) in the current DOM: nothing to toggle.
    // Without this guard, a stale listener from a previous meeting render
    // can mis-hide the whole form after switching to another activity type,
    // since #id_meeting_provider still exists there as a bare hidden input
    // and getFieldRow() falls back to an outer wrapper as its "row".
    if (!cb) return;
    var online = cb.checked;
    var providerRow = getFieldRow('#id_meeting_provider');
    if (providerRow) providerRow.style.display = online ? '' : 'none';
    var urlRow = getFieldRow('[data-online-field="true"]:not(#id_meeting_provider)');
    if (urlRow) urlRow.style.display = online ? '' : 'none';
  }

  window.toggleMeetingUrlField = function (cb) { applyVisibility(); };

  if (firstRun) document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'id_meeting_provider') applyVisibility();
  });

  applyVisibility();
  if (firstRun) document.addEventListener('htmx:afterSwap', applyVisibility);
})();
