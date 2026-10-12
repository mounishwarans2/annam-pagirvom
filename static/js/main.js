// Annam Pagirvom Interactive Utilities & PWA / Camera / GPS Handlers

document.addEventListener('DOMContentLoaded', function() {
  // 1. Auto-dismiss flash alerts after 6 seconds
  const alerts = document.querySelectorAll('.flash-message');
  alerts.forEach(function(alert) {
    setTimeout(function() {
      alert.style.transition = 'opacity 0.5s ease';
      alert.style.opacity = '0';
      setTimeout(function() {
        alert.remove();
      }, 500);
    }, 6000);
  });

  // 2. Client-side quick confirmation for destructive/handover actions
  const confirmForms = document.querySelectorAll('form[data-confirm]');
  confirmForms.forEach(function(form) {
    form.addEventListener('submit', function(e) {
      const msg = form.getAttribute('data-confirm') || 'Are you sure you want to proceed?';
      if (!confirm(msg)) {
        e.preventDefault();
      }
    });
  });

  // 2b. Prevent duplicate submissions across all forms
  const allForms = document.querySelectorAll('form');
  allForms.forEach(function(form) {
    form.addEventListener('submit', function(e) {
      if (!navigator.onLine) {
        e.preventDefault();
        alert('⚠️ Network Offline: Cannot submit to database without internet connection. Please reconnect and retry / நீங்கள் ஆஃப்லைனில் உள்ளீர்கள். இணைய இணைப்பைச் சரிபார்த்து மீண்டும் முயற்சிக்கவும்.');
        return false;
      }
      if (form.getAttribute('data-submitting') === 'true') {
        e.preventDefault();
        return false;
      }
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn && !form.hasAttribute('data-no-disable')) {
        form.setAttribute('data-submitting', 'true');
        const origContent = submitBtn.innerHTML;
        submitBtn.setAttribute('data-orig-content', origContent);
        submitBtn.style.opacity = '0.75';
        submitBtn.innerHTML = '⏳ Submitting... / சமர்ப்பிக்கிறது...';
        setTimeout(function() {
          form.removeAttribute('data-submitting');
          submitBtn.style.opacity = '1';
          submitBtn.innerHTML = origContent;
        }, 10000);
      }
    });
  });

  // 2c. Network Online / Offline Live Status Indicator
  function updateNetworkStatus() {
    const banner = document.getElementById('networkStatusBanner');
    if (!banner) return;
    if (!navigator.onLine) {
      banner.className = 'network-status-banner offline';
      banner.style.display = 'block';
      banner.innerHTML = '⚠️ Offline: No Internet Connection / நீங்கள் ஆஃப்லைனில் உள்ளீர்கள் (இணைய இணைப்பு இல்லை)';
    } else {
      if (banner.style.display !== 'none' && banner.classList.contains('offline')) {
        banner.className = 'network-status-banner online';
        banner.innerHTML = '✓ Connection Restored / இணைய இணைப்பு மீண்டும் கிடைத்தது!';
        setTimeout(function() { banner.style.display = 'none'; }, 3000);
      }
    }
  }
  window.addEventListener('online', updateNetworkStatus);
  window.addEventListener('offline', updateNetworkStatus);
  updateNetworkStatus();

  // 3. Quick demo login credentials auto-fill
  const demoButtons = document.querySelectorAll('.btn-demo-fill');
  demoButtons.forEach(function(btn) {
    btn.addEventListener('click', function() {
      const username = btn.getAttribute('data-username');
      const password = btn.getAttribute('data-password');
      const userInput = document.getElementById('username');
      const passInput = document.getElementById('password');
      if (userInput && passInput) {
        userInput.value = username;
        passInput.value = password;
      }
    });
  });

  // 4. Mobile menu toggle
  const mobileToggle = document.getElementById('mobileMenuToggle');
  const navMenu = document.querySelector('.nav-menu');
  if (mobileToggle && navMenu) {
    mobileToggle.addEventListener('click', function() {
      navMenu.classList.toggle('nav-open');
    });
  }

  // 5. PWA Install Prompt handling
  let deferredPrompt;
  const installBtn = document.getElementById('pwaInstallBtn');
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBtn) {
      installBtn.style.display = 'inline-flex';
    }
  });

  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        if (outcome === 'accepted') {
          installBtn.style.display = 'none';
        }
        deferredPrompt = null;
      } else {
        alert("To install on mobile: Tap browser menu (⋮ or Share) and select 'Add to Home Screen' / 'Install App'.");
      }
    });
  }

  // 6. Register Service Worker if supported
  if ('serviceWorker' in navigator && (window.location.protocol === 'https:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.log('Service Worker registration skipped or failed:', err);
    });
  }

  // 7. Live Camera Module (for Donation Post Form)
  initCameraModule();

  // 8. GPS Location Module (for Donation Post Form)
  initGPSModule();
});

