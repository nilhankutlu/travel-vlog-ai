document.addEventListener('DOMContentLoaded', () => {
    let currentVideos = [];
    let currentStoryboard = null;

    const navButtons = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const folderPathInput = document.getElementById('folder-path-input');
    const startFolderBtn = document.getElementById('start-folder-btn');
    const whisperModelSelect = document.getElementById('whisper-model-select');
    const progressCard = document.getElementById('progress-card');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressStatusText = document.getElementById('progress-status-text');
    const progressPercentText = document.getElementById('progress-percent-text');
    const progressFilename = document.getElementById('progress-filename');
    const videoCatalogGrid = document.getElementById('video-catalog-grid');
    const videoCountBadge = document.getElementById('video-count-badge');
    const statTotalVideos = document.getElementById('stat-total-videos');
    const statSpeechVideos = document.getElementById('stat-speech-videos');
    const fullScriptPreview = document.getElementById('full-script-preview');
    const renderVideoBtn = document.getElementById('render-video-btn');
    const renderFormatSelect = document.getElementById('render-format-select');
    const promptPreview = document.getElementById('prompt-preview');
    const copyPromptBtn = document.getElementById('copy-prompt-btn');
    const catalogSearch = document.getElementById('catalog-search');

    const longVlogPlayer = document.getElementById('long-vlog-player');
    const noLongMsg = document.getElementById('no-long-msg');
    const downloadLongLink = document.getElementById('download-long-link');

    const shortVlogPlayer = document.getElementById('short-vlog-player');
    const noShortMsg = document.getElementById('no-short-msg');
    const downloadShortLink = document.getElementById('download-short-link');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            navButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(targetTab).classList.add('active');

            if (targetTab === 'catalog-tab' || targetTab === 'storyboard-tab' || targetTab === 'video-render-tab' || targetTab === 'prompt-tab') {
                fetchResults();
            }
        });
    });

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

    startFolderBtn.addEventListener('click', async () => {
        const folderPath = folderPathInput.value.trim();
        if (!folderPath) {
            alert('Lütfen bilgisayarınızdaki video klasör yolunu girin.');
            return;
        }

        progressCard.classList.remove('hidden');
        progressStatusText.textContent = 'Klasör taranıyor ve Türkçe transkripsiyon başlatılıyor...';
        progressBarFill.style.width = '2%';

        try {
            const res = await fetch('/api/process_folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_path: folderPath,
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

    renderVideoBtn.addEventListener('click', async () => {
        const selectedFormat = renderFormatSelect.value;
        progressCard.classList.remove('hidden');
        progressFilename.textContent = `Video Birleştiriliyor (${selectedFormat.toUpperCase()})`;
        progressStatusText.textContent = '🎬 Kurgu başlatılıyor...';
        progressBarFill.style.width = '30%';

        try {
            const res = await fetch('/api/render_video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ video_format: selectedFormat })
            });
            if (res.ok) {
                alert('Video birleştirme başlatıldı! Canlı durum çubuğunu takip edebilirsiniz.');
            } else {
                const data = await res.json();
                alert(data.detail || 'Video birleştirme başlatılamadı.');
            }
        } catch (err) {
            console.error(err);
            alert('Video rendering başlatılırken hata oluştu.');
        }
    });

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
        progressStatusText.textContent = 'Dosya aktarılıyor...';
        progressBarFill.style.width = '10%';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/upload_video', {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                progressPercentText.textContent = '100%';
                progressBarFill.style.width = '100%';
                progressStatusText.textContent = 'Video analiz edildi!';
                fetchResults();
            } else {
                alert('Video işlenirken bir hata oluştu.');
            }
        } catch (err) {
            console.error(err);
            alert('Yükleme hatası.');
        }
    }

    async function fetchResults() {
        try {
            const res = await fetch('/api/results');
            const data = await res.json();
            currentVideos = data.videos || [];
            currentStoryboard = data.storyboard || null;

            renderCatalog(currentVideos);
            renderScripts(currentStoryboard);
            renderPrompt(currentStoryboard ? currentStoryboard.chat_ai_prompt : '');

            if (data.rendered_long_video_url) {
                longVlogPlayer.src = data.rendered_long_video_url;
                longVlogPlayer.classList.remove('hidden');
                noLongMsg.classList.add('hidden');
                downloadLongLink.href = data.rendered_long_video_url;
                downloadLongLink.classList.remove('hidden');
            }

            if (data.rendered_short_video_url) {
                shortVlogPlayer.src = data.rendered_short_video_url;
                shortVlogPlayer.classList.remove('hidden');
                noShortMsg.classList.add('hidden');
                downloadShortLink.href = data.rendered_short_video_url;
                downloadShortLink.classList.remove('hidden');
            }

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
            const speechText = item.transcript.has_speech ? item.transcript.full_text : 'Konuşma yok / Sadece Arka Plan Sesi';

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

    function renderScripts(storyboard) {
        if (!storyboard) {
            fullScriptPreview.textContent = 'Henüz oluşturulmuş vlog senaryosu yok.';
            return;
        }

        document.getElementById('storyboard-title').textContent = `Tam Vlog Senaryoları: ${storyboard.vlog_title}`;
        
        const combinedScript = `${storyboard.full_vlog_script_tr || ''}\n\n=======================================================\n\n${storyboard.short_vlog_script_tr || ''}`;
        fullScriptPreview.textContent = combinedScript;
    }

    function renderPrompt(promptText) {
        promptPreview.textContent = promptText || 'Henüz istem oluşturulamadı.';
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

    fetchResults();
});
