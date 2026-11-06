/**
 * Demo database loader (progress bar, per-file status, redirect to login).
 *
 * Loaded by load_data/loading.html. The script tag carries the Django values:
 * data-total-files, data-login-url, data-load-url and the translated labels
 * data-label-loading / data-label-error / data-label-network-error.
 */
(function() {
  const dataset = (document.currentScript && document.currentScript.dataset) || {};
  const labels = {
    loading: dataset.labelLoading || 'Loading',
    error: dataset.labelError || 'Error:',
    networkError: dataset.labelNetworkError || 'Network error occurred',
  };
  const loginUrl = dataset.loginUrl || '/';
  const loadUrl = dataset.loadUrl || '';
  let currentFileIndex = 0;
  const totalFiles = parseInt(dataset.totalFiles, 10) || 0;
  let currentProgress = 0;
  let targetProgress = 0;
  let isLoading = false;
  let animationFrameId = null;

  function animateProgress() {
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');

    if (isLoading && currentProgress < targetProgress - 2) {
      currentProgress += 0.15;
    } else if (currentProgress < targetProgress) {
      currentProgress += 1.0;

      if (currentProgress > targetProgress) {
        currentProgress = targetProgress;
      }
    }

    if (progressBar) {
      progressBar.style.width = currentProgress + '%';

      progressBar.classList.remove('bg-red-500', 'bg-orange-500', 'bg-green-500');
      if (currentProgress < 40) {
        progressBar.classList.add('bg-red-500');
      } else if (currentProgress < 80) {
        progressBar.classList.add('bg-orange-500');
      } else {
        progressBar.classList.add('bg-green-500');
      }
    }

    if (progressPercent) {
      progressPercent.textContent = Math.round(currentProgress) + '%';
    }

    animationFrameId = requestAnimationFrame(animateProgress);
  }

  function updateProgress(data) {
    const progressText = document.getElementById('progress-text');

    if (data.progress !== undefined) {
      targetProgress = data.progress;
      isLoading = false;

      if (!animationFrameId) {
        animateProgress();
      }
    }

    if (progressText) {
      const displayName = data.display_name || data.file;
      progressText.textContent = labels.loading + ' ' + '... (' + data.current + '/' + data.total + ')';
    }

    //if (progressText && data.file) {
    //  progressText.textContent = labels.loading + ' ' + data.file + '... (' + data.current + '/' + data.total + ')';
    //}

    if (data.file) {
      const fileItems = document.querySelectorAll('.file-item');
      fileItems.forEach(item => {
        if (item.dataset.file === data.file) {
          const pending = item.querySelector('.pending');
          const done = item.querySelector('.done');
          if (pending) pending.classList.add('hidden');
          if (done) done.classList.remove('hidden');
        }
      });
    }
  }

  function showError(message, filename) {
    const statusMessage = document.getElementById('status-message');
    if (statusMessage) {
      statusMessage.innerHTML = '<span class="text-red-500">' + labels.error + ' ' + message + '</span>';
    }

    if (filename) {
      const fileItems = document.querySelectorAll('.file-item');
      fileItems.forEach(item => {
        if (item.dataset.file === filename) {
          const pending = item.querySelector('.pending');
          const error = item.querySelector('.error');
          if (pending) pending.classList.add('hidden');
          if (error) error.classList.remove('hidden');
        }
      });
    }

    // Stop animation on error
    isLoading = false;
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
  }

  function showSuccess() {
    const successMessage = document.getElementById('success-message');
    const loadingAnimation = document.getElementById('loading-animation');

    isLoading = false;
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }

    if (successMessage) {
      successMessage.classList.remove('hidden');
    }
    if (loadingAnimation) loadingAnimation.classList.remove('hidden');

    setTimeout(() => {
      window.location.href = loginUrl;
    }, 6000);
  }

  function loadNextFile() {
    if (currentFileIndex >= totalFiles) {
      showSuccess();
      return;
    }

    // Calculate the target progress for this file
    const nextTargetProgress = ((currentFileIndex + 1) / totalFiles) * 100;

    // Set simulated target (leave 2% buffer for server response)
    targetProgress = nextTargetProgress - 2;
    isLoading = true;

    // Start animation if not already running
    if (!animationFrameId) {
      animateProgress();
    }

    const url = loadUrl + '?file_index=' + currentFileIndex;

    fetch(url, {
      method: 'GET',
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
    .then(response => {
      if (!response.ok) {
        throw new Error('Network response was not ok: ' + response.status);
      }
      return response.json();
    })
    .then(data => {
      if (data.status === 'success') {
        updateProgress(data);
        currentFileIndex++;

        // Load next file immediately
        setTimeout(() => loadNextFile(), 100);

      } else if (data.status === 'complete') {
        showSuccess();

      } else if (data.status === 'error') {
        showError(data.message, data.file);
      }
    })
    .catch(error => {
      showError(labels.networkError);
    });
  }

  loadNextFile();
})();