// Camera Implementation
function initCameraModule() {
  const startCamBtn = document.getElementById('startCameraBtn');
  const captureBtn = document.getElementById('capturePhotoBtn');
  const retakeBtn = document.getElementById('retakePhotoBtn');
  const useBtn = document.getElementById('usePhotoBtn');
  const removeBtn = document.getElementById('removePhotoBtn');
  const videoElem = document.getElementById('cameraVideo');
  const canvasElem = document.getElementById('cameraCanvas');
  const cameraContainer = document.getElementById('cameraContainer');
  const photoPreview = document.getElementById('photoPreview');
  const photoPreviewImg = document.getElementById('photoPreviewImg');
  const photoBase64Input = document.getElementById('captured_image_base64');
  const cameraError = document.getElementById('cameraError');
  const fileInput = document.getElementById('food_image_file');

  let mediaStream = null;
  let capturedDataUrl = null;

  if (!startCamBtn) return; // Not on post_donation page

  startCamBtn.addEventListener('click', async function() {
    if (cameraError) cameraError.style.display = 'none';
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (cameraError) {
        cameraError.textContent = "Live camera API is not supported on this browser or requires a secure connection (HTTPS / localhost). Please use the mobile file upload below.";
        cameraError.style.display = 'block';
      }
      return;
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 }
        },
        audio: false
      });
      videoElem.srcObject = mediaStream;
      await videoElem.play();

      cameraContainer.style.display = 'block';
      startCamBtn.style.display = 'none';
      captureBtn.style.display = 'inline-flex';
      retakeBtn.style.display = 'none';
      useBtn.style.display = 'none';
      videoElem.style.display = 'block';
      canvasElem.style.display = 'none';
    } catch (err) {
      console.error("Camera access error:", err);
      if (cameraError) {
        cameraError.textContent = "Camera permission was denied or camera is unavailable. Please grant permission or use the mobile photo upload option below.";
        cameraError.style.display = 'block';
      }
    }
  });

  if (captureBtn) {
    captureBtn.addEventListener('click', function() {
      if (!videoElem) return;
      canvasElem.width = videoElem.videoWidth || 640;
      canvasElem.height = videoElem.videoHeight || 480;
      const ctx = canvasElem.getContext('2d');
      ctx.drawImage(videoElem, 0, 0, canvasElem.width, canvasElem.height);

      capturedDataUrl = canvasElem.toDataURL('image/jpeg', 0.85);

      // Stop camera stream
      stopStream();

      videoElem.style.display = 'none';
      canvasElem.style.display = 'block';
      captureBtn.style.display = 'none';
      retakeBtn.style.display = 'inline-flex';
      useBtn.style.display = 'inline-flex';
    });
  }

  if (retakeBtn) {
    retakeBtn.addEventListener('click', function() {
      startCamBtn.click();
    });
  }

  if (useBtn) {
    useBtn.addEventListener('click', function() {
      if (capturedDataUrl) {
        photoBase64Input.value = capturedDataUrl;
        photoPreviewImg.src = capturedDataUrl;
        photoPreview.style.display = 'block';
        cameraContainer.style.display = 'none';
        startCamBtn.style.display = 'inline-flex';
        // Clear manual file input to prevent ambiguity
        if (fileInput) fileInput.value = '';
      }
    });
  }

  if (removeBtn) {
    removeBtn.addEventListener('click', function() {
      photoBase64Input.value = '';
      photoPreviewImg.src = '';
      photoPreview.style.display = 'none';
      capturedDataUrl = null;
      stopStream();
      cameraContainer.style.display = 'none';
      startCamBtn.style.display = 'inline-flex';
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', function(e) {
      const file = e.target.files[0];
      if (file) {
        if (file.size > 8 * 1024 * 1024) {
          alert("Image file size must be less than 8MB.");
          fileInput.value = '';
          return;
        }
        const reader = new FileReader();
        reader.onload = function(evt) {
          photoPreviewImg.src = evt.target.result;
          photoPreview.style.display = 'block';
          // Clear any base64 from camera since file is chosen
          photoBase64Input.value = '';
          stopStream();
          cameraContainer.style.display = 'none';
        };
        reader.readAsDataURL(file);
      }
    });
  }

  function stopStream() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
      mediaStream = null;
    }
  }
}

