/**
 * VIBESBOT - Trading Dashboard
 */

const APP_VERSION = '1.50.0';
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
        this.statusDot = document.getElementById('status-dot');
        this.currentPrice = document.getElementById('current-price');
        this.roundTimer = document.getElementById('round-timer');
        this.roundRing = document.getElementById('round-ring');
        this.sessionTimerEl = document.getElementById('session-timer');
        this.sessionElapsed = 0;
        this.sessionClockRunning = false;
        this.sessionClockAt = Date.now();
        this.signalDisplay = document.getElementById('signal-display');
        this.confidenceFill = document.getElementById('confidence-fill');
        this.confidenceValue = document.getElementById('confidence-value');
        this.probUp = document.getElementById('prob-up');
        this.probDown = document.getElementById('prob-down');
        this.priceToBeatEl = document.getElementById('price-to-beat');
        this.livePriceEl = document.getElementById('live-price');
        this.priceDiff = document.getElementById('price-diff');
        this.featureRsi = document.getElementById('feature-rsi');
        this.featureMacd = document.getElementById('feature-macd');
        this.featureBb = document.getElementById('feature-bb');
        this.featureMom = document.getElementById('feature-mom');
        this.rsiBar = document.getElementById('rsi-bar');
        this.statCapital = document.getElementById('stat-capital');
        this.statPnl = document.getElementById('stat-pnl');
        this.statTrades = document.getElementById('stat-trades');
        this.statWinrate = document.getElementById('stat-winrate');
        this.statWins = document.getElementById('stat-wins');
        this.statLosses = document.getElementById('stat-losses');
        this.winrateFill = document.getElementById('winrate-fill');
        this.btnStart = document.getElementById('btn-start');
        this.btnPause = document.getElementById('btn-pause');
        this.btnStop = document.getElementById('btn-stop');
        this.modeToggle = document.getElementById('mode-toggle');
        this.modeLabel = document.getElementById('mode-label');
        this.tradeLog = document.getElementById('trade-log');
        this.tradeCount = document.getElementById('trade-count');
        this.activeTrade = document.getElementById('active-trade');
    }
}
