// ── A-Eye Onboarding Wizard JS (self-contained, no app.js dependency) ──

// ── Tagline Quotes (duplicated from app.js — onboard.js is self-contained) ──
var _onboardQuotes = [
    "In space, no one can hear your hard drives click.",
    "I'll be back... after this parity check.",
    "May the source be with you.",
    "To infinity and beyond your storage limits.",
    "I'm sorry Dave, I can't describe that photo.",
    "Live long and self-host.",
    "These aren't the photos you're looking for.",
    "Game over, man! Game over! ...just kidding, the array rebuilt.",
    "The truth is out there. Probably in the metadata.",
    "We're gonna need a bigger model.",
    "I see dead pixels.",
    "Phone home. Then check your server remotely.",
    "Open the pod bay doors, HAL. And the Docker socket.",
    "They mostly scan at night. Mostly.",
    "It's full of stars... and unprocessed photos.",
    "Resistance is futile. Your photos will be catalogued.",
    "Do. Or do not. There is no try. Unless Ollama is down.",
    "I find your lack of metadata disturbing.",
    "My precious... metadata. We wants it, we needs it.",
    "Teaching machines to see, one photo at a time.",
    "Somewhere, a vision model is squinting at your photos.",
    "No photos were harmed in the making of this filename.",
    "Giving your photos names they deserve.",
    "Currently arguing with a vision model about what a dog looks like.",
    "Renaming IMG_20210421_122426.jpg since 2026.",
    "Your photos called. They want proper names."
];

function _onboardRandomQuote() {
    return _onboardQuotes[Math.floor(Math.random() * _onboardQuotes.length)];
}

var _onboardState = {
    connected: false,
    visionModelSelected: false,
    hardwareMode: null,      // 'gpu' | 'cpu'
    purposeMode: null,       // 'catalogue' | 'metadata' | 'full'
    modesValid: true,        // at least one checkbox; always true for catalogue
    renameMode: 'review',
    watchMode: false,
    securityMode: 'skip',    // 'skip' | 'password'
    passwordValid: true,     // true when skip, or when passwords match
    currentStep: 1,
};

// Cached model lists from /api/models (populated on connection test)
var _cachedVisionModels = [];
var _cachedTextModels = [];

// ── Step Sequence (adapts based on purpose) ──────────────────

function _getStepSequence() {
    if (_onboardState.purposeMode === 'catalogue') {
        return [1, 2, 4, 5, 6];  // skip Actions
    }
    return [1, 2, 3, 4, 5, 6];   // metadata or full
}

function _getStepLabels() {
    if (_onboardState.purposeMode === 'catalogue') {
        return ['Connect', 'Purpose', 'Automation', 'Security', 'Ready'];
    }
    return ['Connect', 'Purpose', 'Actions', 'Automation', 'Security', 'Ready'];
}

// ── Progress Indicator ───────────────────────────────────────

function _renderProgress() {
    var seq = _getStepSequence();
    var labels = _getStepLabels();
    var current = _onboardState.currentStep;
    var currentIdx = seq.indexOf(current);
    var container = document.getElementById('onboard-progress');
    if (!container) return;

    var html = '';
    for (var i = 0; i < seq.length; i++) {
        var cls = 'progress-step';
        if (i < currentIdx) cls += ' done';
        else if (i === currentIdx) cls += ' active';

        html += '<div class="' + cls + '">';
        html += '<span class="step-number">' + (i + 1) + '</span>';
        html += '<span class="step-label">' + labels[i] + '</span>';
        html += '</div>';

        if (i < seq.length - 1) {
            html += '<div class="progress-line' + (i < currentIdx ? ' done' : '') + '"></div>';
        }
    }
    container.innerHTML = html;
}

// ── Step Navigation ──────────────────────────────────────────

function onboardNext() {
    var seq = _getStepSequence();
    var idx = seq.indexOf(_onboardState.currentStep);
    if (idx < seq.length - 1) {
        onboardGoToStep(seq[idx + 1]);
    }
}

