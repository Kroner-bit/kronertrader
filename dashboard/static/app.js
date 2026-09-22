// KronerTrader Platform Dashboard Client
let ws = null;
let currentSymbol = "EURUSD";
let allInstruments = [];
const streamTickHistory = new Map();

function getSymbolSpec(symbol) {
    if (!symbol) return { digits: 5, mult: 10000, unit: "pip" };
    const s = symbol.toUpperCase().trim();
    if (s.includes("IDX") || s.includes("INDEX")) {
        return { digits: 2, mult: 1.0, unit: "pt" };
    }
    if (s.includes("BTC")) {
        return { digits: 1, mult: 1.0, unit: "USD" };
    }
    if (s.includes("ETH")) {
        return { digits: 2, mult: 1.0, unit: "USD" };
    }
    if (s.includes("XAU") || s.includes("GOLD")) {
        return { digits: 2, mult: 1.0, unit: "USD" };
    }
    if (s.includes("XAG") || s.includes("SILVER")) {
        return { digits: 3, mult: 1.0, unit: "USD" };
    }
    if (s.includes("CMD") || s.includes("OIL") || s.includes("BRENT") || s.includes("LIGHT")) {
        return { digits: 2, mult: 1.0, unit: "USD" };
    }
    if (s.includes("JPY")) {
        return { digits: 3, mult: 100.0, unit: "pip" };
    }
    return { digits: 5, mult: 10000.0, unit: "pip" };
}

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
    loadDownloadsTab();

    window.addEventListener("resize", () => {
        renderAllSquareCharts();
    });

    // Auto refresh fallback for polling when needed
    setInterval(() => {
        loadMarketStats();
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            loadPositions();
            loadTrades();
            loadAccounts();
            loadActiveStrategies();
            loadDownloadsTab();
        }
    }, 2000);
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
            if (target === "charts-tab") {
                loadLiveStreams();
                setTimeout(renderAllSquareCharts, 40);
            }
            if (target === "active-tab") loadActiveStrategies();
            if (target === "backtest-tab") loadBacktests();
            if (target === "catalog-tab") loadStrategiesCatalog();
            if (target === "data-tab") {
                loadMarketStats();
                loadHistoricalCoverage();
                loadLiveStreams();
            }
            if (target === "downloads-tab") {
                loadDownloadsTab();
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
        console.log("WebSocket connected to KronerTrader live feed");
        const badge = document.getElementById("connection-status");
        if (badge) {
            badge.innerHTML = `<span class="pulsing-dot"></span> FEED AKTÍV`;
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
                renderLiveStreamCharts(data.active_streams);
            }
            if (data.ticks) {
                for (const [sym, tick] of Object.entries(data.ticks)) {
                    if (!streamTickHistory.has(sym)) {
                        streamTickHistory.set(sym, []);
                    }
                    const hist = streamTickHistory.get(sym);
                    const last = hist[hist.length - 1];
                    if (!last || last.bid !== tick.bid || last.ask !== tick.ask || last.timestamp !== tick.timestamp) {
                        hist.push({ bid: parseFloat(tick.bid), ask: parseFloat(tick.ask), timestamp: tick.timestamp });
                        if (hist.length > 10) hist.shift();
                        drawSquareChart(sym);
                    }
                }
            }
            if (data.open_positions) {
                renderPositions(data.open_positions);
            }
            if (data.trades) {
                renderTrades(data.trades);
            }
            if (data.accounts) {
                renderAccounts(data.accounts);
            }
            if (data.active_strategies) {
                renderActiveStrategies(data.active_strategies);
            }
            if (data.download_state) {
                updateDownloadProgress(data.download_state);
            }
            if (data.download_jobs) {
                renderDownloadsTabFromWs(data.download_jobs, data.active_streams);
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
    const spec = getSymbolSpec(tick.symbol || "EURUSD");

    if (bidEl) bidEl.textContent = parseFloat(tick.bid).toFixed(spec.digits);
    if (askEl) askEl.textContent = parseFloat(tick.ask).toFixed(spec.digits);
    if (spreadEl) {
        const spread = ((parseFloat(tick.ask) - parseFloat(tick.bid)) * spec.mult).toFixed(1);
        spreadEl.textContent = `${spread} ${spec.unit}`;
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
        const newAccSymbol = document.getElementById("new-acc-symbol");

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
        if (newAccSymbol) {
            newAccSymbol.innerHTML = optionsHtml;
            newAccSymbol.value = "EURUSD";
        }
        const manualDlSymbol = document.getElementById("manual-dl-symbol");
        if (manualDlSymbol) {
            manualDlSymbol.innerHTML = optionsHtml;
            manualDlSymbol.value = "EURUSD";
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
            const spec = getSymbolSpec(c.symbol);
            const latestPrice = c.latest_bid ? `${c.latest_bid.toFixed(spec.digits)} / ${c.latest_ask.toFixed(spec.digits)}` : "-";
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
                    <button class="btn btn-secondary btn-sm" onclick="startBacktestForSymbol('${c.symbol}')">Visszateszt</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteSymbolCoverage('${c.symbol}')">Törlés</button>
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
        renderLiveStreamCharts(streams);
    } catch (e) {
        console.error("Error loading live streams:", e);
    }
}

// --- Live Square Charts (Bid / Ask 10-Point Rolling Line Chart) ---
function renderLiveStreamCharts(streams) {
    const grid = document.getElementById("stream-charts-grid");
    if (!grid) return;

    if (!streams || streams.length === 0) {
        grid.innerHTML = `<div class="card" style="grid-column: 1 / -1;"><p class="text-muted">Jelenleg nincs aktív élő stream közvetítés. Hozz létre egy új demó számlát kiválasztott devizapárokkal, vagy adj hozzá tickert felül!</p></div>`;
        return;
    }

    const emptyNotice = grid.querySelector(".card");
    if (emptyNotice && streams.length > 0) {
        grid.innerHTML = "";
    }

    streams.forEach(s => {
        let card = document.getElementById(`chart-card-${s.symbol}`);
        if (!card) {
            const cardHtml = `
            <div class="square-chart-card" id="chart-card-${s.symbol}">
                <div class="square-chart-header">
                    <div class="square-chart-title">
                        <span>${s.symbol}</span>
                        <span class="card-tag" style="font-size: 9px; padding: 1px 4px;">LIVE</span>
                    </div>
                    <span class="square-chart-spread" id="chart-spread-${s.symbol}">-</span>
                </div>
                <div class="square-chart-canvas-wrap">
                    <canvas id="canvas-${s.symbol}" class="square-canvas"></canvas>
                </div>
                <div class="square-chart-footer">
                    <div>BID: <strong class="val-green" id="chart-bid-${s.symbol}">-</strong></div>
                    <div>ASK: <strong class="val-red" id="chart-ask-${s.symbol}">-</strong></div>
                </div>
            </div>`;
            grid.insertAdjacentHTML("beforeend", cardHtml);
        }

        if (!streamTickHistory.has(s.symbol)) {
            streamTickHistory.set(s.symbol, []);
        }

        if (s.bid && s.ask) {
            const hist = streamTickHistory.get(s.symbol);
            const last = hist[hist.length - 1];
            if (!last || last.bid !== s.bid || last.ask !== s.ask) {
                hist.push({ bid: parseFloat(s.bid), ask: parseFloat(s.ask), timestamp: s.last_ts || Date.now() });
                if (hist.length > 10) hist.shift();
                drawSquareChart(s.symbol);
            }
        }
    });

    const activeSymbols = new Set(streams.map(s => s.symbol));
    const currentCards = grid.querySelectorAll(".square-chart-card");
    currentCards.forEach(c => {
        const id = c.id.replace("chart-card-", "");
        if (!activeSymbols.has(id)) {
            c.remove();
            streamTickHistory.delete(id);
        }
    });
}

function drawSquareChart(symbol) {
    const canvas = document.getElementById(`canvas-${symbol}`);
    if (!canvas) return;

    const wrap = canvas.parentElement;
    if (!wrap) return;

    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    if (w === 0 || h === 0) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;

    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const ticks = streamTickHistory.get(symbol) || [];
    if (ticks.length === 0) {
        ctx.fillStyle = "#8492a6";
        ctx.font = "11px monospace";
        ctx.fillText("Adatfolyam inicializálása...", 12, 24);
        return;
    }

    const spec = getSymbolSpec(symbol);

    let minPrice = Infinity;
    let maxPrice = -Infinity;
    ticks.forEach(t => {
        if (t.bid < minPrice) minPrice = t.bid;
        if (t.ask > maxPrice) maxPrice = t.ask;
    });

    const minDelta = spec.unit === "pip" ? (spec.digits === 3 ? 0.05 : 0.0005) : (spec.digits <= 2 ? 1.0 : 0.05);
    if (minPrice === maxPrice || !isFinite(minPrice) || !isFinite(maxPrice)) {
        minPrice = (ticks[0].bid || 1.0) - minDelta;
        maxPrice = (ticks[0].ask || 1.0) + minDelta;
    }

    const padPrice = Math.max((maxPrice - minPrice) * 0.15, minDelta * 0.2);
    minPrice -= padPrice;
    maxPrice += padPrice;
    const range = Math.max(maxPrice - minPrice, 0.00001);

    const padX = 12;
    const padY = 12;
    const chartW = w - padX * 2;
    const chartH = h - padY * 2;

    const getY = (val) => padY + chartH - ((val - minPrice) / range) * chartH;
    const getX = (idx, total) => padX + (idx / Math.max(1, total - 1)) * chartW;

    ctx.strokeStyle = "#202938";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padX, padY + chartH / 2);
    ctx.lineTo(w - padX, padY + chartH / 2);
    ctx.stroke();

    // 1. Draw Bid Line (Green)
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ticks.forEach((t, i) => {
        const x = getX(i, ticks.length);
        const y = getY(t.bid);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const lastIdx = ticks.length - 1;
    const lastX = getX(lastIdx, ticks.length);
    const lastBidY = getY(ticks[lastIdx].bid);
    ctx.fillStyle = "#22c55e";
    ctx.beginPath();
    ctx.arc(lastX, lastBidY, 3, 0, Math.PI * 2);
    ctx.fill();

    // 2. Draw Ask Line (Red)
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ticks.forEach((t, i) => {
        const x = getX(i, ticks.length);
        const y = getY(t.ask);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const lastAskY = getY(ticks[lastIdx].ask);
    ctx.fillStyle = "#ef4444";
    ctx.beginPath();
    ctx.arc(lastX, lastAskY, 3, 0, Math.PI * 2);
    ctx.fill();

    const lastTick = ticks[lastIdx];
    const bidEl = document.getElementById(`chart-bid-${symbol}`);
    const askEl = document.getElementById(`chart-ask-${symbol}`);
    const spreadEl = document.getElementById(`chart-spread-${symbol}`);

    if (bidEl) bidEl.textContent = lastTick.bid.toFixed(spec.digits);
    if (askEl) askEl.textContent = lastTick.ask.toFixed(spec.digits);
    if (spreadEl) {
        const spread = ((lastTick.ask - lastTick.bid) * spec.mult).toFixed(1);
        spreadEl.textContent = `Spread: ${spread} ${spec.unit}`;
    }
}

function renderAllSquareCharts() {
    for (const sym of streamTickHistory.keys()) {
        drawSquareChart(sym);
    }
}

function renderLiveStreamsTable(streams) {
    const tbody = document.getElementById("live-streams-body");
    if (!tbody) return;

    if (!streams || streams.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-muted" style="text-align:center;">Jelenleg nincs aktív élő stream feliratkozás.</td></tr>`;
        return;
    }

    tbody.innerHTML = streams.map(s => {
        const spec = getSymbolSpec(s.symbol);
        const bid = s.bid ? parseFloat(s.bid).toFixed(spec.digits) : "-";
        const ask = s.ask ? parseFloat(s.ask).toFixed(spec.digits) : "-";
        const spread = (s.bid && s.ask) ? ((parseFloat(s.ask) - parseFloat(s.bid)) * spec.mult).toFixed(1) + " " + spec.unit : "-";

        const cov = s.coverage_info;
        let coverageCell = '';
        if (cov && cov.is_downloading) {
            coverageCell = `
                <div style="display: flex; align-items: center; gap: 4px;">
                    <span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid #3b82f6; padding: 2px 6px; font-size: 11px;">
                        <span class="pulsing-dot" style="background: #3b82f6; width: 6px; height: 6px; display: inline-block;"></span>
                        Foltozás: ${(cov.job_percent || 0).toFixed(1)}%
                    </span>
                    <button class="btn btn-secondary btn-sm" onclick="stopDownloadJob('${cov.active_job_id || s.symbol}')" style="color: #f87171; border-color: #ef4444; padding: 1px 6px; font-size: 10px;" title="Letöltés leállítása">✕</button>
                </div>
            `;
        } else if (cov && cov.has_one_year) {
            coverageCell = `
                <span class="badge" style="background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid #22c55e; padding: 2px 6px; font-size: 11px;">
                    ✓ 1 Év Megvan (${cov.coverage_pct}%)
                </span>
            `;
        } else {
            const missingDays = cov ? cov.missing_days : 365;
            coverageCell = `
                <button class="btn btn-primary btn-sm" onclick="startGapDownload('${s.symbol}')" style="background: #2563eb; color: #fff; padding: 3px 8px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px;" title="Hiányzó adatok letöltése és foltozása">
                    📥 1 Év Letöltése <span style="opacity: 0.85; font-size: 10px;">(${missingDays} nap hiány)</span>
                </button>
            `;
        }

        return `
        <tr>
            <td><strong>${s.symbol}</strong></td>
            <td>${s.name}</td>
            <td class="val-green"><code>${bid}</code></td>
            <td class="val-red"><code>${ask}</code></td>
            <td>${spread}</td>
            <td>${coverageCell}</td>
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
function renderAccounts(accounts) {
    if (!accounts) return;
    const grid = document.getElementById("accounts-grid");
    const select = document.getElementById("strategy-account-select");

    if (select) {
        const curVal = select.value;
        select.innerHTML = accounts.map(a => `<option value="${a.id}">${a.name} ($${parseFloat(a.balance).toLocaleString()})</option>`).join("");
        if (curVal && accounts.some(a => a.id === curVal)) {
            select.value = curVal;
        }
    }

    if (!grid) return;
    if (accounts.length === 0) {
        grid.innerHTML = `<div class="card"><p class="text-muted">Nincs elérhető demó számla.</p></div>`;
        return;
    }

    grid.innerHTML = accounts.map(acc => {
        const pnl = parseFloat(acc.net_pnl || 0);
        const pnlClass = pnl >= 0 ? "val-green" : "val-red";
        const pnlSign = pnl >= 0 ? "+" : "";
        const stratBadge = (acc.active_strategies && acc.active_strategies.length > 0)
            ? `<div style="margin-top: 4px; font-size: 10px; color: var(--accent-green-bright); font-family: var(--font-mono);">● ${acc.active_strategies.map(s => `${s.strategy} (${s.symbol} ${s.timeframe})`).join(", ")}</div>`
            : '';

        return `
        <div class="card">
            <div class="card-header">
                <div>
                    <div class="card-title">${acc.name}</div>
                    <span class="ticker-label">ID: ${acc.id} • Tőkeáttétel: 1:${acc.leverage}</span>
                    ${stratBadge}
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="card-tag">${acc.currency}</span>
                    <button class="btn btn-danger btn-sm" onclick="deleteAccount('${acc.id}', '${acc.name}')" title="Demó számla törlése">Törlés</button>
                </div>
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
                    <div class="stat-val ${pnlClass}">${pnlSign}$${pnl.toLocaleString(undefined, {minimumFractionDigits: 2})}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-val">${acc.win_rate || 0}% (${acc.total_trades || 0} kötés)</div>
                </div>
            </div>
        </div>
        `;
    }).join("");
}

async function loadAccounts() {
    try {
        const res = await fetch("/api/accounts");
        const accounts = await res.json();
        renderAccounts(accounts);
    } catch (e) {
        console.error("Error loading accounts:", e);
    }
}

async function deleteAccount(accountId, accountName) {
    const displayName = accountName || accountId;
    if (!confirm(`Biztosan törölni szeretnéd a(z) "${displayName}" demó számlát?\n\nA számlához tartozó összes nyitott pozíció és futó stratégia is leáll és véglegesen törlődik.`)) {
        return;
    }
    try {
        const res = await fetch(`/api/accounts/${accountId}`, { method: "DELETE" });
        if (res.ok) {
            loadAccounts();
            loadActiveStrategies();
            loadPositions();
            loadTrades();
        } else {
            const err = await res.json();
            alert("Hiba a számla törlésekor: " + (err.detail || "Ismeretlen hiba"));
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

async function createNewAccount(e) {
    e.preventDefault();
    const id = document.getElementById("new-acc-id").value;
    const name = document.getElementById("new-acc-name").value;
    const balance = parseFloat(document.getElementById("new-acc-balance").value);
    const leverage = parseInt(document.getElementById("new-acc-leverage").value);

    // Stream checkboxes
    const checkboxes = document.querySelectorAll('input[name="stream_pair"]:checked');
    const stream_symbols = Array.from(checkboxes).map(cb => cb.value);

    // Strategy assignment
    const strategy_key = document.getElementById("new-acc-strategy") ? document.getElementById("new-acc-strategy").value : null;
    const strategy_symbol = document.getElementById("new-acc-symbol") ? document.getElementById("new-acc-symbol").value : null;
    const strategy_timeframe = document.getElementById("new-acc-timeframe") ? document.getElementById("new-acc-timeframe").value : "1m";
    const strategy_volume = document.getElementById("new-acc-volume") ? parseFloat(document.getElementById("new-acc-volume").value) : 0.1;

    try {
        const res = await fetch("/api/accounts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                id,
                name,
                initial_balance: balance,
                leverage,
                stream_symbols,
                strategy_key,
                strategy_symbol,
                strategy_timeframe,
                strategy_volume
            })
        });
        if (res.ok) {
            closeModal("modal-account");
            loadAccounts();
            loadActiveStrategies();
            loadLiveStreams();
            // Switch to live charts tab to immediately see the streams!
            const chartsTabBtn = document.querySelector('[data-tab="charts-tab"]');
            if (chartsTabBtn) chartsTabBtn.click();
        } else {
            const err = await res.json();
            alert("Hiba: " + err.detail);
        }
    } catch (e) {
        alert("Hiba történt: " + e.message);
    }
}

// --- Active Strategies ---
function renderActiveStrategies(strategies) {
    if (!strategies) return;
    const tbody = document.getElementById("active-strategies-body");
    if (!tbody) return;

    if (strategies.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-muted" style="text-align:center;">Jelenleg nem fut aktív stratégia demó számlán.</td></tr>`;
        return;
    }

    tbody.innerHTML = strategies.map(s => {
        const isRunning = s.status === "RUNNING";
        const badge = isRunning 
            ? `<span class="status-badge status-live"><span class="pulsing-dot"></span> AKTÍV</span>` 
            : `<span class="status-badge" style="background:var(--accent-red-bg); color:var(--accent-red-bright); border-color:#991b1b">LEÁLLÍTVA</span>`;
        
        const actionBtns = `
            <div style="display: flex; gap: 6px; align-items: center;">
                ${isRunning
                    ? `<button class="btn btn-secondary btn-sm" onclick="stopStrategy('${s.strategy_id}')">Leállítás</button>`
                    : `<button class="btn btn-primary btn-sm" onclick="restartStrategy('${s.strategy_id}', '${s.account_id}', '${s.symbol}', '${s.timeframe}')">Indítás</button>`}
                <button class="btn btn-danger btn-sm" onclick="deleteStrategy('${s.strategy_id}', '${s.strategy_name}')" title="Stratégia végleges törlése">Törlés</button>
            </div>
        `;

        return `
        <tr>
            <td><strong>${s.strategy_name}</strong></td>
            <td>${s.account_name || s.account_id}</td>
            <td><span class="card-tag">${s.symbol}</span></td>
            <td>${s.timeframe}</td>
            <td>${badge}</td>
            <td>${s.started_at}</td>
            <td>${actionBtns}</td>
        </tr>
        `;
    }).join("");
}

async function loadActiveStrategies() {
    try {
        const res = await fetch("/api/active-strategies");
        const strategies = await res.json();
        renderActiveStrategies(strategies);
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
            loadAccounts();
        }
    } catch (e) {
        console.error("Error stopping strategy:", e);
    }
}

async function deleteStrategy(strategyId, strategyName) {
    const displayName = strategyName || strategyId;
    if (!confirm(`Biztosan törölni szeretnéd a(z) "${displayName}" stratégiát a rendszerből?`)) {
        return;
    }
    try {
        const res = await fetch(`/api/active-strategies/${strategyId}`, { method: "DELETE" });
        if (res.ok) {
            loadActiveStrategies();
            loadAccounts();
        } else {
            const err = await res.json();
            alert("Hiba a stratégia törlésekor: " + (err.detail || "Ismeretlen hiba"));
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

async function restartStrategy(strategyId, accountId, symbol, timeframe) {
    const parts = strategyId.split("_");
    const strategy_key = parts.length > 2 ? parts.slice(0, -1).join("_") : parts[0];
    try {
        const res = await fetch("/api/active-strategies/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                strategy_key,
                account_id: accountId,
                symbol,
                timeframe,
                volume: 0.1
            })
        });
        if (res.ok) {
            loadActiveStrategies();
            loadAccounts();
        } else {
            const err = await res.json();
            alert("Hiba a stratégia újraindításakor: " + (err.detail || "Ismeretlen hiba"));
        }
    } catch (e) {
        alert("Hiba: " + e.message);
    }
}

// --- Positions & Trades ---
function renderPositions(positions) {
    if (!positions) return;
    const tbody = document.getElementById("positions-body");
    if (!tbody) return;

    if (positions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-muted" style="text-align:center;">Nincs nyitott pozíció.</td></tr>`;
        return;
    }

    tbody.innerHTML = positions.map(pos => {
        const spec = getSymbolSpec(pos.symbol);
        const sideClass = pos.side === "BUY" ? "val-green" : "val-red";
        const pnl = parseFloat(pos.unrealized_pnl || 0);
        const pnlClass = pnl >= 0 ? "val-green" : "val-red";
        const pnlSign = pnl >= 0 ? "+" : "";
        const openPrice = parseFloat(pos.open_price);
        const currPrice = parseFloat(pos.current_price || pos.open_price);
        return `
        <tr>
            <td><span class="card-tag">${pos.symbol}</span></td>
            <td><strong class="${sideClass}">${pos.side}</strong></td>
            <td>${pos.volume} lot</td>
            <td>${openPrice.toFixed(spec.digits)}</td>
            <td>${currPrice.toFixed(spec.digits)}</td>
            <td>${pos.stop_loss ? parseFloat(pos.stop_loss).toFixed(spec.digits) : '-'}</td>
            <td>${pos.take_profit ? parseFloat(pos.take_profit).toFixed(spec.digits) : '-'}</td>
            <td><strong class="${pnlClass}">${pnlSign}$${pnl.toFixed(2)}</strong></td>
            <td>
                <button class="btn btn-danger btn-sm" onclick="closePosition('${pos.id}')">Zárás</button>
            </td>
        </tr>
        `;
    }).join("");
}

async function loadPositions() {
    try {
        const res = await fetch("/api/positions");
        const positions = await res.json();
        renderPositions(positions);
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

function renderTrades(trades) {
    if (!trades) return;
    const tbody = document.getElementById("trades-body");
    if (!tbody) return;

    if (trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Nincs korábbi lezárt kötés.</td></tr>`;
        return;
    }

    tbody.innerHTML = trades.map(t => {
        const spec = getSymbolSpec(t.symbol);
        const sideClass = t.side === "BUY" ? "val-green" : "val-red";
        const pnl = parseFloat(t.pnl || 0);
        const pnlClass = pnl >= 0 ? "val-green" : "val-red";
        const pnlSign = pnl >= 0 ? "+" : "";
        const closeTime = t.close_time ? new Date(t.close_time).toLocaleTimeString() : '-';
        const openPrice = parseFloat(t.open_price);
        const closePrice = parseFloat(t.close_price);
        return `
        <tr>
            <td><span class="card-tag">${t.symbol}</span></td>
            <td><strong class="${sideClass}">${t.side}</strong></td>
            <td>${t.volume} lot</td>
            <td>${openPrice.toFixed(spec.digits)}</td>
            <td>${closePrice.toFixed(spec.digits)}</td>
            <td><strong class="${pnlClass}">${pnlSign}$${pnl.toFixed(2)}</strong></td>
            <td><span class="ticker-label">${t.close_reason || 'MANUAL'}</span></td>
            <td>${closeTime}</td>
        </tr>
        `;
    }).join("");
}

async function loadTrades() {
    try {
        const res = await fetch("/api/trades");
        const trades = await res.json();
        renderTrades(trades);
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
                ? `<a href="/reports/${r.html_report_path}" target="_blank" class="btn btn-secondary btn-sm">Bokeh Riport</a>`
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
    btn.innerHTML = `Futtatás folyamatban...`;
    btn.disabled = true;

    const strategy_key = document.getElementById("bt-strategy").value;
    const symbol = document.getElementById("bt-symbol").value;
    const timeframe = document.getElementById("bt-timeframe").value;
    const cash = parseFloat(document.getElementById("bt-cash").value);
    const from_date = document.getElementById("bt-from") ? (document.getElementById("bt-from").value || null) : null;
    const to_date = document.getElementById("bt-to") ? (document.getElementById("bt-to").value || null) : null;

    try {
        const res = await fetch("/api/backtests/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ strategy_key, symbol, timeframe, cash, from_date, to_date })
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
        const newAccStrat = document.getElementById("new-acc-strategy");

        if (btSelect) {
            btSelect.innerHTML = strategies.map(s => `<option value="${s.key}">${s.name}</option>`).join("");
        }
        if (startSelect) {
            startSelect.innerHTML = strategies.map(s => `<option value="${s.key}">${s.name}</option>`).join("");
        }
        if (newAccStrat) {
            newAccStrat.innerHTML = strategies.map(s => `<option value="${s.key}">${s.name}</option>`).join("");
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
                    <button class="btn btn-primary btn-sm" onclick="openStartStrategyModal('${s.key}')">Indítás Demón</button>
                    <button class="btn btn-secondary btn-sm" onclick="openBacktestTab('${s.key}')">Visszateszt</button>
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

        if (data.download_state) {
            updateDownloadProgress(data.download_state);
        }
    } catch (e) {
        console.error("Error loading market stats:", e);
    }
}

let downloadNotificationTimer = null;
let activeDownloadInProgress = false;

function updateDownloadProgress(state) {
    const box = document.getElementById("download-progress-box");
    const bar = document.getElementById("download-bar-inner");
    const msg = document.getElementById("download-msg");
    const pct = document.getElementById("download-pct");

    const badge = document.getElementById("auto-download-badge");
    const badgeText = document.getElementById("auto-download-text");
    const badgeDot = document.getElementById("auto-download-dot");
    const headerStopBtn = document.getElementById("header-stop-btn");
    const tabStopBtn = document.getElementById("tab-stop-btn");

    // Case 1: Empty / Idle state
    if (!state || (!state.is_running && (!state.message || state.message === "" || state.status === "IDLE"))) {
        if (!downloadNotificationTimer) {
            if (box) box.style.display = "none";
            if (badge) badge.style.display = "none";
            if (headerStopBtn) headerStopBtn.style.display = "none";
            if (tabStopBtn) tabStopBtn.style.display = "none";
        }
        activeDownloadInProgress = false;
        return;
    }

    // Case 2: Actively running download
    if (state.is_running) {
        activeDownloadInProgress = true;
        if (downloadNotificationTimer) {
            clearTimeout(downloadNotificationTimer);
            downloadNotificationTimer = null;
        }

        // Show data tab box and stop button
        if (box) box.style.display = "block";
        if (bar) bar.style.width = `${state.percent}%`;
        if (pct) pct.textContent = `${state.percent}%`;
        if (msg) msg.textContent = state.message;
        if (tabStopBtn) tabStopBtn.style.display = "inline-block";

        // Show top header badge with stop button
        if (badge && badgeText) {
            badge.style.display = "inline-flex";
            badge.style.background = "rgba(59, 130, 246, 0.15)";
            badge.style.borderColor = "#3b82f6";
            badge.style.color = "#60a5fa";
            if (badgeDot) {
                badgeDot.style.background = "#3b82f6";
                badgeDot.style.display = "inline-block";
            }
            if (headerStopBtn) {
                headerStopBtn.style.display = "inline-block";
            }
            const sym = state.symbol ? `[${state.symbol}] ` : "";
            const prefix = state.auto ? "1 ÉVES LETÖLTÉS" : "LETÖLTÉS";
            badgeText.textContent = `${sym}${prefix} (${state.percent}%)`;
        }
        return;
    }

    // Case 3: Stopped / Completed / Error (Transition from running, or one-shot notification)
    // Always hide stop buttons immediately!
    if (headerStopBtn) headerStopBtn.style.display = "none";
    if (tabStopBtn) tabStopBtn.style.display = "none";

    const isStopped = state.status === "STOPPED" || (state.message && (state.message.includes("leállítva") || state.message.includes("megszakítva")));
    const isCompleted = state.status === "COMPLETED" || state.percent >= 100;
    const isError = state.message && state.message.toLowerCase().includes("hiba");

    if (isStopped) {
        if (box) box.style.display = "block";
        if (bar) bar.style.width = "0%";
        if (pct) pct.textContent = "0%";
        if (msg) msg.textContent = state.message;

        if (badge && badgeText) {
            badge.style.display = "inline-flex";
            badge.style.background = "rgba(245, 158, 11, 0.15)";
            badge.style.borderColor = "#f59e0b";
            badge.style.color = "#fbbf24";
            if (badgeDot) badgeDot.style.background = "#f59e0b";
            const sym = state.symbol ? `[${state.symbol}] ` : "";
            badgeText.textContent = `✕ ${sym}LETÖLTÉS LEÁLLÍTVA`;
        }
    } else if (isCompleted) {
        if (box) box.style.display = "block";
        if (bar) bar.style.width = "100%";
        if (pct) pct.textContent = "100%";
        if (msg) msg.textContent = state.message;

        if (badge && badgeText) {
            badge.style.display = "inline-flex";
            badge.style.background = "rgba(34, 197, 94, 0.15)";
            badge.style.borderColor = "#22c55e";
            badge.style.color = "#4ade80";
            if (badgeDot) badgeDot.style.background = "#22c55e";
            const sym = state.symbol ? `[${state.symbol}] ` : "";
            badgeText.textContent = `✓ ${sym}1 ÉV ADAT KÉSZ`;
        }
    } else if (isError) {
        if (box) box.style.display = "block";
        if (msg) msg.textContent = state.message;

        if (badge && badgeText) {
            badge.style.display = "inline-flex";
            badge.style.background = "rgba(239, 68, 68, 0.15)";
            badge.style.borderColor = "#ef4444";
            badge.style.color = "#f87171";
            if (badgeDot) badgeDot.style.background = "#ef4444";
            badgeText.textContent = `⚠ LETÖLTÉSI HIBA`;
        }
    }

    if (!downloadNotificationTimer) {
        downloadNotificationTimer = setTimeout(() => {
            if (badge) badge.style.display = "none";
            if (box) box.style.display = "none";
            if (headerStopBtn) headerStopBtn.style.display = "none";
            if (tabStopBtn) tabStopBtn.style.display = "none";
            loadMarketStats();
            loadHistoricalCoverage();
            downloadNotificationTimer = null;
        }, 3000);
    }
    activeDownloadInProgress = false;
}

async function stopHistoricalDownload(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    const btnHeader = document.getElementById("header-stop-btn");
    const btnTab = document.getElementById("tab-stop-btn");
    if (btnHeader) {
        btnHeader.disabled = true;
        btnHeader.textContent = "...";
    }
    if (btnTab) {
        btnTab.disabled = true;
        btnTab.textContent = "Leállítás...";
    }

    try {
        const res = await fetch("/api/market/download/stop", {
            method: "POST"
        });
        const data = await res.json();
        console.log("Download stopped:", data);
        updateDownloadProgress({
            is_running: false,
            status: "STOPPED",
            percent: 0.0,
            message: data.message || "Letöltés leállítva a felhasználó által."
        });
        loadMarketStats();
        loadHistoricalCoverage();
    } catch (err) {
        console.error("Error stopping download:", err);
    } finally {
        if (btnHeader) {
            btnHeader.disabled = false;
            btnHeader.textContent = "✕ Leállítás";
            btnHeader.style.display = "none";
        }
        if (btnTab) {
            btnTab.disabled = false;
            btnTab.textContent = "✕ Letöltés Leállítása";
            btnTab.style.display = "none";
        }
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

// ==========================================================================
// Downloads & Smart Data Stitcher Manager (Independent background threads,
// gap filling, duplicate-free SQLite stitching, per-job cancellation)
// ==========================================================================

async function loadDownloadsTab() {
    try {
        const res = await fetch("/api/downloads");
        const data = await res.json();
        renderActiveDownloadJobs(data.active_jobs || []);
        renderCompletedDownloadJobs(data.completed_jobs || []);
        renderStreamsCoverageTable(data.streams_coverage || {});
    } catch (e) {
        console.error("Error loading downloads tab:", e);
    }
}

function renderDownloadsTabFromWs(downloadJobs, activeStreams) {
    if (!downloadJobs) return;
    renderActiveDownloadJobs(downloadJobs.active_jobs || []);
    renderCompletedDownloadJobs(downloadJobs.completed_jobs || []);

    const activeTab = document.querySelector(".nav-tab.active");
    if (activeTab && activeTab.getAttribute("data-tab") === "downloads-tab") {
        const coverageMap = {};
        if (activeStreams) {
            activeStreams.forEach(s => {
                if (s.coverage_info) {
                    coverageMap[s.symbol] = {
                        symbol: s.symbol,
                        name: s.name,
                        has_one_year: s.coverage_info.has_one_year,
                        missing_days_count: s.coverage_info.missing_days,
                        coverage_pct: s.coverage_info.coverage_pct,
                        total_ticks: s.coverage_info.total_ticks,
                        present_days_count: s.coverage_info.present_days,
                        total_gaps: s.coverage_info.gaps_count,
                        is_downloading: s.coverage_info.is_downloading,
                        job_percent: s.coverage_info.job_percent,
                        active_job_id: s.coverage_info.active_job_id
                    };
                }
            });
        }
        if (Object.keys(coverageMap).length > 0) {
            renderStreamsCoverageTable(coverageMap);
        }
    }
}

function renderActiveDownloadJobs(jobs) {
    const container = document.getElementById("active-downloads-container");
    const countBadge = document.getElementById("active-jobs-count-badge");
    if (countBadge) {
        countBadge.textContent = `${jobs.length} aktív`;
        countBadge.style.background = jobs.length > 0 ? "rgba(59, 130, 246, 0.25)" : "rgba(100, 116, 139, 0.2)";
        countBadge.style.color = jobs.length > 0 ? "#60a5fa" : "var(--text-muted)";
    }
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = `
            <div class="card" style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px;">
                Jelenleg nincs aktív letöltési folyamat a háttérben. Indíts egyet a Live Stream listából vagy a fenti gombbal!
            </div>
        `;
        return;
    }

    container.innerHTML = jobs.map(j => {
        const pct = (j.percent || 0).toFixed(1);
        const ticksImported = (j.total_ticks_imported || 0).toLocaleString();
        const isStopping = j.status === "STOPPING";
        const statusBadge = isStopping
            ? `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; padding: 2px 6px; font-size: 11px;">LEÁLLÍTÁS...</span>`
            : `<span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #3b82f6; padding: 2px 6px; font-size: 11px;"><span class="pulsing-dot" style="background:#3b82f6; width:6px; height:6px; display:inline-block; margin-right:4px;"></span>FOLTOZÁS</span>`;

        return `
        <div class="card" style="margin-bottom: 12px; border-left: 3px solid #3b82f6;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="card-tag" style="font-size: 13px; font-weight: 700;">${j.symbol}</span>
                    ${statusBadge}
                    <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">Indítva: ${j.started_at || '-'}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-family: var(--font-mono); font-size: 12px; font-weight: 700; color: #60a5fa;">${pct}%</span>
                    <button class="btn btn-danger btn-sm" onclick="stopDownloadJob('${j.job_id}')" ${isStopping ? 'disabled' : ''} style="padding: 3px 8px; font-size: 11px;">
                        ${isStopping ? 'Leállítás...' : '✕ Leállítás'}
                    </button>
                </div>
            </div>

            <!-- Progress bar -->
            <div class="progress-bar-wrap" style="height: 6px; margin-bottom: 8px; background: rgba(255,255,255,0.05);">
                <div class="progress-bar-inner" style="width: ${pct}%; height: 100%; background: #3b82f6;"></div>
            </div>

            <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono);">
                <div>
                    <span style="color: var(--text-muted);">Állapot:</span>
                    <span>${j.stitching_status || 'Foltozás...'}</span>
                </div>
                <div>
                    <span style="color: var(--text-muted);">Illesztett tickek:</span>
                    <strong class="val-cyan">${ticksImported} db</strong>
                </div>
            </div>
        </div>
        `;
    }).join("");
}

function renderStreamsCoverageTable(streamsCoverage) {
    const tbody = document.getElementById("streams-coverage-body");
    if (!tbody) return;

    const entries = Object.entries(streamsCoverage);
    if (entries.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Nincs aktív live stream szimbólum.</td></tr>`;
        return;
    }

    tbody.innerHTML = entries.map(([sym, cov]) => {
        const meta = (allInstruments || []).find(i => i.symbol === sym);
        const name = meta ? meta.name : (cov.name || sym);
        const totalTicks = (cov.total_ticks || 0).toLocaleString();
        const dateRange = (cov.min_date && cov.max_date && cov.min_date !== "-") ? `${cov.min_date} -> ${cov.max_date}` : "Nincs adat";
        const spanDays = cov.actual_span_days || 0;
        const missingDays = cov.missing_days_count !== undefined ? cov.missing_days_count : 365;

        let statusBadge = '';
        let actionBtn = '';

        if (cov.is_downloading) {
            statusBadge = `
                <span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid #3b82f6; padding: 2px 6px; font-size: 11px;">
                    <span class="pulsing-dot" style="background: #3b82f6; width: 6px; height: 6px; display: inline-block; margin-right:4px;"></span>
                    Folyamatban (${(cov.job_percent || 0).toFixed(1)}%)
                </span>
            `;
            actionBtn = `
                <button class="btn btn-secondary btn-sm" onclick="stopDownloadJob('${cov.active_job_id || sym}')" style="color: #f87171; border-color: #ef4444; padding: 2px 8px; font-size: 11px;">
                    ✕ Leállítás
                </button>
            `;
        } else if (cov.has_one_year) {
            statusBadge = `
                <span class="badge" style="background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid #22c55e; padding: 2px 6px; font-size: 11px;">
                    ✓ 1 Év Megvan (${cov.coverage_pct}%)
                </span>
            `;
            actionBtn = `
                <button class="btn btn-secondary btn-sm" onclick="startGapDownload('${sym}', 365)" style="padding: 2px 8px; font-size: 11px;">
                    Újraellenőrzés
                </button>
            `;
        } else {
            statusBadge = `
                <span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b; padding: 2px 6px; font-size: 11px;">
                    Hiányos (${cov.coverage_pct}%)
                </span>
            `;
            actionBtn = `
                <button class="btn btn-primary btn-sm" onclick="startGapDownload('${sym}', 365)" style="padding: 2px 8px; font-size: 11px; display: inline-flex; align-items: center; gap: 4px;">
                    📥 1 Év Foltozása (${missingDays} nap)
                </button>
            `;
        }

        return `
        <tr>
            <td><strong>${sym}</strong></td>
            <td>${name}</td>
            <td><strong class="val-cyan">${totalTicks}</strong></td>
            <td><code>${dateRange}</code></td>
            <td><span class="card-tag">${spanDays} nap</span></td>
            <td><strong class="${missingDays > 5 ? 'val-red' : 'val-green'}">${missingDays} nap</strong></td>
            <td>${statusBadge}</td>
            <td>${actionBtn}</td>
        </tr>
        `;
    }).join("");
}

function renderCompletedDownloadJobs(completedJobs) {
    const tbody = document.getElementById("completed-downloads-body");
    if (!tbody) return;

    if (!completedJobs || completedJobs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-muted" style="text-align:center;">Még nem fejeződött be letöltés ebben a munkamenetben.</td></tr>`;
        return;
    }

    tbody.innerHTML = completedJobs.map(c => {
        let badge = '';
        if (c.status === "COMPLETED") {
            badge = `<span class="badge" style="background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid #22c55e; padding: 2px 6px; font-size: 11px;">✓ BEFEJEZVE</span>`;
        } else if (c.status === "STOPPED") {
            badge = `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b; padding: 2px 6px; font-size: 11px;">✕ LEÁLLÍTVA</span>`;
        } else {
            badge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid #ef4444; padding: 2px 6px; font-size: 11px;">⚠ HIBA</span>`;
        }

        return `
        <tr>
            <td><code style="font-size: 10px;">${c.job_id}</code></td>
            <td><strong>${c.symbol}</strong></td>
            <td>${badge}</td>
            <td><strong class="val-cyan">+${(c.total_ticks_imported || 0).toLocaleString()}</strong></td>
            <td>${(c.total_ticks_in_db || 0).toLocaleString()}</td>
            <td>${c.duration_days ? c.duration_days + ' nap' : '-'}</td>
            <td>${c.completed_at || '-'}</td>
            <td style="font-size: 11px;">${c.message || 'Sikeresen illesztve.'}</td>
        </tr>
        `;
    }).join("");
}

async function startGapDownload(symbol, targetDays = 365) {
    try {
        const res = await fetch("/api/downloads/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol: symbol, target_days: targetDays })
        });
        const data = await res.json();
        console.log("Gap download triggered:", data);
        loadDownloadsTab();
        loadLiveStreams();
    } catch (e) {
        alert("Hiba a letöltés indításakor: " + e.message);
    }
}

async function stopDownloadJob(jobId) {
    try {
        const res = await fetch(`/api/downloads/${jobId}/stop`, {
            method: "POST"
        });
        const data = await res.json();
        console.log("Job stop triggered:", data);
        loadDownloadsTab();
        loadLiveStreams();
    } catch (e) {
        console.error("Error stopping job:", e);
    }
}

async function handleManualGapDownload(e) {
    e.preventDefault();
    const symbol = document.getElementById("manual-dl-symbol").value;
    const days = parseInt(document.getElementById("manual-dl-days").value || "365", 10);
    closeModal("modal-manual-download");

    const tab = document.querySelector('[data-tab="downloads-tab"]');
    if (tab) tab.click();

    await startGapDownload(symbol, days);
}
