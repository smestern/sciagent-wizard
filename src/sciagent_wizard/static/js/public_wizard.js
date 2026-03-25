/**
 * public_wizard.js — Client-side logic for the public guided wizard.
 *
 * No freeform chat — users interact only via the expanded form steps
 * and structured question cards presented by the AI.
 */

// ── State ──────────────────────────────────────────────────────────────

const wizardState = {
    step: 1,
    domainDescription: '',
    dataTypes: [],        // from selectable cards
    analysisGoals: [],    // from selectable cards
    researchGoals: [],    // from tag input
    experienceLevel: '',  // beginner | intermediate | advanced
    fileTypes: [],        // from tag input
    knownPackages: [],    // from tag input
    uploadedFiles: [],
    uploadedFilePaths: [],
    sessionId: null,
    model: 'claude-opus-4.5',  // LLM model for billing
};

// ── Quick-start templates ──────────────────────────────────────────────

const quickstarts = {
    electrophysiology: {
        description: 'I study patch-clamp electrophysiology. I record voltage and current traces from neurons to analyze ion channel properties, action potential firing patterns, and synaptic responses.',
        dataTypes: ['Time Series', 'Tabular / CSV'],
        analysisGoals: ['Curve Fitting', 'Peak Detection', 'Visualization', 'Statistical Testing'],
        researchGoals: ['Extract action potential features', 'Fit exponential decay curves', 'Analyze synaptic events'],
        fileTypes: ['.abf', '.csv', '.nwb'],
        packages: ['pyabf', 'neo', 'elephant'],
        experience: '',
    },
    genomics: {
        description: 'I work in genomics and transcriptomics. I process sequencing data, perform quality control, and do differential expression analysis.',
        dataTypes: ['Genomic Sequences', 'Tabular / CSV'],
        analysisGoals: ['Data Cleaning', 'Statistical Testing', 'Visualization', 'Clustering'],
        researchGoals: ['Quality control on FASTQ files', 'Differential expression analysis', 'Gene set enrichment'],
        fileTypes: ['.fastq', '.bam', '.vcf', '.csv'],
        packages: ['biopython', 'pysam', 'scanpy'],
        experience: '',
    },
    imaging: {
        description: 'I do calcium imaging experiments on neurons. I acquire TIFF stacks, extract fluorescence intensity traces from ROIs, and detect calcium transient events.',
        dataTypes: ['Images / Microscopy', 'Time Series'],
        analysisGoals: ['Image Analysis', 'Peak Detection', 'Visualization', 'Clustering'],
        researchGoals: ['Extract fluorescence traces from ROIs', 'Detect calcium events', 'Correlate neural activity'],
        fileTypes: ['.tif', '.tiff', '.csv', '.npy'],
        packages: ['suite2p', 'caiman', 'scikit-image'],
        experience: '',
    },
    chemistry: {
        description: 'I am a chemist working with spectroscopy data (UV-Vis, NMR, IR). I need to load spectra, perform baseline correction, and fit peaks.',
        dataTypes: ['Spectral Data', 'Tabular / CSV'],
        analysisGoals: ['Curve Fitting', 'Peak Detection', 'Visualization', 'Data Cleaning'],
        researchGoals: ['Baseline correction', 'Peak fitting', 'Build calibration curves'],
        fileTypes: ['.csv', '.txt', '.json', '.xlsx'],
        packages: ['lmfit', 'nmrglue', 'rampy'],
        experience: '',
    },
    other: {
        description: '',
        dataTypes: [],
        analysisGoals: [],
        researchGoals: [],
        fileTypes: [],
        packages: [],
        experience: '',
    },
};

// ── Quick-start ────────────────────────────────────────────────────────

function useQuickstart(key) {
    const qs = quickstarts[key];
    if (!qs) return;

    document.getElementById('domain-desc').value = qs.description;

    // Set data types
    wizardState.dataTypes = [...qs.dataTypes];
    document.querySelectorAll('#data-type-cards .selectable-card').forEach(card => {
        const val = card.dataset.value;
        if (qs.dataTypes.includes(val)) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    });

    // Set analysis goals
    wizardState.analysisGoals = [...qs.analysisGoals];
    document.querySelectorAll('#analysis-goal-cards .selectable-card').forEach(card => {
        const val = card.dataset.value;
        if (qs.analysisGoals.includes(val)) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    });

    // Set research goals
    wizardState.researchGoals = [...qs.researchGoals];
    renderTags('goals-container', 'goals-input', wizardState.researchGoals);

    // Set file types
    wizardState.fileTypes = [...qs.fileTypes];
    renderTags('filetypes-container', 'filetypes-input', wizardState.fileTypes);

    // Set packages
    wizardState.knownPackages = [...qs.packages];
    renderTags('packages-container', 'packages-input', wizardState.knownPackages);

    // Focus the textarea for custom entry when description is empty ("Other")
    const descEl = document.getElementById('domain-desc');
    if (!qs.description) descEl.focus();
}

