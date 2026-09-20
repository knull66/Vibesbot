// ═══════════════════════════════════════════════════════════
// VIBESBOT — Dashboard JavaScript
// ═══════════════════════════════════════════════════════════

class VibesBot {
    constructor() {
        this.ws = null;
        this.isRunning = false;
        this.isPaused = false;
        this.isSimulation = true;
        this.trades = [];
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        
        this.init();
    }

    init() {
        this.cacheDom();
        this.bindEvents();
        this.startClock();
        this.connectWebSocket();
        this.loadVersion();
    }

    cacheDom() {
        // Status
        this.statusDot = document.getElementById('status-dot');
        this.priceEl = document.getElementById('current-price');
        this.timerEl = document.getElementById('round-timer');
        
        // Signal
        this.signalDisplay = document.getElementById('signal-display');
        this.confidenceFill = document.getElementById('confidence-fill');
        this.confidenceValue = document.getElementById('confidence-value');
        this.probUp = document.getElementById('prob-up');
        this.probDown = document.getElementById('prob-down');
        
        // Features
        this.featureRsi = document.getElementById('feature-rsi');
        this.featureMacd = document.getElementById('feature-macd');
        this.featureObi = document.getElementById('feature-obi');
        this.featureVol = document.getElementById('feature-vol');
        
        // Stats
        this.statCapital = document.getElementById('stat-capital');
        this.statPnl = document.getElementById('stat-pnl');
        this.statTrades = document.getElementById('stat-trades');
        this.statWinrate = document.getElementById('stat-winrate');
        this.statWins = document.getElementById('stat-wins');
        this.statLosses = document.getElementById('stat-losses');
        this.statStreak = document.getElementById('stat-streak');
        this.statDrawdown = document.getElementById('stat-drawdown');
        
        // Controls
        this.btnStart = document.getElementById('btn-start');
        this.btnPause = document.getElementById('btn-pause');
        this.btnStop = document.getElementById('btn-stop');
        this.btnSettings = document.getElementById('btn-settings');
        this.modeToggle = document.getElementById('mode-toggle');
        this.modeLabel = document.getElementById('mode-label');
        
        // Modals
        this.settingsModal = document.getElementById('settings-modal');
        this.realModeModal = document.getElementById('real-mode-modal');
        
        // Trade log
        this.tradeLog = document.getElementById('trade-log');
        this.tradeCount = document.getElementById('trade-count');
        
        // Footer
        this.modelStatus = document.getElementById('model-status');
        this.clockEl = document.getElementById('clock');
        this.versionEl = document.getElementById('app-version');
    }