function onboardBack() {
    var seq = _getStepSequence();
    var idx = seq.indexOf(_onboardState.currentStep);
    if (idx > 0) {
        onboardGoToStep(seq[idx - 1]);
    }
}

function onboardGoToStep(step) {
    // Validation gates
    if (step > 1 && (!_onboardState.connected || !_onboardState.visionModelSelected)) return;
    if (step > 2 && !_onboardState.purposeMode) return;
    if (step === 3 && _onboardState.purposeMode === 'catalogue') return;

    // Configure Step 3 content based on purpose mode
    if (step === 3) _configureStep3();

    // Populate summary on final step
    if (step === 6) _populateSummary();

    // Hide all steps, show target
    for (var i = 1; i <= 6; i++) {
        var el = document.getElementById('onboard-step-' + i);
        if (el) el.style.display = (i === step) ? '' : 'none';
    }

    _onboardState.currentStep = step;
    _renderProgress();
}

// ── Step 1: Connection ───────────────────────────────────────

function onboardTestConnection() {
    var host = document.getElementById('onboard-host').value.trim();
    var resultDiv = document.getElementById('onboard-connection-result');
    var testBtn = document.getElementById('onboard-test-btn');

    if (!host) {
        resultDiv.innerHTML = '<span class="badge badge-error">Please enter a host URL</span>';
        return;
    }

    // Reset panels from any previous connection attempt
    document.getElementById('onboard-hardware-group').style.display = 'none';
    document.getElementById('onboard-recommendation').style.display = 'none';
    document.getElementById('onboard-model-group').style.display = 'none';
    _onboardState.hardwareMode = null;
    _onboardState.visionModelSelected = false;

    resultDiv.innerHTML = '<span class="badge badge-processing">Connecting...</span>';
    testBtn.disabled = true;

    // Save host so backend uses it for health check
    fetch('/api/onboard/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { ollama_host: host } })
    })
    .then(function(r) { return r.json(); })
    .then(function() {
        return fetch('/api/health');
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var connected = data.ollama && data.ollama.connected;
        if (!connected) {
            resultDiv.innerHTML = '<span class="badge badge-error">Failed</span> <small>Could not reach Ollama at ' + _escapeHtml(host) + '</small>';
            _onboardState.connected = false;
            _updateStep1Next();
            testBtn.disabled = false;
            return;
        }

        resultDiv.innerHTML = '<span class="badge badge-processing">Loading models...</span>';

        fetch('/api/models')
        .then(function(r) { return r.json(); })
        .then(function(modelData) {
            var visionModels = modelData.vision || [];
            var textModels = modelData.text || [];
            var total = (modelData.all || []).length;

            resultDiv.innerHTML = '<span class="badge badge-success">Connected</span> <small>' +
                total + ' model(s) found (' + visionModels.length + ' vision)</small>';

            _onboardState.connected = true;

            // Cache models for later use
            _cachedVisionModels = visionModels;
            _cachedTextModels = textModels;

            // Show GPU/CPU hardware selection
            document.getElementById('onboard-hardware-group').style.display = '';

            // If user clicked Back and had a previous hardware selection, re-apply it
            if (_onboardState.hardwareMode) {
                onboardSelectHardware(_onboardState.hardwareMode);
            }

            _updateStep1Next();
            testBtn.disabled = false;
        })
        .catch(function() {
            resultDiv.innerHTML = '<span class="badge badge-warning">Connected</span> <small>Could not load model list</small>';
            _onboardState.connected = true;
            testBtn.disabled = false;
        });
    })
    .catch(function() {
        resultDiv.innerHTML = '<span class="badge badge-error">Failed</span> <small>Connection error</small>';
        _onboardState.connected = false;
        _updateStep1Next();
        testBtn.disabled = false;
    });
}

function _updateStep1Next() {
    var btn = document.getElementById('onboard-next-1');
    if (btn) btn.disabled = !(_onboardState.connected && _onboardState.visionModelSelected);
}