// ── Selectable cards (multi-select) ────────────────────────────────────

function toggleCard(el, stateKey) {
    const val = el.dataset.value;
    const arr = wizardState[stateKey];
    const idx = arr.indexOf(val);
    if (idx >= 0) {
        arr.splice(idx, 1);
        el.classList.remove('selected');
    } else {
        arr.push(val);
        el.classList.add('selected');
    }
}

// ── Radio cards (single-select) ────────────────────────────────────────

function selectRadio(el, stateKey) {
    const group = el.parentElement;
    group.querySelectorAll('.radio-card').forEach(c => c.classList.remove('selected'));
    el.classList.add('selected');
    if (stateKey === 'experience') {
        wizardState.experienceLevel = el.dataset.value;
    }
}

// ── Step navigation ────────────────────────────────────────────────────

function goToStep(step) {
    // Save current domain text
    const descEl = document.getElementById('domain-desc');
    if (descEl) wizardState.domainDescription = descEl.value;

    // Update step indicators
    document.querySelectorAll('.wizard-step').forEach(el => {
        const s = parseInt(el.dataset.step);
        el.classList.remove('active', 'completed');
        if (s < step) el.classList.add('completed');
        if (s === step) el.classList.add('active');
    });

    // Show/hide panels
    document.querySelectorAll('.wizard-panel').forEach(el => {
        el.classList.remove('active');
    });
    document.getElementById(`step-${step}`).classList.add('active');

    wizardState.step = step;
}

// ── Tag input helpers ──────────────────────────────────────────────────

function setupTagInput(containerId, inputId, stateArray) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && input.value.trim()) {
            e.preventDefault();
            const val = input.value.trim();
            if (!stateArray.includes(val)) {
                stateArray.push(val);
                renderTags(containerId, inputId, stateArray);
            }
            input.value = '';
        }
    });
    document.getElementById(containerId).addEventListener('click', () => {
        input.focus();
    });
}

function renderTags(containerId, inputId, arr) {
    const container = document.getElementById(containerId);
    const input = document.getElementById(inputId);
    container.querySelectorAll('.tag').forEach(t => t.remove());
    arr.forEach((val, idx) => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.innerHTML = `${escHtml(val)} <button onclick="removeTag('${containerId}', '${inputId}', ${idx})">&times;</button>`;
        container.insertBefore(tag, input);
    });
}

function removeTag(containerId, inputId, idx) {
    if (containerId === 'goals-container') wizardState.researchGoals.splice(idx, 1);
    else if (containerId === 'filetypes-container') wizardState.fileTypes.splice(idx, 1);
    else if (containerId === 'packages-container') wizardState.knownPackages.splice(idx, 1);

    const arr = containerId === 'goals-container' ? wizardState.researchGoals :
                containerId === 'filetypes-container' ? wizardState.fileTypes :
                wizardState.knownPackages;
    renderTags(containerId, inputId, arr);
}

// ── File upload ────────────────────────────────────────────────────────

function setupFileUpload() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', () => {
        handleFiles(fileInput.files);
        fileInput.value = '';
    });
}

function handleFiles(fileList) {
    for (const file of fileList) {
        if (!wizardState.uploadedFiles.find(f => f.name === file.name)) {
            wizardState.uploadedFiles.push(file);
        }
    }
    renderFileList();
}

function removeFile(idx) {
    wizardState.uploadedFiles.splice(idx, 1);
    renderFileList();
}

function renderFileList() {
    const list = document.getElementById('file-list');
    if (!list) return;
    list.innerHTML = wizardState.uploadedFiles.map((f, i) => `
        <div class="file-item">
            <span>📄 ${escHtml(f.name)} <span style="color: var(--text-secondary)">(${(f.size/1024).toFixed(1)} KB)</span></span>
            <button onclick="removeFile(${i})">&times;</button>
        </div>
    `).join('');
}

// ── Start guided wizard ────────────────────────────────────────────────

