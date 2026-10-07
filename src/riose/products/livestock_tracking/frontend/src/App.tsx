import { HardwareAssembly } from './HardwareAssembly';

export function App() {
  return <div className="digital-twin">
    <header className="farm-header">
      <a className="farm-nav" href="/" aria-label="Return to Riose homepage">live demo</a>
      <a className="farm-wordmark" href="/" aria-label="Riose"><span>Riose</span><img src="/assets/riose-mark.png" alt="" aria-hidden="true" /></a>
      <span className="farm-location">sao paulo, brazil</span>
    </header>

    <main className="hardware-only-main">
      <section className="hardware-section" aria-labelledby="hardware-title">
        <div className="hardware-intro">
          <h1 id="hardware-title">Inside the Riose tag</h1>
        </div>
        <HardwareAssembly />
      </section>
    </main>
  </div>;
}
