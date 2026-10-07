// Test-only local EVM. The ephemeral signer stays in a mode-0600 file.
const fs = require('fs');
const ganache = require('ganache');

const secretPath = process.argv[2];
if (!secretPath) throw new Error('secret file path required');
const server = ganache.server({
  chain: { chainId: 31337 },
  wallet: { totalAccounts: 3 },
  miner: { blockTime: 0 },
  logging: { quiet: true },
});
server.listen(0, '127.0.0.1', (error) => {
  if (error) throw error;
  const accounts = server.provider.getInitialAccounts();
  const [address, account] = Object.entries(accounts)[0];
  fs.writeFileSync(secretPath, JSON.stringify({ address, privateKey: account.secretKey }), {
    mode: 0o600, flag: 'wx',
  });
  process.stdout.write(JSON.stringify({ port: server.address().port }) + '\n');
});
process.on('SIGTERM', () => server.close(() => process.exit(0)));
