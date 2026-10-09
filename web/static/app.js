/**
 * VIBESBOT - Trading Dashboard
 */

const APP_VERSION = '1.52.0';
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
        this.priceToBeat = null;
        this.priceToBeatTopic = '';
        this.sessionId = this.getSessionId();
        this.user = null;
        
        this.init();
    }
    
    init() {
        this.cacheElements();
        this.loadSoundPrefs();
        this.bindEvents();
        this.lockBrowserChrome();
        this.bindSettingsChrome();
        this.startClock();
        this.loadVersion();
        this.requireAccount();
        window.__vbOpenSettings = (panel) => this.openSettings(panel);
    }
    
    cacheElements() {
        // Status
        this.statusDot = document.getElementById('status-dot');
        this.currentPrice = document.getElementById('current-price');
        this.roundTimer = document.getElementById('round-timer');
        this.roundRing = document.getElementById('round-ring');
        this.sessionTimerEl = document.getElementById('session-timer');
        this.sessionElapsed = 0;
        this.sessionClockRunning = false;
        this.sessionClockAt = Date.now();
        
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
        document.getElementById('btn-save-trading')?.addEventListener('click', () => this.saveTradingSettings({withStrategy: true}));
        this.bindStakeInputs();
        document.getElementById('btn-save-binance')?.addEventListener('click', () => this.saveBinanceSettings());
        document.getElementById('btn-test-api')?.addEventListener('click', () => this.testApi());
        document.getElementById('btn-reset-sim')?.addEventListener('click', () => this.resetStats('sim'));
        document.getElementById('btn-reset-real')?.addEventListener('click', () => this.resetStats('real'));
        document.getElementById('btn-clear-feed')?.addEventListener('click', () => this.clearFeed());
        document.getElementById('btn-check-update')?.addEventListener('click', () => this.checkUpdates({prompt: false, manual: true}));
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
                if (label) label.textConte