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
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  window.dashboard = new VibesbotDashboard();
});