// ── Step 1b: Hardware Selection + Model Recommendation ───────

function onboardSelectHardware(mode) {
    _onboardState.hardwareMode = mode;
    document.getElementById('hw-card-gpu').className =
        'mode-card mode-card-compact' + (mode === 'gpu' ? ' selected' : '');
    document.getElementById('hw-card-cpu').className =
        'mode-card mode-card-compact' + (mode === 'cpu' ? ' selected' : '');

    _buildRecommendation(mode);
    _populateModelDropdowns();
    document.getElementById('onboard-recommendation').style.display = '';
    document.getElementById('onboard-model-group').style.display = '';
    _updateStep1Next();
}

function _buildRecommendation(mode) {
    var recContent = document.getElementById('onboard-rec-content');
    var pullArea = document.getElementById('onboard-pull-area');
    pullArea.style.display = 'none';

    var recModel, recNote;
    var html = '';

    if (mode === 'gpu') {
        recModel = 'minicpm-v';
        recNote = 'Good balance of speed and quality. Requires approximately 6\u20137GB VRAM.';
    } else {
        recModel = 'llava';
        recNote = 'Lightweight and works reasonably well without GPU acceleration.';
        html += '<div class="onboard-warning" style="margin-top:0;margin-bottom:0.75rem">' +
            'Running vision models on CPU is significantly slower than GPU. ' +
            'Processing each photo will take significantly longer than with a GPU. ' +
            'This is fine for small batches but not recommended for large photo libraries.' +
            '</div>';
    }

    var match = _findModelMatch(recModel, _cachedVisionModels);

    if (match) {
        html += '<div class="onboard-info" style="margin-top:0">' +
            '<strong>' + _escapeHtml(match) + '</strong> is already installed and recommended. ' +
            recNote + '</div>';
        recContent.innerHTML = html;
        // Auto-select in dropdown after it's populated
        setTimeout(function() { _preselectVisionModel(match); }, 0);
    } else {
        html += '<div class="onboard-info" style="margin-top:0">' +
            'We recommend <strong>' + _escapeHtml(recModel) + '</strong>. ' + recNote +
            '<br><br>' +
            '<button class="btn btn-sm btn-primary" id="onboard-pull-btn" ' +
            'onclick="onboardPullModel(\'' + recModel + '\')">Download ' +
            _escapeHtml(recModel) + '</button>' +
            '</div>';
        recContent.innerHTML = html;
    }
}

function _findModelMatch(baseName, modelList) {
    for (var i = 0; i < modelList.length; i++) {
        var name = modelList[i];
        var base = name.split(':')[0];
        if (base === baseName) return name;
    }
    return null;
}

function _preselectVisionModel(modelName) {
    var vSelect = document.getElementById('onboard-vision-model');
    for (var i = 0; i < vSelect.options.length; i++) {
        if (vSelect.options[i].value === modelName) {
            vSelect.selectedIndex = i;
            _onboardState.visionModelSelected = true;
            _updateStep1Next();
            return;
        }
    }
}

function _populateModelDropdowns() {
    var vSelect = document.getElementById('onboard-vision-model');
    vSelect.innerHTML = '';
    if (_cachedVisionModels.length === 0) {
        vSelect.innerHTML = '<option value="" disabled selected>No vision models found</option>';
    } else {
        var ph = document.createElement('option');
        ph.value = ''; ph.disabled = true; ph.selected = true;
        ph.textContent = 'Select a vision model...';
        vSelect.appendChild(ph);
        _cachedVisionModels.forEach(function(name) {
            var opt = document.createElement('option');
            opt.value = name; opt.textContent = name;
            vSelect.appendChild(opt);
        });
    }
    vSelect.onchange = function() {
        _onboardState.visionModelSelected = !!vSelect.value;
        _updateStep1Next();
    };

    var lSelect = document.getElementById('onboard-llm-model');
    lSelect.innerHTML = '<option value="">None \u2014 keyword search only</option>';
    _cachedTextModels.forEach(function(name) {
        var opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        lSelect.appendChild(opt);
    });
}

