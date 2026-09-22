const fs = require('fs');
const path = require('path');
const { instrumentMetaData } = require('dukascopy-node');

const outPath = path.join(__dirname, '..', 'data', 'instruments.json');

const instruments = [];

// Curated prioritized list
const categories = {
    forex_majors: ['eurusd', 'gbpusd', 'usdjpy', 'usdchf', 'usdcad', 'audusd', 'nzdusd'],
    forex_crosses: [
        'eurgbp', 'eurjpy', 'eurchf', 'euraud', 'euscad', 'gbpjpy', 'gbpchf', 'gbpaud',
        'audjpy', 'audcad', 'chfjpy', 'cadjpy', 'nzdjpy', 'eurnzd', 'gbpnzd', 'audnzd'
    ],
    crypto: ['btcusd', 'ethusd', 'ltcusd', 'xrpusd', 'bchusd'],
    commodities: ['xauusd', 'xagusd', 'brentcmdusd', 'lightcmdusd', 'coppercmdusd', 'gascmdusd'],
    indices: ['usa500idxusd', 'usa30idxusd', 'usatechidxusd', 'deuidxeur', 'gbridxgbp', 'jpnidxjpy', 'fraidxeur', 'euidxeur']
};

const categorizedKeys = new Set([
    ...categories.forex_majors,
    ...categories.forex_crosses,
    ...categories.crypto,
    ...categories.commodities,
    ...categories.indices
]);

// 1. Add curated ones first with human-readable categories
for (const [catKey, list] of Object.entries(categories)) {
    let catLabel = 'Forex Főpárok';
    if (catKey === 'forex_crosses') catLabel = 'Forex Keresztpárok';
    if (catKey === 'crypto') catLabel = 'Kriptovaluták';
    if (catKey === 'commodities') catLabel = 'Nyersanyagok & Fémek (Arany, Olaj)';
    if (catKey === 'indices') catLabel = 'Részvényindexek (S&P 500, DAX, NASDAQ)';

    for (const key of list) {
        const meta = instrumentMetaData[key];
        if (meta) {
            instruments.push({
                id: key,
                symbol: key.toUpperCase(),
                name: meta.name,
                description: meta.description,
                category: catLabel,
                start_year: meta.startYearForDailyCandles ? meta.startYearForDailyCandles.slice(0, 4) : '2000'
            });
        }
    }
}

// 2. Add other interesting instruments from Dukascopy
for (const [key, meta] of Object.entries(instrumentMetaData)) {
    if (!categorizedKeys.has(key)) {
        let cat = 'Egyéb';
        if (key.includes('idx')) cat = 'Egyéb Indexek';
        else if (key.includes('cmd')) cat = 'Egyéb Nyersanyagok';
        else if (meta.name && meta.name.includes('/')) cat = 'Egyéb Devizák';
        else cat = 'Részvények';

        // Add if reasonably known
        if (cat !== 'Részvények' || instruments.length < 150) {
            instruments.push({
                id: key,
                symbol: key.toUpperCase(),
                name: meta.name || key.toUpperCase(),
                description: meta.description || meta.name,
                category: cat,
                start_year: meta.startYearForDailyCandles ? meta.startYearForDailyCandles.slice(0, 4) : '2010'
            });
        }
    }
}

fs.writeFileSync(outPath, JSON.stringify(instruments, null, 2), 'utf-8');
console.log(`Exported ${instruments.length} instruments to ${outPath}`);
