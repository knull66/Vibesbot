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
}