// ── Model Pull (streaming NDJSON) ────────────────────────────

function onboardPullModel(modelName) {
    var btn = document.getElementById('onboard-pull-btn');
    if (btn) btn.disabled = true;
    var pullArea = document.getElementById('onboard-pull-area');
    pullArea.style.display = '';
    var bar = document.getElementById('onboard-pull-bar');
    var status = document.getElementById('onboard-pull-status');
    bar.style.width = '0%';
    bar.className = 'pull-progress-bar';
    status.textContent = 'Preparing download...';

    fetch('/api/models/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: modelName })
    })
    .then(function(response) {
        if (!response.ok) throw new Error('Pull request failed');
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function read() {
            return reader.read().then(function(result) {
                if (result.done) {
                    _onPullComplete(modelName);
                    return;
                }
                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop();

                lines.forEach(function(line) {
                    line = line.trim();
                    if (!line) return;
                    try {
                        var obj = JSON.parse(line);
                        if (obj.error) {
                            bar.className = 'pull-progress-bar pull-error';
                            status.textContent = 'Error: ' + obj.error;
                            if (btn) btn.disabled = false;
                            return;
                        }
                        if (obj.percentage !== undefined) {
                            bar.style.width = obj.percentage + '%';
                        }
                        if (obj.total && obj.completed) {
                            var dlMB = (obj.completed / 1048576).toFixed(0);
                            var totalMB = (obj.total / 1048576).toFixed(0);
                            status.textContent = (obj.status || 'downloading') +
                                '... ' + dlMB + ' / ' + totalMB + ' MB (' +
                                (obj.percentage || 0) + '%)';
                        } else if (obj.status) {
                            status.textContent = obj.status + '...';
                        }
                        if (obj.status === 'success') {
                            _onPullComplete(modelName);
                        }
                    } catch (e) {
                        // skip malformed lines
                    }
                });
                return read();
            });
        }
        return read();
    })
    .catch(function(err) {
        bar.className = 'pull-progress-bar pull-error';
        status.textContent = 'Download failed: ' + (err.message || 'unknown error');
        if (btn) btn.disabled = false;
    });
}

function _onPullComplete(modelName) {
    var bar = document.getElementById('onboard-pull-bar');
    var status = document.getElementById('onboard-pull-status');
    bar.style.width = '100%';
    status.textContent = 'Download complete! Refreshing model list...';

    fetch('/api/models')
    .then(function(r) { return r.json(); })
    .then(function(modelData) {
        _cachedVisionModels = modelData.vision || [];
        _cachedTextModels = modelData.text || [];
        _populateModelDropdowns();
        _preselectVisionModel(modelName);
        _buildRecommendation(_onboardState.hardwareMode);
        _updateStep1Next();
    })
    .catch(function() {
        status.textContent = 'Download complete! Please select the model from the dropdown below.';
    });
}

// ── Step 2: Purpose ──────────────────────────────────────────

function onboardSelectPurpose(mode) {
    // Block non-catalogue choices when photos dir is read-only
    if (typeof _photosReadOnly !== 'undefined' && _photosReadOnly && mode !== 'catalogue') return;

    _onboardState.purposeMode = mode;

    var catCard = document.getElementById('mode-card-catalogue');
    var metaCard = document.getElementById('mode-card-metadata');
    var fullCard = document.getElementById('mode-card-full');
    catCard.className = 'mode-card' + (mode === 'catalogue' ? ' selected' : '');
    metaCard.className = 'mode-card' + (mode === 'metadata' ? ' selected' : '');
    fullCard.className = 'mode-card' + (mode === 'full' ? ' selected' : '');

    var nextBtn = document.getElementById('onboard-next-2');
    if (nextBtn) nextBtn.disabled = false;

    // Re-render progress since sequence may have changed
    _renderProgress();
}

