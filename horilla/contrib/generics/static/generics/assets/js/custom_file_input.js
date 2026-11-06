// Behaviour for the CustomFileInput widget (forms/widgets/custom_file_input.html).
// The widget is rendered once per field and its fragment can be swapped in by HTMX,
// so this script runs many times: every run initialises only the widgets that have
// not been set up yet. Per-widget values (ids and translated strings) are read from
// data-* attributes on the widget wrapper ([data-file-upload]).
(function () {
  function initFileUpload(wrapper) {
    var data = wrapper.dataset;
    var fileInput = document.getElementById(data.inputId);
    var uploadBoxContent = document.getElementById("uploadBoxContent_" + data.inputId);
    var clearButton = document.getElementById("clearButton_" + data.inputId);
    var dropZone = document.getElementById("dropZone_" + data.inputId);

    if (fileInput && uploadBoxContent && dropZone) {
      wrapper.dataset.fileUploadReady = "1";

      // Remove any existing listeners to prevent duplicates
      var newFileInput = fileInput.cloneNode(true);
      fileInput.parentNode.replaceChild(newFileInput, fileInput);

      // File change handler
      function handleFileSelect(file) {
        if (file) {
          uploadBoxContent.innerHTML = `
            <i class="fa-solid fa-file text-xl mb-2 text-green-500"></i>
            <p class="text-sm font-semibold text-gray-700 truncate max-w-full">${file.name}</p>
            <p class="text-xs text-[#9e9e9e]">${data.fileSelectedText}</p>
          `;
          if (clearButton) {
            clearButton.classList.remove("hidden");
          }
        } else {
          uploadBoxContent.innerHTML = `
            <i class="fa-solid fa-arrow-up-from-bracket text-xl mb-2 text-gray-500"></i>
            <p class="text-sm font-semibold text-gray-700">${data.uploadPromptText}</p>
            <p class="text-xs text-[#9e9e9e]">${data.uploadHintText}</p>
          `;
          if (clearButton) {
            clearButton.classList.add("hidden");
          }
        }
      }

      // File input change event
      newFileInput.addEventListener("change", function () {
        handleFileSelect(this.files[0]);
      });

      // Drag and drop events
      ["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
      });

      function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
      }

      // Highlight drop zone when dragging over it
      ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, function () {
          dropZone.classList.add("border-blue-500", "bg-blue-50");
        }, false);
      });

      ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, function () {
          dropZone.classList.remove("border-blue-500", "bg-blue-50");
        }, false);
      });

      // Handle dropped files
      dropZone.addEventListener("drop", function (e) {
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files.length > 0) {
          // Create a new DataTransfer object to set files on the input
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(files[0]);
          newFileInput.files = dataTransfer.files;

          // Trigger the change event
          handleFileSelect(files[0]);
        }
      });

      // Clear button functionality
      if (clearButton) {
        // Remove existing listeners
        var newClearButton = clearButton.cloneNode(true);
        clearButton.parentNode.replaceChild(newClearButton, clearButton);

        newClearButton.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();

          // Clear the file input
          newFileInput.value = "";

          // Check the hidden checkbox to mark file for deletion
          const clearCheckbox = document.getElementById(data.checkboxId);
          if (clearCheckbox) {
            clearCheckbox.checked = true;
          }

          // Reset the upload box content
          handleFileSelect(null);
        });
      }
    }
  }

  function initAllFileUploads() {
    document
      .querySelectorAll("[data-file-upload]:not([data-file-upload-ready])")
      .forEach(initFileUpload);
  }

  // Initialize on DOM load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAllFileUploads);
  } else {
    initAllFileUploads();
  }

  // Re-initialize after HTMX swaps content (one shared listener for every widget)
  if (!window._horillaFileInputSwapBound) {
    window._horillaFileInputSwapBound = true;
    document.body.addEventListener("htmx:afterSwap", function () {
      // Small delay to ensure DOM is updated
      setTimeout(initAllFileUploads, 10);
    });
  }
})();
