const fs = require('fs');
const solc = require('solc');

const source = fs.readFileSync(process.argv[2], 'utf8');
const input = {
  language: 'Solidity',
  sources: { 'RioseCommitmentRegistry.sol': { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object'] } },
  },
};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
if (output.errors?.some((item) => item.severity === 'error')) {
  throw new Error(output.errors.filter((item) => item.severity === 'error').map((item) => item.message).join('\n'));
}
process.stdout.write(JSON.stringify(output.contracts['RioseCommitmentRegistry.sol'].RioseCommitmentRegistry));