// ── Step 3: Actions ──────────────────────────────────────────

function _configureStep3() {
    var isMetadata = _onboardState.purposeMode === 'metadata';
    var renameGroup = document.getElementById('onboard-rename-group');
    var renameOpts = document.getElementById('onboard-rename-options');
    var renameCheckbox = document.getElementById('onboard-process-rename');
    var descCheckbox = document.getElementById('onboard-process-description');
    var tagsCheckbox = document.getElementById('onboard-process-tags');

    if (isMetadata) {
        // Metadata mode: hide rename, show only XMP checkboxes, default both checked
        if (renameGroup) renameGroup.style.display = 'none';
        if (renameOpts) renameOpts.style.display = 'none';
        renameCheckbox.checked = false;
        descCheckbox.checked = true;
        tagsCheckbox.checked = true;
    } else {
        // Full mode: show everything, rename checked by default
        if (renameGroup) renameGroup.style.display = '';
        renameCheckbox.checked = true;
        // Show/hide rename options based on checkbox
        if (renameOpts) renameOpts.style.display = renameCheckbox.checked ? '' : 'none';
    }

    // Update validation state
    onboardCheckModes();
}

function onboardCheckModes() {
    var isMetadata = _onboardState.purposeMode === 'metadata';
    var rename = document.getElementById('onboard-process-rename').checked;
    var desc = document.getElementById('onboard-process-description').checked;
    var tags = document.getElementById('onboard-process-tags').checked;

    // For metadata mode, only desc/tags count
    var anyChecked = isMetadata ? (desc || tags) : (rename || desc || tags);

    _onboardState.modesValid = anyChecked;

    var error = document.getElementById('onboard-mode-error');
    if (error) error.style.display = anyChecked ? 'none' : '';

    var nextBtn = document.getElementById('onboard-next-3');
    if (nextBtn) nextBtn.disabled = !anyChecked;

    // Show Immich tip when metadata modes selected
    var tip = document.getElementById('onboard-immich-tip');
    if (tip) tip.style.display = (desc || tags) ? '' : 'none';

    // Show/hide rename options (full mode only)
    if (!isMetadata) {
        var renameOpts = document.getElementById('onboard-rename-options');
        if (renameOpts) renameOpts.style.display = rename ? '' : 'none';
    }
}

function onboardRenameMode() {
    var selected = document.querySelector('input[name="onboard_rename_mode"]:checked');
    _onboardState.renameMode = selected ? selected.value : 'review';

    var confGroup = document.getElementById('onboard-confidence-group');
    if (confGroup) confGroup.style.display = (_onboardState.renameMode === 'auto-low-confidence') ? '' : 'none';
}

// ── Step 4: Watch Mode ───────────────────────────────────────

function onboardSelectWatch(watch) {
    _onboardState.watchMode = watch;

    var manualCard = document.getElementById('mode-card-manual');
    var watchCard = document.getElementById('mode-card-watch');
    manualCard.className = 'mode-card mode-card-compact' + (!watch ? ' selected' : '');
    watchCard.className = 'mode-card mode-card-compact' + (watch ? ' selected' : '');
}

// ── Step 5: Security ────────────────────────────────────────

function onboardSelectSecurity(mode) {
    _onboardState.securityMode = mode;

    var nopassCard = document.getElementById('mode-card-nopass');
    var setpassCard = document.getElementById('mode-card-setpass');
    nopassCard.className = 'mode-card mode-card-compact' + (mode === 'skip' ? ' selected' : '');
    setpassCard.className = 'mode-card mode-card-compact' + (mode === 'password' ? ' selected' : '');

    var fields = document.getElementById('onboard-password-fields');
    if (fields) fields.style.display = (mode === 'password') ? '' : 'none';

    // Clear password fields when switching to skip
    if (mode === 'skip') {
        var pass = document.getElementById('onboard-password');
        var confirm = document.getElementById('onboard-password-confirm');
        if (pass) pass.value = '';
        if (confirm) confirm.value = '';
        var strengthDiv = document.getElementById('onboard-strength');
        if (strengthDiv) strengthDiv.style.display = 'none';
        var matchError = document.getElementById('onboard-match-error');
        if (matchError) matchError.style.display = 'none';
    }

    _updateStep5Next();
}

