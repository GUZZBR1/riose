// Optional fault-injection wrapper for the native STM32 SPI controller.
// The watchdog is simulation instrumentation, not a STM32 hardware register.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Riose
{
    public sealed class SPITransferFault : IBytePeripheral, IWordPeripheral, IDoubleWordPeripheral, IKnownSize
    {
        public SPITransferFault(Machine machine, STM32SPI controller)
        {
            this.controller = controller;
            watchdog = new LimitTimer(machine.ClockSource, 1000000, this, "SPI transfer watchdog",
                limit: 1, eventEnabled: true, direction: Direction.Ascending,
                enabled: false, autoUpdate: false, workMode: WorkMode.OneShot);
            watchdog.LimitReached += () =>
            {
                TimeoutCount++;
                CancelTransfer();
            };
        }

        public bool StallTransfers { get; set; }
        public uint TimeoutUs { get => timeoutUs; set => timeoutUs = Math.Max(1u, value); }
        public uint TimeoutCount { get; private set; }
        public bool TransferPending => watchdog.Enabled;
        public long Size => controller.Size;

        public byte ReadByte(long offset) => (byte)ReadDoubleWord(offset);
        public ushort ReadWord(long offset) => (ushort)ReadDoubleWord(offset);
        public void WriteByte(long offset, byte value) => WriteDoubleWord(offset, value);
        public void WriteWord(long offset, ushort value) => WriteDoubleWord(offset, value);

        public uint ReadDoubleWord(long offset)
        {
            if(TransferPending && offset == Data) return 0;
            var value = controller.ReadDoubleWord(offset);
            // A stalled transfer supplies no byte and cannot accept another one.
            if(TransferPending && offset == Status) return (value & ~3u) | 0x80u;
            return value;
        }

        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == Control1 && (value & 0x40u) == 0) CancelTransfer();
            if(offset == Data)
            {
                if(TransferPending) return;
                if(StallTransfers && (controller.ReadDoubleWord(Control1) & 0x40u) != 0)
                {
                    // Discard stale RX data so it cannot satisfy the failed transfer.
                    if((controller.ReadDoubleWord(Status) & 1u) != 0) controller.ReadDoubleWord(Data);
                    watchdog.Reset();
                    watchdog.Limit = TimeoutUs;
                    watchdog.Enabled = true;
                    return;
                }
            }
            controller.WriteDoubleWord(offset, value);
        }

        public void Reset()
        {
            CancelTransfer();
            StallTransfers = false;
            TimeoutUs = 10000;
            TimeoutCount = 0;
            controller.Reset();
        }

        private void CancelTransfer()
        {
            watchdog.Enabled = false;
            watchdog.Reset();
        }

        private const long Control1 = 0;
        private const long Status = 8;
        private const long Data = 12;
        private readonly STM32SPI controller;
        private readonly LimitTimer watchdog;
        private uint timeoutUs = 10000;
    }
}
