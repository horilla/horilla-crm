var emailPillsFallbackUrls = (function (script) {
  if (script) {
    window.__emailPillsFallbackUrls = {
      add: script.getAttribute("data-add-email-url"),
      remove: script.getAttribute("data-remove-email-url"),
    };
  }
  return window.__emailPillsFallbackUrls;
})(document.currentScript);

function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email.trim());
}

function _emailPillsUrl(fieldType, cls, fallback) {
  const el = document.querySelector(`#email-input-${fieldType} .${cls}`);
  return el ? el.value : fallback;
}

function addEmailPill(email, fieldType) {
  if (!email || !isValidEmail(email)) {
    return false;
  }

  // Use HTMX to add the email
  htmx.ajax("POST", _emailPillsUrl(fieldType, "email-pills-add-url", emailPillsFallbackUrls.add), {
    values: {
      email: email.trim(),
      field_type: fieldType,
      [fieldType + "_email_list"]: document.querySelector(
        `[name="${fieldType}_email_list"]`
      ).value,
    },
    target: `#email-input-${fieldType}`,
    swap: "outerHTML",
  });

  return true;
}

function handleEmailInput(event, fieldType) {
  const input = event.target;
  const email = input.value.trim();

  // Handle Enter, Tab, comma, or semicolon
  if (
    event.key === "Enter" ||
    event.key === "Tab" ||
    event.key === "," ||
    event.key === ";"
  ) {
    event.preventDefault();

    if (email && isValidEmail(email)) {
      addEmailPill(email, fieldType);
      // Clear suggestions
      document.getElementById(`email-suggestions-${fieldType}`).innerHTML =
        "";
    }
  }

  // Handle Backspace when input is empty (remove last pill)
  if (event.key === "Backspace" && !email) {
    const emailListInput = document.querySelector(
      `[name="${fieldType}_email_list"]`
    );
    const currentEmails = emailListInput.value
      .split(",")
      .filter((e) => e.trim());

    if (currentEmails.length > 0) {
      // Remove the last email
      const emailToRemove = currentEmails[currentEmails.length - 1].trim();

      htmx.ajax("POST", _emailPillsUrl(fieldType, "email-pills-remove-url", emailPillsFallbackUrls.remove), {
        values: {
          email_to_remove: emailToRemove,
          field_type: fieldType,
          [fieldType + "_email_list"]: emailListInput.value,
        },
        target: `#email-input-${fieldType}`,
        swap: "outerHTML",
      });
    }
  }
}

function handleEmailBlur(event, fieldType) {
  const email = event.target.value.trim();
  const sugg = document.getElementById(`email-suggestions-${fieldType}`);

  // If focus is moving to a suggestion item, let its own click handler
  // add the pill and clear the dropdown; don't race it here.
  if (sugg && sugg.dataset.mousedown === "1") {
    return;
  }

  // Small delay to allow for suggestion clicks
  setTimeout(() => {
    // Add email as pill when user clicks away or tabs out, if valid
    if (email && isValidEmail(email)) {
      addEmailPill(email, fieldType);
    }
    // Always clear suggestions on blur, valid email or not
    if (sugg) sugg.innerHTML = "";
  }, 100);
}

if (!window.__emailPillsListenersBound) {
  window.__emailPillsListenersBound = true;

  document.addEventListener(
    "mousedown",
    function (event) {
      const sugg = event.target.closest('[id^="email-suggestions-"]');
      if (sugg) {
        sugg.dataset.mousedown = "1";
        setTimeout(() => {
          delete sugg.dataset.mousedown;
        }, 300);
      }
    },
    true
  );

  document.addEventListener("paste", function (event) {
    const target = event.target;
    if (target.name && target.name.endsWith("_email_input")) {
      const fieldType = target.name.replace("_email_input", "");

      setTimeout(() => {
        const pastedText = target.value;
        const emails = pastedText
          .split(/[,;\s]+/)
          .filter((email) => email.trim() && isValidEmail(email.trim()));

        if (emails.length > 1) {
          // Clear the input
          target.value = "";

          // Add each valid email as a pill
          emails.forEach((email) => {
            addEmailPill(email.trim(), fieldType);
          });
        }
      }, 10);
    }
  });
}
