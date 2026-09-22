const { getHistoricRates } = require('dukascopy-node');

async function main() {
    const args = process.argv.slice(2);
    let symbol = 'eurusd';
    let fromMinutes = 10;
    let fromTs = null;

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--symbol' && args[i + 1]) {
            symbol = args[i + 1].toLowerCase();
        } else if (args[i] === '--minutes' && args[i + 1]) {
            fromMinutes = parseInt(args[i + 1], 10);
        } else if (args[i] === '--from-ts' && args[i + 1]) {
            fromTs = parseInt(args[i + 1], 10);
        }
    }

    const now = new Date();
    let fromDate;
    if (fromTs) {
        fromDate = new Date(fromTs);
    } else {
        fromDate = new Date(now.getTime() - fromMinutes * 60 * 1000);
    }

    try {
        const rates = await getHistoricRates({
            instrument: symbol,
            dates: {
                from: fromDate,
                to: now
            },
            timeframe: 'tick',
            volumes: true
        });

        // output json string
        process.stdout.write(JSON.stringify(rates));
    } catch (err) {
        console.error('Error fetching Dukascopy ticks:', err);
        process.stdout.write('[]');
    }
}

main();
