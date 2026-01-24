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
                value: 10,
                pnlToday: 0,
                winRate: 0,
                positions: 0
            },
            markets: [],
            trades: []
        };

        this.markers = [];

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
        const priceContainer = document.getElementById('price-chart');
        const probContainer = document.getElementById('prob-chart');

        if (!priceContainer || !probContainer) return;

        // --- CHART 1: BTC Price ---
        this.chart = LightweightCharts.createChart(priceContainer, {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#a0a3bd' },
            grid: { vertLines: { color: 'rgba(255, 255, 255, 0.05)' }, horzLines: { color: 'rgba(255, 255, 255, 0.05)' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: 'rgba(255, 255, 255, 0.1)' },
            timeScale: { borderColor: 'rgba(255, 255, 255, 0.1)', timeVisible: true, secondsVisible: true },
            handleScroll: { vertTouchDrag: false },
        });

        this.candleSeries = this.chart.addCandlestickSeries({
            upColor: '#00ff88', downColor: '#ff4d6a', borderUpColor: '#00ff88', borderDownColor: '#ff4d6a', wickUpColor: '#00ff88', wickDownColor: '#ff4d6a',
        });

        this.lineSeries = this.chart.addLineSeries({
            color: '#00d4ff', lineWidth: 2, crosshairMarkerVisible: true,
        });

        // --- CHART 2: Polymarket Probability ---
        this.probChart = LightweightCharts.createChart(probContainer, {
            layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#a0a3bd' },
            grid: { vertLines: { color: 'rgba(255, 255, 255, 0.05)' }, horzLines: { color: 'rgba(255, 255, 255, 0.05)' } },
            rightPriceScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                scaleMargins: { top: 0.1, bottom: 0.1 },
                visible: true,
            },
            timeScale: {
                borderColor: 'rgba(255, 255, 255, 0.1)',
                timeVisible: true,
                secondsVisible: true,
                visible: true
            },
            handleScroll: { vertTouchDrag: false },
        });

        // Area series for Probability (0-100%)
        this.probSeries = this.probChart.addAreaSeries({
            lineColor: '#00ff88', topColor: 'rgba(0, 255, 136, 0.4)', bottomColor: 'rgba(0, 255, 136, 0.0)',
            lineWidth: 2,
            priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
        });

        // Sync Charts (rough sync via timestamps)
        // Note: For perfect sync we'd need a wrapper, but separate is fine for dashboard

        // Add entry price line (horizontal)
        this.entryLine = null;
        this.strikeLine = null;

        // Fetch real historical data
        this.fetchHistoricalData();

        // Periodic refresh
        setInterval(() => this.fetchHistoricalData(), 60000);

        // Responsive
        new ResizeObserver(() => {
            this.chart.applyOptions({ width: priceContainer.clientWidth, height: priceContainer.clientHeight });
            this.probChart.applyOptions({ width: probContainer.clientWidth, height: probContainer.clientHeight });
        }).observe(priceContainer);
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
            this.showToast('Sunucuya bağlanıldı', 'success');
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
        if (initialMsg && initialMsg.textContent === 'Bot logları bekleniyor...') {
            container.innerHTML = '';
        }

        const entry = document.createElement('div');
        entry.className = `log-entry ${data.level || 'info'}`;

        const time = new Date(data.time).toLocaleTimeString('tr-TR', {
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
        const source = data.source;

        const priceElement = document.getElementById('btc-price');
        const changeElement = document.getElementById('price-change');

        // Update price title or subtitle to show source
        const allOk = Array.from(document.querySelectorAll('p'));
        const subtitle = allOk.find(el => el.textContent.includes('BTC 15-Dakikalık'));

        if (subtitle && source) {
            subtitle.textContent = `BTC 15-Dakikalık Tahmin Piyasaları (Fiyat Kaynağı: ${source})`;
        }

        // Also update legend if possible
        const legendItem = document.querySelector('.chart-legend-item.price span');
        if (legendItem && source) {
            legendItem.textContent = `Ref Fiyat (${source})`;
        }

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

        if (this.lineSeries) {
            const time = Math.floor(Date.now() / 1000);
            this.lineSeries.update({ time, value: price });

            // Auto-scroll to keep chart real-time
            this.chart.timeScale().scrollToRealTime();

            // --- UPDATE PROBABILITY CHART ---
            if (this.probSeries && this.state.markets.length > 0) {
                // Get best active market (sorted by expiry usually)
                const m = this.state.markets[0];
                const prices = m.outcome_prices || {};
                const probUp = (prices.up || 0.5) * 100; // Convert to percentage

                this.probSeries.update({ time, value: probUp });
                this.probChart.timeScale().scrollToRealTime();
            }
        }

        this.lastPrice = price;

        // --- UPDATE STRATEGY PULSE UI ---
        if (data.rsi !== undefined && data.trend !== undefined) {
            const rsi = data.rsi;
            const trend = data.trend;

            // Update RSI Bar
            const rsiFill = document.getElementById('rsi-fill');
            const rsiVal = document.getElementById('rsi-value');
            if (rsiFill && rsiVal) {
                rsiFill.style.width = `${rsi}%`;
                rsiVal.textContent = rsi.toFixed(1);

                // Color logic for RSI
                rsiFill.style.background =
                    rsi > 70 ? 'var(--warning)' :
                        rsi < 30 ? 'var(--accent-secondary)' :
                            'linear-gradient(90deg, var(--loss) 0%, var(--warning) 50%, var(--profit) 100%)';
            }

            // Update Trend Badge
            const trendBadge = document.getElementById('strategy-trend');
            const smaVal = document.getElementById('sma-value');

            if (trendBadge) {
                trendBadge.className = `trend-badge ${trend.toLowerCase()}`;

                // Translate Trend
                const trendMap = { 'UP': 'YÜKSELİŞ', 'DOWN': 'DÜŞÜŞ', 'FLAT': 'YATAY' };
                trendBadge.textContent = trendMap[trend] || trend;
            }

            if (smaVal && data.sma) {
                const diff = ((price - data.sma) / data.sma) * 100;
                smaVal.textContent = `SMA ${diff >= 0 ? '+' : ''}${diff.toFixed(2)}%`;
                smaVal.style.color = diff >= 0 ? 'var(--profit)' : 'var(--loss)';
            }

            // Update Decision Text
            const decisionEl = document.getElementById('strategy-decision');
            if (decisionEl) {
                let text = "NÖTR / BEKLE";
                let cls = "decision-wait";

                if (trend === 'UP') {
                    if (rsi > 70) { text = "AŞIRI ALIM (BEKLE)"; cls = "decision-wait"; }
                    else { text = "ALIM FIRSATI ARA"; cls = "decision-up"; }
                } else if (trend === 'DOWN') {
                    if (rsi < 30) { text = "AŞIRI SATIM (BEKLE)"; cls = "decision-wait"; }
                    else { text = "SATIŞ FIRSATI ARA"; cls = "decision-down"; }
                }

                decisionEl.innerHTML = `<span class="${cls}">${text}</span>`;
            }
        }
    }

    handleMarketsUpdate(data) {
        this.state.markets = data.markets || [];
        this.renderMarkets();

        // Also update probability chart immediately if possible
        if (this.probSeries && this.state.markets.length > 0) {
            const time = Math.floor(Date.now() / 1000);
            const m = this.state.markets[0];
            const prices = m.outcome_prices || {};
            const probUp = (prices.up || 0.5) * 100;

            this.probSeries.update({ time, value: probUp });
        }
    }

    handleNewTrade(data) {
        const trade = data.trade;
        this.state.trades.unshift(trade);
        this.state.trades = this.state.trades.slice(0, 100);

        if (data.portfolio) {
            this.handlePortfolioUpdate({ portfolio: data.portfolio });
        }

        this.renderTrades();
        this.showToast(`İşlem gerçekleştirildi: ${trade.side} ${trade.market}`, trade.pnl >= 0 ? 'success' : 'error');

        // Show active trade panel if trade is pending
        if (trade.status === 'pending') {
            this.showActiveTrade(trade, data.message);
        } else {
            // Trade Completed - Add EXIT marker
            if (this.candleSeries) {
                const time = Math.floor(Date.now() / 1000);
                const isWin = trade.status === 'won';

                this.markers.push({
                    time: time,
                    position: isWin ? 'aboveBar' : 'belowBar',
                    color: isWin ? '#00ff88' : '#ff4d6a',
                    shape: 'circle',
                    text: `${isWin ? 'KAZANDI' : 'KAYBETTİ'} $${Math.abs(trade.pnl).toFixed(2)}`
                });

                this.markers.sort((a, b) => a.time - b.time);
                this.candleSeries.setMarkers(this.markers);
            }

            this.hideActiveTrade();
        }
    }

    showActiveTrade(trade, message) {
        const panel = document.getElementById('active-trade-panel');
        if (!panel) return;

        panel.style.display = 'block';

        // Update side
        const sideEl = document.getElementById('active-side');
        sideEl.textContent = trade.side.toUpperCase();
        sideEl.className = `info-value trade-side ${trade.side.toLowerCase()}`;

        // Update entry price
        document.getElementById('active-entry').textContent = `$${trade.price.toFixed(3)}`;

        // Parse end time from market slug (btc-updown-15m-TIMESTAMP)
        const slugMatch = trade.market?.match(/(\d{10})/);
        if (slugMatch) {
            const endTimestamp = parseInt(slugMatch[1]) * 1000;
            this.activeTradeEndTime = endTimestamp;
            this.startCountdown();
        }

        // Reinit icons
        lucide.createIcons();

        // Add Strike Price Line to Chart
        // PINNED TO ACTIVE TRADE - Force use of trade data or persistent DOM data
        let strikePrice = trade.strike;

        // If not directly in trade obj, try DOM backup (persistence)
        if (!strikePrice) {
            const stored = document.getElementById('active-strike').dataset.price;
            if (stored) strikePrice = parseFloat(stored);
        }

        // Fallback: parse from market string
        if (!strikePrice && trade.market) {
            const match = trade.market.match(/\$?([\d,]+\.?\d*)/);
            if (match) strikePrice = parseFloat(match[1].replace(/,/g, ''));
        }

        // Save to DOM for future redraws
        if (strikePrice) {
            const strikeEl = document.getElementById('active-strike');
            if (strikeEl) {
                strikeEl.dataset.price = strikePrice;
                strikeEl.textContent = `$${strikePrice.toFixed(2)}`;
            }
        }

        if (strikePrice && this.chart && this.candleSeries) {
            // Remove old line if exists
            if (this.strikeLine) {
                this.candleSeries.removePriceLine(this.strikeLine);
            }

            this.strikeLine = this.candleSeries.createPriceLine({
                price: strikePrice,
                color: '#ff4d6a', // Red for strike
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid, // Solid for active trade
                axisLabelVisible: true,
                title: 'HEDEF STRIKE',
            });
        }

        // Add Entry Marker
        if (this.candleSeries) {
            const time = Math.floor(Date.now() / 1000);

            // Add to markers list
            this.markers.push({
                time: time,
                position: trade.side === 'up' ? 'belowBar' : 'aboveBar',
                color: trade.side === 'up' ? '#00ff88' : '#ff4d6a',
                shape: trade.side === 'up' ? 'arrowUp' : 'arrowDown',
                text: `GİRİŞ ${trade.side.toUpperCase()} @ ${trade.price.toFixed(2)}`
            });

            // Sort markers by time (required by library)
            this.markers.sort((a, b) => a.time - b.time);
            this.candleSeries.setMarkers(this.markers);
        }
    }

    hideActiveTrade() {
        const panel = document.getElementById('active-trade-panel');
        if (panel) {
            panel.style.display = 'none';
        }

        // Remove strike line
        if (this.strikeLine && this.candleSeries) {
            this.candleSeries.removePriceLine(this.strikeLine);
            this.strikeLine = null;
        }

        this.activeTradeEndTime = null;
    }

    startCountdown() {
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }

        this.countdownInterval = setInterval(() => {
            if (!this.activeTradeEndTime) {
                clearInterval(this.countdownInterval);
                return;
            }

            const now = Date.now();
            const remaining = Math.max(0, this.activeTradeEndTime - now);
            const minutes = Math.floor(remaining / 60000);
            const seconds = Math.floor((remaining % 60000) / 1000);

            const timerEl = document.getElementById('countdown-timer');
            if (timerEl) {
                timerEl.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }

            // Update BTC price in panel
            const btcEl = document.getElementById('active-btc');
            if (btcEl) {
                btcEl.textContent = this.formatCurrency(this.lastPrice);
            }

            if (remaining <= 0) {
                clearInterval(this.countdownInterval);
                this.hideActiveTrade();
            }
        }, 1000);
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
                if (text) text.textContent = 'Botu Durdur';
            } else {
                botToggle.classList.remove('running');
                if (icon) icon.setAttribute('data-lucide', 'play');
                if (text) text.textContent = 'Botu Başlat';
            }
            lucide.createIcons();
        }

        if (dryRunToggle) {
            const text = dryRunToggle.querySelector('span');
            if (text) text.textContent = `Test Modu: ${this.state.dryRun ? 'AÇIK' : 'KAPALI'}`;
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
                    this.state.botRunning ? 'Bot durduruldu' : 'Bot başlatıldı',
                    'success'
                );
            }
        } catch (e) {
            this.showToast('Bot durumu değiştirilemedi', 'error');
        }
    }

    async toggleDryRun() {
        try {
            const response = await fetch('/api/bot/toggle-dry-run', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                this.showToast(
                    `Test modu ${data.status.dry_run ? 'açıldı' : 'kapatıldı'}`,
                    'info'
                );
            }
        } catch (e) {
            this.showToast('Test modu değiştirilemedi', 'error');
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
                    <span>Piyasalar yüklenemedi</span>
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
                    <span>Aktif piyasa yok</span>
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
                        <a href="https://polymarket.com/event/${market.slug}" target="_blank" style="text-decoration: none; color: inherit; display: flex; align-items: center; gap: 4px;">
                            <span class="market-name">BTC 15-min: ${timeDisplay}</span>
                            <i data-lucide="external-link" style="width: 14px; height: 14px; opacity: 0.7;"></i>
                        </a>
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
            countEl.textContent = `${this.state.trades.length} işlem`;
        }

        if (this.state.trades.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">
                        <div class="empty-state">
                            <i data-lucide="inbox"></i>
                            <span>Henüz işlem yok</span>
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
                    <td>
                        <a href="https://polymarket.com/event/${trade.market_slug}" target="_blank" style="color: #a0a3bd; text-decoration: none; display: flex; align-items: center; gap: 4px;">
                            ${trade.market || 'BTC 15m'} <i data-lucide="external-link" style="width: 12px; height: 12px;"></i>
                        </a>
                    </td>
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
        text.textContent = connected ? 'Bağlı' : 'Bağlantı Yok';
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
