// Deterministic digital models for Renode. These are protocol-level models,
// not electrical or RF simulations. Behavior is intentionally scoped to the
// commands/registers exercised by the RIOSE Zephyr firmware.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.GPIOPort;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Riose
{
    public sealed class SX1262 : ISPIPeripheral, IGPIOReceiver
    {
        private const int FifoSize = 256;
        private const byte CmdOk = 0x02;
        private const byte CmdDataAvailable = 0x04;
        private const byte CmdTimeout = 0x06;
        private const byte CmdInvalid = 0x08;
        private const byte CmdFailed = 0x0A;
        private const ushort IrqTxDone = 0x0001;
        private const ushort IrqTimeout = 0x0200;
        private const ulong TicksPerMillisecond = 64; // SX126x timeout ticks are 15.625 us.
        private const ulong ContinuousRxWindowTicks = 64000; // One documented virtual second.

        private readonly byte[] fifo = new byte[FifoSize];
        private readonly List<byte> txFrame = new List<byte>();
        private readonly byte[] modulation = new byte[4];
        private readonly byte[] packetParams = new byte[9];
        private readonly byte[] paConfig = new byte[4];
        private readonly byte[] imageCalibration = new byte[2];
        private readonly LimitTimer operationTimer;
        private int txLength;
        private byte opcode;
        private byte mode = 0x20; // standby RC
        private byte commandStatus = CmdOk;
        private ushort irqStatus;
        private ushort irqMask;
        private ushort dio1Mask;
        private ushort dio2Mask;
        private ushort dio3Mask;
        private uint txLatencyMs = 30;
        private uint txCount;
        private uint faultCount;
        private uint rfFrequencyWord;
        private byte packetType;
        private byte txPower;
        private byte rampTime;
        private byte txBase;
        private byte rxBase;
        private bool selected;
        private bool operationIsRx;
        private bool operationTimesOut;
        private bool holdBusy;
        private bool suppressIRQ;
        private bool dropSPI;
        private bool dio2RfSwitchEnabled;

        public SX1262(Machine machine)
        {
            Busy = new GPIO();
            IRQ = new GPIO();
            operationTimer = new LimitTimer(machine.ClockSource, 64000, this, "SX1262 operation",
                limit: 1, eventEnabled: true, direction: Direction.Ascending,
                enabled: false, autoUpdate: false, workMode: WorkMode.OneShot);
            operationTimer.LimitReached += CompleteOperation;
            Reset();
        }

        public GPIO Busy { get; }
        public GPIO IRQ { get; }

        // Fault hooks can be controlled from Renode scripts and Robot tests.
        public bool HoldBusy { get => holdBusy; set { holdBusy = value; UpdatePins(); } }
        public bool SuppressIRQ { get => suppressIRQ; set { suppressIRQ = value; UpdateIRQ(); } }
        public bool DropSPI { get => dropSPI; set => dropSPI = value; }
        public uint TxLatencyMs { get => txLatencyMs; set => txLatencyMs = Math.Max(1u, value); }
        public uint FaultCount => faultCount;
        public uint TxCount => txCount;
        public byte LastOpcode => opcode;
        public byte CurrentMode => mode;
        public ushort IRQStatus => irqStatus;
        public uint RfFrequencyWord => rfFrequencyWord;
        public byte PacketType => packetType;
        public byte TxBase => txBase;
        public byte RxBase => rxBase;
        public bool Dio2RfSwitchEnabled => dio2RfSwitchEnabled;
        public bool BusyAsserted => HoldBusy || mode == 0x60 || mode == 0x50;
        public bool IRQAsserted => !SuppressIRQ && (irqStatus & irqMask & dio1Mask) != 0;

        public byte Transmit(byte data)
        {
            if(DropSPI) return 0xFF;
            if(!selected)
            {
                if(data != 0xC0) commandStatus = CmdOk;
                selected = true;
                txLength = 0;
                opcode = data;
                txFrame.Clear();
                txFrame.Add(data);
                txLength++;
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

            txFrame.Add(data);
            txLength++;
            return result;
        }

        public void FinishTransmission()
        {
            if(!selected) return;
            selected = false;
            if(DropSPI) return;

            switch(opcode)
            {
                case 0xC0: // GetStatus
                    if(RequireLength(2)) commandStatus = CmdOk;
                    break;
                case 0x84: // SetSleep
                    if(RequireLength(2))
                    {
                        mode = 0x00;
                        CancelOperation();
                    }
                    break;
                case 0x80: // SetStandby
                    if(RequireLength(2))
                    {
                        if(txFrame[1] > 1) Fault(CmdInvalid);
                        else
                        {
                            mode = txFrame[1] == 1 ? (byte)0x30 : (byte)0x20;
                            CancelOperation();
                        }
                    }
                    break;
                case 0x8A: // SetPacketType
                    if(RequireLength(2))
                    {
                        if(txFrame[1] > 1) Fault(CmdInvalid);
                        else packetType = txFrame[1];
                    }
                    break;
                case 0x9D: // SetDio2AsRfSwitchCtrl
                    if(RequireLength(2))
                    {
                        if(txFrame[1] > 1) Fault(CmdInvalid);
                        else dio2RfSwitchEnabled = txFrame[1] != 0;
                    }
                    break;
                case 0x86: // SetRfFrequency
                    if(RequireLength(5)) rfFrequencyWord = ReadU32(1);
                    break;
                case 0x8E: // SetTxParams
                    if(RequireLength(3)) { txPower = txFrame[1]; rampTime = txFrame[2]; }
                    break;
                case 0x98: // CalibrateImage
                    if(RequireLength(3)) { imageCalibration[0] = txFrame[1]; imageCalibration[1] = txFrame[2]; }
                    break;
                case 0x95: // SetPaConfig
                    if(RequireLength(5))
                    {
                        if(txFrame[1] > 0x07 || txFrame[2] > 0x07 || txFrame[3] > 1 || txFrame[4] != 1)
                            Fault(CmdInvalid);
                        else
                            for(int i = 0; i < paConfig.Length; i++) paConfig[i] = txFrame[i + 1];
                    }
                    break;
                case 0x8B: // SetModulationParams
                    if(RequireLength(5))
                    {
                        if(packetType == 1 && (txFrame[1] < 5 || txFrame[1] > 12 || !ValidLoRaBandwidth(txFrame[2]) ||
                            txFrame[3] < 1 || txFrame[3] > 4 || txFrame[4] > 1)) Fault(CmdInvalid);
                        else
                            for(int i = 0; i < modulation.Length; i++) modulation[i] = txFrame[i + 1];
                    }
                    break;
                case 0x8C: // SetPacketParams (LoRa: six args; GFSK: nine args)
                    if(RequireLength(packetType == 1 ? 7 : 10))
                    {
                        Array.Clear(packetParams, 0, packetParams.Length);
                        for(int i = 1; i < txLength; i++) packetParams[i - 1] = txFrame[i];
                    }
                    break;
                case 0x8F: // SetBufferBaseAddress
                    if(RequireLength(3)) { txBase = txFrame[1]; rxBase = txFrame[2]; }
                    break;
                case 0x08: // SetDioIrqParams
                    if(RequireLength(9))
                    {
                        irqMask = ReadU16(1);
                        dio1Mask = ReadU16(3);
                        dio2Mask = ReadU16(5);
                        dio3Mask = ReadU16(7);
                        UpdateIRQ();
                    }
                    break;
                case 0x02: // ClearIrqStatus
                    if(RequireLength(3)) { irqStatus &= (ushort)~ReadU16(1); UpdateIRQ(); }
                    break;
                case 0x0E: // WriteBuffer
                    if(RequireAtLeastLength(2))
                        for(int i = 2; i < txLength; i++) fifo[(byte)(txFrame[1] + i - 2)] = txFrame[i];
                    break;
                case 0x1E: // ReadBuffer
                    if(RequireAtLeastLength(3)) commandStatus = CmdDataAvailable;
                    break;
                case 0x12: // GetIrqStatus
                    if(RequireLength(4)) commandStatus = CmdDataAvailable;
                    break;
                case 0x83: // SetTx
                    StartOperation(isRx: false);
                    break;
                case 0x82: // SetRx
                    StartOperation(isRx: true);
                    break;
                default:
                    Fault(CmdInvalid);
                    break;
            }
            UpdatePins();
        }

        public void OnGPIO(int number, bool value)
        {
            // GPIO 0 is the external active-low reset pin.
            if(number == 0 && !value) Reset();
        }

        public void Reset()
        {
            Array.Clear(fifo, 0, fifo.Length);
            Array.Clear(modulation, 0, modulation.Length);
            Array.Clear(packetParams, 0, packetParams.Length);
            Array.Clear(paConfig, 0, paConfig.Length);
            Array.Clear(imageCalibration, 0, imageCalibration.Length);
            txFrame.Clear();
            operationTimer.Reset();
            mode = 0x20;
            commandStatus = CmdOk;
            irqStatus = irqMask = dio1Mask = dio2Mask = dio3Mask = 0;
            txCount = faultCount = rfFrequencyWord = 0;
            packetType = txPower = rampTime = txBase = rxBase = 0;
            selected = operationIsRx = operationTimesOut = false;
            holdBusy = suppressIRQ = dropSPI = dio2RfSwitchEnabled = false;
            UpdatePins();
        }

        private byte Status() => (byte)(mode | (commandStatus & 0x0E));

        private bool RequireLength(int expected)
        {
            if(txLength == expected) return true;
            Fault(CmdInvalid);
            return false;
        }

        private bool ValidLoRaBandwidth(byte bandwidth) => bandwidth == 0x00 || bandwidth == 0x01 || bandwidth == 0x02 ||
            bandwidth == 0x03 || bandwidth == 0x04 || bandwidth == 0x05 || bandwidth == 0x06 || bandwidth == 0x09 ||
            bandwidth == 0x0A || bandwidth == 0x0B;

        private bool RequireAtLeastLength(int minimum)
        {
            if(txLength >= minimum) return true;
            Fault(CmdInvalid);
            return false;
        }

        private void Fault(byte status)
        {
            commandStatus = status;
            faultCount++;
        }

        private ushort ReadU16(int offset) => (ushort)((txFrame[offset] << 8) | txFrame[offset + 1]);

        private uint ReadU32(int offset) => ((uint)txFrame[offset] << 24) | ((uint)txFrame[offset + 1] << 16) |
            ((uint)txFrame[offset + 2] << 8) | txFrame[offset + 3];

        private ulong ReadTimeoutTicks() => ((ulong)txFrame[1] << 16) | ((ulong)txFrame[2] << 8) | txFrame[3];

        private void StartOperation(bool isRx)
        {
            if(txLength != 4 || mode == 0x00 || mode == 0x60 || HoldBusy)
            {
                Fault(txLength == 4 ? CmdFailed : CmdInvalid);
                return;
            }

            operationIsRx = isRx;
            ulong requestedTicks = ReadTimeoutTicks();
            ulong latencyTicks = (ulong)TxLatencyMs * TicksPerMillisecond;
            if(isRx && requestedTicks == 0) requestedTicks = ContinuousRxWindowTicks;
            operationTimesOut = isRx
                ? requestedTicks != 0
                : requestedTicks != 0 && requestedTicks <= latencyTicks;
            ulong eventTicks = isRx
                ? requestedTicks
                : operationTimesOut ? requestedTicks : latencyTicks;
            operationTimer.Reset();
            operationTimer.Limit = Math.Max(1UL, eventTicks);
            mode = isRx ? (byte)0x50 : (byte)0x60;
            operationTimer.Enabled = true;
            if(!isRx) txCount++;
        }

        private void CompleteOperation()
        {
            mode = 0x20;
            irqStatus |= operationTimesOut ? IrqTimeout : operationIsRx ? IrqTimeout : IrqTxDone;
            commandStatus = operationTimesOut ? CmdTimeout : CmdOk;
            UpdatePins();
        }

        private void CancelOperation()
        {
            operationTimer.Reset();
            operationIsRx = operationTimesOut = false;
            UpdatePins();
        }

        private void UpdateIRQ()
        {
            IRQ.Set(!SuppressIRQ && (irqStatus & irqMask & dio1Mask) != 0);
        }

        private void UpdatePins()
        {
            Busy.Set(HoldBusy || mode == 0x60 || mode == 0x50);
            UpdateIRQ();
        }
    }

}
