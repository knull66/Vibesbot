/* ═══════════════════════════════════════════════════════════
   VIBESBOT — Dashboard Frontend
   ═══════════════════════════════════════════════════════════ */

class VibesbotDashboard {
  constructor() {
    this.ws = null;
    this.chart = null;
    this.chartData = { pnl: [], winRate: [], labels: [] };
    this.isRunning = false;
    this.isPaused = false;
    
    this.init();
  }

  init() {
    this.bootSequence();
    this.setupEventListeners();
    this.setupTabs();
    this.initChart();
    this.updateClock();
    setInterval(() => this.updateClock(), 1000);
  }

  // ═══════════════════════════════════════════════════════════
  // BOOT SEQUENCE
  // ═══════════════════════════════════════════════════════════

  bootSequence() {
    const bootFill = document.getElementById('boot-fill');
    let progress = 0;
    
    const bootInterval = setInterval(() => {
      progress += Math.random() * 15;
      if (progress >= 100) {
        progress = 100;
        clearInterval(bootInterval);
        setTimeout(() => {
          document.body.classList.remove('is-booting');
          this.connectWebSocket();
        }, 500);
      }
      bootFill.style.width = `${progress}%`;
    }, 150);
  }

  // ═══════════════════════════════════════════════════════════
  // WEBSOCKET
  // ═══════════════════════════════════════════════════════════

  connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.updateConnectionStatus(true);
      this.enableControls();
    };
    
    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      this.updateConnectionStatus(false);
      this.disableControls();
      setTimeout(() => this.connectWebSocket(), 3000);
    };
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };
  }

  handleMessage(data) {
    switch (data.type) {
      case 'price':
        this.updatePrice(data);
        break;
      case 'prediction':
        this.updatePrediction(data);
        break;
      case 'trade':
        this.addTradeLog(data);
        break;
      case 'stats':
        this.updateStats(data);
        break;
      case 'risk':
        this.updateRisk(data);
        break;
      case 'timer':
        this.updateTimer(data);
        break;
      case 'features':
        this.updateFeatures(data);
        break;
      case 'status':
        this.updateBotStatus(data);
        break;
      default:
        console.log('Unknown message type:', data.type);
    }
  }

  sendCommand(command) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ command }));
    }
  }

  // ═══════════════════════════════════════════════════════════
  // UI UPDATES
  // ═══════════════════════════════════════════════════════════

  updateConnectionStatus(online) {
    const status = document.getElementById('connection-status');
    const dot = status.querySelector('.status-dot');
    const text = status.querySelector('span:last-child');
    
    if (online) {
      dot.classList.remove('offline');
      dot.classList.add('online');
      text.textContent = 'LIVE';
      document.getElementById('data-status').textContent = 'Connected';
    } else {
      dot.classList.remove('online');
      dot.classList.add('offline');
      text.textContent = 'OFFLINE';
      document.getElementById('data-status').textContent = 'Disconnected';
    }
  }

  updatePrice(data) {
    const priceEl = document.getElementById('current-price');
    priceEl.textContent = `$${data.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  }

  updatePrediction(data) {
    const direction = document.getElementById('signal-direction');
    const arrow = direction.querySelector('.signal-arrow');
    const text = direction.querySelector('.signal-text');
    const confidenceFill = document.getElementById('confidence-fill');
    const confidenceValue = document.getElementById('confidence-value');
    const probUp = document.getElementById('prob-up');
    const probDown = document.getElementById('prob-down');
    
    direction.className = 'signal-direction';
    
    if (data.signal === 'UP') {
      direction.classList.add('up');
      arrow.textContent = '↑';
      text.textContent = 'UP';
    } else if (data.signal === 'DOWN') {
      direction.classList.add('down');
      arrow.textContent = '↓';
      text.textContent = 'DOWN';
    } else {
      arrow.textContent = '—';
      text.textContent = 'WAITING';
    }
    
    const confidence = data.confidence * 100;
    confidenceFill.style.width = `${confidence}%`;
    confidenceValue.textContent = `${confidence.toFixed(1)}%`;
    
    probUp.textContent = `${(data.prob_up * 100).toFixed(1)}%`;
    probDown.textContent = `${(data.prob_down * 100).toFixed(1)}%`;
  }

  updateTimer(data) {
    const timer = document.getElementById('round-timer');
    const minutes = Math.floor(data.seconds / 60);
    const seconds = data.seconds % 60;
    timer.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    
    if (data.seconds <= 15) {
      timer.style.color = 'var(--down)';
    } else if (data.seconds <= 60) {
      timer.style.color = 'var(--warn)';
    } else {
      timer.style.color = 'var(--warn)';
    }
  }

  updateFeatures(data) {
    document.getElementById('feat-rsi').textContent = data.rsi?.toFixed(1) || '--';
    document.getElementById('feat-macd').textContent = data.macd?.toFixed(4) || '--';
    document.getElementById('feat-obi').textContent = data.obi?.toFixed(3) || '--';
    document.getElementById('feat-vol').textContent = data.volatility?.toFixed(4) || '--';
  }

  updateStats(data) {
    document.getElementById('stat-capital').textContent = `$${data.capital.toFixed(2)}`;
    
    const pnlEl = document.getElementById('stat-pnl');
    pnlEl.textContent = `$${data.daily_pnl >= 0 ? '+' : ''}${data.daily_pnl.toFixed(2)}`;
    pnlEl.className = 'stat-card-value ' + (data.daily_pnl >= 0 ? 'highlight' : '');
    pnlEl.style.color = data.daily_pnl >= 0 ? 'var(--up)' : 'var(--down)';
    
    document.getElementById('stat-trades').textContent = data.trades;
    document.getElementById('stat-winrate').textContent = `${(data.win_rate * 100).toFixed(1)}%`;
    document.getElementById('stat-wins').textContent = data.wins;
    document.getElementById('stat-losses').textContent = data.losses;
    document.getElementById('stat-streak').textContent = data.streak;
    document.getElementById('stat-drawdown').textContent = `${(data.drawdown * 100).toFixed(1)}%`;
    
    this.updateChart(data);
  }

  updateRisk(data) {
    const status = document.getElementById('risk-status');
    const icon = status.querySelector('.risk-icon');
    const text = status.querySelector('.risk-text');
    
    status.className = 'risk-status';
    
    if (data.status === 'OK') {
      icon.textContent = '✓';
      text.textContent = 'ALL SYSTEMS NORMAL';
    } else if (data.status === 'WARNING') {
      status.classList.add('warning');
      icon.textContent = '⚠';
      text.textContent = data.message || 'WARNING';
    } else {
      status.classList.add('danger');
      icon.textContent = '✕';
      text.textContent = data.message || 'CIRCUIT BREAKER ACTIVE';
    }
    
    const dailyMeter = document.getElementById('meter-daily');
    const dailyVal = document.getElementById('meter-daily-val');
    dailyMeter.style.width = `${(data.daily_loss_pct || 0) * 100}%`;
    dailyVal.textContent = `$${Math.abs(data.daily_loss || 0).toFixed(0)} / $${data.max_daily_loss || 20}`;
    
    const tradesMeter = document.getElementById('meter-trades');
    const tradesVal = document.getElementById('meter-trades-val');
    tradesMeter.style.width = `${((data.trades_today || 0) / (data.max_trades || 100)) * 100}%`;
    tradesVal.textContent = `${data.trades_today || 0} / ${data.max_trades || 100}`;
    
    const lossesMeter = document.getElementById('meter-losses');
    const lossesVal = document.getElementById('meter-losses-val');
    lossesMeter.style.width = `${((data.consecutive_losses || 0) / (data.circuit_breaker || 5)) * 100}%`;
    lossesVal.textContent = `${data.consecutive_losses || 0} / ${data.circuit_breaker || 5}`;
  }

  addTradeLog(data) {
    const logList = document.getElementById('log-list');
    const logCount = document.getElementById('log-count');
    
    const empty = logList.querySelector('.log-empty');
    if (empty) empty.remove();
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${data.result.toLowerCase()}`;
    
    const time = new Date().toLocaleTimeString();
    const pnlClass = data.pnl >= 0 ? 'positive' : 'negative';
    const pnlSign = data.pnl >= 0 ? '+' : '';
    
    entry.innerHTML = `
      <div class="log-header">
        <span class="log-time">${time}</span>
        <span class="log-tag ${data.direction.toLowerCase()}">${data.direction}</span>
      </div>
      <div class="log-body">
        <span class="log-details">$${data.amount.toFixed(2)} @ ${data.confidence.toFixed(0)}%</span>
        <span class="log-pnl ${pnlClass}">${pnlSign}$${data.pnl.toFixed(2)}</span>
      </div>
    `;
    
    logList.insertBefore(entry, logList.firstChild);
    
    const count = logList.querySelectorAll('.log-entry').length;
    logCount.textContent = count;
    
    if (count > 50) {
      logList.removeChild(logList.lastChild);
    }
  }

  updateBotStatus(data) {
    this.isRunning = data.running;
    this.isPaused = data.paused;
    
    const btnStart = document.getElementById('btn-start');
    const btnPause = document.getElementById('btn-pause');
    const btnStop = document.getElementById('btn-stop');
    
    if (this.isRunning) {
      btnStart.disabled = true;
      btnPause.disabled = false;
      btnStop.disabled = false;
      btnPause.textContent = this.isPaused ? '▶ RESUME' : '⏸ PAUSE';
    } else {
      btnStart.disabled = false;
      btnPause.disabled = true;
      btnStop.disabled = true;
    }
    
    document.getElementById('model-status').textContent = data.model_loaded ? 'Loaded' : 'Not loaded';
  }

  // ═══════════════════════════════════════════════════════════
  // CHART
  // ═══════════════════════════════════════════════════════════

  initChart() {
    const ctx = document.getElementById('pnl-chart').getContext('2d');
    
    this.chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Cumulative P&L',
            data: [],
            borderColor: '#00ff88',
            backgroundColor: 'rgba(0, 255, 136, 0.1)',
            fill: true,
            tension: 0.4,
            pointRadius: 0,
          },
          {
            label: 'Win Rate %',
            data: [],
            borderColor: '#00aaff',
            backgroundColor: 'transparent',
            borderDash: [5, 5],
            tension: 0.4,
            pointRadius: 0,
            yAxisID: 'y1',
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          intersect: false,
          mode: 'index',
        },
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            display: true,
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#555570', maxTicksLimit: 10 }
          },
          y: {
            display: true,
            position: 'left',
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { 
              color: '#00ff88',
              callback: (value) => `$${value}`
            }
          },
          y1: {
            display: true,
            position: 'right',
            min: 0,
            max: 100,
            grid: { display: false },
            ticks: { 
              color: '#00aaff',
              callback: (value) => `${value}%`
            }
          }
        }
      }
    });
  }

  updateChart(data) {
    const time = new Date().toLocaleTimeString();
    
    this.chartData.labels.push(time);
    this.chartData.pnl.push(data.daily_pnl);
    this.chartData.winRate.push(data.win_rate * 100);
    
    if (this.chartData.labels.length > 100) {
      this.chartData.labels.shift();
      this.chartData.pnl.shift();
      this.chartData.winRate.shift();
    }
    
    this.chart.data.labels = this.chartData.labels;
    this.chart.data.datasets[0].data = this.chartData.pnl;
    this.chart.data.datasets[1].data = this.chartData.winRate;
    this.chart.update('none');
  }

  // ═══════════════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════════════

  setupEventListeners() {
    document.getElementById('btn-start').addEventListener('click', () => {
      this.sendCommand('start');
    });
    
    document.getElementById('btn-pause').addEventListener('click', () => {
      this.sendCommand(this.isPaused ? 'resume' : 'pause');
    });
    
    document.getElementById('btn-stop').addEventListener('click', () => {
      this.sendCommand('stop');
    });
    
    // Settings button
    const btnSettings = document.getElementById('btn-settings');
    if (btnSettings) {
      btnSettings.addEventListener('click', () => {
        console.log('Settings button clicked');
        this.openSettings();
      });
    } else {
      console.error('Settings button not found');
    }
    
    const settingsClose = document.getElementById('settings-close');
    if (settingsClose) {
      settingsClose.addEventListener('click', () => {
        this.closeSettings();
      });
    }
    
    const modalBackdrop = document.querySelector('.modal-backdrop');
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', () => {
        this.closeSettings();
      });
    }
    
    // Settings tabs
    document.querySelectorAll('.settings-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`panel-${tabId}`).classList.add('active');
      });
    });
    
    // Binance settings
    document.getElementById('btn-test-binance').addEventListener('click', () => this.testBinanceConnection());
    document.getElementById('btn-save-binance').addEventListener('click', () => this.saveBinanceSettings());
    
    // Trading settings
    document.getElementById('btn-save-trading').addEventListener('click', () => this.saveTradingSettings());
    document.getElementById('trading-confidence').addEventListener('input', (e) => {
      document.getElementById('confidence-value').textContent = `${e.target.value}%`;
    });
    
    // Simulation
    document.getElementById('btn-reset-simulation').addEventListener('click', () => this.resetSimulation());
    
    // Mode toggle
    const modeToggle = document.getElementById('mode-toggle');
    if (modeToggle) {
      modeToggle.addEventListener('click', () => this.toggleMode());
    }
    
    // Updates
    document.getElementById('btn-check-updates').addEventListener('click', () => this.checkForUpdates());
    document.getElementById('btn-install-update').addEventListener('click', () => this.installUpdate());
  }

  setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        document.querySelectorAll('.tab-content').forEach(content => {
          content.classList.remove('active');
        });
        document.getElementById(`tab-${tabId}`).classList.add('active');
      });
    });
  }

  enableControls() {
    document.getElementById('btn-start').disabled = false;
  }

  disableControls() {
    document.getElementById('btn-start').disabled = true;
    document.getElementById('btn-pause').disabled = true;
    document.getElementById('btn-stop').disabled = true;
  }

  updateClock() {
    const clock = document.getElementById('footer-time');
    clock.textContent = new Date().toLocaleTimeString();
  }

  // ═══════════════════════════════════════════════════════════
  // SETTINGS
  // ═══════════════════════════════════════════════════════════

  openSettings() {
    console.log('Opening settings...');
    const modal = document.getElementById('settings-modal');
    if (modal) {
      modal.classList.add('active');
      this.loadSettings();
    } else {
      console.error('Settings modal not found!');
      alert('Error: Panel de configuración no encontrado');
    }
  }

  closeSettings() {
    const modal = document.getElementById('settings-modal');
    if (modal) {
      modal.classList.remove('active');
    }
  }

  async loadSettings() {
    try {
      const response = await fetch('/api/settings');
      const settings = await response.json();
      
      // Binance
      document.getElementById('binance-api-key').value = settings.binance?.api_key || '';
      document.getElementById('binance-testnet').checked = settings.binance?.is_testnet !== false;
      
      // Trading
      const tradingMode = settings.trading?.mode || 'simulation';
      document.getElementById('trading-mode').value = tradingMode;
      document.getElementById('trading-bet-amount').value = settings.trading?.bet_amount || 1;
      
      // Update mode toggle UI
      this.updateModeUI(tradingMode);
      document.getElementById('trading-confidence').value = (settings.trading?.confidence_threshold || 0.62) * 100;
      document.getElementById('confidence-value').textContent = `${Math.round((settings.trading?.confidence_threshold || 0.62) * 100)}%`;
      document.getElementById('trading-max-loss').value = settings.trading?.max_daily_loss || 50;
      document.getElementById('trading-max-trades').value = settings.trading?.max_trades_per_day || 50;
      document.getElementById('trading-auto').checked = settings.trading?.auto_trade || false;
      
      // Simulation
      this.updateSimulationUI(settings.simulation);
      
      // Updates
      this.checkForUpdates();
      
    } catch (error) {
      console.error('Error loading settings:', error);
    }
  }

  async testBinanceConnection() {
    const statusEl = document.getElementById('binance-status');
    statusEl.className = 'connection-status';
    statusEl.style.display = 'block';
    statusEl.textContent = 'Probando conexión...';
    
    // Save first
    await this.saveBinanceSettings();
    
    try {
      const response = await fetch('/api/settings/binance/test', { method: 'POST' });
      const result = await response.json();
      
      if (result.success) {
        statusEl.className = 'connection-status success';
        let info = `✓ ${result.message}`;
        if (result.account_info) {
          info += `\n${result.account_info.account_type} - Can Trade: ${result.account_info.can_trade ? 'Sí' : 'No'}`;
          if (result.account_info.balances) {
            const balances = Object.entries(result.account_info.balances)
              .slice(0, 3)
              .map(([asset, amount]) => `${asset}: ${amount}`)
              .join(', ');
            if (balances) info += `\nBalances: ${balances}`;
          }
        }
        statusEl.textContent = info;
      } else {
        statusEl.className = 'connection-status error';
        statusEl.textContent = `✗ ${result.message}`;
      }
    } catch (error) {
      statusEl.className = 'connection-status error';
      statusEl.textContent = `✗ Error: ${error.message}`;
    }
  }

  async saveBinanceSettings() {
    const apiKey = document.getElementById('binance-api-key').value;
    const apiSecret = document.getElementById('binance-api-secret').value;
    const isTestnet = document.getElementById('binance-testnet').checked;
    
    try {
      await fetch('/api/settings/binance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: apiKey,
          api_secret: apiSecret,
          is_testnet: isTestnet
        })
      });
    } catch (error) {
      console.error('Error saving Binance settings:', error);
    }
  }

  async saveTradingSettings() {
    const settings = {
      mode: document.getElementById('trading-mode').value,
      bet_amount: parseFloat(document.getElementById('trading-bet-amount').value),
      confidence_threshold: parseFloat(document.getElementById('trading-confidence').value) / 100,
      max_daily_loss: parseFloat(document.getElementById('trading-max-loss').value),
      max_trades_per_day: parseInt(document.getElementById('trading-max-trades').value),
      auto_trade: document.getElementById('trading-auto').checked
    };
    
    try {
      const response = await fetch('/api/settings/trading', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      
      if (response.ok) {
        this.showNotification('Configuración guardada', 'success');
      }
    } catch (error) {
      console.error('Error saving trading settings:', error);
      this.showNotification('Error guardando configuración', 'error');
    }
  }

  updateSimulationUI(sim) {
    if (!sim) return;
    
    document.getElementById('sim-balance').textContent = `$${sim.balance?.toFixed(2) || '1,000.00'}`;
    
    const pnlEl = document.getElementById('sim-pnl');
    const pnl = sim.total_pnl || 0;
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
    pnlEl.className = `sim-stat-value ${pnl >= 0 ? 'positive' : 'negative'}`;
    
    const winRate = (sim.win_rate || 0) * 100;
    document.getElementById('sim-winrate').textContent = `${winRate.toFixed(1)}%`;
    document.getElementById('sim-trades').textContent = `${sim.total_trades || 0}`;
    
    // History
    const historyEl = document.getElementById('sim-history');
    const history = sim.history || [];
    
    if (history.length === 0) {
      historyEl.innerHTML = '<p class="settings-hint">No hay trades en el historial</p>';
    } else {
      historyEl.innerHTML = history.slice(-20).reverse().map(trade => `
        <div class="sim-history-item">
          <span class="sim-history-direction ${trade.direction.toLowerCase()}">${trade.direction}</span>
          <span>$${trade.amount.toFixed(2)}</span>
          <span class="sim-history-pnl ${trade.pnl >= 0 ? 'positive' : 'negative'}">
            ${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}
          </span>
        </div>
      `).join('');
    }
  }

  async resetSimulation() {
    if (!confirm('¿Estás seguro de reiniciar la simulación? Se perderá todo el historial.')) {
      return;
    }
    
    const startingBalance = parseFloat(document.getElementById('sim-starting-balance').value) || 1000;
    
    try {
      const response = await fetch('/api/simulation/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starting_balance: startingBalance })
      });
      
      const result = await response.json();
      if (result.success) {
        this.updateSimulationUI(result.simulation);
        this.showNotification('Simulación reiniciada', 'success');
      }
    } catch (error) {
      console.error('Error resetting simulation:', error);
    }
  }

  async checkForUpdates() {
    const statusEl = document.getElementById('update-status');
    const installBtn = document.getElementById('btn-install-update');
    
    statusEl.textContent = 'Verificando actualizaciones...';
    statusEl.className = 'update-status';
    
    try {
      const response = await fetch('/api/updates/check');
      const info = await response.json();
      
      document.getElementById('current-version').textContent = info.current_version;
      
      if (info.available) {
        statusEl.innerHTML = `<strong>Nueva versión disponible:</strong> ${info.latest_version}`;
        statusEl.className = 'update-status available';
        installBtn.disabled = false;
        
        if (info.release_notes) {
          statusEl.innerHTML += `<br><small>${info.release_notes.substring(0, 100)}...</small>`;
        }
      } else {
        statusEl.textContent = '✓ Estás usando la última versión';
        statusEl.className = 'update-status';
        installBtn.disabled = true;
      }
    } catch (error) {
      statusEl.textContent = 'Error verificando actualizaciones';
      statusEl.className = 'update-status error';
    }
  }

  async installUpdate() {
    const statusEl = document.getElementById('update-status');
    const installBtn = document.getElementById('btn-install-update');
    
    installBtn.disabled = true;
    statusEl.textContent = 'Instalando actualización...';
    
    try {
      const response = await fetch('/api/updates/install', { method: 'POST' });
      const result = await response.json();
      
      if (result.success) {
        statusEl.innerHTML = `✓ ${result.message}<br><strong>Reinicia la aplicación para aplicar los cambios.</strong>`;
        statusEl.className = 'update-status available';
      } else {
        statusEl.textContent = `Error: ${result.message}`;
        statusEl.className = 'update-status error';
        installBtn.disabled = false;
      }
    } catch (error) {
      statusEl.textContent = `Error: ${error.message}`;
      statusEl.className = 'update-status error';
      installBtn.disabled = false;
    }
  }

  showNotification(message, type = 'info') {
    // Simple notification - could be enhanced with a toast library
    console.log(`[${type.toUpperCase()}] ${message}`);
  }

  // ═══════════════════════════════════════════════════════════
  // MODE TOGGLE - Simulation vs Real
  // ═══════════════════════════════════════════════════════════

  async toggleMode() {
    const toggle = document.getElementById('mode-toggle');
    const text = document.getElementById('mode-text');
    const indicator = document.getElementById('mode-indicator');
    
    const isSimulation = toggle.classList.contains('simulation');
    
    if (isSimulation) {
      // Switching to REAL - show warning
      const confirmed = confirm(
        '⚠️ MODO REAL\n\n' +
        'Estás a punto de activar el modo REAL.\n' +
        'Los trades se ejecutarán con dinero real.\n\n' +
        '¿Estás seguro?'
      );
      
      if (!confirmed) return;
      
      toggle.classList.remove('simulation');
      text.textContent = 'REAL';
      indicator.textContent = 'REAL';
      indicator.className = 'mode-indicator real';
      
      await this.updateTradingMode('live');
    } else {
      // Switching to SIMULATION
      toggle.classList.add('simulation');
      text.textContent = 'SIM';
      indicator.textContent = 'SIMULATION';
      indicator.className = 'mode-indicator sim';
      
      await this.updateTradingMode('simulation');
    }
  }

  async updateTradingMode(mode) {
    try {
      await fetch('/api/settings/trading', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode })
      });
      console.log(`Mode changed to: ${mode}`);
    } catch (error) {
      console.error('Error updating mode:', error);
    }
  }

  updateModeUI(mode) {
    const toggle = document.getElementById('mode-toggle');
    const text = document.getElementById('mode-text');
    const indicator = document.getElementById('mode-indicator');
    
    if (!toggle) return;
    
    if (mode === 'simulation') {
      toggle.classList.add('simulation');
      text.textContent = 'SIM';
      indicator.textContent = 'SIMULATION';
      indicator.className = 'mode-indicator sim';
    } else {
      toggle.classList.remove('simulation');
      text.textContent = 'REAL';
      indicator.textContent = 'REAL';
      indicator.className = 'mode-indicator real';
    }
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  window.dashboard = new VibesbotDashboard();
});