async function startGuidedWizard() {
    wizardState.domainDescription = document.getElementById('domain-desc').value;

    if (!wizardState.domainDescription.trim()) {
        alert('Please describe your research domain first (Step 1).');
        goToStep(1);
        return;
    }

    // Upload files if any
    if (wizardState.uploadedFiles.length > 0) {
        await uploadFiles();
    }

    try {
        // Check auth status before calling API — avoids redirect/CORS issues
        try {
            const authCheck = await fetch('/auth/status');
            if (authCheck.ok) {
                const authData = await authCheck.json();
                if (authData.authenticated === false) {
                    window.location.href = '/auth/login?return_to=/public/';
                    return;
                }
            }
        } catch (_) { /* auth endpoint not available — OAuth not configured */ }

        const resp = await fetch('/public/api/start', {
            method: 'POST',
            redirect: 'manual',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify({
                domain_description: wizardState.domainDescription,
                research_goals: wizardState.researchGoals,
                data_types: wizardState.dataTypes,
                analysis_goals: wizardState.analysisGoals,
                experience_level: wizardState.experienceLevel || 'beginner',
                file_types: wizardState.fileTypes,
                known_packages: wizardState.knownPackages,
            }),
        });

        // Handle auth redirect (opaque redirect or 401)
        if (resp.type === 'opaqueredirect' || resp.status === 0) {
            window.location.href = '/auth/login?return_to=/public/';
            return;
        }

        if (resp.status === 401) {
            try {
                const authData = await resp.json();
                if (authData.auth_required && authData.login_url) {
                    window.location.href = authData.login_url;
                    return;
                }
            } catch (_) {}
            window.location.href = '/auth/login?return_to=/public/';
            return;
        }

        if (resp.status === 429) {
            alert('Rate limit exceeded. Please try again in an hour.');
            return;
        }

        const data = await resp.json();
        if (data.error) {
            alert(data.error);
            return;
        }

        wizardState.sessionId = data.session_id;
        goToStep(6);
        initGuidedChat(data.kickoff_prompt);
    } catch (err) {
        console.error('Failed to start wizard:', err);
        alert('Failed to start the wizard. Check your connection.');
    }
}

async function uploadFiles() {
    for (const file of wizardState.uploadedFiles) {
        try {
            const form = new FormData();
            form.append('file', file);
            form.append('session_id', wizardState.sessionId || 'public-upload');
            const resp = await fetch('/upload', {method: 'POST', body: form});
            const data = await resp.json();
            if (data.path) {
                wizardState.uploadedFilePaths.push(data.path);
            }
        } catch (err) {
            console.error(`Upload failed for ${file.name}:`, err);
        }
    }
}

// ── Guided chat (no freeform input) ────────────────────────────────────

let ws = null;
let currentAssistantEl = null;
let assistantBuffer = '';