function _updateStep5Next() {
    var btn = document.getElementById('onboard-next-5');
    if (!btn) return;

    if (_onboardState.securityMode === 'skip') {
        _onboardState.passwordValid = true;
        btn.disabled = false;
    } else {
        var pass = document.getElementById('onboard-password');
        var confirm = document.getElementById('onboard-password-confirm');
        var valid = pass && pass.value && confirm && confirm.value && pass.value === confirm.value;
        _onboardState.passwordValid = !!valid;
        btn.disabled = !valid;
    }
}

// ── Step 6: Summary ─────────────────────────────────────────

function _populateSummary() {
    // Host
    document.getElementById('summary-host').textContent =
        document.getElementById('onboard-host').value;

    // Vision model
    var vSelect = document.getElementById('onboard-vision-model');
    document.getElementById('summary-model').textContent =
        vSelect.options[vSelect.selectedIndex]
            ? vSelect.options[vSelect.selectedIndex].text : '-';

    // LLM model
    var lSelect = document.getElementById('onboard-llm-model');
    document.getElementById('summary-llm').textContent = lSelect.value || 'None';

    // Mode
    var modeLabels = {
        catalogue: 'Catalogue Only',
        metadata: 'Enrich Metadata',
        full: 'Full Processing'
    };
    document.getElementById('summary-mode').textContent =
        modeLabels[_onboardState.purposeMode] || '-';

    // Actions
    var actionsRow = document.getElementById('summary-actions-row');
    if (_onboardState.purposeMode === 'catalogue') {
        document.getElementById('summary-actions').textContent = 'Catalogue only \u2014 no file changes';
        actionsRow.onclick = function() { onboardGoToStep(2); };
    } else {
        var actions = [];
        if (document.getElementById('onboard-process-rename').checked) {
            var renameLabel = { review: 'review', auto: 'auto', 'auto-low-confidence': 'smart auto' };
            actions.push('Rename (' + (renameLabel[_onboardState.renameMode] || 'review') + ')');
        }
        if (document.getElementById('onboard-process-description').checked) actions.push('XMP Description');
        if (document.getElementById('onboard-process-tags').checked) actions.push('XMP Tags');
        document.getElementById('summary-actions').textContent = actions.join(', ') || '-';
        actionsRow.onclick = function() { onboardGoToStep(3); };
    }

    // Watch mode
    document.getElementById('summary-watch').textContent =
        _onboardState.watchMode ? 'Auto-watch' : 'Manual scan';

    // Auth
    var authEl = document.getElementById('summary-auth');
    if (_onboardState.securityMode === 'password') {
        var user = document.getElementById('onboard-username').value.trim() || 'admin';
        authEl.textContent = 'Enabled (user: ' + user + ')';
    } else {
        authEl.textContent = 'Disabled';
    }
}

// ── Password ────────────────────────────────────────────────

function onboardCheckPassword() {
    var password = document.getElementById('onboard-password').value;
    var confirm = document.getElementById('onboard-password-confirm').value;
    var strengthDiv = document.getElementById('onboard-strength');
    var fillDiv = document.getElementById('onboard-strength-fill');
    var labelSpan = document.getElementById('onboard-strength-label');
    var matchError = document.getElementById('onboard-match-error');

    if (!password) {
        if (strengthDiv) strengthDiv.style.display = 'none';
        if (matchError) matchError.style.display = 'none';
        _updateStep5Next();
        return;
    }

    // Show strength meter
    if (strengthDiv) strengthDiv.style.display = '';
    var strength = _passwordStrength(password);
    if (fillDiv) {
        fillDiv.className = 'strength-fill ' + strength.level;
        fillDiv.style.width = strength.percent + '%';
    }
    if (labelSpan) {
        labelSpan.textContent = strength.label;
        labelSpan.className = 'strength-label strength-' + strength.level;
    }

    // Check match
    if (matchError) {
        matchError.style.display = (confirm && password !== confirm) ? '' : 'none';
    }

    _updateStep5Next();
}