// GPS Geolocation Implementation
function initGPSModule() {
  const gpsBtn = document.getElementById('captureGpsBtn');
  const gpsStatus = document.getElementById('gpsStatus');
  const gpsBadge = document.getElementById('gpsBadge');
  const latInput = document.getElementById('latitude');
  const lngInput = document.getElementById('longitude');
  const accInput = document.getElementById('location_accuracy');
  const latDisplay = document.getElementById('gpsLatDisplay');
  const lngDisplay = document.getElementById('gpsLngDisplay');
  const accDisplay = document.getElementById('gpsAccDisplay');
  const mapLink = document.getElementById('osmMapLink');
  const addressTextarea = document.getElementById('pickup_address');

  if (!gpsBtn) return; // Not on post_donation page

  gpsBtn.addEventListener('click', function() {
    if (!navigator.geolocation) {
      if (gpsStatus) {
        gpsStatus.textContent = "Geolocation is not supported by your browser. Please type the pickup address manually.";
        gpsStatus.style.display = 'block';
      }
      return;
    }

    gpsBtn.disabled = true;
    gpsStatus.textContent = "Requesting GPS coordinates (Please grant permission)...";
    gpsStatus.style.display = 'block';
    gpsStatus.className = 'form-hint text-warning';

    navigator.geolocation.getCurrentPosition(
      function(position) {
        const lat = position.coords.latitude;
        const lng = position.coords.longitude;
        const acc = position.coords.accuracy;

        latInput.value = lat.toFixed(6);
        lngInput.value = lng.toFixed(6);
        accInput.value = acc.toFixed(1);

        latDisplay.textContent = lat.toFixed(6);
        lngDisplay.textContent = lng.toFixed(6);
        accDisplay.textContent = acc.toFixed(1) + ' m';

        if (mapLink) {
          mapLink.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}`;
          mapLink.style.display = 'inline-block';
        }

        gpsBadge.style.display = 'block';
        gpsStatus.textContent = "GPS position captured successfully!";
        gpsStatus.className = 'form-hint text-success';
        gpsBtn.disabled = false;

        // Try gentle reverse geocoding via OpenStreetMap Nominatim if network permits
        fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`, {
          headers: { 'Accept': 'application/json' }
        })
        .then(res => res.json())
        .then(data => {
          if (data && data.display_name && addressTextarea && !addressTextarea.value.trim()) {
            addressTextarea.value = data.display_name;
          }
        })
        .catch(() => {
          // Fallback silently if offline or Nominatim blocks
        });
      },
      function(error) {
        gpsBtn.disabled = false;
        let errMsg = "Could not obtain GPS location.";
        switch(error.code) {
          case error.PERMISSION_DENIED:
            errMsg = "Location permission was denied. Please enter the pickup address manually below.";
            break;
          case error.POSITION_UNAVAILABLE:
            errMsg = "Location information is currently unavailable. Please enter the pickup address manually.";
            break;
          case error.TIMEOUT:
            errMsg = "The request to get user location timed out. Please try again or type the address.";
            break;
        }
        gpsStatus.textContent = errMsg;
        gpsStatus.className = 'form-hint text-danger';
        gpsStatus.style.display = 'block';
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0
      }
    );
  });
}
