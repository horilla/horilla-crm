(function () {
    function clearFileInput(event) {
        event.preventDefault();
        event.stopPropagation();
        const clearBtn = event.currentTarget;
        const fieldId = clearBtn.getAttribute('data-file-clear');
        const kind = clearBtn.getAttribute('data-file-kind');
        const input = document.getElementById(fieldId);
        const fileName = document.getElementById(fieldId + '-name');
        const clearedFlag = document.getElementById(fieldId + '-cleared');
        const preview = document.getElementById(fieldId + '-preview');
        const placeholder = document.getElementById(fieldId + '-placeholder');

        if (input) {
            input.value = '';
            if (kind === 'file') {
                fileName.textContent = clearBtn.getAttribute('data-no-file-text');
                fileName.setAttribute('data-has-file', 'false');
            }
            if (clearBtn) clearBtn.style.display = 'none';
            if (clearedFlag) clearedFlag.value = 'true';
            if (kind === 'image') {
                if (preview) {
                    preview.style.display = 'none';
                    preview.removeAttribute('src');
                }
                if (placeholder) placeholder.style.removeProperty('display');
            }
        }
    }

    function initImageField(clearBtn, fieldId) {
        const input = document.getElementById(fieldId);
        const clearedFlag = document.getElementById(fieldId + '-cleared');
        const preview = document.getElementById(fieldId + '-preview');
        const placeholder = document.getElementById(fieldId + '-placeholder');

        if (input) {
            input.addEventListener('change', function() {
                if (this.files && this.files.length > 0) {
                    if (clearBtn) clearBtn.style.removeProperty('display');
                    if (clearedFlag) clearedFlag.value = 'false';
                    if (preview) {
                        const reader = new FileReader();
                        reader.onload = function(e) {
                            preview.src = e.target.result;
                            preview.style.removeProperty('display');
                            if (placeholder) placeholder.style.display = 'none';
                        };
                        reader.readAsDataURL(this.files[0]);
                    }
                } else {
                    if (clearBtn) clearBtn.style.display = 'none';
                    if (preview) {
                        preview.style.display = 'none';
                        preview.removeAttribute('src');
                    }
                    if (placeholder) placeholder.style.removeProperty('display');
                }
            });
        }
    }

    function initFileField(clearBtn, fieldId) {
        const input = document.getElementById(fieldId);
        const fileName = document.getElementById(fieldId + '-name');
        const clearedFlag = document.getElementById(fieldId + '-cleared');
        const noFileText = clearBtn.getAttribute('data-no-file-text');

        if (input && fileName) {
            input.addEventListener('change', function() {
                if (this.files && this.files.length > 0) {
                    fileName.textContent = this.files[0].name;
                    fileName.setAttribute('data-has-file', 'true');
                    if (clearBtn) clearBtn.style.display = 'inline-block';
                    if (clearedFlag) clearedFlag.value = 'false';
                } else {
                    fileName.textContent = noFileText;
                    fileName.setAttribute('data-has-file', 'false');
                    if (clearBtn) clearBtn.style.display = 'none';
                }
            });

            // Show clear button based on session state
            const hasFile = fileName.getAttribute('data-has-file') === 'true';
            if (hasFile && clearBtn) {
                clearBtn.style.display = 'inline-block';
            }
        }
    }

    function initFormViewFileFields() {
        document.querySelectorAll('[data-file-clear]').forEach(function(clearBtn) {
            if (clearBtn.dataset.fileFieldInit === 'true') return;
            clearBtn.dataset.fileFieldInit = 'true';
            const fieldId = clearBtn.getAttribute('data-file-clear');
            clearBtn.addEventListener('click', clearFileInput);
            if (clearBtn.getAttribute('data-file-kind') === 'image') {
                initImageField(clearBtn, fieldId);
            } else {
                initFileField(clearBtn, fieldId);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFormViewFileFields);
    } else {
        initFormViewFileFields();
    }

    $(document).ready(function () {
        $("select").on("select2:select", function (e) {
            $(this).closest("select")[0].dispatchEvent(new Event("change"));
        });
    });

    if (!window.__formViewSelect2PaginationBound) {
        window.__formViewSelect2PaginationBound = true;
        document.addEventListener('htmx:afterSettle', function(event) {
            initializeSelect2Pagination();
        });
    }
    initializeSelect2Pagination();
})();

(function () {
    function initImageFileInput(input) {
        const clearBtn = document.getElementById(input.id + '-clear');
        const clearInput = document.getElementById(input.id + '_clear_input');
        const preview = document.getElementById(input.id + '-preview');
        const placeholder = document.getElementById(input.id + '-placeholder');

        if (!clearBtn || !clearInput || !preview || !placeholder) return;
        if (input.dataset.fileInit === "true") return;
        input.dataset.fileInit = "true";

        input.addEventListener('change', function() {
            if (input.files.length > 0) {
                clearInput.value = 'false';
                const reader = new FileReader();
                reader.onload = function(e) {
                    preview.src = e.target.result;
                    preview.style.removeProperty('display');
                    placeholder.style.display = 'none';
                    clearBtn.style.removeProperty('display');
                };
                reader.readAsDataURL(input.files[0]);
            } else {
                preview.style.display = 'none';
                preview.removeAttribute('src');
                placeholder.style.removeProperty('display');
                clearBtn.style.display = 'none';
                clearInput.value = 'true';
            }
        });

        clearBtn.addEventListener('click', function(event) {
            event.stopPropagation();
            input.value = '';
            preview.style.display = 'none';
            preview.removeAttribute('src');
            placeholder.style.removeProperty('display');
            clearBtn.style.display = 'none';
            clearInput.value = 'true';
        });
    }

    function initFileInput(input) {
        const fileName = document.getElementById(input.id + '-name');
        const clearBtn = document.getElementById(input.id + '-clear');
        const clearInput = document.getElementById(input.id + '_clear_input');

        if (!fileName || !clearBtn || !clearInput) return;
        if (input.dataset.fileInit === "true") return;
        input.dataset.fileInit = "true";

        const noFileText = 'No file chosen';
        const wasCleared = fileName.getAttribute('data-cleared') === 'true';
        const uploadedFilename = fileName.getAttribute('data-uploaded') || '';
        const existingFilename = fileName.getAttribute('data-existing') || '';

        let currentFilename = '';
        let hasFile = false;

        if (wasCleared) {
            clearInput.value = 'true';
        } else if (uploadedFilename) {
            currentFilename = uploadedFilename;
            clearInput.value = 'false';
            hasFile = true;
        } else if (existingFilename) {
            currentFilename = existingFilename.split('/').pop();
            clearInput.value = 'false';
            hasFile = true;
        }

        if (hasFile && currentFilename) {
            fileName.textContent = currentFilename;
            clearBtn.style.removeProperty('display');
        } else {
            fileName.textContent = noFileText;
            clearBtn.style.display = 'none';
        }

        input.addEventListener('change', function() {
            if (input.files.length > 0) {
                fileName.textContent = input.files[0].name;
                clearBtn.style.removeProperty('display');
                clearInput.value = 'false';
            } else {
                fileName.textContent = noFileText;
                clearBtn.style.display = 'none';
                clearInput.value = 'true';
            }
        });

        clearBtn.addEventListener('click', function() {
            input.value = '';
            fileName.textContent = noFileText;
            clearBtn.style.display = 'none';
            clearInput.value = 'true';
        });
    }

    function initAllFileInputs(root=document) {
        root.querySelectorAll('input[type="file"]').forEach(function(input) {
            initImageFileInput(input);
            initFileInput(input);
        });
    }

    window.initImageFileInput = initImageFileInput;
    window.initFileInput = initFileInput;
    window.initAllFileInputs = initAllFileInputs;

    document.addEventListener('DOMContentLoaded', function() {
        initAllFileInputs();
    });

    if (!window.__singleFormViewFileInputsBound) {
        window.__singleFormViewFileInputsBound = true;
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            if (evt.target.querySelectorAll) {
                initAllFileInputs(evt.target);
            }
        });
    }

    initAllFileInputs();
})();
