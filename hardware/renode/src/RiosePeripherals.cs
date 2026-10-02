// Deterministic digital models for Renode. These are protocol-level models,
// not electrical or RF simulations. Behavior is intentionally scoped to the
// commands/registers exercised by the RIOSE Zephyr firmware.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.GPIOPort;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.Riose
{
    public sealed class SX1262 : ISPIPeripheral, IGPIOReceiver
    {
        private const int FifoSize = 256;
        private readonly byte[] fifo = new byte[FifoSize];
        private readonly byte[] txFrame = new byte[512];
        private int txLength;
        private byte opcode;
        private byte mode = 0x20; // standby RC
        private ushort irqStatus;
        private ushort irqMask;
        private bool selected;
        private long txCompletionNs;
        private long timeoutNs;
        private bool holdBusy;
        private bool suppressIRQ;

        public SX1262(Machine machine)
        {
            Busy = new GPIO();
            IRQ = new GPIO();
            Reset();
        }

        public GPIO Busy { get; }
        public GPIO IRQ { get; }

        // Public fault hooks are settable from Renode monitor/Python scripts.
        public bool HoldBusy { get => holdBusy; set { holdBusy = value; UpdatePins(); } }
        public bool SuppressIRQ { get => suppressIRQ; set { suppressIRQ = value; UpdateIRQ(); } }
        public bool DropSPI { get; set; }
        public uint TxLatencyMs { get; set; } = 30;

        public byte Transmit(byte data)
        {
            if(DropSPI) return 0;
            UpdateTime();
            if(!selected)
            {
                selected = true;
                txLength = 0;
                opcode = data;
                if(txLength < txFrame.Length) txFrame[txLength++] = data;
                return 0;
            }

            byte result = 0;
            if(opcode == 0xC0) result = Status();
            else if(opcode == 0x12)
            {
                if(txLength == 1) result = Status();
                else if(txLength == 2) result = (byte)(irqStatus >> 8);
                else if(txLength == 3) result = (byte)irqStatus;
            }
            else if(opcode == 0x1E && txLength >= 3)
                result = fifo[(byte)(txFrame[1] + txLength - 3)];

            if(txLength < txFrame.Length) txFrame[txLength++] = data;
            return result;
        }

        public void FinishTransmission()
        {
            if(!selected) return;
            selected = false;
            if(DropSPI) return;
            switch(opcode)
            {
                case 0x84: mode = 0x00; txCompletionNs = 0; break; // SetSleep
                case 0x80: mode = txLength > 1 && txFrame[1] == 1 ? (byte)0x30 : (byte)0x20; break;
                case 0x08: if(txLength >= 3) irqMask = (ushort)((txFrame[1] << 8) | txFrame[2]); break;
                case 0x02: if(txLength >= 3) irqStatus &= (ushort)~((txFrame[1] << 8) | txFrame[2]); UpdateIRQ(); break;
                case 0x0E:
                    if(txLength >= 2) for(int i = 2; i < txLength; i++) fifo[(byte)(txFrame[1] + i - 2)] = txFrame[i];
                    break;
                case 0x83: // SetTx: virtual deterministic completion; timeout is in 15.625 us units
                    if(mode == 0x00 || mode == 0x60) break;
                    mode = 0x60;
                    timeoutNs = txLength >= 4 ? (((long)txFrame[1] << 16) | (txFrame[2] << 8) | txFrame[3]) * 15625 : 0;
                    txCompletionNs = (long)TxLatencyMs * 1000000;
                    break;
                case 0x82: // SetRx; no RF medium is modeled
                    if(mode != 0x00 && mode != 0x60) { mode = 0x50; timeoutNs = 1000000000; txCompletionNs = timeoutNs; }
                    break;
            }
        }

        public void OnGPIO(int number, bool value)
        {
            // GPIO 0 is the external reset pin. SPI chip-select is controlled
            // by the SPI controller's transaction boundaries.
            if(number == 0 && !value) Reset();
        }

        public void Reset()
        {
            Array.Clear(fifo, 0, fifo.Length);
            mode = 0x20;
            irqStatus = irqMask = 0;
            txCompletionNs = timeoutNs = 0;
            selected = false;
            holdBusy = suppressIRQ = DropSPI = false;
            UpdatePins();
        }

        private byte Status() => (byte)(mode | 0x02);

        private void UpdateTime()
        {
            if(txCompletionNs <= 0) { UpdatePins(); return; }
            // Renode virtual time is monotonic; a relative completion is
            // decremented from emulated SPI activity to keep the model
            // independent of host wall clock.
            txCompletionNs -= 1000000;
            if(txCompletionNs <= 0)
            {
                bool timedOut = timeoutNs > 0 && timeoutNs < (long)TxLatencyMs * 1000000;
                mode = 0x20;
                irqStatus |= timedOut ? (ushort)0x0200 : (ushort)0x0001;
            }
            UpdatePins();
        }

        private void UpdateIRQ()
        {
            IRQ.Set(!SuppressIRQ && (irqStatus & irqMask) != 0);
        }

        private void UpdatePins()
        {
            Busy.Set(HoldBusy || mode == 0x60 || mode == 0x50);
            UpdateIRQ();
        }
    }

    public sealed class LIS2DW12 : II2CPeripheral
    {
        private readonly byte[] registers = new byte[64];
        private byte pointer;
        private bool pointerSet;
        private uint failedTransactions;
        private int sample = 0;
        private bool holdIRQ;

        public LIS2DW12(Machine machine, int address) { Reset(); INT1 = new GPIO(); }
        public GPIO INT1 { get; }
        public bool HoldIRQ { get => holdIRQ; set { holdIRQ = value; UpdateWakeupIRQ(); } }
        public bool FailI2C { get; set; }
        public string MotionProfile { get; set; } = "STATIC";
        public bool WakeupIRQAsserted { get; private set; }

        public void Write(byte[] data)
        {
            if(ConsumeI2cFault()) { registers[0x0F] = 0x00; return; }
            if(data == null || data.Length == 0) return;
            pointer = (byte)(data[0] & 0x3F);
            pointerSet = true;
            for(int i = 1; i < data.Length && pointer < registers.Length; i++, pointer++)
            {
                if(pointer == 0x0F || pointer == 0x27 || (pointer >= 0x28 && pointer <= 0x2D) || pointer == 0x38 || pointer == 0x3B) continue;
                registers[pointer] = data[i];
                if(pointer == 0x23 || pointer == 0x3F) UpdateWakeupIRQ();
            }
        }

        public byte[] Read(int count = 1)
        {
            bool fail = ConsumeI2cFault();
            if(!pointerSet) pointer = 0;
            byte[] result = new byte[Math.Max(0, count)];
            for(int i = 0; i < result.Length; i++)
            {
                if(pointer == 0x28) UpdateSample();
                result[i] = fail ? (byte)0 : pointer < registers.Length ? registers[pointer] : (byte)0;
                if(pointer == 0x38 || pointer == 0x3B)
                {
                    registers[0x38] = 0;
                    registers[0x3B] = 0;
                    UpdateWakeupIRQ();
                }
                pointer = (byte)((pointer + 1) & 0x3F);
            }
            return result;
        }

        public void FinishTransmission() { pointerSet = true; }

        public void Reset()
        {
            Array.Clear(registers, 0, registers.Length);
            registers[0x0F] = 0x44;
            registers[0x34] = 0x02;
            registers[0x2C] = 0x10; // +1 g default in the model's coarse representation
            failedTransactions = 0;
            pointer = 0;
            pointerSet = false;
            sample = 0;
            HoldIRQ = FailI2C = false;
            registers[0x23] = registers[0x3F] = 0;
            UpdateWakeupIRQ();
        }

        // Fault injection hooks callable by monitor/Python automation.
        public void FailNextI2C(uint transactions) { failedTransactions = transactions; }

        // Inject a deterministic wake event from the environment. Respect the
        // same routing and global interrupt-enable bits as UpdateSample so a
        // test cannot accidentally claim an IRQ when firmware left it masked.
        public void TriggerWakeup()
        {
            registers[0x38] |= 0x08;
            registers[0x3B] |= 0x08;
            UpdateWakeupIRQ();
        }

        private void UpdateWakeupIRQ()
        {
            bool routed = (registers[0x23] & 0x20) != 0 &&
                (registers[0x3F] & 0x20) != 0;
            WakeupIRQAsserted = routed && !HoldIRQ && (registers[0x38] & 0x08) != 0;
            INT1?.Set(WakeupIRQAsserted);
        }

        private bool ConsumeI2cFault()
        {
            if(FailI2C) { FailI2C = false; return true; }
            if(failedTransactions == 0) return false;
            failedTransactions--;
            return true;
        }

        private void UpdateSample()
        {
            sample++;
            int x = 0, y = 0, z = 0x10;
            if(MotionProfile == "WALK") { x = sample % 2 == 0 ? 3 : -3; y = 1; }
            else if(MotionProfile == "RUN") { x = sample % 2 == 0 ? 8 : -8; y = 4; }
            else if(MotionProfile == "IMPACT") { x = 0x30; y = -0x20; z = 0x30; }
            else if(MotionProfile == "RANDOM_MOVEMENT") { x = (sample * 17 % 31) - 15; y = (sample * 7 % 25) - 12; z = 16 + (sample * 11 % 18); }
            registers[0x28] = (byte)x; registers[0x29] = (byte)(x >> 8);
            registers[0x2A] = (byte)y; registers[0x2B] = (byte)(y >> 8);
            registers[0x2C] = (byte)z; registers[0x2D] = (byte)(z >> 8);
            registers[0x27] |= 1;
            int threshold = registers[0x34] & 0x3F;
            bool routed = (registers[0x23] & 0x20) != 0 && (registers[0x3F] & 0x20) != 0;
            if(routed && MotionProfile != "STATIC" && threshold > 0)
            {
                registers[0x38] = 0x08; registers[0x3B] |= 0x08;
                UpdateWakeupIRQ();
            }
        }
    }
}
