using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Riose
{
    // Counts actual GPIO receiver notifications, including pulses that disappear
    // before a Robot test reads the MCU input register.
    public sealed class GPIOTransitionProbe : IDoubleWordPeripheral, IGPIOReceiver, IKnownSize
    {
        public long Size => 8;
        public uint RisingEdgeCount { get; private set; }
        public uint FallingEdgeCount { get; private set; }
        public uint ReadDoubleWord(long offset) => offset == 0 ? RisingEdgeCount : FallingEdgeCount;
        public void WriteDoubleWord(long offset, uint value) { }

        public void OnGPIO(int number, bool value)
        {
            if(value == previous) return;
            if(value) RisingEdgeCount++;
            else FallingEdgeCount++;
            previous = value;
        }

        public void Reset()
        {
            previous = false;
            RisingEdgeCount = 0;
            FallingEdgeCount = 0;
        }

        private bool previous;
    }
}
