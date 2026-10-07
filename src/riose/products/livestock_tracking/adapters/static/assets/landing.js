const header = document.getElementById('floating-header');
const updateHeader = () => header.classList.toggle('is-scrolled', window.scrollY > 72);
updateHeader();
window.addEventListener('scroll', updateHeader, { passive: true });

const brandMeaning = document.querySelector('.brand-meaning');
const brandTrigger = brandMeaning.querySelector('.wordmark-trigger');
const brandPanel = brandMeaning.querySelector('.brand-definition');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const fineHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
let closeTimer;

function openBrandDefinition() {
  window.clearTimeout(closeTimer);
  brandMeaning.classList.add('is-open');
  brandTrigger.setAttribute('aria-expanded', 'true');
  brandPanel.setAttribute('aria-hidden', 'false');
}

function closeBrandDefinition() {
  window.clearTimeout(closeTimer);
  brandTrigger.setAttribute('aria-expanded', 'false');
  brandPanel.setAttribute('aria-hidden', 'true');
  if (reducedMotion) {
    brandMeaning.classList.remove('is-open');
    return;
  }
  closeTimer = window.setTimeout(() => brandMeaning.classList.remove('is-open'), 140);
}

brandMeaning.addEventListener('pointerenter', (event) => {
  if (event.pointerType === 'mouse') openBrandDefinition();
});
brandMeaning.addEventListener('pointerleave', (event) => {
  if (event.pointerType === 'mouse' && !brandTrigger.matches(':focus-visible')) closeBrandDefinition();
});
brandMeaning.addEventListener('focusin', openBrandDefinition);
brandMeaning.addEventListener('focusout', (event) => {
  if (!brandMeaning.contains(event.relatedTarget)) closeBrandDefinition();
});
brandTrigger.addEventListener('click', (event) => {
  if (fineHover && event.detail > 0) return;
  if (brandMeaning.classList.contains('is-open')) closeBrandDefinition();
  else openBrandDefinition();
});
brandTrigger.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  closeBrandDefinition();
  brandTrigger.blur();
});
document.addEventListener('pointerdown', (event) => {
  if (event.pointerType === 'touch' && !brandMeaning.contains(event.target)) closeBrandDefinition();
});