// ── Finish ───────────────────────────────────────────────────

function onboardFinish() {
    var finishBtn = document.getElementById('onboard-finish-btn');
    if (finishBtn) finishBtn.disabled = true;

    var purpose = _onboardState.purposeMode;
    var isCatalogue = purpose === 'catalogue';
    var isMetadata = purpose === 'metadata';

    var settings = {
        ollama_host: document.getElementById('onboard-host').value.trim(),
        vision_model: document.getElementById('onboard-vision-model').value,
        llm_model: document.getElementById('onboard-llm-model').value,
        catalogue_mode: isCatalogue ? 'true' : 'false',
        watch_mode: _onboardState.watchMode ? 'true' : 'false',
        setup_complete: 'true',
    };

    if (isCatalogue) {
        settings.process_rename = 'false';
        settings.process_write_description = 'false';
        settings.process_write_tags = 'false';
    } else if (isMetadata) {
        settings.process_rename = 'false';
        settings.process_write_description = document.getElementById('onboard-process-description').checked ? 'true' : 'false';
        settings.process_write_tags = document.getElementById('onboard-process-tags').checked ? 'true' : 'false';
    } else {
        // Full processing
        settings.process_rename = document.getElementById('onboard-process-rename').checked ? 'true' : 'false';
        settings.process_write_description = document.getElementById('onboard-process-description').checked ? 'true' : 'false';
        settings.process_write_tags = document.getElementById('onboard-process-tags').checked ? 'true' : 'false';
        settings.rename_mode = _onboardState.renameMode;
        if (_onboardState.renameMode === 'auto-low-confidence') {
            settings.confidence_threshold = document.getElementById('onboard-confidence').value;
        }
    }

    // Auth
    if (_onboardState.securityMode === 'password') {
        var pass = document.getElementById('onboard-password');
        var confirm = document.getElementById('onboard-password-confirm');
        if (pass && pass.value && confirm && pass.value === confirm.value) {
            settings.basic_auth_user = document.getElementById('onboard-username').value.trim() || 'admin';
            settings.basic_auth_pass = pass.value;
        }
    } else {
        settings.basic_auth_user = '';
        settings.basic_auth_pass = '';
    }

    fetch('/api/onboard/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: settings })
    })
    .then(function(r) { return r.json(); })
    .then(function() {
        window.location.href = '/';
    })
    .catch(function() {
        alert('Failed to save settings. Please try again.');
        if (finishBtn) finishBtn.disabled = false;
    });
}

// ── Password Strength ────────────────────────────────────────

function _passwordStrength(password) {
    var score = 0;
    var len = password.length;
    if (len >= 4) score++;
    if (len >= 8) score++;
    if (len >= 12) score++;
    if (len >= 16) score++;
    if (/[a-z]/.test(password)) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^a-zA-Z0-9]/.test(password)) score++;

    if (score <= 3) return { score: score, level: 'weak', label: 'Weak', percent: 33 };
    if (score <= 5) return { score: score, level: 'medium', label: 'Medium', percent: 66 };
    return { score: score, level: 'strong', label: 'Strong', percent: 100 };
}

// ── Utilities ────────────────────────────────────────────────

function _escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Init ─────────────────────────────────────────────────────

_renderProgress();

// Lock to catalogue-only when photos dir is read-only
if (typeof _photosReadOnly !== 'undefined' && _photosReadOnly) {
    onboardSelectPurpose('catalogue');
    document.getElementById('mode-card-metadata').classList.add('readonly-locked');
    document.getElementById('mode-card-full').classList.add('readonly-locked');
    var notice = document.getElementById('readonly-notice');
    if (notice) notice.style.display = '';
}
