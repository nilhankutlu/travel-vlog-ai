document.addEventListener('DOMContentLoaded', () => {
    // State
    let currentVideos = [];
    let currentStoryboard = null;

    // Elements
    const navButtons = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const folderPathInput = document.getElementById('folder-path-input');
    const startFolderBtn = document.getElementById('start-folder-btn');
    const whisperModelSelect = document.getElementById('whisper-model-select');
    const geminiKeyInput = document.getElementById('gemini-key-input');
    const progressCard = document.getElementById('progress-card');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressStatusText = document.getElementById('progress-status-text');
    const progressPercentText = document.getElementById('progress-percent-text');
    const progressFilename = document.getElementById('progress-filename');
    const videoCatalogGrid = document.getElementById('video-catalog-grid');
    const videoCountBadge = document.getElementById('video-count-badge');
    const statTotalVideos = document.getElementById('stat-total-videos');
    const statSpeechVideos = document.getElementById('stat-speech-videos');
    const storyboardTimeline = document.getElementById('storyboard-timeline');
    const promptPreview = document.getElementById('prompt-preview');
    const copyPromptBtn = document.getElementById('copy-prompt-btn');
    const catalogSearch = document.getElementById('catalog-search');

    // Tab Navigation
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            navButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');

            if (targetTab === 'catalog-tab' || targetTab === 'storyboard-tab' || targetTab === 'prompt-tab') {
                fetchResults();
            }
        });
    });

    // Setup SSE Stream
    function initSSEStream() {
        const evtSource = new EventSource('/api/status_stream');
        evtSource.addEventListener('progress', (e) => {
            const data = JSON.parse(e.data);
            progressCard.classList.remove('hidden');
            
            progressFilename.textContent = `İşleniyor: ${data.filename}`;
            progressStatusText.textContent = data.status_message;
            progressPercentText.textContent = `${data.overall_progress}%`;
            progressBarFill.style.width = `${data.overall_progress}%`;

            if (data.overall_progress >= 100) {
                setTimeout(() => {
                    fetchResults();
                }, 1000);
            }
        });
    }

    initSSEStream();

    // Start Folder Processing
    startFolderBtn.addEventListener('click', async () => {
        const folderPath = folderPathInput.value.trim();
        if (!folderPath) {
            alert('Lütfen bilgisayarınızdaki video klasör yolunu girin.');
            return;
        }

        progressCard.classList.remove('hidden');
        progressStatusText.textContent = 'Klasör taranıyor ve işleyici başlatılıyor...';
        progressBarFill.style.width = '2%';

        try {
            const res = await fetch('/api/process_folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_path: folderPath,
                    gemini_api_key: geminiKeyInput.value.trim() || null,
                    whisper_model: whisperModelSelect.value
                })
            });

            const data = await res.json();
            if (!res.ok) {
                alert(data.detail || 'Klasör işleme başlatılamadı.');
            }
        } catch (err) {
            console.error(err);
            alert('Sunucu ile iletişim hatası.');
        }
    });

    // Single File Drag & Drop
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');

    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadSingleFile(e.target.files[0]);
        }
    });

    async function uploadSingleFile(file) {
        progressCard.classList.remove('hidden');
        progressFilename.textContent = `Yükleniyor: ${file.name}`;
        progressStatusText.textContent = 'Dosya sunucuya aktarılıyor...';
        progressBarFill.style.width = '10%';

        const formData = new FormData();
        formData.append('file', file);
        if (geminiKeyInput.value.trim()) {
            formData.append('gemini_api_key', geminiKeyInput.value.trim());
        }

        try {
            const res = await fetch('/api/upload_video', {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                progressPercentText.textContent = '100%';
                progressBarFill.style.width = '100%';
                progressStatusText.textContent = 'Video başarıyla analiz edildi!';
                fetchResults();
            } else {
                alert('Video işlenirken bir hata oluştu.');
            }
        } catch (err) {
            console.error(err);
            alert('Yükleme hatası.');
        }
    }

    // Fetch Results & Render
    async function fetchResults() {
        try {
            const res = await fetch('/api/results');
            const data = await res.json();
            currentVideos = data.videos || [];
            currentStoryboard = data.storyboard || null;

            renderCatalog(currentVideos);
            renderStoryboard(currentStoryboard);
            renderPrompt(currentStoryboard ? currentStoryboard.chat_ai_prompt : '');
        } catch (err) {
            console.error('Sonuçlar alınamadı:', err);
        }
    }

    function renderCatalog(videos) {
        videoCountBadge.textContent = videos.length;
        statTotalVideos.textContent = videos.length;

        const speechCount = videos.filter(v => v.transcript && v.transcript.has_speech).length;
        statSpeechVideos.textContent = speechCount;

        if (videos.length === 0) {
            videoCatalogGrid.innerHTML = `
                <div class="empty-state">
                    <i class="fa-solid fa-film"></i>
                    <p>Henüz işlenmiş video yok. "Video İçe Aktar" sekmesinden klasör taraması yapın.</p>
                </div>
            `;
            return;
        }

        videoCatalogGrid.innerHTML = videos.map(item => {
            const loc = item.metadata.location;
            const placeStr = loc.place_name || loc.city || 'Bilinmeyen Konum';
            const speechText = item.transcript.has_speech ? item.transcript.full_text : 'Konuşma yok / Sadece Müzik';

            return `
                <div class="video-card">
                    <div class="video-card-header">
                        <div class="location-badge">
                            <i class="fa-solid fa-location-dot"></i> ${placeStr}
                        </div>
                        <span class="time-text">${item.metadata.creation_time || 'Zaman Yok'}</span>
                    </div>

                    <h4 style="margin: 8px 0; font-size: 14px;">${item.metadata.file_name}</h4>
                    <p style="font-size: 12px; color: var(--text-muted);">Süre: ${item.metadata.duration_seconds}s | Estetik: ${item.vision.aesthetic_score}/10</p>

                    <div class="transcript-box">
                        <i class="fa-solid fa-quote-left"></i> ${speechText}
                    </div>

                    <div class="vision-box">
                        <strong>Görsel Analiz:</strong> ${item.vision.summary || item.vision.detailed_description}
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderStoryboard(storyboard) {
        if (!storyboard || !storyboard.storyline || storyboard.storyline.length === 0) {
            storyboardTimeline.innerHTML = '<p class="card-desc">İşlenmiş kurgu senaryosu bulunmuyor.</p>';
            return;
        }

        document.getElementById('storyboard-title').textContent = `Otomatik Vlog Kurgusu: ${storyboard.vlog_title}`;

        storyboardTimeline.innerHTML = storyboard.storyline.map(seg => `
            <div style="background: rgba(0,0,0,0.3); border-left: 3px solid var(--primary); padding: 14px; margin-bottom: 12px; border-radius: 8px;">
                <div style="display:flex; justify-content:space-between; margin-bottom: 6px;">
                    <strong style="color: var(--primary);">${seg.suggested_title}</strong>
                    <span style="font-size: 12px; color: var(--text-muted);"><i class="fa-solid fa-clock"></i> ${seg.start_time}s - ${seg.end_time}s</span>
                </div>
                <p style="font-size: 13px; margin-bottom: 6px;">${seg.narration_voiceover}</p>
                <span class="tag"><i class="fa-solid fa-video"></i> ${seg.editing_notes}</span>
            </div>
        `).join('');
    }

    function renderPrompt(promptText) {
        promptPreview.textContent = promptText || 'Henüz prompt oluşturulamadı.';
    }

    copyPromptBtn.addEventListener('click', () => {
        const text = promptPreview.textContent;
        navigator.clipboard.writeText(text).then(() => {
            copyPromptBtn.innerHTML = '<i class="fa-solid fa-check"></i> Kopyalandı!';
            setTimeout(() => {
                copyPromptBtn.innerHTML = '<i class="fa-regular fa-copy"></i> İstem Metnini Kopyala';
            }, 2000);
        });
    });

    // Search filter
    catalogSearch.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const filtered = currentVideos.filter(v => {
            const loc = (v.metadata.location.place_name || '').toLowerCase();
            const transcript = (v.transcript.full_text || '').toLowerCase();
            const vision = (v.vision.summary || '').toLowerCase();
            const name = (v.metadata.file_name || '').toLowerCase();
            return loc.includes(term) || transcript.includes(term) || vision.includes(term) || name.includes(term);
        });
        renderCatalog(filtered);
    });

    // Initial fetch
    fetchResults();
});