function initGuidedChat(kickoffPrompt) {
    appendMessage('system', '🧙 Connecting to the wizard…');

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const modelParam = encodeURIComponent(wizardState.model);
    ws = new WebSocket(`${protocol}//${location.host}/ws/public-chat?model=${modelParam}`);

    ws.onopen = () => {
        appendMessage('system', '🧙 Connected! Searching for domain tools…');
        setTimeout(() => {
            ws.send(JSON.stringify({text: kickoffPrompt}));
        }, 500);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    ws.onerror = () => appendMessage('system', '❌ Connection error');
    ws.onclose = () => appendMessage('system', '🔌 Session ended');
}

function handleWsMessage(msg) {
    console.log('[WS] Received message:', msg.type, msg);
    switch (msg.type) {
        case 'connected':
            break;
        case 'status':
            appendMessage('system', msg.text);
            break;
        case 'text_delta':
            if (!currentAssistantEl) {
                currentAssistantEl = appendMessage('assistant', '');
                assistantBuffer = '';
            }
            assistantBuffer += msg.text;
            currentAssistantEl.innerHTML = renderMarkdown(assistantBuffer);
            scrollChat();
            break;
        case 'thinking':
            break;
        case 'tool_start':
            console.log('[WS] Tool started:', msg.name);
            appendMessage('system', `⚙️ Running ${msg.name}…`);
            break;
        case 'tool_complete':
            console.log('[WS] Tool complete:', msg.name);
            appendMessage('system', `✅ ${msg.name} done`);
            break;
        case 'question_card':
            console.log('[WS] QUESTION CARD received:', msg);
            // Render a structured question card
            currentAssistantEl = null;
            assistantBuffer = '';
            renderQuestionCard(msg);
            break;
        case 'download_ready':
            console.log('[WS] DOWNLOAD READY received:', msg);
            // Render a download card for the generated project
            currentAssistantEl = null;
            assistantBuffer = '';
            renderDownloadCard(msg);
            break;
        case 'done':
            currentAssistantEl = null;
            assistantBuffer = '';
            break;
        case 'error':
            appendMessage('system', `❌ ${msg.text}`);
            break;
    }
}

// ── Download card rendering ────────────────────────────────────────────

function renderDownloadCard(msg) {
    const messages = document.getElementById('chat-messages');
    const cardDiv = document.createElement('div');
    cardDiv.className = 'question-card';
    cardDiv.style.borderColor = '#22c55e';

    const modeName = msg.output_mode === 'copilot_agent'
        ? 'VS Code / Claude Code Agent Config'
        : msg.output_mode === 'markdown'
        ? 'Markdown Agent Specification'
        : 'Agent Project';

    let html = `<h3>🎉 Your agent is ready!</h3>`;
    html += `<p style="margin: 0.5rem 0; color: var(--text-secondary);">
        <strong>${escHtml(msg.project_name)}</strong> — ${escHtml(modeName)}
    </p>`;

    // File list
    if (msg.files && msg.files.length > 0) {
        html += `<div style="margin: 0.75rem 0; font-size: 0.85rem;">`;
        html += `<strong>Files included:</strong><br>`;
        msg.files.forEach(f => {
            html += `<span style="margin-right: 0.5rem;">📄 ${escHtml(f)}</span>`;
        });
        html += `</div>`;
    }

    // Instructions
    if (msg.instructions) {
        html += `<div style="margin: 0.75rem 0; font-size: 0.85rem; background: var(--bg-primary); padding: 0.75rem; border-radius: 6px;">`;
        html += `<strong>How to use:</strong><br>`;
        for (const [key, val] of Object.entries(msg.instructions)) {
            html += `<div style="margin-top: 0.3rem;"><strong>${escHtml(key)}:</strong> ${escHtml(val)}</div>`;
        }
        html += `</div>`;
    }

    // Download button
    if (msg.download_url) {
        html += `<a href="${msg.download_url}" download
            style="display: inline-block; margin-top: 0.75rem; padding: 0.75rem 1.5rem;
            background: #22c55e; color: white; border-radius: 8px; text-decoration: none;
            font-weight: 600; font-size: 1rem; transition: background 0.2s;"
            onmouseover="this.style.background='#16a34a'"
            onmouseout="this.style.background='#22c55e'">
            ⬇️ Download ${escHtml(msg.project_name)}.zip
        </a>`;
    }

    cardDiv.innerHTML = html;
    messages.appendChild(cardDiv);
    scrollChat();
}

// ── Question card rendering ────────────────────────────────────────────

function renderQuestionCard(msg) {
    const messages = document.getElementById('chat-messages');
    const cardDiv = document.createElement('div');
    cardDiv.className = 'question-card';

    const isMultiple = msg.allow_multiple || false;
    const hasFreetext = msg.allow_freetext || false;
    const maxLen = msg.max_length || 100;
    const cardId = 'qcard-' + Date.now();

    // Split question into a short header and a longer body.
    // Look for the first sentence-ending boundary or double-newline.
    const qText = msg.question || '';
    let header = '';
    let body = '';
    const splitIdx = qText.search(/(?:\n\n|:\s*\n|:\s*📦|:\s*🔬)/);
    if (splitIdx > 0 && splitIdx < 200) {
        // Check if split point is at a colon (include it in header)
        const colonMatch = qText.slice(splitIdx).match(/^:\s*/);
        const offset = colonMatch ? colonMatch[0].length : 0;
        header = qText.slice(0, splitIdx + (colonMatch ? 1 : 0)).trim();
        body = qText.slice(splitIdx + offset).trim();
    } else {
        header = qText;
    }

    let html = `<div class="question-header">${renderMarkdown(header)}</div>`;
    if (body) {
        html += `<div class="question-body">${renderMarkdown(body)}</div>`;
    }

    if (msg.options && msg.options.length > 0) {
        html += `<div class="question-options" id="${cardId}-options">`;
        msg.options.forEach((opt, i) => {
            html += `<button class="question-option" data-value="${escHtml(opt)}"
                onclick="toggleQuestionOption(this, ${isMultiple})">${escHtml(opt)}</button>`;
        });
        html += `</div>`;
    }

    if (hasFreetext) {
        html += `<input type="text" class="question-freetext" id="${cardId}-freetext"
            maxlength="${maxLen}" placeholder="Type your answer…">`;
    }

    html += `<button class="question-submit" id="${cardId}-submit"
        onclick="submitQuestionResponse('${cardId}', ${isMultiple}, ${hasFreetext})">
        Submit →</button>`;

    cardDiv.innerHTML = html;
    messages.appendChild(cardDiv);
    scrollChat();
}

function toggleQuestionOption(el, isMultiple) {
    if (isMultiple) {
        el.classList.toggle('selected');
    } else {
        // Single select — deselect siblings
        el.parentElement.querySelectorAll('.question-option').forEach(o => o.classList.remove('selected'));
        el.classList.add('selected');
    }
}

function submitQuestionResponse(cardId, isMultiple, hasFreetext) {
    const optionsContainer = document.getElementById(`${cardId}-options`);
    const freetextInput = document.getElementById(`${cardId}-freetext`);
    const submitBtn = document.getElementById(`${cardId}-submit`);

    let answer = '';

    if (optionsContainer) {
        const selected = optionsContainer.querySelectorAll('.question-option.selected');
        const selectedValues = Array.from(selected).map(el => el.dataset.value);

        if (selectedValues.length > 0) {
            answer = isMultiple ? selectedValues.join(', ') : selectedValues[0];
        }
    }

    if (hasFreetext && freetextInput && freetextInput.value.trim()) {
        answer = freetextInput.value.trim();
    }

    if (!answer) {
        return; // nothing selected
    }

    // Disable the card
    submitBtn.disabled = true;
    if (optionsContainer) {
        optionsContainer.querySelectorAll('.question-option').forEach(o => {
            o.style.pointerEvents = 'none';
        });
    }
    if (freetextInput) freetextInput.disabled = true;

    // Show user response
    appendMessage('user', answer);

    // Send as question_response (not freeform chat)
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'question_response',
            answer: answer,
        }));
    }
}