    bindEvents() {
        // Control buttons
        this.btnStart?.addEventListener('click', () => this.start());
        this.btnPause?.addEventListener('click', () => this.pause());
        this.btnStop?.addEventListener('click', () => this.stop());
        
        // Settings
        this.btnSettings?.addEventListener('click', () => this.openSettings());
        document.getElementById('modal-close')?.addEventListener('click', () => this.closeSettings());
        document.querySelector('.modal-backdrop')?.addEventListener('click', () => this.closeSettings());
        
        // Mode toggle
        this.modeToggle?.addEventListener('click', () => this.toggleMode());
        
        // Real mode confirmation
        document.getElementById('btn-cancel-real')?.addEventListener('click', () => this.cancelRealMode());
        document.getElementById('btn-confirm-real')?.addEventListener('click', () => this.confirmRealMode());
        
        // Tabs
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', (e) => this.switchTab(e.target));
        });
        
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', (e) => this.switchSettingsTab(e.target));
        });
        
        // Settings actions
        document.getElementById('btn-test-api')?.addEventListener('click', () => this.testApiConnection());
        document.getElementById('btn-save-binance')?.addEventListener('click', () => this.saveBinanceSettings());
        document.getElementById('btn-save-trading')?.addEventListener('click', () => this.saveTradingSettings());
        document.getElementById('btn-reset-sim')?.addEventListener('click', () => this.resetSimulation());
        document.getElementById('btn-check-update')?.addEventListener('click', () => this.checkUpdates());
        document.getElementById('btn-install-update')?.addEventListener('click', () => this.installUpdate());
    }

    bootSequence() {
        const bootBar = document.querySelector('.boot-bar-fill');
        let progress = 0;
        
        const interval = setInterval(() => {
            progress += Math.random() * 15 + 5;
            if (progress >= 100) {
                progress = 100;
                clearInterval(interval);
                setTimeout(() => {
                    document.body.classList.remove('is-booting');
                }, 300);
            }
            if (bootBar) bootBar.style.width = progress + '%';
        }, 100);
    }

    startClock() {
        const update = () => {
            const now = new Date();
            if (this.clockEl) {
                this.clockEl.textContent = now.toLocaleTimeString('en-US', { hour12: false });
            }
        };
        update();
        setInterval(update, 1000);
    }

    // WebSocket Connection
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('[WS] Connected');
            this.reconnectAttempts = 0;
            this.statusDot?.classList.add('online');
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };
        
        this.ws.onclose = () => {
            console.log('[WS] Disconnected');
            this.statusDot?.classList.remove('online');
            this.scheduleReconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('[WS] Error:', error);
        };
    }

    scheduleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            this.reconnectAttempts++;
            console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
            setTimeout(() => this.connectWebSocket(), delay);
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'market_data':
                this.updateMarketData(data);
                break;
            case 'prediction':
                this.updatePrediction(data);
                break;
            case 'trade':
                this.addTrade(data);
                break;
            case 'stats':
                this.updateStats(data);
                break;
            case 'status':
                this.updateStatus(data);
                break;
            case 'log':
                this.addLog(data);
                break;
        }
    }
    
    addLog(data) {
        // Add log entry to trade log area
        if (!this.tradeLog) return;
        
        const logEntry = document.createElement('div');
        logEntry.className = 'log-item';
        logEntry.style.borderLeftColor = data.level === 'error' ? 'var(--down)' : 
                                         data.level === 'success' ? 'var(--up)' : 
                                         data.level === 'warn' ? 'var(--warn)' : 'var(--accent)';
        
        const time = new Date().toLocaleTimeString('en-US', { hour12: false });
        logEntry.innerHTML = `
            <div class="log-header">
                <span class="log-time">${time}</span>
            </div>
            <div class="log-body">
                <span class="log-details">${data.message}</span>
            </div>
        `;
        
        // Remove "No trades yet" message if present
        const emptyMsg = this.tradeLog.querySelector('.log-empty');
        if (emptyMsg) emptyMsg.remove();
        
        // Add at the top
        this.tradeLog.insertBefore(logEntry, this.tradeLog.firstChild);
        
        // Keep only last 50 entries
        while (this.tradeLog.children.length > 50) {
            this.tradeLog.removeChild(this.tradeLog.lastChild);
        }
        
        // Update count
        if (this.tradeCount) {
            this.tradeCount.textContent = this.tradeLog.children.length;
        }
    }

    updateMarketData(data) {
        if (data.price && this.priceEl) {
            this.priceEl.textContent = '$' + parseFloat(data.price).toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }
        
        if (data.round_timer && this.timerEl) {
            const mins = Math.floor(data.round_timer / 60);
            const secs = data.round_timer % 60;
            this.timerEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
        }
        
        if (data.features) {
            if (this.featureRsi) this.featureRsi.textContent = data.features.rsi?.toFixed(1) || '--';
            if (this.featureMacd) this.featureMacd.textContent = data.features.macd?.toFixed(4) || '--';
            if (this.featureObi) this.featureObi.textContent = data.features.obi?.toFixed(4) || '--';
            if (this.featureVol) this.featureVol.textContent = data.features.volatility?.toFixed(5) || '--';
        }
    }

    updatePrediction(data) {
        const signal = data.signal || 'WAIT';
        const confidence = data.confidence || 0;
        const probUp = data.prob_up || 50;
        const probDown = data.prob_down || 50;
        
        if (this.signalDisplay) {
            this.signalDisplay.className = 'signal-direction ' + signal.toLowerCase();
            
            let arrow = '—';
            if (signal === 'UP') arrow = '▲';
            else if (signal === 'DOWN') arrow = '▼';
            
            this.signalDisplay.querySelector('.signal-arrow').textContent = arrow;
            this.signalDisplay.querySelector('.signal-text').textContent = signal;
        }
        
        if (this.confidenceFill) {
            this.confidenceFill.style.width = confidence + '%';
        }
        if (this.confidenceValue) {
            this.confidenceValue.textContent = confidence.toFixed(1) + '%';
        }
        
        if (this.probUp) this.probUp.textContent = probUp.toFixed(1) + '%';
        if (this.probDown) this.probDown.textContent = probDown.toFixed(1) + '%';
    }

    updateStats(data) {
        if (this.statCapital) this.statCapital.textContent = '$' + (data.capital || 100).toFixed(2);
        if (this.statPnl) {
            const pnl = data.pnl || 0;
            this.statPnl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
            this.statPnl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');
        }
        if (this.statTrades) this.statTrades.textContent = data.trades || 0;
        if (this.statWinrate) this.statWinrate.textContent = (data.winrate || 0).toFixed(1) + '%';
        if (this.statWins) this.statWins.textContent = data.wins || 0;
        if (this.statLosses) this.statLosses.textContent = data.losses || 0;
        if (this.statStreak) this.statStreak.textContent = data.streak || 0;
        if (this.statDrawdown) this.statDrawdown.textContent = (data.max_drawdown || 0).toFixed(1) + '%';
    }

    updateStatus(data) {
        if (data.model_loaded !== undefined && this.modelStatus) {
            this.modelStatus.textContent = data.model_loaded ? 'Loaded' : 'Not loaded';
        }
        
        if (data.running !== undefined) {
            this.isRunning = data.running;
            this.updateControlState();
        }
    }

    addTrade(data) {
        this.trades.unshift(data);
        if (this.trades.length > 50) this.trades.pop();
        this.renderTrades();
    }

    renderTrades() {
        if (!this.tradeLog) return;
        
        if (this.trades.length === 0) {
            this.tradeLog.innerHTML = `
                <div class="log-empty">
                    No trades yet<br>
                    <small>Start the bot to begin</small>
                </div>
            `;
            if (this.tradeCount) this.tradeCount.textContent = '0';
            return;
        }
        
        if (this.tradeCount) this.tradeCount.textContent = this.trades.length;
        
        this.tradeLog.innerHTML = this.trades.map(trade => {
            const isWin = trade.pnl >= 0;
            const time = new Date(trade.timestamp).toLocaleTimeString('en-US', { hour12: false });
            
            return `
                <div class="log-item ${isWin ? 'win' : 'loss'}">
                    <div class="log-header">
                        <span class="log-time">${time}</span>
                        <span class="log-tag ${trade.direction?.toLowerCase()}">${trade.direction}</span>
                    </div>
                    <div class="log-body">
                        <span class="log-details">@$${parseFloat(trade.entry_price).toLocaleString()}</span>
                        <span class="log-pnl ${isWin ? 'positive' : 'negative'}">
                            ${isWin ? '+' : ''}$${trade.pnl.toFixed(2)}
                        </span>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Control actions
    start() {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: 'start', simulation: this.isSimulation }));
            this.isRunning = true;
            this.isPaused = false;
            this.updateControlState();
        }
    }

    pause() {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: 'pause' }));
            this.isPaused = !this.isPaused;
            this.updateControlState();
        }
    }

    stop() {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: 'stop' }));
            this.isRunning = false;
            this.isPaused = false;
            this.updateControlState();
        }
    }

    updateControlState() {
        if (this.btnStart) {
            this.btnStart.disabled = this.isRunning;
        }
        if (this.btnPause) {
            this.btnPause.disabled = !this.isRunning;
            this.btnPause.textContent = this.isPaused ? '▶ RESUME' : '⏸ PAUSE';
        }
        if (this.btnStop) {
            this.btnStop.disabled = !this.isRunning;
        }
    }

    // Mode toggle
    toggleMode() {
        if (this.isSimulation) {
            this.realModeModal?.classList.add('active');
        } else {
            this.setMode(true);
        }
    }

    cancelRealMode() {
        this.realModeModal?.classList.remove('active');
    }

    confirmRealMode() {
        this.realModeModal?.classList.remove('active');
        this.setMode(false);
    }

    setMode(simulation) {
        this.isSimulation = simulation;
        
        if (this.modeToggle) {
            this.modeToggle.classList.toggle('simulation', simulation);
        }
        if (this.modeLabel) {
            this.modeLabel.textContent = simulation ? 'SIM' : 'REAL';
            this.modeLabel.className = 'mode-indicator ' + (simulation ? 'sim' : 'real');
        }
        
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: 'set_mode', simulation }));
        }
    }

    // Tabs
    switchTab(tab) {
        const tabId = tab.dataset.tab;
        
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        
        tab.classList.add('active');
        document.getElementById('tab-' + tabId)?.classList.add('active');
    }

    switchSettingsTab(tab) {
        const panelId = tab.dataset.panel;
        
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
        
        tab.classList.add('active');
        document.getElementById('panel-' + panelId)?.classList.add('active');
    }

    // Settings modal
    openSettings() {
        this.settingsModal?.classList.add('active');
        this.loadSettings();
    }

    closeSettings() {
        this.settingsModal?.classList.remove('active');
    }

    async loadSettings() {
        try {
            const resp = await fetch('/api/settings');
            if (resp.ok) {
                const data = await resp.json();
                
                // Binance
                document.getElementById('api-key').value = data.binance?.api_key || '';
                document.getElementById('api-secret').value = data.binance?.api_secret || '';
                document.getElementById('use-testnet').checked = data.binance?.use_testnet !== false;
                
                // Trading
                document.getElementById('bet-amount').value = data.trading?.bet_amount || 1;
                document.getElementById('confidence-threshold').value = data.trading?.confidence_threshold || 62;
                document.getElementById('daily-loss-limit').value = data.trading?.daily_loss_limit || 20;
                document.getElementById('max-consec-loss').value = data.trading?.max_consecutive_losses || 5;
                document.getElementById('sizing-method').value = data.trading?.sizing_method || 'fixed';
                
                // Simulation
                if (data.simulation) {
                    document.getElementById('sim-balance').textContent = '$' + (data.simulation.balance || 100).toFixed(2);
                    document.getElementById('sim-pnl').textContent = '$' + (data.simulation.total_pnl || 0).toFixed(2);
                    document.getElementById('sim-trades').textContent = data.simulation.total_trades || 0;
                    document.getElementById('sim-winrate').textContent = (data.simulation.win_rate || 0).toFixed(1) + '%';
                }
            }
        } catch (e) {
            console.error('Failed to load settings:', e);
        }
    }

    async testApiConnection() {
        const statusEl = document.getElementById('api-status');
        statusEl.className = 'connection-status';
        statusEl.textContent = 'Testing...';
        statusEl.style.display = 'block';
        
        try {
            const resp = await fetch('/api/settings/binance/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    api_key: document.getElementById('api-key').value,
                    api_secret: document.getElementById('api-secret').value,
                    use_testnet: document.getElementById('use-testnet').checked
                })
            });
            
            const data = await resp.json();
            
            if (data.success) {
                statusEl.className = 'connection-status success';
                statusEl.textContent = '✓ Connected! Balance: ' + (data.balance || 'OK');
            } else {
                statusEl.className = 'connection-status error';
                statusEl.textContent = '✗ ' + (data.error || 'Connection failed');
            }
        } catch (e) {
            statusEl.className = 'connection-status error';
            statusEl.textContent = '✗ Network error';
        }
    }

    async saveBinanceSettings() {
        try {
            await fetch('/api/settings/binance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    api_key: document.getElementById('api-key').value,
                    api_secret: document.getElementById('api-secret').value,
                    use_testnet: document.getElementById('use-testnet').checked
                })
            });
        } catch (e) {
            console.error('Failed to save:', e);
        }
    }

    async saveTradingSettings() {
        try {
            await fetch('/api/settings/trading', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    bet_amount: parseFloat(document.getElementById('bet-amount').value),
                    confidence_threshold: parseInt(document.getElementById('confidence-threshold').value),
                    daily_loss_limit: parseFloat(document.getElementById('daily-loss-limit').value),
                    max_consecutive_losses: parseInt(document.getElementById('max-consec-loss').value),
                    sizing_method: document.getElementById('sizing-method').value
                })
            });
        } catch (e) {
            console.error('Failed to save:', e);
        }
    }

    async resetSimulation() {
        if (!confirm('Reset simulation? All trades will be cleared.')) return;
        
        try {
            const resp = await fetch('/api/simulation/reset', { method: 'POST' });
            if (resp.ok) {
                this.trades = [];
                this.renderTrades();
                this.loadSettings();
            }
        } catch (e) {
            console.error('Failed to reset:', e);
        }
    }

    async loadVersion() {
        try {
            const resp = await fetch('/api/version');
            if (resp.ok) {
                const data = await resp.json();
                if (this.versionEl) this.versionEl.textContent = 'v' + data.version;
                document.getElementById('current-version').textContent = 'v' + data.version;
            }
        } catch (e) {}
    }

    async checkUpdates() {
        const statusEl = document.getElementById('update-status');
        const latestEl = document.getElementById('latest-version');
        const installBtn = document.getElementById('btn-install-update');
        
        statusEl.textContent = 'Checking...';
        statusEl.className = 'update-status';
        
        try {
            const resp = await fetch('/api/updates/check');
            const data = await resp.json();
            
            if (data.update_available) {
                latestEl.textContent = 'v' + data.latest_version;
                statusEl.textContent = 'Update available!';
                statusEl.className = 'update-status available';
                installBtn.disabled = false;
            } else {
                latestEl.textContent = 'v' + data.current_version;
                statusEl.textContent = 'You are up to date';
                statusEl.className = 'update-status';
                installBtn.disabled = true;
            }
        } catch (e) {
            statusEl.textContent = 'Failed to check updates';
            statusEl.className = 'update-status error';
        }
    }

    async installUpdate() {
        const statusEl = document.getElementById('update-status');
        statusEl.textContent = 'Downloading and installing...';
        
        try {
            const resp = await fetch('/api/updates/install', { method: 'POST' });
            const data = await resp.json();
            
            if (data.success) {
                statusEl.textContent = 'Update installed! Restarting...';
                statusEl.className = 'update-status available';
                setTimeout(() => window.location.reload(), 2000);
            } else {
                statusEl.textContent = 'Update failed: ' + (data.error || 'Unknown error');
                statusEl.className = 'update-status error';
            }
        } catch (e) {
            statusEl.textContent = 'Update failed';
            statusEl.className = 'update-status error';
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.vibesbot = new VibesBot();
});
