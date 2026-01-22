/**
 * Polymarket Trading Dashboard
 * Main Application JavaScript
 */

class TradingDashboard {
    constructor() {
        this.ws = null;
        this.chart = null;
        this.candleSeries = null;
        this.priceData = [];
        this.lastPrice = 0;
        this.state = {
            connected: false,
            botRunning: false,
            dryRun: true,
            portfolio: {
                value: 10000,
                pnlToday: 0,
                winRate: 0,
                positions: 0
            },
            markets: [],
            trades: []
        };

        this.init();
    }

    async init() {
        // Initialize Lucide icons
        lucide.createIcons();

        // Initialize chart
        this.initChart();

        // Setup event listeners
        this.setupEventListeners();

        // Connect WebSocket
        this.connectWebSocket();

        // Load initial data
        await this.loadMarkets();
    }

    initChart() {
        const container = document.getElementById('price-chart');
        if (!container) return;

        this.chart = LightweightCharts.createChart(container, {
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: '#a0a3bd',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                timeVisible: true,
                secondsVisible: false,
            },
            handleScroll: { vertTouchDrag: false },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00ff88',
            downColor: '#ff4d6a',
            borderUpColor: '#00ff88',
            borderDownColor: '#ff4d6a',
            wickUpColor: '#00ff88',
            wickDownColor: '#ff4d6a',
        });

        // Add line series for live price
        this.lineSeries = this.chart.addLineSeries({
            color: '#00d4ff',
            lineWidth: 2,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 4,
        });

        // Fetch real historical data
        this.fetchHistoricalData();

