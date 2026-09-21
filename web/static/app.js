/**
 * VIBESBOT - Trading Dashboard
 */

const APP_VERSION = '1.33.0';
const SOUND_PREFS_KEY = 'vb_sound';

class VibesBot {
    constructor() {
        this.ws = null;
        this.isRunning = false;
        this.isPaused = false;
        this.isSimulation = true;
        this.trades = [];
        this.tradeHistory = [];
        this.priceHistory = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.soundEnabled = true;
        this.soundVolume = 0.6;
        this.audioCtx = null;
        this.entryPrice = null;
        this.sessionId = this.getSessionId();
        this.user = null;
        
        this.init();
    }
    
    init() {
        this.cacheElements();
        this.loadSoundPrefs();
        this.bindEvents();
        this.lockBrowserChrome();
        this.startClock();
        this.loadVersion();
        this.requireAccount();
    }
    
    cacheElements() {
        // Status
        this.statusDot = document.getElementById('status-dot');
        this.currentPrice = document.getElementById('current-price');
        this.roundTimer = document.getElementById('round-timer');
        
        // Signal
        this.signalDisplay = document.getElementById('signal-display');
        this.confidenceFill = document.getElementById('confidence-fill');
        this.confidenceValue = document.getElementById('confidence-value');
        this.probUp = document.getElementById('prob-up');
        this.probDown = document.getElementById('prob-down');
        
        // Price to Beat
        this.priceToBeatEl = document.getElementById('price-to-beat');
        this.livePriceEl = document.getElementById('live-price');
        this.priceDiff = document.getElementById('price-diff');
        
        // Features
        this.featureRsi = document.getElementById('feature-rsi');
        this.featureMacd = document.getElementById('feature-macd');
        this.featureBb = document.getElementById('feature-bb');
        this.featureMom = document.getElementById('feature-mom');
        this.rsiBar = document.getElementById('rsi-bar');
        
        // Stats
        this.statCapital = document.getElementById('stat-capital');
        this.statPnl = document.getElementById('stat-pnl');
        this.statTrades = document.getElementById('stat-trades');
        this.statWinrate = document.getElementById('stat-winrate');
        this.statWins = document.getElementById('stat-wins');
        this.statLosses = document.getElementById('stat-losses');
        this.winrateFill = document.getElementById('winrate-fill');
        
        // Controls
        this.btnStart = document.getElementById('btn-start');
        this.btnPause = document.getElementById('btn-pause');
        this.btnStop = document.getElementById('btn-stop');
        this.modeToggle = document.getElementById('mode-toggle');
        this.modeLabel = document.getElementById('mode-label');
        
        // Log
        this.tradeLog = document.getElementById('trade-log');
        this.tradeCount = document.getElementById('trade-count');
        this.activeTrade = document.getElementById('active-trade');
    }

