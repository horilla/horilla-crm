(function () {
    var script = document.currentScript;
    var id = script.getAttribute('data-id');
    var idSafe = script.getAttribute('data-id-safe');
    var csrfCookieName = script.getAttribute('data-csrf-cookie-name');
    var disableAttachment = script.getAttribute('data-disable-attachment') === 'true';
    var lazy = script.getAttribute('data-lazy') === 'true';

    function jquery(arg) {
        var fn = script.getAttribute('data-jquery').split('.').reduce(function(obj, key) {
            return obj[key];
        }, window);
        return fn(arg);
    }

    function initSummernote() {
        jquery(document).ready(function($) {
            var origin = window.document.getElementById(id);
            var csrftoken = getCookie(csrfCookieName);
            var settings = JSON.parse(script.getAttribute('data-settings'));
            var attrs = JSON.parse(document.getElementById(script.getAttribute('data-attrs-id')).textContent);
            var $sn = $(origin);
            $sn.html(origin.value);
            if (settings.codeviewFilterRegexSource) {
                settings.codeviewFilterRegex = new RegExp(settings.codeviewFilterRegexSource, 'gi');
            }
            var $nEditor, $nCodable;

            function recalcHeight(e) {
                var nEditable = e.find('.note-editable');
                var nEditor = $('.note-editor');
                var height = parseInt(
                    parseInt(settings.height)  // default
                    - e.find('.note-toolbar').outerHeight()
                    - e.find('.note-status-output').outerHeight()
                    - e.find('.note-statusbar').outerHeight()
                    - (nEditor.outerHeight() - nEditor.innerHeight())  // editor's border
                );
                nEditable.outerHeight(height);
            }

            var initEditor = function() {
                var callbacks = {
                    onInit: function() {
                        $nEditor = $sn.next();
                        $nCodable = $nEditor.find('.note-codable');
                        recalcHeight($nEditor);

                        // Leaving full screen restores the height summernote read when the
                        // mode was entered, which is the full screen height now that the
                        // editing area is sized by CSS. Put the normal height back.
                        var wasFullscreen = false;
                        new MutationObserver(function () {
                            var isFullscreen = $nEditor.hasClass('fullscreen');
                            if (wasFullscreen && !isFullscreen) {
                                recalcHeight($nEditor);
                            }
                            wasFullscreen = isFullscreen;
                        }).observe($nEditor[0], { attributes: true, attributeFilter: ['class'] });

                        // Apply attributes with wrapper div
                        var $wrap = $($nEditor).wrap(
                            '<div class="summernote-div"></div>'
                        ).parent();
                        Object.keys(attrs).forEach(function(k) {
                            $wrap.attr(k, String(attrs[k]));
                        });

                        // Move dropdown dialog when it exceeds the bound of the editor.
                        // Summernote shows/hides these by toggling an "open" class on
                        // .note-btn-group directly (no shown.bs.dropdown event is fired),
                        // so watch for that instead of listening for a Bootstrap event.
                        var margin = 15;
                        function repositionDropdown(nBtnGroup) {
                            var nDropdown = nBtnGroup.find(".note-dropdown-menu");
                            if( !nDropdown.length ) {
                                return;
                            }
                            nDropdown.css({ top: "", bottom: "", left: "", "max-height": "" });

                            var offset = nDropdown.offset();
                            var width = nDropdown.width();
                            var height = nDropdown.outerHeight();

                            var windowWidth = $(window).width();
                            var windowHeight = $(window).height();

                            if( offset.left + width + margin > windowWidth ) {
                                var left = windowWidth - width - offset.left - margin;
                                nDropdown.css("left", left + "px");
                            }

                            if( offset.top + height + margin > windowHeight ) {
                                // Not enough room below: open the dropdown upward instead
                                // of letting it run past the bottom of the viewport.
                                nDropdown.css({ top: "auto", bottom: "100%" });
                                var spaceAbove = nBtnGroup.offset().top - margin;
                                if( height > spaceAbove ) {
                                    nDropdown.css({
                                        "max-height": spaceAbove + "px",
                                        "overflow-y": "auto"
                                    });
                                }
                            }
                        }
                        $nEditor.find('.note-btn-group').each(function () {
                            var nBtnGroup = $(this);
                            new MutationObserver(function () {
                                if( nBtnGroup.hasClass('open') ) {
                                    repositionDropdown(nBtnGroup);
                                }
                            }).observe(this, { attributes: true, attributeFilter: ['class'] });
                        });
                    },
                    onBlur: function() {
                        origin.value = $sn.summernote('code');
                    },
                    onBlurCodeview: function() {
                        origin.value = $sn.summernote('code');
                    }
                };
                if (!disableAttachment) {
                    callbacks.onImageUpload = function(files) {
                        var formData = new FormData();
                        formData.append('csrfmiddlewaretoken', csrftoken);
                        $.each(files, function(i, file) {
                            formData.append('files', file);
                        });
                        $.ajax({
                            url: settings.url.upload_attachment,
                            type: 'POST',
                            data: formData,
                            processData: false,
                            contentType: false,
                            success: function(data) {
                                if (data.files && data.files.length) {
                                    $.each(data.files, function(i, file) {
                                        $sn.summernote('insertImage', file.url);
                                    });
                                }
                            },
                            error: function() {
                                alert('Got an error while uploading images.');
                            }
                        });
                    };
                }
                $sn.summernote($.extend(settings, {
                    callbacks: callbacks
                }));
            };

            // include summernote language pack, synchronously
            $.ajax({url: settings.url.language, dataType: "script", complete: initEditor})

            // For CodeMirror
            $sn.on('summernote.codeview.toggled', function() {
                var cmEditor = $nCodable.data('cmEditor');
                if( cmEditor ) {
                    cmEditor.on('blur', function() {
                        origin.value = cmEditor.getValue();
                    });
                }
            });

            // See https://docs.djangoproject.com/en/dev/ref/contrib/csrf/#ajax
            function getCookie(name) {
                var cookieValue = null;
                if (document.cookie && document.cookie != '') {
                    var cookies = document.cookie.split(';');
                    for (var i = 0; i < cookies.length; i++) {
                        var cookie = jQuery.trim(cookies[i]);
                        // Does this cookie string begin with the name we want?
                        if (cookie.substring(0, name.length + 1) == (name + '=')) {
                            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                            break;
                        }
                    }
                }
                return cookieValue;
            }
        });
    }

    window['initSummernote_' + idSafe] = initSummernote;

    if (lazy) {
        if (window.__summernotes__ === undefined) {
            window.__summernotes__ = new Array();
            window.initSummernote = function() {
                for (var i = 0, l = window.__summernotes__.length; i < l; ++i) {
                    window.__summernotes__[i]();
                }
            };
        }
        window.__summernotes__.push(initSummernote);
    } else {
        initSummernote();
    }
})();
