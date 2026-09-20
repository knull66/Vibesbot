/**
 * VIBESBOT - Trading Dashboard
 * Arcade-style trading interface
 */

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
        this.audioCtx = null;
        this.entryPrice = null;
        
        this.init();
    }
    
    init() {
        this.cacheElements();
        this.bindEvents();
        this.connect();
        this.startClock();
        this.loadVersion();
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
        
        // Price target
        this.entryPriceEl = document.getElementById('entry-price');
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
    
    bindEvents() {
        // Control buttons
        this.btnStart?.addEventListener('click', () => this.start());
        this.btnPause?.addEventListener('click', () => this.pause());
        this.btnStop?.addEventListener('click', () => this.stop());
        
        // Mode toggle
        this.modeToggle?.addEventListener('click', () => this.toggleMode());
        
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
        document.getElementById('btn-check-update')?.addEventListener('click', () => this.checkUpdates());
        document.getElementById('btn-install-update')?.addEventListener('click', () => this.installUpdate());
        
        // Real mode confirmation
        document.getElementById('btn-cancel-real')?.addEventListener('click', () => {
            document.getElementById('real-mode-modal')?.classList.remove('active');
        });
        
        document.getElementById('btn-confirm-real')?.addEventListener('click', () => {
            this.confirmRealMode();
        });
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
            this.addLog('🔗 Connected to server', 'info');
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (e) {
                console.error('Parse error:', e);
            }
        };
        
        this.ws.onclose = () => {
            console.log('Disconnected');
            this.statusDot?.classList.remove('connected');
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
            case 'trade':
                this.addTrade(data);
                break;
            case 'log':
                this.addLog(data.message, data.level || 'info');
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
        if (data.timer && this.roundTimer) {
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
        
        // Draw charts
        this.drawMiniChart();
        this.drawPriceChart();
    }
    
    updatePriceDiff(currentPrice) {
        if (!this.entryPrice || !this.priceDiff) return;
        
        const diff = currentPrice - this.entryPrice;
        const pct = (diff / this.entryPrice) * 100;
        
        this.priceDiff.innerHTML = `<span>${diff >= 0 ? '+' : ''}$${diff.toFixed(2)}</span>`;
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
        
        // Probabilities
        if (this.probUp) this.probUp.textContent = ((data.prob_up || 0.5) * 100).toFixed(1) + '%';
        if (this.probDown) this.probDown.textContent = ((data.prob_down || 0.5) * 100).toFixed(1) + '%';
        
        // Entry price for new prediction
        if (data.entry_price) {
            this.entryPrice = parseFloat(data.entry_price);
            if (this.entryPriceEl) {
                this.entryPriceEl.textContent = '$' + this.entryPrice.toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
        }
    }
    
    updateStats(data) {
        // Main stats
        if (this.statCapital) this.statCapital.textContent = '$' + (data.capital || 100).toFixed(2);
        
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
        if (this.tradeHistory.length > 50) this.tradeHistory.pop();
        
        // Update history tab
        this.renderHistory();
        
        // Play sound
        if (data.result === 'WIN') {
            this.playSound('win');
        } else if (data.result === 'LOSS') {
            this.playSound('loss');
        }
        
        // Clear entry price after trade closes
        this.entryPrice = null;
        if (this.entryPriceEl) this.entryPriceEl.textContent = '$--';
        if (this.priceDiff) {
            this.priceDiff.innerHTML = '<span>--</span>';
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
    
    renderHistory() {
        const list = document.getElementById('history-list');
        const count = document.getElementById('history-count');
        if (!list) return;
        
        if (count) count.textContent = this.tradeHistory.length + ' trades';
        
        if (this.tradeHistory.length === 0) {
            list.innerHTML = '<div class="history-empty">No trades yet</div>';
            return;
        }
        
        list.innerHTML = this.tradeHistory.slice(0, 20).map(trade => `
            <div class="history-item ${trade.result?.toLowerCase() || ''}">
                <div class="history-direction ${trade.direction?.toLowerCase() || ''}">${trade.direction || '?'}</div>
                <div class="history-details">
                    <div>${new Date(trade.timestamp || Date.now()).toLocaleTimeString()}</div>
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
        ctx.fillStyle = '#0a0e14';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw line
        const lastPrice = prices[prices.length - 1];
        const firstPrice = prices[0];
        const color = lastPrice >= firstPrice ? '#00FF88' : '#FF3366';
        
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
        ctx.fillStyle = lastPrice >= firstPrice ? 'rgba(0, 255, 136, 0.1)' : 'rgba(255, 51, 102, 0.1)';
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
        ctx.fillStyle = '#0a0e14';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Grid
        ctx.strokeStyle = '#21262d';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= 4; i++) {
            const y = (i / 4) * canvas.height;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(canvas.width, y);
            ctx.stroke();
            
            // Price label
            const price = max - (i / 4) * range;
            ctx.fillStyle = '#484F58';
            ctx.font = '9px JetBrains Mono';
            ctx.fillText('$' + price.toFixed(2), 5, y + 12);
        }
        
        // Price line
        const lastPrice = prices[prices.length - 1];
        const firstPrice = prices[0];
        const color = lastPrice >= firstPrice ? '#00FF88' : '#FF3366';
        
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
            gradient.addColorStop(0, 'rgba(0, 255, 136, 0.3)');
            gradient.addColorStop(1, 'rgba(0, 255, 136, 0)');
        } else {
            gradient.addColorStop(0, 'rgba(255, 51, 102, 0.3)');
            gradient.addColorStop(1, 'rgba(255, 51, 102, 0)');
        }
        ctx.fillStyle = gradient;
        ctx.fill();
        
        // Current price dot
        const lastY = canvas.height - ((lastPrice - min) / range) * canvas.height;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(canvas.width - 5, lastY, 4, 0, Math.PI * 2);
        ctx.fill();
        
        // Entry price line if active
        if (this.entryPrice && this.entryPrice >= min && this.entryPrice <= max) {
            const entryY = canvas.height - ((this.entryPrice - min) / range) * canvas.height;
            ctx.strokeStyle = '#FFB800';
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(0, entryY);
            ctx.lineTo(canvas.width, entryY);
            ctx.stroke();
            ctx.setLineDash([]);
            
            ctx.fillStyle = '#FFB800';
            ctx.font = '9px JetBrains Mono';
            ctx.fillText('ENTRY $' + this.entryPrice.toFixed(2), canvas.width - 100, entryY - 5);
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
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // $100 reference line
        const y100 = canvas.height - ((100 - min) / range) * canvas.height;
        ctx.strokeStyle = '#21262d';
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(0, y100);
        ctx.lineTo(canvas.width, y100);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Equity line
        const lastVal = equityData[equityData.length - 1];
        const color = lastVal >= 100 ? '#00FFFF' : '#FF3366';
        
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
        ctx.font = 'bold 11px JetBrains Mono';
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
            this.btnPause.textContent = this.isPaused ? '▶ RESUME' : '⏸ PAUSE';
        }
    }
    
    updateBotStatus(data) {
        this.isRunning = data.running || false;
        this.isPaused = data.paused || false;
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
    
    setMode(simulation) {
        this.isSimulation = simulation;
        this.send({ action: 'set_mode', simulation: simulation });
        
        if (this.modeToggle) {
            this.modeToggle.classList.toggle('real', !simulation);
        }
        if (this.modeLabel) {
            this.modeLabel.textContent = simulation ? 'SIM' : 'REAL';
            this.modeLabel.className = 'mode-indicator ' + (simulation ? 'sim' : 'real');
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // Settings
    // ═══════════════════════════════════════════════════════════
    
    async saveTradingSettings() {
        const settings = {
            bet_amount: parseFloat(document.getElementById('bet-amount')?.value || 1),
            confidence_threshold: parseFloat(document.getElementById('confidence-threshold')?.value || 55) / 100,
            daily_loss_limit: parseFloat(document.getElementById('daily-loss-limit')?.value || 20)
        };
        
        try {
            const response = await fetch('/api/settings/trading', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            
            if (response.ok) {
                this.addLog('✓ Trading settings saved', 'info');
            }
        } catch (e) {
            this.addLog('✗ Error saving settings', 'loss');
        }
    }
    
    async saveBinanceSettings() {
        const settings = {
            api_key: document.getElementById('api-key')?.value || '',
            api_secret: document.getElementById('api-secret')?.value || '',
            testnet: document.getElementById('use-testnet')?.checked || false
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
                    testnet: document.getElementById('use-testnet')?.checked || false
                })
            });
            
            const data = await response.json();
            
            if (statusEl) {
                statusEl.textContent = data.success ? '✓ Connected' : '✗ ' + (data.error || 'Failed');
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
            await fetch('/api/simulation/reset', { method: 'POST' });
            this.addLog('✓ Simulation reset', 'info');
        } catch (e) {
            this.addLog('✗ Error resetting', 'loss');
        }
    }
    
    async checkUpdates() {
        const statusEl = document.getElementById('update-status');
        const latestEl = document.getElementById('latest-version');
        const installBtn = document.getElementById('btn-install-update');
        
        if (statusEl) statusEl.textContent = 'Checking...';
        
        try {
            const response = await fetch('/api/updates/check');
            const data = await response.json();
            
            if (latestEl) latestEl.textContent = 'v' + data.latest_version;
            
            if (data.available) {
                if (statusEl) statusEl.textContent = 'Update available!';
                if (installBtn) installBtn.disabled = false;
            } else {
                if (statusEl) statusEl.textContent = 'You have the latest version';
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error checking updates';
        }
    }
    
    async installUpdate() {
        const statusEl = document.getElementById('update-status');
        if (statusEl) statusEl.textContent = 'Installing...';
        
        try {
            const response = await fetch('/api/updates/install', { method: 'POST' });
            const data = await response.json();
            
            if (data.success) {
                if (statusEl) statusEl.textContent = 'Updated! Restart the app.';
            } else {
                if (statusEl) statusEl.textContent = 'Update failed: ' + data.message;
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Error installing update';
        }
    }
    
    async loadVersion() {
        try {
            const response = await fetch('/api/version');
            const data = await response.json();
            
            const versionEl = document.getElementById('app-version');
            const currentEl = document.getElementById('current-version');
            
            if (versionEl) versionEl.textContent = 'v' + data.version;
            if (currentEl) currentEl.textContent = 'v' + data.version;
        } catch (e) {
            console.error('Error loading version');
        }
    }
    
    // ═══════════════════════════════════════════════════════════
    // Audio
    // ═══════════════════════════════════════════════════════════
    
    playSound(type) {
        if (!this.soundEnabled) return;
        
        try {
            if (!this.audioCtx) {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            
            const oscillator = this.audioCtx.createOscillator();
            const gainNode = this.audioCtx.createGain();
            
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
            
            gainNode.gain.setValueAtTime(0.1, this.audioCtx.currentTime);
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
});