    lockBrowserChrome() {
        const local = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
        if (!local) return;
        document.addEventListener('contextmenu', (event) => event.preventDefault(), true);
        document.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && (event.key === 'r' || event.key === 'R') && !window.__vbAllowReload) {
                event.preventDefault();
            }
        }, true);
    }
    
    bindEvents() {
        // Control buttons
        this.btnStart?.addEventListener('click', () => this.start());
        this.btnPause?.addEventListener('click', () => this.pause());
        this.btnStop?.addEventListener('click', () => this.stop());
        
        // Mode toggle
        this.modeToggle?.addEventListener('click', () => this.toggleMode());

        document.getElementById('btn-refresh')?.addEventListener('click', () => {
            window.__vbAllowReload = true;
            window.location.reload();
        });
        document.getElementById('btn-sound')?.addEventListener('click', () => this.toggleSound());
        document.getElementById('sound-enabled')?.addEventListener('change', (e) => {
            this.setSoundEnabled(!!e.target.checked);
        });
        document.getElementById('sound-volume')?.addEventListener('input', (e) => {
            this.setSoundVolume(Number(e.target.value) / 100);
        });
        
        // Settings
        document.getElementById('btn-settings')?.addEventListener('click', () => {
            document.getElementById('settings-modal')?.classList.add('active');
        });
        
        document.getElementById('modal-close')?.addEventListener('click', () => {
            document.getElementById('settings-modal')?.classList.remove('active');
        });
        
        document.querySelector('.modal-backdrop')?.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal-backdrop')) {
                document.getElementById('settings-modal')?.classList.remove('active');
            }
        });
        
        // Settings tabs
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
                tab.classList.add('active');
                const panel = document.getElementById('panel-' + tab.dataset.panel);
                panel?.classList.add('active');
            });
        });
        
        // Content tabs
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const content = document.getElementById('tab-' + tab.dataset.tab);
                content?.classList.add('active');
            });
        });
        
        // Save buttons
        document.getElementById('btn-save-trading')?.addEventListener('click', () => this.saveTradingSettings());
        document.getElementById('btn-save-binance')?.addEventListener('click', () => this.saveBinanceSettings());
        document.getElementById('btn-test-api')?.addEventListener('click', () => this.testApi());
        document.getElementById('btn-reset-sim')?.addEventListener('click', () => this.resetSimulation());
        document.getElementById('btn-check-update')?.addEventListener('click', () => this.checkUpdates({prompt: true}));
        document.getElementById('btn-install-update')?.addEventListener('click', () => this.installUpdate());
        document.getElementById('btn-update-now')?.addEventListener('click', () => this.installUpdate());
        document.getElementById('btn-update-later')?.addEventListener('click', () => this.snoozeUpdate());
        
        // Real mode confirmation
        document.getElementById('btn-cancel-real')?.addEventListener('click', () => {
            document.getElementById('real-mode-modal')?.classList.remove('active');
        });
        
        document.getElementById('btn-confirm-real')?.addEventListener('click', () => {
            this.confirmRealMode();
        });
        
        // Strategy controls
        document.getElementById('strategy-select')?.addEventListener('change', async (e) => {
            const response = await fetch('/api/strategies');
            const data = await response.json();
            const strategy = data.strategies?.find(s => s.id === e.target.value);
            this.updateStrategyInfo(strategy);
            this.saveStrategy();
        });
        
        document.getElementById('btn-save-strategy')?.addEventListener('click', () => this.saveStrategy());
        
        // Weight sliders
        ['rsi', 'macd', 'bb', 'mom'].forEach(id => {
            const slider = document.getElementById(id + '-weight');
            const label = document.getElementById(id + '-weight-val');
            slider?.addEventListener('input', (e) => {
                if (label) label.textContent = e.target.value;
            });
        });
        
        // Backtest
        document.getElementById('btn-run-backtest')?.addEventListener('click', () => this.runBacktest());
        
        // Export
        document.getElementById('btn-export-csv')?.addEventListener('click', () => this.exportCSV());
        document.getElementById('btn-export-json')?.addEventListener('click', () => this.exportJSON());
        document.getElementById('btn-export-report')?.addEventListener('click', () => this.generateReport());
        
        // Load strategies on init
        this.loadStrategies();
        this.bindMobileNav();
        this.bindAccount();
    }
    
    bindAccount() {
        document.getElementById('user-chip')?.addEventListener('click', () => this.openProfile());
        document.getElementById('btn-logout')?.addEventListener('click', () => this.logout());
        document.getElementById('btn-logout-settings')?.addEventListener('click', () => this.logout());
        document.getElementById('btn-change-password')?.addEventListener('click', () => this.changePassword());
        document.getElementById('btn-create-invite')?.addEventListener('click', () => this.createInvite());
        document.getElementById('btn-refresh-pin')?.addEventListener('click', () => this.refreshCompanionPin());
        document.getElementById('companion-enabled')?.addEventListener('change', async (e) => {
            await fetch('/api/companion/enable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: e.target.checked })
            });
            this.loadCompanionInfo();
        });
        document.getElementById('open-registration')?.addEventListener('change', async (e) => {
            await fetch('/api/auth/registration', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: e.target.checked })
            });
        });
    }
    
    async requireAccount() {
        try {
            const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
            if (!response.ok) {
                window.location.replace('/static/lobby.html');
                return;
            }
            const data = await response.json();
            if (!data.user || !data.user.username) {
                window.location.replace('/static/lobby.html');
                return;
            }
            this.user = data.user;
            this.isCompanion = !!data.companion;
            this.renderProfile(data);
            document.body.classList.remove('auth-wait');
            this.connect();
            this.loadSavedSettings();
            this.loadJournal();
            this.checkUpdates({prompt: true});
            window.setInterval(() => this.checkUpdates({prompt: true}), 30 * 60 * 1000);
            if (this.isCompanion) {
                document.body.classList.add('companion-mode');
                document.querySelector('.settings-tab[data-panel="binance"]')?.style.setProperty('display', 'none');
                document.querySelector('.settings-tab[data-panel="trading"]')?.style.setProperty('display', 'none');
                document.querySelector('.mode-switch')?.style.setProperty('display', 'none');
                const ownerTools = document.getElementById('owner-account-tools');
                if (ownerTools) ownerTools.style.display = 'none';
            } else if (data.user?.is_owner) {
                const ownerTools = document.getElementById('owner-account-tools');
                if (ownerTools) ownerTools.style.display = 'block';
                this.loadOwnerTools();
                this.loadCompanionInfo();
            } else {
                document.querySelector('.settings-tab[data-panel="binance"]')?.style.setProperty('display', 'none');
                document.querySelector('.settings-tab[data-panel="trading"]')?.style.setProperty('display', 'none');
                document.querySelector('.mode-switch')?.style.setProperty('display', 'none');
            }
        } catch (e) {
            window.location.replace('/static/lobby.html');
        }
    }

    initials(name) {
        const clean = (name || 'VB').trim();
        const parts = clean.split(/[\s_]+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return clean.slice(0, 2).toUpperCase();
    }

    renderProfile(data) {
        const username = data.user?.username || 'Guest';
        const role = data.companion ? 'Companion' : (data.user?.is_owner ? 'Owner' : 'Account');
        const initials = this.initials(username);
        const nameEl = document.getElementById('user-name');
        const roleChip = document.getElementById('user-role-chip');
        const avatar = document.getElementById('user-avatar');
        const profileName = document.getElementById('profile-name');
        const profileAvatar = document.getElementById('profile-avatar');
        const roleEl = document.getElementById('account-role');
        const tagEl = document.getElementById('brand-tag');
        if (nameEl) nameEl.textContent = username;
        if (roleChip) roleChip.textContent = role;
        if (avatar) avatar.textContent = initials;
        if (profileName) profileName.textContent = username;
        if (profileAvatar) profileAvatar.textContent = initials;
        if (roleEl) roleEl.textContent = data.companion ? 'Paired with the Mac app' : (data.user?.is_owner ? 'Owner desk' : 'Signed in');
        if (tagEl && data.companion) tagEl.textContent = 'Companion';
    }

    openProfile() {
        document.getElementById('settings-modal')?.classList.add('active');
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
        const tab = document.querySelector('.settings-tab[data-panel="account"]');
        tab?.classList.add('active');
        document.getElementById('panel-account')?.classList.add('active');
    }

    logout() {
        fetch('/api/auth/logout', { method: 'POST', keepalive: true }).catch(() => {});
        window.location.replace('/static/lobby.html');
    }
    
    async changePassword() {
        const status = document.getElementById('password-status');
        const current = document.getElementById('current-password')?.value || '';
        const next = document.getElementById('new-password')?.value || '';
        try {
            const response = await fetch('/api/auth/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current, new_password: next })
            });
            const data = await response.json();
            if (status) status.textContent = data.success ? 'Password updated' : (data.error || 'Failed');
        } catch (e) {
            if (status) status.textContent = 'Error';
        }
    }
    
    async loadOwnerTools() {
        try {
            const response = await fetch('/api/auth/users');
            if (!response.ok) return;
            const data = await response.json();
            const inviteList = document.getElementById('invite-list');
            const usersList = document.getElementById('users-list');
            const openReg = document.getElementById('open-registration');
            if (openReg) openReg.checked = !!data.allow_open_registration;
            if (inviteList) {
                inviteList.innerHTML = (data.invites || []).map(code =>
                    `<div class="invite-item"><span>${code}</span></div>`
                ).join('') || '<div class="settings-hint">No unused invites</div>';
            }
            if (usersList) {
                usersList.innerHTML = (data.users || []).map(user => `
                    <div class="user-row">
                        <span>${user.username}${user.is_owner ? ' (owner)' : ''}</span>
                        ${user.is_owner ? '' : `<button class="btn btn-danger btn-delete-user" data-id="${user.id}">DEL</button>`}
                    </div>
                `).join('');
                usersList.querySelectorAll('.btn-delete-user').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        await fetch('/api/auth/users/delete', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ user_id: btn.dataset.id })
                        });
                        this.loadOwnerTools();
                    });
                });
            }
        } catch (e) {
            console.error('Owner tools failed', e);
        }
    }
    
    async loadCompanionInfo() {
        try {
            const response = await fetch('/api/companion/info');
            if (!response.ok) return;
            const data = await response.json();
            const enabled = document.getElementById('companion-enabled');
            const details = document.getElementById('companion-details');
            const pin = document.getElementById('companion-pin');
            const urls = document.getElementById('companion-urls');
            if (enabled) enabled.checked = !!data.enabled;
            if (details) details.style.display = data.enabled ? 'block' : 'none';
            if (pin) pin.textContent = data.pin || '------';
            if (urls) {
                urls.textContent = (data.urls || []).join('  ') || 'No LAN URL yet';
            }
        } catch (e) {}
    }
    
    async refreshCompanionPin() {
        await fetch('/api/companion/pin', { method: 'POST' });
        this.loadCompanionInfo();
        this.addLog('Companion pairing code refreshed', 'info');
    }
    
    async createInvite() {
        const response = await fetch('/api/auth/invite', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            this.addLog('Invite created: ' + data.code, 'info');
            this.loadOwnerTools();
        } else {
            this.addLog(data.error || 'Could not create invite', 'loss');
        }
    }
    
    getSessionId() {
        const key = 'vibesbot_session_id';
        let id = localStorage.getItem(key);
        if (!id) {
            id = (crypto.randomUUID && crypto.randomUUID()) ||
                ('sess-' + Date.now() + '-' + Math.random().toString(16).slice(2));
            localStorage.setItem(key, id);
        }
        return id;
    }
    
    bindMobileNav() {
        document.querySelectorAll('.mobile-nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const view = btn.dataset.view;
                this.setMobileView(view);
            });
        });
        
        const mq = window.matchMedia('(max-width: 1099px)');
        const apply = () => {
            if (mq.matches) {
                this.setMobileView(document.body.dataset.view || 'signal');
            } else {
                document.body.dataset.view = '';
            }
        };
        mq.addEventListener?.('change', apply);
        apply();
    }
    
    setMobileView(view) {
        document.body.dataset.view = view;
        document.querySelectorAll('.mobile-nav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === view);
        });
        
        if (view === 'chart' || view === 'stats' || view === 'history') {
            const tabName = view === 'chart' ? 'chart' : (view === 'history' ? 'history' : 'stats');
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector(`.tab[data-tab="${tabName}"]`)?.classList.add('active');
            document.getElementById('tab-' + tabName)?.classList.add('active');
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // WebSocket Connection
    // ═══════════════════════════════════════════════════════════
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('Connected to server');
            this.statusDot?.classList.add('connected');
            this.reconnectAttempts = 0;
            this.send({ action: 'hello', session_id: this.sessionId });
            this.addLog('Connected to server', 'info');
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('Parse error:', e);
            }
        };
        
        this.ws.onclose = (event) => {
            console.log('Disconnected');
            this.statusDot?.classList.remove('connected');
            if (event.code === 4401) {
                window.location.href = '/login';
                return;
            }
            this.reconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    reconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            setTimeout(() => this.connect(), 2000);
        }
    }
    
    send(data) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // Message Handling
    // ═══════════════════════════════════════════════════════════
    
    handleMessage(data) {
        switch (data.type) {
            case 'market':
                this.updateMarket(data);
                break;
            case 'signal':
                this.updateSignal(data);
                break;
            case 'stats':
                this.updateStats(data);
                break;
            case 'journal':
                this.applyJournal(data.trades || []);
                break;
            case 'update':
                if (data.available) this.showUpdatePrompt(data);
                break;
            case 'trade':
                this.addTrade(data);
                break;
            case 'log':
                this.addLog(data.message, data.level || 'info');
                break;
            case 'error':
                if ((data.message || '').toLowerCase().includes('unauthorized')) {
                    window.location.href = '/login';
                }
                break;
            case 'status':
                this.updateBotStatus(data);
                break;
            case 'active_trade':
                this.updateActiveTrade(data);
                break;
        }
    }
    
    updateMarket(data) {
        // Price
        if (data.price && this.currentPrice) {
            const price = parseFloat(data.price);
            this.currentPrice.textContent = '$' + price.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
            
            // Update live price
            if (this.livePriceEl) {
                this.livePriceEl.textContent = '$' + price.toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
            
            // Update chart price
            const chartPrice = document.getElementById('chart-current-price');
            if (chartPrice) {
                chartPrice.textContent = '$' + price.toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
            
            // Store for chart
            this.priceHistory.push(price);
            if (this.priceHistory.length > 100) this.priceHistory.shift();
            
            // Update price difference if we have entry price
            this.updatePriceDiff(price);
        }
        
        // Timer
        if (data.timer != null && this.roundTimer) {
            const minutes = Math.floor(data.timer / 60);
            const seconds = data.timer % 60;
            this.roundTimer.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            
            // Color based on urgency
            if (data.timer <= 10) {
                this.roundTimer.style.color = 'var(--down)';
            } else if (data.timer <= 30) {
                this.roundTimer.style.color = 'var(--warning)';
            } else {
                this.roundTimer.style.color = 'var(--warning)';
            }
        }
        
        // Features/Indicators
        if (data.features) {
            this.updateFeatures(data.features);
        }
        if (data.prob_up != null && this.probUp) {
            this.probUp.textContent = (Number(data.prob_up) * 100).toFixed(1) + '%';
        }
        if (data.prob_down != null && this.probDown) {
            this.probDown.textContent = (Number(data.prob_down) * 100).toFixed(1) + '%';
        }
        const upOddsEl = document.getElementById('prob-up-odds');
        const downOddsEl = document.getElementById('prob-down-odds');
        if (upOddsEl && data.up_odds) upOddsEl.textContent = Number(data.up_odds).toFixed(2) + 'x';
        if (downOddsEl && data.down_odds) downOddsEl.textContent = Number(data.down_odds).toFixed(2) + 'x';
        this.applyPriceToBeat(data);
        
        // Draw charts
        this.drawMiniChart();
        this.drawPriceChart();
    }
    
    updatePriceDiff(currentPrice) {
        if (!this.priceToBeat || !this.priceDiff) return;
        
        const diff = currentPrice - this.priceToBeat;
        
        this.priceDiff.textContent = (diff >= 0 ? '+' : '') + '$' + diff.toFixed(2);
        this.priceDiff.className = 'price-diff ' + (diff >= 0 ? 'positive' : 'negative');
    }
    
    updateFeatures(features) {
        // RSI
        if (features.rsi !== undefined) {
            const rsi = parseFloat(features.rsi);
            if (this.featureRsi) this.featureRsi.textContent = rsi.toFixed(1);
            if (this.rsiBar) this.rsiBar.style.width = rsi + '%';
        }
        
        // MACD
        if (features.macd !== undefined) {
            const macd = parseFloat(features.macd);
            if (this.featureMacd) this.featureMacd.textContent = macd.toFixed(2);
            const macdInd = document.getElementById('macd-indicator');
            if (macdInd) {
                macdInd.className = 'feature-indicator ' + (macd > 0 ? 'bullish' : 'bearish');
            }
        }
        
        // Bollinger
        if (features.bb !== undefined) {
            if (this.featureBb) this.featureBb.textContent = features.bb;
            const bbInd = document.getElementById('bb-indicator');
            if (bbInd) {
                bbInd.className = 'feature-indicator ' + 
                    (features.bb === 'LOWER' ? 'bullish' : features.bb === 'UPPER' ? 'bearish' : 'neutral');
            }
        }
        
        // Momentum
        if (features.momentum !== undefined) {
            const mom = parseFloat(features.momentum);
            if (this.featureMom) this.featureMom.textContent = mom.toFixed(2);
            const momInd = document.getElementById('mom-indicator');
            if (momInd) {
                momInd.className = 'feature-indicator ' + (mom > 0 ? 'bullish' : 'bearish');
            }
        }
    }
    
    updateSignal(data) {
        if (!this.signalDisplay) return;
        
        const signal = data.signal || 'WAIT';
        const confidence = data.confidence || 0;
        
        // Update signal display
        this.signalDisplay.className = 'signal-direction ' + signal.toLowerCase();
        
        if (signal === 'UP') {
            this.signalDisplay.innerHTML = '<span class="signal-arrow">▲</span><span class="signal-text">UP</span>';
        } else if (signal === 'DOWN') {
            this.signalDisplay.innerHTML = '<span class="signal-arrow">▼</span><span class="signal-text">DOWN</span>';
        } else {
            this.signalDisplay.innerHTML = '<span class="signal-arrow">—</span><span class="signal-text">WAIT</span>';
        }
        
        // Confidence
        const confPct = Math.round(confidence * 100);
        if (this.confidenceFill) this.confidenceFill.style.width = confPct + '%';
        if (this.confidenceValue) this.confidenceValue.textContent = confPct + '%';
        
        // Probabilities from Binance Wallet market
        if (this.probUp && data.prob_up != null) this.probUp.textContent = (Number(data.prob_up) * 100).toFixed(1) + '%';
        if (this.probDown && data.prob_down != null) this.probDown.textContent = (Number(data.prob_down) * 100).toFixed(1) + '%';
        const upOdds = document.getElementById('prob-up-odds');
        const downOdds = document.getElementById('prob-down-odds');
        if (upOdds && data.up_odds) upOdds.textContent = Number(data.up_odds).toFixed(2) + 'x';
        if (downOdds && data.down_odds) downOdds.textContent = Number(data.down_odds).toFixed(2) + 'x';
        
        this.applyPriceToBeat(data);
    }

    applyPriceToBeat(data) {
        const sourceEl = document.getElementById('price-to-beat-source');
        const beat = parseFloat(data.price_to_beat);
        if (beat && !Number.isNaN(beat)) {
            this.priceToBeat = beat;
            if (this.priceToBeatEl) {
                this.priceToBeatEl.textContent = '$' + beat.toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
            const source = data.price_to_beat_source || '';
            if (sourceEl) {
                sourceEl.textContent = source === 'wallet'
                    ? 'Wallet lock'
                    : source === 'spot-5m-open'
                        ? 'Est. 5m open'
                        : source || 'Lock';
            }
            const live = parseFloat(data.price || data.live_price);
            if (live && !Number.isNaN(live)) this.updatePriceDiff(live);
            return;
        }
        if (this.priceToBeatEl) this.priceToBeatEl.textContent = '$--';
        if (sourceEl) sourceEl.textContent = 'Waiting for lock';
    }
    
    updateStats(data) {
        if (data.simulation === false) {
            this.applyModeUi(false);
        } else if (data.simulation === true && data.live !== true) {
            this.applyModeUi(true);
        }
        const capital = Number(data.capital ?? 0);
        if (this.statCapital) this.statCapital.textContent = '$' + capital.toFixed(2);
        const sourceEl = document.getElementById('stat-capital-source');
        if (sourceEl) {
            if (data.live) {
                sourceEl.textContent = data.live_error ? 'LIVE · ERROR' : 'LIVE';
            } else {
                sourceEl.textContent = 'SIMULATION';
            }
        }
        
        if (this.statPnl) {
            const pnl = data.pnl || 0;
            this.statPnl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
            this.statPnl.className = 'main-stat-value ' + (pnl >= 0 ? 'positive' : 'negative');
        }
        
        if (this.statTrades) this.statTrades.textContent = data.trades || 0;
        
        if (this.statWinrate) {
            const wr = data.winrate || 0;
            this.statWinrate.textContent = wr.toFixed(1) + '%';
            if (this.winrateFill) this.winrateFill.style.width = wr + '%';
        }
        
        if (this.statWins) this.statWins.textContent = data.wins || 0;
        if (this.statLosses) this.statLosses.textContent = data.losses || 0;

        const profileCapital = document.getElementById('profile-capital');
        const profilePnl = document.getElementById('profile-pnl');
        const profileTrades = document.getElementById('profile-trades');
        const profileWinrate = document.getElementById('profile-winrate');
        if (profileCapital) profileCapital.textContent = '$' + Number(data.capital ?? 0).toFixed(2);
        if (profilePnl) {
            const pnl = data.pnl || 0;
            profilePnl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
            profilePnl.classList.toggle('positive', pnl >= 0);
            profilePnl.classList.toggle('negative', pnl < 0);
        }
        if (profileTrades) profileTrades.textContent = data.trades || 0;
        if (profileWinrate) profileWinrate.textContent = (data.winrate || 0).toFixed(1) + '%';
        
        // Advanced stats
        const streakEl = document.getElementById('stat-streak');
        if (streakEl) {
            const streak = data.streak || 0;
            streakEl.textContent = streak > 0 ? '+' + streak : streak;
            streakEl.style.color = streak >= 0 ? 'var(--up)' : 'var(--down)';
        }
        
        const bestEl = document.getElementById('stat-best-streak');
        if (bestEl) bestEl.textContent = '+' + (data.best_streak || 0);
        
        const worstEl = document.getElementById('stat-worst-streak');
        if (worstEl) worstEl.textContent = data.worst_streak || 0;
        
        const kellyEl = document.getElementById('stat-kelly');
        if (kellyEl) kellyEl.textContent = (data.kelly || 0).toFixed(1) + '%';
        
        const pfEl = document.getElementById('stat-profit-factor');
        if (pfEl) pfEl.textContent = (data.profit_factor || 0).toFixed(2);
        
        const ddEl = document.getElementById('stat-max-dd');
        if (ddEl) ddEl.textContent = (data.max_drawdown || 0).toFixed(1) + '%';
        
        // Equity chart
        if (data.equity_history) {
            this.drawEquityChart(data.equity_history);
        }
        
        // Update trade count
        if (this.tradeCount) this.tradeCount.textContent = data.trades || 0;
    }
    
    addTrade(data) {
        // Add to history
        this.tradeHistory.unshift(data);
        if (this.tradeHistory.length > 80) this.tradeHistory.pop();
        
        // Update history tab
        this.renderHistory();
        
        // Play sound
        if (data.result === 'WIN') {
            this.playSound('win');
        } else if (data.result === 'LOSS') {
            this.playSound('loss');
        }
        
        // Clear price to beat after trade closes
        this.priceToBeat = null;
        if (this.priceToBeatEl) this.priceToBeatEl.textContent = '$--';
        if (this.priceDiff) {
            this.priceDiff.textContent = '--';
            this.priceDiff.className = 'price-diff';
        }
    }
    
    updateActiveTrade(data) {
        if (!this.activeTrade) return;
        
        if (data.active) {
            this.activeTrade.style.display = 'block';
            document.getElementById('active-direction').textContent = data.direction;
            document.getElementById('active-direction').className = 'active-trade-direction ' + data.direction.toLowerCase();
            document.getElementById('active-entry').textContent = '$' + data.entry_price?.toFixed(2);
            document.getElementById('active-current').textContent = '$' + data.current_price?.toFixed(2);
            
            const pnl = data.pnl || 0;
            const pnlEl = document.getElementById('active-pnl');
            pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
            pnlEl.className = pnl >= 0 ? 'positive' : 'negative';
            
            // Progress bar (time remaining)
            document.getElementById('trade-progress').style.width = (data.progress || 0) + '%';
        } else {
            this.activeTrade.style.display = 'none';
        }
    }
    
    addLog(message, level = 'info') {
        if (!this.tradeLog) return;
        
        // Remove empty state
        const empty = this.tradeLog.querySelector('.log-empty');
        if (empty) empty.remove();
        
        const item = document.createElement('div');
        item.className = 'log-item ' + level;
        
        const time = new Date().toLocaleTimeString('en-US', { hour12: false });
        
        item.innerHTML = `
            <div class="log-time">${time}</div>
            <div class="log-message">${message}</div>
        `;
        
        this.tradeLog.insertBefore(item, this.tradeLog.firstChild);
        
        // Limit log size
        while (this.tradeLog.children.length > 30) {
            this.tradeLog.removeChild(this.tradeLog.lastChild);
        }
    }

    async loadJournal() {
        try {
            const response = await fetch('/api/journal');
            if (!response.ok) return;
            const data = await response.json();
            this.applyJournal(data.trades || []);
        } catch (e) {}
    }

    applyJournal(trades) {
        if (!Array.isArray(trades) || !trades.length) return;
        const incoming = trades.slice().reverse();
        const merged = incoming.concat(this.tradeHistory);
        const seen = new Set();
        const deduped = [];
        for (const row of merged) {
            const key = [row.timestamp, row.order_id || '', row.pnl, row.direction].join('|');
            if (seen.has(key)) continue;
            seen.add(key);
            deduped.push(row);
        }
        this.tradeHistory = deduped.slice(0, 80);
        this.renderHistory();
    }
    
    renderHistory() {
        const list = document.getElementById('history-list');
        const count = document.getElementById('history-count');
        if (!list) return;
        
        if (count) count.textContent = this.tradeHistory.length + ' trades';
        
        if (this.tradeHistory.length === 0) {
            list.innerHTML = '<div class="history-empty">No trades yet</div>';
            return;
        }
        
        list.innerHTML = this.tradeHistory.slice(0, 40).map(trade => `
            <div class="history-item ${trade.result?.toLowerCase() || ''}">
                <div class="history-direction ${trade.direction?.toLowerCase() || ''}">${trade.direction || '?'}</div>
                <div class="history-details">
                    <div>${trade.mode || (trade.live ? 'REAL' : 'SIM')} · ${new Date(trade.timestamp || Date.now()).toLocaleTimeString()}</div>
                    <div class="history-prices">
                        Entry: $${(trade.entry_price || 0).toFixed(2)} → Exit: $${(trade.exit_price || 0).toFixed(2)}
                    </div>
                </div>
                <div class="history-result ${trade.pnl >= 0 ? 'positive' : 'negative'}">
                    ${trade.pnl >= 0 ? '+' : ''}$${(trade.pnl || 0).toFixed(2)}
                </div>
            </div>
        `).join('');
    }
    
    // ═══════════════════════════════════════════════════════════
    // Charts
    // ═══════════════════════════════════════════════════════════
    
    drawMiniChart() {
        const canvas = document.getElementById('mini-chart');
        if (!canvas || this.priceHistory.length < 2) return;
        
        const ctx = canvas.getContext('2d');
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width - 8;
        canvas.height = rect.height - 8;
        
        const prices = this.priceHistory.slice(-50);
        const min = Math.min(...prices) * 0.9999;
        const max = Math.max(...prices) * 1.0001;
        const range = max - min || 1;
        
        // Clear
        ctx.fillStyle = 'rgba(7, 8, 9, 0.35)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw line
        const lastPrice = prices[prices.length - 1];
        const firstPrice = prices[0];
        const color = lastPrice >= firstPrice ? '#3DFFB0' : '#FF5C7A';
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        
        for (let i = 0; i < prices.length; i++) {
            const x = (i / (prices.length - 1)) * canvas.width;
            const y = canvas.height - ((prices[i] - min) / range) * canvas.height;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        
        // Fill
        ctx.lineTo(canvas.width, canvas.height);
        ctx.lineTo(0, canvas.height);
        ctx.closePath();
        ctx.fillStyle = lastPrice >= firstPrice ? 'rgba(61, 255, 176, 0.12)' : 'rgba(255, 92, 122, 0.12)';
        ctx.fill();
    }
    
    drawPriceChart() {
        const canvas = document.getElementById('price-chart');
        if (!canvas || this.priceHistory.length < 2) return;
        
        const ctx = canvas.getContext('2d');
        const container = canvas.parentElement;
        canvas.width = container.clientWidth - 16;
        canvas.height = Math.max(200, container.clientHeight - 16);
        
        const prices = this.priceHistory.slice(-100);
        const min = Math.min(...prices) * 0.9998;
        const max = Math.max(...prices) * 1.0002;
        const range = max - min || 1;
        
        // Background
        ctx.fillStyle = 'rgba(7, 8, 9, 0.35)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Grid
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = (i / 4) * canvas.height;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(canvas.width, y);
            ctx.stroke();
            
            // Price label
            const price = max - (i / 4) * range;
            ctx.fillStyle = 'rgba(244, 247, 250, 0.38)';
            ctx.font = '11px Outfit, sans-serif';
            ctx.fillText('$' + price.toFixed(2), 5, y + 12);
        }
        
        // Price line
        const lastPrice = prices[prices.length - 1];
        const firstPrice = prices[0];
        const color = lastPrice >= firstPrice ? '#3DFFB0' : '#FF5C7A';
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        
        for (let i = 0; i < prices.length; i++) {
            const x = (i / (prices.length - 1)) * canvas.width;
            const y = canvas.height - ((prices[i] - min) / range) * canvas.height;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        
        // Fill gradient
        ctx.lineTo(canvas.width, canvas.height);
        ctx.lineTo(0, canvas.height);
        ctx.closePath();
        
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
        if (lastPrice >= firstPrice) {
            gradient.addColorStop(0, 'rgba(61, 255, 176, 0.22)');
            gradient.addColorStop(1, 'rgba(61, 255, 176, 0)');
        } else {
            gradient.addColorStop(0, 'rgba(255, 92, 122, 0.22)');
            gradient.addColorStop(1, 'rgba(255, 92, 122, 0)');
        }
        ctx.fillStyle = gradient;
        ctx.fill();
        
        // Current price dot
        const lastY = canvas.height - ((lastPrice - min) / range) * canvas.height;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(canvas.width - 5, lastY, 4, 0, Math.PI * 2);
        ctx.fill();
        
        // Price to Beat line if active
        if (this.priceToBeat && this.priceToBeat >= min && this.priceToBeat <= max) {
            const targetY = canvas.height - ((this.priceToBeat - min) / range) * canvas.height;
            ctx.strokeStyle = '#FFD166';
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(0, targetY);
            ctx.lineTo(canvas.width, targetY);
            ctx.stroke();
            ctx.setLineDash([]);
            
            ctx.fillStyle = '#FFD166';
            ctx.font = '11px Outfit, sans-serif';
            ctx.fillText('TARGET $' + this.priceToBeat.toFixed(2), canvas.width - 110, targetY - 5);
        }
    }
    
    drawEquityChart(equityData) {
        const canvas = document.getElementById('equity-chart');
        if (!canvas || !equityData || equityData.length < 2) return;
        
        const ctx = canvas.getContext('2d');
        const container = canvas.parentElement;
        canvas.width = container.clientWidth;
        canvas.height = 80;
        
        const min = Math.min(...equityData) * 0.98;
        const max = Math.max(...equityData) * 1.02;
        const range = max - min || 1;
        
        // Clear
        ctx.fillStyle = 'rgba(7, 8, 9, 0.2)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // $100 reference line
        const y100 = canvas.height - ((100 - min) / range) * canvas.height;
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(0, y100);
        ctx.lineTo(canvas.width, y100);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Equity line
        const lastVal = equityData[equityData.length - 1];
        const color = lastVal >= 100 ? '#5CF2FF' : '#FF5C7A';
        
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        
        for (let i = 0; i < equityData.length; i++) {
            const x = (i / (equityData.length - 1)) * canvas.width;
            const y = canvas.height - ((equityData[i] - min) / range) * canvas.height;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        
        // Label
        ctx.fillStyle = color;
        ctx.font = '600 13px Outfit, sans-serif';
        ctx.fillText('$' + lastVal.toFixed(2), 5, 15);
    }
    
    // ═══════════════════════════════════════════════════════════
    // Controls
    // ═══════════════════════════════════════════════════════════
    
    start() {
        this.send({ action: 'start' });
        this.isRunning = true;
        this.isPaused = false;
        this.updateControlButtons();
        this.addLog('▶ Bot started', 'info');
    }
    
    pause() {
        this.send({ action: 'pause' });
        this.isPaused = !this.isPaused;
        this.updateControlButtons();
        this.addLog(this.isPaused ? '⏸ Bot paused' : '▶ Bot resumed', 'info');
    }
    
    stop() {
        this.send({ action: 'stop' });
        this.isRunning = false;
        this.isPaused = false;
        this.updateControlButtons();
        this.addLog('⏹ Bot stopped', 'info');
    }
    
    updateControlButtons() {
        if (this.btnStart) this.btnStart.disabled = this.isRunning;
        if (this.btnPause) this.btnPause.disabled = !this.isRunning;
        if (this.btnStop) this.btnStop.disabled = !this.isRunning;
        
        if (this.btnPause) {
            this.btnPause.textContent = this.isPaused ? 'Resume' : 'Pause';
        }
    }
    
    updateBotStatus(data) {
        this.isRunning = data.running || false;
        this.isPaused = data.paused || false;
        if (typeof data.simulation === 'boolean') {
            this.applyModeUi(data.simulation);
        }
        const engine = document.getElementById('model-status');
        if (engine) {
            const label = data.signal_engine || (data.model_loaded ? 'Indicators + tape' : 'Waiting');
            engine.textContent = label === 'indicators+tape' ? 'Indicators + tape' : label;
        }
        const strategy = document.getElementById('strategy-status');
        if (strategy && data.signal_engine) {
            strategy.textContent = 'Live weights';
        }
        this.updateControlButtons();
    }
    
    toggleMode() {
        if (this.isSimulation) {
            document.getElementById('real-mode-modal')?.classList.add('active');
        } else {
            this.setMode(true);
        }
    }
    
    confirmRealMode() {
        document.getElementById('real-mode-modal')?.classList.remove('active');
        this.setMode(false);
    }
    
    applyModeUi(simulation) {
        this.isSimulation = simulation;
        if (this.modeToggle) {
            this.modeToggle.classList.toggle('real', !simulation);
        }
        if (this.modeLabel) {
            this.modeLabel.textContent = simulation ? 'SIM' : 'REAL';
            this.modeLabel.className = 'mode-indicator ' + (simulation ? 'sim' : 'real');
        }
    }

    async setMode(simulation) {
        this.applyModeUi(simulation);
        const sourceEl = document.getElementById('stat-capital-source');
        if (!simulation && sourceEl) {
            sourceEl.textContent = 'LOADING LIVE…';
        }
        this.send({ action: 'set_mode', simulation: simulation });
        if (simulation) {
            return;
        }
        try {
            const response = await fetch('/api/binance/balances', { credentials: 'same-origin' });
            const data = await response.json();
            if (data && (data.display_balance != null || data.wallets)) {
                this.updateStats({
                    type: 'stats',
                    capital: data.display_balance ?? 0,
                    pnl: 0,
                    trades: 0,
                    winrate: 0,
                    wins: 0,
                    losses: 0,
                    live: true,
                    simulation: false,
                    wallet: data.display_wallet || 'My Wallet',
                    wallets: data.wallets || {},
                    wallet_address: data.wallet_address || '',
                    network: data.network || 'BNB Smart Chain',
                    live_error: data.error || '',
                });
            } else if (data && data.error) {
                this.addLog(data.error, 'loss');
            }
        } catch (error) {
            this.addLog('Could not read live Binance balances', 'loss');
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // Settings
    // ═══════════════════════════════════════════════════════════
    
    applyTradingSettings(trading) {
        if (!trading) return;
        const betEl = document.getElementById('bet-amount');
        if (betEl && trading.bet_amount != null) {
            betEl.value = Number(trading.bet_amount).toFixed(2);
        }
        const confEl = document.getElementById('confidence-threshold');
        if (confEl && trading.confidence_threshold != null) {
            confEl.value = Math.round(Number(trading.confidence_threshold) * 100);
        }
        const lossEl = document.getElementById('daily-loss-limit');
        const loss = trading.max_daily_loss ?? trading.daily_loss_limit;
        if (lossEl && loss != null) {
            lossEl.value = Number(loss);
        }
    }

    async saveTradingSettings() {
        const rawBet = parseFloat(document.getElementById('bet-amount')?.value || 1.5);
        const settings = {
            bet_amount: Math.max(1.5, rawBet || 1.5),
            confidence_threshold: parseFloat(document.getElementById('confidence-threshold')?.value || 50) / 100,
            daily_loss_limit: parseFloat(document.getElementById('daily-loss-limit')?.value || 20),
            max_daily_loss: parseFloat(document.getElementById('daily-loss-limit')?.value || 20)
        };
        
        try {
            const response = await fetch('/api/settings/trading', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            
            if (response.ok) {
                const payload = await response.json();
                this.applyTradingSettings(payload.settings || settings);
                await this.saveStrategy();
                this.addLog('✓ Trading settings saved for SIM and REAL', 'info');
            }
        } catch (e) {
            this.addLog('✗ Error saving settings', 'loss');
        }
    }
    
    async loadSavedSettings() {
        try {
            const response = await fetch('/api/settings', { credentials: 'same-origin' });
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            const binance = data.binance || {};
            const keyEl = document.getElementById('api-key');
            const secretEl = document.getElementById('api-secret');
            const statusEl = document.getElementById('api-status');
            const testnetEl = document.getElementById('use-testnet');
            if (keyEl && !keyEl.value) {
                keyEl.placeholder = binance.configured
                    ? ((binance.api_key || 'Key saved on this Mac') + ' — leave blank to keep')
                    : 'Enter API Key';
            }
            if (secretEl) {
                secretEl.value = '';
                secretEl.placeholder = binance.has_secret
                    ? 'Saved on this Mac — leave blank to keep'
                    : 'Enter API Secret';
            }
            if (testnetEl) {
                testnetEl.checked = !!binance.is_testnet;
            }
            const walletEl = document.getElementById('prediction-wallet');
            if (walletEl) {
                walletEl.value = binance.prediction_wallet || '';
            }
            if (statusEl && binance.configured) {
                statusEl.textContent = 'Keys saved on this Mac';
                statusEl.style.color = 'var(--up)';
            }
            this.applyTradingSettings(data.trading);
        } catch (error) {
            // Keep empty form if settings cannot be read
        }
    }

    async saveBinanceSettings() {
        const testnet = !!document.getElementById('use-testnet')?.checked;
        const settings = {
            api_key: document.getElementById('api-key')?.value || '',
            api_secret: document.getElementById('api-secret')?.value || '',
            testnet,
            is_testnet: testnet,
            use_testnet: testnet,
            prediction_wallet: document.getElementById('prediction-wallet')?.value || '',
        };
        
        try {
            const response = await fetch('/api/settings/binance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            
            if (response.ok) {
                this.addLog('✓ Binance settings saved', 'info');
            }
        } catch (e) {
            this.addLog('✗ Error saving settings', 'loss');
        }
    }
    
    async testApi() {
        const statusEl = document.getElementById('api-status');
        if (statusEl) {
            statusEl.textContent = 'Testing...';
            statusEl.style.color = 'var(--text-dim)';
        }
        
        try {
            const response = await fetch('/api/settings/binance/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    api_key: document.getElementById('api-key')?.value || '',
                    api_secret: document.getElementById('api-secret')?.value || '',
                    testnet: !!document.getElementById('use-testnet')?.checked,
                    is_testnet: !!document.getElementById('use-testnet')?.checked,
                    use_testnet: !!document.getElementById('use-testnet')?.checked,
                    prediction_wallet: document.getElementById('prediction-wallet')?.value || '',
                })
            });
            
            const data = await response.json();
            const detail = data.message || data.error || 'Failed';
            
            if (statusEl) {
                statusEl.textContent = data.success ? '✓ ' + (data.message || 'Connected') : '✗ ' + detail;
                statusEl.style.color = data.success ? 'var(--up)' : 'var(--down)';
            }
        } catch (e) {
            if (statusEl) {
                statusEl.textContent = '✗ Connection error';
                statusEl.style.color = 'var(--down)';
            }
        }
    }
    
    async resetSimulation() {
        try {
            await fetch('/api/simulation/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionId })
            });
            this.addLog('✓ Simulation reset', 'info');
        } catch (e) {
            this.addLog('✗ Error resetting', 'loss');
        }
    }
    
    parseVersion(value) {
        return String(value || '0').replace(/^v/i, '').split('.').map(part => parseInt(part, 10) || 0);
    }

    isNewerVersion(latest, current) {
        const a = this.parseVersion(latest);
        const b = this.parseVersion(current);
        const len = Math.max(a.length, b.length);
        for (let i = 0; i < len; i++) {
            const left = a[i] || 0;
            const right = b[i] || 0;
            if (left > right) return true;
            if (left < right) return false;
        }
        return false;
    }

    async checkUpdates(options = {}) {
        const statusEl = document.getElementById('update-status');
        const latestEl = document.getElementById('latest-version');
        const currentEl = document.getElementById('current-version');
        const installBtn = document.getElementById('btn-install-update');
        const prompt = options.prompt !== false;
        
        try {
            const response = await fetch('/api/updates/check');
            const data = await response.json();
            const current = APP_VERSION;
            const latest = data.latest_version || '';
            const available = this.isNewerVersion(latest, current);
            
            if (currentEl) currentEl.textContent = 'v' + current;
            if (latestEl) latestEl.textContent = latest ? ('v' + String(latest).replace(/^v/i, '')) : '--';
            
            if (available) {
                if (statusEl) statusEl.textContent = 'Update available';
                if (installBtn) installBtn.disabled = false;
                if (prompt && data.prompt !== false) this.showUpdatePrompt(data);
            } else if (statusEl && !prompt) {
                statusEl.textContent = 'You have the latest version';
                if (installBtn) installBtn.disabled = true;
            }
        } catch (e) {
            if (statusEl && !prompt) statusEl.textContent = 'Error checking updates';
        }
    }

    showUpdatePrompt(data) {
        const latest = String(data.latest_version || '').replace(/^v/i, '');
        if (!latest || this._updatePromptShown === latest) return;
        this._updatePromptShown = latest;
        this._pendingUpdateVersion = latest;
        const fromEl = document.getElementById('update-prompt-from');
        const toEl = document.getElementById('update-prompt-to');
        const notesEl = document.getElementById('update-prompt-notes');
        if (fromEl) fromEl.textContent = 'v' + APP_VERSION;
        if (toEl) toEl.textContent = 'v' + latest;
        if (notesEl) notesEl.textContent = data.release_notes || 'A new Vibesbot build is ready.';
        document.getElementById('update-prompt')?.classList.add('active');
    }

    async snoozeUpdate() {
        const latest = this._pendingUpdateVersion || '';
        document.getElementById('update-prompt')?.classList.remove('active');
        try {
            await fetch('/api/updates/later', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ latest_version: latest })
            });
        } catch (e) {}
        this.addLog('Update later — reminder in ~12h', 'info');
    }
    
    async installUpdate() {
        const statusEl = document.getElementById('update-status');
        if (statusEl) statusEl.textContent = 'Installing...';
        
        try {
            const response = await fetch('/api/updates/install', { method: 'POST' });
            const data = await response.json();
            
            if (data.success) {
                if (statusEl) statusEl.textContent = 'Updated. Loading the new interface...';
                document.getElementById('restart-banner')?.classList.add('show');
                window.setTimeout(() => window.location.reload(), 2600);
            } else {
                if (statusEl) statusEl.textContent = 'Update failed: ' + data.message;
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error installing update';
        }
    }
    
    async loadVersion() {
        const versionEl = document.getElementById('app-version');
        const currentEl = document.getElementById('current-version');
        if (versionEl) versionEl.textContent = 'v' + APP_VERSION;
        if (currentEl) currentEl.textContent = 'v' + APP_VERSION;
    }
    
    // ═══════════════════════════════════════════════════════════
    // Strategy Management
    // ═══════════════════════════════════════════════════════════
    
    async loadStrategies() {
        try {
            const response = await fetch('/api/strategies');
            const data = await response.json();
            
            const select = document.getElementById('strategy-select');
            if (select && data.strategies) {
                select.innerHTML = data.strategies.map(s => 
                    `<option value="${s.id}" ${s.id === data.active ? 'selected' : ''}>${s.name}</option>`
                ).join('');
                
                this.updateStrategyInfo(data.strategies.find(s => s.id === data.active));
            }
        } catch (e) {
            console.error('Error loading strategies');
        }
    }
    
    updateStrategyInfo(strategy) {
        if (!strategy) return;
        const trades = document.getElementById('strat-trades');
        const winrate = document.getElementById('strat-winrate');
        const pnl = document.getElementById('strat-pnl');
        if (trades) trades.textContent = strategy.stats?.total_trades || 0;
        if (winrate) winrate.textContent = (strategy.stats?.win_rate || 0).toFixed(1) + '%';
        if (pnl) pnl.textContent = '$' + (strategy.stats?.total_pnl || 0).toFixed(2);
        
        if (strategy.weights) {
            this.setSlider('rsi-weight', strategy.weights.rsi);
            this.setSlider('macd-weight', strategy.weights.macd);
            this.setSlider('bb-weight', strategy.weights.bollinger);
            this.setSlider('mom-weight', strategy.weights.momentum);
        }
    }
    
    setSlider(id, value) {
        const slider = document.getElementById(id);
        const label = document.getElementById(id + '-val');
        if (slider) slider.value = value;
        if (label) label.textContent = value;
    }
    
    async saveStrategy() {
        const strategyId = document.getElementById('strategy-select')?.value || 'default';
        
        const data = {
            rsi_weight: parseInt(document.getElementById('rsi-weight')?.value || 2),
            macd_weight: parseInt(document.getElementById('macd-weight')?.value || 2),
            bollinger_weight: parseInt(document.getElementById('bb-weight')?.value || 1),
            momentum_weight: parseInt(document.getElementById('mom-weight')?.value || 1)
        };
        
        try {
            await fetch(`/api/strategies/${strategyId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            // Set as active
            await fetch('/api/strategies/active', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: strategyId })
            });
            
            this.addLog('Strategy saved', 'info');
        } catch (e) {
            this.addLog('Error saving strategy', 'loss');
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // Backtesting
    // ═══════════════════════════════════════════════════════════
    
    async runBacktest() {
        const progressDiv = document.getElementById('backtest-progress');
        const resultDiv = document.getElementById('backtest-result');
        const statusEl = document.getElementById('backtest-status');
        const barEl = document.getElementById('backtest-bar');
        
        if (progressDiv) progressDiv.style.display = 'block';
        if (resultDiv) resultDiv.style.display = 'none';
        
        const data = {
            strategy_id: document.getElementById('strategy-select')?.value || 'default',
            days: parseInt(document.getElementById('backtest-days')?.value || 7),
            initial_capital: parseFloat(document.getElementById('backtest-capital')?.value || 100),
            bet_amount: parseFloat(document.getElementById('backtest-bet')?.value || 1)
        };
        
        try {
            if (statusEl) statusEl.textContent = 'Fetching data...';
            if (barEl) barEl.style.width = '10%';
            
            const response = await fetch('/api/backtest/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (result.success) {
                if (barEl) barEl.style.width = '100%';
                if (statusEl) statusEl.textContent = 'Complete!';
                
                this.displayBacktestResult(result.result);
            } else {
                if (statusEl) statusEl.textContent = 'Error: ' + (result.error || 'Unknown');
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error: ' + e.message;
        }
    }
    
    displayBacktestResult(result) {
        const resultDiv = document.getElementById('backtest-result');
        if (resultDiv) resultDiv.style.display = 'block';
        
        document.getElementById('bt-trades').textContent = result.trades?.total || 0;
        document.getElementById('bt-winrate').textContent = (result.trades?.win_rate || 0).toFixed(1) + '%';
        document.getElementById('bt-capital').textContent = '$' + (result.capital?.final || 100).toFixed(2);
        document.getElementById('bt-pnl').textContent = '$' + (result.metrics?.total_pnl || 0).toFixed(2);
        document.getElementById('bt-drawdown').textContent = (result.metrics?.max_drawdown || 0).toFixed(1) + '%';
        document.getElementById('bt-pf').textContent = (result.metrics?.profit_factor || 0).toFixed(2);
        
        // Color coding
        const pnlEl = document.getElementById('bt-pnl');
        const capitalEl = document.getElementById('bt-capital');
        if (pnlEl) pnlEl.style.color = result.metrics?.total_pnl >= 0 ? 'var(--up)' : 'var(--down)';
        if (capitalEl) capitalEl.style.color = result.capital?.final >= result.capital?.initial ? 'var(--up)' : 'var(--down)';
    }
    
    // ═══════════════════════════════════════════════════════════
    // Data Export
    // ═══════════════════════════════════════════════════════════
    
    async exportCSV() {
        try {
            const response = await fetch('/api/export/trades/csv');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'vibesbot_trades.csv';
            a.click();
            window.URL.revokeObjectURL(url);
            this.addLog('CSV exported', 'info');
        } catch (e) {
            this.addLog('Export failed', 'loss');
        }
    }
    
    async exportJSON() {
        try {
            const response = await fetch('/api/export/trades/json');
            const data = await response.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'vibesbot_trades.json';
            a.click();
            window.URL.revokeObjectURL(url);
            this.addLog('JSON exported', 'info');
        } catch (e) {
            this.addLog('Export failed', 'loss');
        }
    }
    
    async generateReport() {
        try {
            const response = await fetch('/api/export/report');
            const report = await response.json();
            
            const resultDiv = document.getElementById('report-result');
            const contentDiv = document.getElementById('report-content');
            
            if (resultDiv) resultDiv.style.display = 'block';
            
            if (contentDiv && report.analysis) {
                contentDiv.innerHTML = `
                    <div style="margin-bottom:8px;"><b>Summary:</b></div>
                    <div>Total Trades: ${report.summary?.total_trades || 0}</div>
                    <div>Win Rate: ${(report.summary?.win_rate || 0).toFixed(1)}%</div>
                    <div>Total P&L: $${(report.summary?.total_pnl || 0).toFixed(2)}</div>
                    <div style="margin:8px 0;"><b>Analysis:</b></div>
                    <div>Best Hour: ${report.analysis?.best_hour !== null ? report.analysis.best_hour + ':00' : 'N/A'}</div>
                    <div>Worst Hour: ${report.analysis?.worst_hour !== null ? report.analysis.worst_hour + ':00' : 'N/A'}</div>
                    <div>Best Streak: +${report.analysis?.best_streak || 0}</div>
                    <div>Worst Streak: ${report.analysis?.worst_streak || 0}</div>
                    <div>UP Win Rate: ${(report.analysis?.up_signal_win_rate || 0).toFixed(1)}%</div>
                    <div>DOWN Win Rate: ${(report.analysis?.down_signal_win_rate || 0).toFixed(1)}%</div>
                `;
            }
        } catch (e) {
            this.addLog('Report generation failed', 'loss');
        }
    }
    
    loadSoundPrefs() {
        try {
            const raw = localStorage.getItem(SOUND_PREFS_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (typeof parsed.enabled === 'boolean') this.soundEnabled = parsed.enabled;
                if (typeof parsed.volume === 'number') this.soundVolume = Math.min(1, Math.max(0, parsed.volume));
            }
        } catch (e) {}
        this.syncSoundUi();
    }

    persistSoundPrefs() {
        try {
            localStorage.setItem(SOUND_PREFS_KEY, JSON.stringify({
                enabled: this.soundEnabled,
                volume: this.soundVolume,
            }));
        } catch (e) {}
    }

    syncSoundUi() {
        const btn = document.getElementById('btn-sound');
        const icon = document.getElementById('sound-icon');
        const box = document.getElementById('sound-enabled');
        const slider = document.getElementById('sound-volume');
        const label = document.getElementById('sound-volume-val');
        if (btn) {
            btn.classList.toggle('is-off', !this.soundEnabled);
            btn.setAttribute('aria-pressed', this.soundEnabled ? 'true' : 'false');
            btn.title = this.soundEnabled ? 'Sound on' : 'Sound off';
        }
        if (icon) icon.textContent = this.soundEnabled ? '♪' : '✖';
        if (box) box.checked = this.soundEnabled;
        if (slider) slider.value = String(Math.round(this.soundVolume * 100));
        if (label) label.textContent = Math.round(this.soundVolume * 100) + '%';
    }

    toggleSound() {
        this.setSoundEnabled(!this.soundEnabled);
        if (this.soundEnabled) this.playSound('win');
    }

    setSoundEnabled(enabled) {
        this.soundEnabled = !!enabled;
        this.persistSoundPrefs();
        this.syncSoundUi();
    }

    setSoundVolume(volume) {
        this.soundVolume = Math.min(1, Math.max(0, Number(volume) || 0));
        this.persistSoundPrefs();
        this.syncSoundUi();
    }

    // ═══════════════════════════════════════════════════════════
    // Audio
    // ═══════════════════════════════════════════════════════════
    
    playSound(type) {
        if (!this.soundEnabled || this.soundVolume <= 0) return;
        
        try {
            if (!this.audioCtx) {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (this.audioCtx.state === 'suspended') {
                this.audioCtx.resume();
            }
            
            const oscillator = this.audioCtx.createOscillator();
            const gainNode = this.audioCtx.createGain();
            const level = Math.max(0.02, Math.min(0.22, this.soundVolume * 0.22));
            
            oscillator.connect(gainNode);
            gainNode.connect(this.audioCtx.destination);
            
            if (type === 'win') {
                oscillator.frequency.setValueAtTime(523, this.audioCtx.currentTime);
                oscillator.frequency.setValueAtTime(659, this.audioCtx.currentTime + 0.1);
                oscillator.frequency.setValueAtTime(784, this.audioCtx.currentTime + 0.2);
            } else if (type === 'loss') {
                oscillator.frequency.setValueAtTime(392, this.audioCtx.currentTime);
                oscillator.frequency.setValueAtTime(330, this.audioCtx.currentTime + 0.15);
            }
            
            gainNode.gain.setValueAtTime(level, this.audioCtx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, this.audioCtx.currentTime + 0.3);
            
            oscillator.start(this.audioCtx.currentTime);
            oscillator.stop(this.audioCtx.currentTime + 0.3);
        } catch (e) {}
    }
    
    // ═══════════════════════════════════════════════════════════
    // Clock
    // ═══════════════════════════════════════════════════════════
    
    startClock() {
        const update = () => {
            const clock = document.getElementById('clock');
            if (clock) {
                clock.textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
            }
        };
        update();
        setInterval(update, 1000);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.vibesbot = new VibesBot();
    
    // Register Service Worker for PWA
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js')
            .then(registration => {
                console.log('[PWA] Service Worker registered:', registration.scope);
                
                // Check for updates periodically
                setInterval(() => {
                    registration.update();
                }, 60000);
            })
            .catch(error => {
                console.error('[PWA] Service Worker registration failed:', error);
            });
    }
    
    // Handle PWA install prompt
    let deferredPrompt;
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        
        // Show install button if not already installed
        showInstallPrompt();
    });
    
    function showInstallPrompt() {
        const installBtn = document.getElementById('pwa-install-btn');
        if (installBtn) {
            installBtn.style.display = 'block';
            installBtn.addEventListener('click', async () => {
                if (deferredPrompt) {
                    deferredPrompt.prompt();
                    const { outcome } = await deferredPrompt.userChoice;
                    console.log('[PWA] Install prompt result:', outcome);
                    deferredPrompt = null;
                    installBtn.style.display = 'none';
                }
            });
        }
    }
    
    // Handle standalone mode detection
    if (window.matchMedia('(display-mode: standalone)').matches || 
        window.navigator.standalone === true) {
        document.body.classList.add('pwa-standalone');
        console.log('[PWA] Running in standalone mode');
    }
    
    // Handle online/offline status
    function updateOnlineStatus() {
        const isOnline = navigator.onLine;
        document.body.classList.toggle('offline', !isOnline);
        
        if (!isOnline) {
            const statusEl = document.getElementById('status-dot');
            if (statusEl) statusEl.classList.add('offline');
        }
    }
    
    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);
    updateOnlineStatus();
});