// ── Message rendering ──────────────────────────────────────────────────

function appendMessage(role, content) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return null;
    const div = document.createElement('div');
    div.style.marginBottom = '1rem';

    if (role === 'user') {
        div.style.textAlign = 'right';
        div.innerHTML = `<span style="background: #a855f7; color: white; padding: 0.5rem 1rem;
            border-radius: 1rem; display: inline-block; max-width: 80%;">${escHtml(content)}</span>`;
    } else if (role === 'assistant') {
        div.innerHTML = `<div class="md-content" style="background: var(--bg-secondary); padding: 0.75rem 1rem;
            border-radius: 8px; max-width: 90%;">${renderMarkdown(content)}</div>`;
    } else {
        div.innerHTML = `<div style="color: var(--text-secondary); font-size: 0.85rem;
            text-align: center;">${content}</div>`;
    }

    messages.appendChild(div);
    scrollChat();
    return div.querySelector('div') || div;
}

function scrollChat() {
    const messages = document.getElementById('chat-messages');
    if (messages) messages.scrollTop = messages.scrollHeight;
}

// ── Utility ────────────────────────────────────────────────────────────

function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
        return marked.parse(text);
    }
    // Fallback: basic rendering if marked.js failed to load
    let s = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    s = s.replace(/```(\w*)\n([\s\S]*?)```/g,
        '<pre><code>$2</code></pre>');
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\n/g, '<br>');
    return s;
}

function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Config Loading ─────────────────────────────────────────────────────

async function loadConfig() {
    try {
        const resp = await fetch('/public/api/config', {
            credentials: 'same-origin',  // Ensure session cookie is sent
        });
        if (!resp.ok) {
            const text = await resp.text();
            console.error('Config fetch failed:', resp.status, text);
            throw new Error(`HTTP ${resp.status}: ${text.slice(0, 100)}`);
        }
        const config = await resp.json();

        // Populate model selector
        const select = document.getElementById('model-select');
        if (select && config.models && config.models.length > 0) {
            select.innerHTML = config.models.map((m, i) => {
                const isDefault = m.value === config.default_model;
                return `<option value="${m.value}"${isDefault ? ' selected' : ''}>${m.label}${isDefault ? ' (default)' : ''}</option>`;
            }).join('');
            wizardState.model = config.default_model || config.models[0]?.value || 'claude-opus-4.5';
            console.log('Loaded', config.models.length, 'models, default:', wizardState.model);
        } else {
            console.warn('Config response missing models:', config);
        }
    } catch (err) {
        console.error('Failed to load config:', err);
        // Show error in dropdown instead of silent failure
        const select = document.getElementById('model-select');
        if (select) {
            select.innerHTML = '<option value="claude-opus-4.5">claude-opus-4.5 (fallback)</option>';
            wizardState.model = 'claude-opus-4.5';
        }
    }
}

// ── Init ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();  // Load models dynamically
    setupTagInput('goals-container', 'goals-input', wizardState.researchGoals);
    setupTagInput('filetypes-container', 'filetypes-input', wizardState.fileTypes);
    setupTagInput('packages-container', 'packages-input', wizardState.knownPackages);
    setupFileUpload();
});