        // Make chart responsive
        new ResizeObserver(() => {
            this.chart.applyOptions({
                width: container.clientWidth,
                height: container.clientHeight
            });
        }).observe(container);
    }

    async fetchHistoricalData() {
        try {
            // Fetch last 1000 candles (1m interval) from Binance
            const response = await fetch('https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1000');
            const data = await response.json();

            const candles = data.map(d => ({
                time: d[0] / 1000,
                open: parseFloat(d[1]),
                high: parseFloat(d[2]),
                low: parseFloat(d[3]),
                close: parseFloat(d[4])
            }));

            this.candleSeries.setData(candles);

            if (candles.length > 0) {
                this.lastPrice = candles[candles.length - 1].close;
                // Update price display
                const priceElement = document.getElementById('btc-price');
                if (priceElement) {
                    priceElement.textContent = this.formatCurrency(this.lastPrice);
                }
            }
        } catch (e) {
            console.error('Failed to load historical data:', e);
        }
    }

    setupEventListeners() {
        // Bot toggle button
        const botToggle = document.getElementById('bot-toggle');
        if (botToggle) {
            botToggle.addEventListener('click', () => this.toggleBot());
        }

        // Dry run toggle
        const dryRunToggle = document.getElementById('dry-run-toggle');
        if (dryRunToggle) {
            dryRunToggle.addEventListener('click', () => this.toggleDryRun());
        }

        // Refresh markets button
        const refreshBtn = document.getElementById('refresh-markets');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadMarkets());
        }

        // Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();

                // Remove active class from all nav items
                document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));

                // Add active class to clicked item
                item.classList.add('active');

                // Get target page ID
                const pageId = item.dataset.page;

                // Hide all pages
                document.querySelectorAll('.page-view').forEach(page => {
                    page.style.display = 'none';
                });

                // Show target page
                const targetPage = document.getElementById(`page-${pageId}`);
                if (targetPage) {
                    targetPage.style.display = 'block';
                }
            });
        });
    }

    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws`;
        console.log('Connecting to WebSocket:', wsUrl);

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.state.connected = true;
            this.updateConnectionStatus(true);
            this.showToast('Connected to server', 'success');
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.state.connected = false;
            this.updateConnectionStatus(false);

            // Reconnect after 3 seconds
            setTimeout(() => this.connectWebSocket(), 3000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus(false);
        };

        this.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (e) {
                console.error('Failed to parse message:', e);
            }
        };

        // Send ping every 30 seconds
        setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    }

    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'full_state':
                this.handleFullState(message.data);
                break;
            case 'price_update':
                this.handlePriceUpdate(message.data);
                break;
            case 'markets_update':
                this.handleMarketsUpdate(message.data);
                break;
            case 'new_trade':
                this.handleNewTrade(message.data);
                break;
            case 'portfolio_update':
                this.handlePortfolioUpdate(message.data);
                break;
            case 'bot_status':
                this.handleBotStatus(message.data);
                break;
            case 'log':
                this.handleLog(message.data);
                break;
        }
    }

    handleLog(data) {
        const container = document.getElementById('activity-log');
        if (!container) return;

        // Remove initial waiting message if present
        const initialMsg = container.querySelector('.log-message');
        if (initialMsg && initialMsg.textContent === 'Waiting for bot logs...') {
            container.innerHTML = '';
        }

        const entry = document.createElement('div');
        entry.className = `log-entry ${data.level || 'info'}`;

        const time = new Date(data.time).toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });

        entry.innerHTML = `
            <span class="log-time">${time}</span>
            <span class="log-message">${data.message}</span>
        `;

        container.prepend(entry);

        // Limit to 50 logs
        if (container.children.length > 50) {
            container.lastElementChild.remove();
        }
    }

    handleFullState(data) {
        if (data.bot_status) {
            this.state.botRunning = data.bot_status.running;
            this.state.dryRun = data.bot_status.dry_run;
            this.updateBotButtons();
        }

        if (data.portfolio) {
            this.handlePortfolioUpdate({ portfolio: data.portfolio });
        }

        if (data.markets) {
            this.state.markets = data.markets;
            this.renderMarkets();
        }

        if (data.trades) {
            this.state.trades = data.trades;
            this.renderTrades();
        }

        if (data.btc_price) {
            this.handlePriceUpdate({ btc_price: data.btc_price });
        }
    }

    handlePriceUpdate(data) {
        const price = data.btc_price;
        const priceElement = document.getElementById('btc-price');
        const changeElement = document.getElementById('price-change');

        if (priceElement) {
            priceElement.textContent = this.formatCurrency(price);
        }

        // Calculate price change
        if (this.lastPrice > 0 && changeElement) {
            const change = ((price - this.lastPrice) / this.lastPrice) * 100;
            changeElement.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
            changeElement.classList.toggle('profit', change >= 0);
            changeElement.classList.toggle('loss', change < 0);
        }

        // Update chart
        if (this.lineSeries) {
            const time = Math.floor(Date.now() / 1000);
            this.lineSeries.update({ time, value: price });
        }

        this.lastPrice = price;
    }

    handleMarketsUpdate(data) {
        this.state.markets = data.markets || [];
        this.renderMarkets();
    }

    handleNewTrade(data) {
        const trade = data.trade;
        this.state.trades.unshift(trade);
        this.state.trades = this.state.trades.slice(0, 100);

        if (data.portfolio) {
            this.handlePortfolioUpdate({ portfolio: data.portfolio });
        }

        this.renderTrades();
        this.showToast(`Trade executed: ${trade.side} ${trade.market}`, trade.pnl >= 0 ? 'success' : 'error');
    }

    handlePortfolioUpdate(data) {
        const p = data.portfolio;

        document.getElementById('portfolio-value').textContent =
            this.formatCurrency(p.value);

        const pnlElement = document.getElementById('pnl-today');
        pnlElement.textContent = `${p.pnl_today >= 0 ? '+' : ''}${this.formatCurrency(p.pnl_today)}`;
        pnlElement.classList.toggle('profit', p.pnl_today >= 0);
        pnlElement.classList.toggle('loss', p.pnl_today < 0);

        // Update P&L icon
        const pnlIcon = pnlElement.closest('.stat-card').querySelector('.stat-icon');
        if (pnlIcon) {
            pnlIcon.classList.toggle('profit', p.pnl_today >= 0);
            pnlIcon.classList.toggle('loss', p.pnl_today < 0);
        }

        document.getElementById('win-rate').textContent =
            `${(p.win_rate || 0).toFixed(1)}%`;

        document.getElementById('active-positions').textContent =
            this.state.markets.filter(m => m.accepting_orders).length.toString();
    }

    handleBotStatus(data) {
        this.state.botRunning = data.bot_status.running;
        this.state.dryRun = data.bot_status.dry_run;
        this.updateBotButtons();
    }

    updateBotButtons() {
        const botToggle = document.getElementById('bot-toggle');
        const dryRunToggle = document.getElementById('dry-run-toggle');

        if (botToggle) {
            const icon = botToggle.querySelector('i');
            const text = botToggle.querySelector('span');

            if (this.state.botRunning) {
                botToggle.classList.add('running');
                if (icon) icon.setAttribute('data-lucide', 'square');
                if (text) text.textContent = 'Stop Bot';
            } else {
                botToggle.classList.remove('running');
                if (icon) icon.setAttribute('data-lucide', 'play');
                if (text) text.textContent = 'Start Bot';
            }
            lucide.createIcons();
        }

        if (dryRunToggle) {
            const text = dryRunToggle.querySelector('span');
            if (text) text.textContent = `Dry Run: ${this.state.dryRun ? 'ON' : 'OFF'}`;
            dryRunToggle.classList.toggle('active', this.state.dryRun);
        }
    }

    async toggleBot() {
        const endpoint = this.state.botRunning ? '/api/bot/stop' : '/api/bot/start';
        try {
            const response = await fetch(endpoint, { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                this.showToast(
                    this.state.botRunning ? 'Bot stopped' : 'Bot started',
                    'success'
                );
            }
        } catch (e) {
            this.showToast('Failed to toggle bot', 'error');
        }
    }

    async toggleDryRun() {
        try {
            const response = await fetch('/api/bot/toggle-dry-run', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                this.showToast(
                    `Dry run ${data.status.dry_run ? 'enabled' : 'disabled'}`,
                    'info'
                );
            }
        } catch (e) {
            this.showToast('Failed to toggle dry run', 'error');
        }
    }

    async loadMarkets() {
        const list = document.getElementById('markets-list');
        list.innerHTML = `
            <div class="loading">
                <div class="spinner"></div>
                <span>Loading markets...</span>
            </div>
        `;

        try {
            const response = await fetch('/api/markets');
            const data = await response.json();
            this.state.markets = data.markets || [];
            this.renderMarkets();
        } catch (e) {
            list.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="alert-circle"></i>
                    <span>Failed to load markets</span>
                </div>
            `;
            lucide.createIcons();
        }
    }

    renderMarkets() {
        const list = document.getElementById('markets-list');
        if (!list) return;

        if (this.state.markets.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="search"></i>
                    <span>No active markets</span>
                </div>
            `;
            lucide.createIcons();
            return;
        }

        list.innerHTML = this.state.markets.slice(0, 10).map(market => {
            const upPercent = (market.outcome_prices?.up || 0.5) * 100;
            const downPercent = (market.outcome_prices?.down || 0.5) * 100;
            const timeRemaining = this.getTimeRemaining(market.end_date);

            // Extract time from question
            const timeMatch = market.question.match(/(\d+:\d+[AP]M-\d+:\d+[AP]M \w+)/);
            const timeDisplay = timeMatch ? timeMatch[1] : 'Unknown';

            return `
                <div class="market-item">
                    <div class="market-header">
                        <span class="market-name">BTC 15-min: ${timeDisplay}</span>
                        <span class="market-time">
                            <i data-lucide="clock"></i>
                            ${timeRemaining}
                        </span>
                    </div>
                    <div class="market-odds">
                        <div class="odds-bar">
                            <div class="odds-fill up" style="width: ${upPercent}%"></div>
                        </div>
                    </div>
                    <div class="market-prices">
                        <span class="price-up">Up ${upPercent.toFixed(0)}%</span>
                        <span class="price-down">Down ${downPercent.toFixed(0)}%</span>
                    </div>
                </div>
            `;
        }).join('');

        lucide.createIcons();

        // Update active positions count
        document.getElementById('active-positions').textContent =
            this.state.markets.length.toString();
    }

    renderTrades() {
        const tbody = document.getElementById('trades-body');
        const countEl = document.getElementById('trade-count');

        if (!tbody) return;

        if (countEl) {
            countEl.textContent = `${this.state.trades.length} trades`;
        }

        if (this.state.trades.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">
                        <div class="empty-state">
                            <i data-lucide="inbox"></i>
                            <span>No trades yet</span>
                        </div>
                    </td>
                </tr>
            `;
            lucide.createIcons();
            return;
        }

        tbody.innerHTML = this.state.trades.slice(0, 20).map(trade => {
            const pnlClass = trade.pnl >= 0 ? 'profit' : 'loss';
            const statusIcon = trade.status === 'won' ? 'check-circle' :
                trade.status === 'lost' ? 'x-circle' : 'clock';

            return `
                <tr>
                    <td>${this.formatTime(trade.time)}</td>
                    <td>${trade.market || 'BTC 15m'}</td>
                    <td><span class="trade-type ${trade.type?.toLowerCase()}">${trade.type || 'Snipe'}</span></td>
                    <td><span class="trade-side ${trade.side?.toLowerCase()}">${trade.side || 'Up'}</span></td>
                    <td>${this.formatCurrency(trade.price)}</td>
                    <td>${this.formatCurrency(trade.amount)}</td>
                    <td><span class="trade-pnl ${pnlClass}">${trade.pnl >= 0 ? '+' : ''}${this.formatCurrency(trade.pnl)}</span></td>
                    <td>
                        <span class="trade-status ${trade.status}">
                            <i data-lucide="${statusIcon}"></i>
                            ${trade.status}
                        </span>
                    </td>
                </tr>
            `;
        }).join('');

        lucide.createIcons();
    }

    updateConnectionStatus(connected) {
        const status = document.getElementById('connection-status');
        if (!status) return;

        const dot = status.querySelector('.status-dot');
        const text = status.querySelector('.status-text');

        dot.classList.toggle('connected', connected);
        dot.classList.toggle('disconnected', !connected);
        text.textContent = connected ? 'Connected' : 'Disconnected';
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const icons = {
            success: 'check-circle',
            error: 'alert-circle',
            info: 'info'
        };

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <i data-lucide="${icons[type]}"></i>
            <span class="toast-message">${message}</span>
        `;

        container.appendChild(toast);
        lucide.createIcons();

        // Remove after 4 seconds
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // Utility functions
    formatCurrency(value) {
        if (value === undefined || value === null) return '$0.00';
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value);
    }

    formatTime(isoString) {
        if (!isoString) return '--:--';
        const date = new Date(isoString);
        return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    getTimeRemaining(endDate) {
        if (!endDate) return 'Unknown';

        const end = new Date(endDate);
        const now = new Date();
        const diff = end - now;

        if (diff <= 0) return 'Ended';

        const mins = Math.floor(diff / 60000);
        const secs = Math.floor((diff % 60000) / 1000);

        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new TradingDashboard();
});
