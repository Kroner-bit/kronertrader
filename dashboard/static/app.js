// Nautilus Trading Engine Dashboard Client
let ws = null;
let currentSymbol = "EURUSD";
let allInstruments = [];

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initWebSocket();
    loadInstruments();
    loadAccounts();
    loadActiveStrategies();
    loadPositions();
    loadTrades();
    loadStrategiesCatalog();
    loadBacktests();
    loadMarketStats();
    loadHistoricalCoverage();
    loadLiveStreams();

    // Auto refresh every 5s as fallback
    setInterval(() => {
        loadMarketStats();
        loadPositions();
    }, 5000);
});

// --- Tab Navigation ---
function initNavigation() {
    const tabs = document.querySelectorAll(".nav-tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
            tab.classList.add("active");
            const target = tab.getAttribute("data-tab");
            const pane = document.getElementById(target);
            if (pane) pane.classList.add("active");

            // Refresh tab data
            if (target === "accounts-tab") loadAccounts();
            if (target === "active-tab") loadActiveStrategies();
            if (target === "backtest-tab") loadBacktests();
            if (target === "catalog-tab") loadStrategiesCatalog();
            if (target === "data-tab") {
                loadMarketStats();
                loadHistoricalCoverage();
                loadLiveStreams();
            }
        });
    });
}

// --- WebSocket Connection ---
function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;
    
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("WebSocket connected to Nautilus live feed");
        const badge = document.getElementById("connection-status");
        if (badge) {
            badge.innerHTML = `<span class="pulsing-dot"></span> LIVE FEED AKTÍV`;
            badge.className = "status-badge status-live";
        }
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.tick) {
                updateLiveTicker(data.tick);
            }
            if (data.active_streams) {
                renderLiveStreamsTable(data.active_streams);
            }
            if (data.download_state && data.download_state.is_running) {
                updateDownloadProgress(data.download_state);
            }
        } catch (e) {
            console.error("WS error:", e);
        }
    };

    ws.onclose = () => {
        const badge = document.getElementById("connection-status");
        if (badge) {
            badge.innerHTML = `DISCONNECTED`;
            badge.className = "status-badge";
        }
        setTimeout(initWebSocket, 3000);
    };
}

function updateLiveTicker(tick) {
    const bidEl = document.getElementById("ticker-bid");
    const askEl = document.getElementById("ticker-ask");
    const spreadEl = document.getElementById("ticker-spread");

    if (bidEl) bidEl.textContent = parseFloat(tick.bid).toFixed(5);
    if (askEl) askEl.textContent = parseFloat(tick.ask).toFixed(5);
    if (spreadEl) {
        const spread = ((parseFloat(tick.ask) - parseFloat(tick.bid)) * 10000).toFixed(1);
        spreadEl.textContent = `${spread} pip`;
    }
}

// --- Instruments List & Selectors ---
async function loadInstruments() {
    try {
        const res = await fetch("/api/instruments");
        allInstruments = await res.json();

        // Group by category
        const groups = {};
        allInstruments.forEach(inst => {
            const cat = inst.category || "Egyéb";
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(inst);
        });

        const generateOptions = () => {
            let html = "";
            for (const [category, list] of Object.entries(groups)) {
                html += `<optgroup label="${category}">`;
                list.forEach(i => {
                    html += `<option value="${i.symbol}">${i.name} (${i.description})</option>`;
                });
                html += `</optgroup>`;
            }
            return html;
        };

        const optionsHtml = generateOptions();

        const btSelect = document.getElementById("bt-symbol");
        const stratSelect = document.getElementById("strategy-symbol");
        const dlSelect = document.getElementById("dl-symbol");
        const streamSelect = document.getElementById("stream-ticker-select");

        if (btSelect) {
            btSelect.innerHTML = optionsHtml;
            btSelect.value = "EURUSD";
        }
        if (stratSelect) {
            stratSelect.innerHTML = optionsHtml;
            stratSelect.value = "EURUSD";
        }
        if (dlSelect) {
            dlSelect.innerHTML = optionsHtml;
            dlSelect.value = "EURUSD";
        }
        if (streamSelect) {
            streamSelect.innerHTML = optionsHtml;
            streamSelect.value = "GBPUSD";
        }
    } catch (e) {
        console.error("Error loading instruments:", e);
    }
}

// --- Historical Coverage Table ---
async function loadHistoricalCoverage() {
    try {
        const res = await fetch("/api/market/coverage");
        const coverage = await res.json();
        const tbody = document.getElementById("coverage-body");
        if (!tbody) return;

        if (coverage.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Még nincs letöltött tick adat az adatbázisban.</td></tr>`;
            return;
        }

        tbody.innerHTML = coverage.map(c => {
            const latestPrice = c.latest_bid ? `${c.latest_bid.toFixed(5)} / ${c.latest_ask.toFixed(5)}` : "-";
            return `
            <tr>
                <td><strong>${c.symbol}</strong></td>
                <td>${c.name} <span class="card-tag" style="margin-left: 6px;">${c.category}</span></td>
                <td><strong class="val-cyan">${c.tick_count.toLocaleString()}</strong></td>
                <td>${c.from_date}</td>
                <td>${c.to_date}</td>
                <td><span class="card-tag">${c.duration_days} nap</span></td>
                <td><code>${latestPrice}</code></td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="startBacktestForSymbol('${c.symbol}')">🧪 Visszateszt</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteSymbolCoverage('${c.symbol}')">🗑️ Törlés</button>
                </td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading coverage:", e);
    }
}

async function deleteSymbolCoverage(symbol) {
    if (!confirm(`Biztosan törölni szeretnéd a(z) ${symbol} letöltött tick adatait az SQLite-ból?`)) {
        return;
    }
    try {
        const res = await fetch(`/api/market/coverage/${symbol}`, { method: "DELETE" });
        if (res.ok) {
            loadHistoricalCoverage();
            loadMarketStats();
        }
    } catch (e) {
        console.error("Error deleting coverage:", e);
    }
}

function startBacktestForSymbol(symbol) {
    const tab = document.querySelector('[data-tab="backtest-tab"]');
    if (tab) tab.click();
    const btSelect = document.getElementById("bt-symbol");
    if (btSelect) btSelect.value = symbol;
}

// --- Live Streams Manager ---
async function loadLiveStreams() {
    try {
        const res = await fetch("/api/market/live-streams");
        const streams = await res.json();
        renderLiveStreamsTable(streams);
    } catch (e) {
        console.error("Error loading live streams:", e);
    }
}

function renderLiveStreamsTable(streams) {
    const tbody = document.getElementById("live-streams-body");
    if (!tbody) return;

    if (!streams || streams.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Jelenleg nincs aktív élő stream feliratkozás.</td></tr>`;
        return;
    }

    tbody.innerHTML = streams.map(s => {
        const bid = s.bid ? parseFloat(s.bid).toFixed(5) : "-";
        const ask = s.ask ? parseFloat(s.ask).toFixed(5) : "-";
        const spread = (s.bid && s.ask) ? ((parseFloat(s.ask) - parseFloat(s.bid)) * 10000).toFixed(1) + " pip" : "-";

        return `
        <tr>
            <td><strong>${s.symbol}</strong></td>
            <td>${s.name}</td>
            <td class="val-green"><code>${bid}</code></td>
            <td class="val-red"><code>${ask}</code></td>
            <td>${spread}</td>
            <td>${s.last_update || '-'}</td>
            <td>
                <span class="status-badge status-live">
                    <span class="pulsing-dot"></span> ${s.status}
                </span>
            </td>
            <td>
                <button class="btn btn-danger btn-sm" onclick="stopLiveStream('${s.symbol}')">Leállítás</button>
            </td>
        </tr>
        `;
    }).join("");
}

async function addLiveStreamTicker(e) {
    e.preventDefault();
    const symbol = document.getElementById("stream-ticker-select").value;
    try {
        const res = await fetch("/api/market/live-streams/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol })
        });
        if (res.ok) {
            closeModal("modal-add-stream");
            loadLiveStreams();
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

async function stopLiveStream(symbol) {
    try {
        const res = await fetch("/api/market/live-streams/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol })
        });
        if (res.ok) {
            loadLiveStreams();
        }
    } catch (e) {
        console.error("Error stopping live stream:", e);
    }
}

// --- Demo Accounts ---
async function loadAccounts() {
    try {
        const res = await fetch("/api/accounts");
        const accounts = await res.json();
        const grid = document.getElementById("accounts-grid");
        const select = document.getElementById("strategy-account-select");

        if (select) {
            select.innerHTML = accounts.map(a => `<option value="${a.id}">${a.name} ($${a.balance.toLocaleString()})</option>`).join("");
        }

        if (!grid) return;
        if (accounts.length === 0) {
            grid.innerHTML = `<div class="card"><p class="text-muted">Nincs elérhető demó számla.</p></div>`;
            return;
        }

        grid.innerHTML = accounts.map(acc => {
            const pnlClass = acc.net_pnl >= 0 ? "val-green" : "val-red";
            const pnlSign = acc.net_pnl >= 0 ? "+" : "";
            return `
            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">${acc.name}</div>
                        <span class="ticker-label">ID: ${acc.id} • Tőkeáttétel: 1:${acc.leverage}</span>
                    </div>
                    <span class="card-tag">${acc.currency}</span>
                </div>
                <div class="card-stats">
                    <div class="stat-box">
                        <div class="stat-label">Egyenleg</div>
                        <div class="stat-val">$${parseFloat(acc.balance).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Equity (Tőke)</div>
                        <div class="stat-val val-cyan">$${parseFloat(acc.equity).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Realizált PnL</div>
                        <div class="stat-val ${pnlClass}">${pnlSign}$${parseFloat(acc.net_pnl || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Win Rate</div>
                        <div class="stat-val">${acc.win_rate || 0}% (${acc.total_trades || 0} kötés)</div>
                    </div>
                </div>
            </div>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading accounts:", e);
    }
}

async function createNewAccount(e) {
    e.preventDefault();
    const id = document.getElementById("new-acc-id").value;
    const name = document.getElementById("new-acc-name").value;
    const balance = parseFloat(document.getElementById("new-acc-balance").value);
    const leverage = parseInt(document.getElementById("new-acc-leverage").value);

    try {
        const res = await fetch("/api/accounts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id, name, initial_balance: balance, leverage })
        });
        if (res.ok) {
            closeModal("modal-account");
            loadAccounts();
        } else {
            const err = await res.json();
            alert("Hiba: " + err.detail);
        }
    } catch (e) {
        alert("Hiba történt: " + e.message);
    }
}

// --- Active Strategies ---
async function loadActiveStrategies() {
    try {
        const res = await fetch("/api/active-strategies");
        const strategies = await res.json();
        const tbody = document.getElementById("active-strategies-body");
        if (!tbody) return;

        if (strategies.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-muted" style="text-align:center;">Jelenleg nem fut aktív stratégia demó számlán.</td></tr>`;
            return;
        }

        tbody.innerHTML = strategies.map(s => {
            const isRunning = s.status === "RUNNING";
            const badge = isRunning 
                ? `<span class="status-badge status-live"><span class="pulsing-dot"></span> FUT</span>` 
                : `<span class="status-badge" style="background:rgba(239,68,68,0.15); color:var(--accent-red)">LEÁLLÍTVA</span>`;
            
            const actionBtn = isRunning
                ? `<button class="btn btn-danger btn-sm" onclick="stopStrategy('${s.strategy_id}')">Leállítás</button>`
                : `<button class="btn btn-primary btn-sm" onclick="restartStrategy('${s.strategy_name}', '${s.account_id}', '${s.symbol}', '${s.timeframe}')">Indítás</button>`;

            return `
            <tr>
                <td><strong>${s.strategy_name}</strong></td>
                <td>${s.account_name || s.account_id}</td>
                <td><span class="card-tag">${s.symbol}</span></td>
                <td>${s.timeframe}</td>
                <td>${badge}</td>
                <td>${s.started_at}</td>
                <td>${actionBtn}</td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading active strategies:", e);
    }
}

async function startNewStrategy(e) {
    e.preventDefault();
    const strategy_key = document.getElementById("strategy-select").value;
    const account_id = document.getElementById("strategy-account-select").value;
    const symbol = document.getElementById("strategy-symbol").value;
    const timeframe = document.getElementById("strategy-timeframe").value;
    const volume = parseFloat(document.getElementById("strategy-volume").value);

    try {
        const res = await fetch("/api/active-strategies/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ strategy_key, account_id, symbol, timeframe, volume })
        });
        if (res.ok) {
            closeModal("modal-start-strategy");
            loadActiveStrategies();
            loadAccounts();
        } else {
            const err = await res.json();
            alert("Hiba: " + err.detail);
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

async function stopStrategy(strategyId) {
    try {
        const res = await fetch("/api/active-strategies/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ strategy_id: strategyId })
        });
        if (res.ok) {
            loadActiveStrategies();
        }
    } catch (e) {
        console.error("Error stopping strategy:", e);
    }
}

// --- Positions & Trades ---
async function loadPositions() {
    try {
        const res = await fetch("/api/positions");
        const positions = await res.json();
        const tbody = document.getElementById("positions-body");
        if (!tbody) return;

        if (positions.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-muted" style="text-align:center;">Nincs nyitott pozíció.</td></tr>`;
            return;
        }

        tbody.innerHTML = positions.map(pos => {
            const sideClass = pos.side === "BUY" ? "val-green" : "val-red";
            const pnlClass = pos.unrealized_pnl >= 0 ? "val-green" : "val-red";
            const pnlSign = pos.unrealized_pnl >= 0 ? "+" : "";
            return `
            <tr>
                <td><span class="card-tag">${pos.symbol}</span></td>
                <td><strong class="${sideClass}">${pos.side}</strong></td>
                <td>${pos.volume} lot</td>
                <td>${pos.open_price.toFixed(5)}</td>
                <td>${pos.current_price.toFixed(5)}</td>
                <td>${pos.stop_loss ? pos.stop_loss.toFixed(5) : '-'}</td>
                <td>${pos.take_profit ? pos.take_profit.toFixed(5) : '-'}</td>
                <td><strong class="${pnlClass}">${pnlSign}$${pos.unrealized_pnl.toFixed(2)}</strong></td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="closePosition('${pos.id}')">Zárás</button>
                </td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading positions:", e);
    }
}

async function closePosition(positionId) {
    try {
        const res = await fetch(`/api/positions/${positionId}/close`, { method: "POST" });
        if (res.ok) {
            loadPositions();
            loadAccounts();
            loadTrades();
        }
    } catch (e) {
        console.error("Error closing position:", e);
    }
}

async function loadTrades() {
    try {
        const res = await fetch("/api/trades");
        const trades = await res.json();
        const tbody = document.getElementById("trades-body");
        if (!tbody) return;

        if (trades.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Nincs korábbi lezárt kötés.</td></tr>`;
            return;
        }

        tbody.innerHTML = trades.map(t => {
            const sideClass = t.side === "BUY" ? "val-green" : "val-red";
            const pnlClass = t.pnl >= 0 ? "val-green" : "val-red";
            const pnlSign = t.pnl >= 0 ? "+" : "";
            const closeTime = new Date(t.close_time).toLocaleTimeString();
            return `
            <tr>
                <td><span class="card-tag">${t.symbol}</span></td>
                <td><strong class="${sideClass}">${t.side}</strong></td>
                <td>${t.volume} lot</td>
                <td>${t.open_price.toFixed(5)}</td>
                <td>${t.close_price.toFixed(5)}</td>
                <td><strong class="${pnlClass}">${pnlSign}$${t.pnl.toFixed(2)}</strong></td>
                <td><span class="ticker-label">${t.close_reason || 'MANUAL'}</span></td>
                <td>${closeTime}</td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading trades:", e);
    }
}

// --- Backtest Hub ---
async function loadBacktests() {
    try {
        const res = await fetch("/api/backtests");
        const runs = await res.json();
        const tbody = document.getElementById("backtest-runs-body");
        if (!tbody) return;

        if (runs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-muted" style="text-align:center;">Még nem futott visszateszt. Indíts egyet fent!</td></tr>`;
            return;
        }

        tbody.innerHTML = runs.map(r => {
            const retClass = r.return_pct >= 0 ? "val-green" : "val-red";
            const reportBtn = r.html_report_path 
                ? `<a href="/reports/${r.html_report_path}" target="_blank" class="btn btn-secondary btn-sm">📊 Bokeh Grafikon</a>`
                : '-';

            return `
            <tr>
                <td><strong>${r.strategy_name}</strong></td>
                <td><span class="card-tag">${r.symbol} (${r.timeframe})</span></td>
                <td>${r.start_date} -> ${r.end_date}</td>
                <td>$${r.initial_cash.toLocaleString()}</td>
                <td>$${r.final_equity.toLocaleString()}</td>
                <td><strong class="${retClass}">${r.return_pct}%</strong></td>
                <td>${r.sharpe_ratio}</td>
                <td>${r.win_rate_pct}% (${r.total_trades})</td>
                <td>${reportBtn}</td>
            </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading backtests:", e);
    }
}

async function runBacktestForm(e) {
    e.preventDefault();
    const btn = document.getElementById("btn-run-backtest");
    const originalText = btn.innerHTML;
    btn.innerHTML = `⏳ Futtatás folyamatban...`;
    btn.disabled = true;

    const strategy_key = document.getElementById("bt-strategy").value;
    const symbol = document.getElementById("bt-symbol").value;
    const timeframe = document.getElementById("bt-timeframe").value;
    const cash = parseFloat(document.getElementById("bt-cash").value);

    try {
        const res = await fetch("/api/backtests/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ strategy_key, symbol, timeframe, cash })
        });
        if (res.ok) {
            const result = await res.json();
            loadBacktests();
            if (result.report_file) {
                window.open(`/reports/${result.report_file}`, "_blank");
            }
        } else {
            const err = await res.json();
            alert("Hiba a visszateszt során: " + err.detail);
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// --- Strategy Catalog ---
async function loadStrategiesCatalog() {
    try {
        const res = await fetch("/api/strategies");
        const strategies = await res.json();
        const grid = document.getElementById("catalog-grid");
        const btSelect = document.getElementById("bt-strategy");
        const startSelect = document.getElementById("strategy-select");

        if (btSelect) {
            btSelect.innerHTML = strategies.map(s => `<option value="${s.key}">${s.name}</option>`).join("");
        }
        if (startSelect) {
            startSelect.innerHTML = strategies.map(s => `<option value="${s.key}">${s.name}</option>`).join("");
        }

        if (!grid) return;
        grid.innerHTML = strategies.map(s => `
            <div class="card">
                <div class="card-header">
                    <div class="card-title">${s.name}</div>
                    <span class="card-tag">${s.default_symbol} • ${s.default_timeframe}</span>
                </div>
                <p class="section-desc" style="margin-bottom: 16px;">${s.description}</p>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-primary btn-sm" onclick="openStartStrategyModal('${s.key}')">⚡ Indítás Demón</button>
                    <button class="btn btn-secondary btn-sm" onclick="openBacktestTab('${s.key}')">🧪 Visszateszt</button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading strategies catalog:", e);
    }
}

// --- Market & Data Management ---
async function loadMarketStats() {
    try {
        const res = await fetch(`/api/market/stats?symbol=${currentSymbol}`);
        const data = await res.json();
        
        const tickCountEl = document.getElementById("stat-total-ticks");
        const symbolTicksEl = document.getElementById("stat-symbol-ticks");
        if (tickCountEl) tickCountEl.textContent = data.total_ticks.toLocaleString();
        if (symbolTicksEl) symbolTicksEl.textContent = data.symbol_ticks.toLocaleString();

        if (data.download_state && data.download_state.is_running) {
            updateDownloadProgress(data.download_state);
        }
    } catch (e) {
        console.error("Error loading market stats:", e);
    }
}

function updateDownloadProgress(state) {
    const box = document.getElementById("download-progress-box");
    const bar = document.getElementById("download-bar-inner");
    const msg = document.getElementById("download-msg");
    const pct = document.getElementById("download-pct");

    if (box) box.style.display = "block";
    if (bar) bar.style.width = `${state.percent}%`;
    if (pct) pct.textContent = `${state.percent}%`;
    if (msg) msg.textContent = state.message;

    if (!state.is_running && state.percent >= 100) {
        setTimeout(() => {
            if (box) box.style.display = "none";
            loadMarketStats();
            loadHistoricalCoverage();
        }, 4000);
    }
}

async function triggerHistoricalDownload(e) {
    e.preventDefault();
    const symbol = document.getElementById("dl-symbol").value;
    const from_date = document.getElementById("dl-from").value;
    const to_date = document.getElementById("dl-to").value;

    try {
        const res = await fetch("/api/market/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol, from_date, to_date, chunk_days: 7 })
        });
        if (res.ok) {
            loadMarketStats();
            loadHistoricalCoverage();
        } else {
            const err = await res.json();
            alert("Hiba: " + err.detail);
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

// --- Modal Helpers ---
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add("active");
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove("active");
}

function openStartStrategyModal(strategyKey) {
    const select = document.getElementById("strategy-select");
    if (select) select.value = strategyKey;
    openModal("modal-start-strategy");
}

function openBacktestTab(strategyKey) {
    const tab = document.querySelector('[data-tab="backtest-tab"]');
    if (tab) tab.click();
    const select = document.getElementById("bt-strategy");
    if (select) select.value = strategyKey;
}
