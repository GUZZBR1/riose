    const productParams = new URLSearchParams(window.location.search);
    const productViewerMode = productParams.get('view') === 'tag';
    if (productViewerMode) {
      const animalId = productParams.get('animal_id') || 'unassigned';
      const embeddedViewer = productParams.get('embed') === '1';
      document.body.classList.add(embeddedViewer ? 'is-tag-embed' : 'is-tag-viewer');
      document.querySelector('.hero-copy').hidden = true;
      document.querySelector('.research').hidden = true;
      if (embeddedViewer) document.querySelector('.floating-header').hidden = true;
      const viewer = document.createElement('aside');
      viewer.className = 'tag-viewer-controls';
      viewer.setAttribute('aria-label', 'Ear tag product viewer');
      const label = document.createElement('p');
      label.className = 'tag-viewer-label';
      label.textContent = `RIOSE TAG · ${animalId}`;
      viewer.append(label);
      const modes = document.createElement('div');
      modes.className = 'tag-viewer-modes';
      for (const [mode, text] of [['solid', 'Solid'], ['transparent', 'Transparent'], ['exploded', 'Exploded']]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = text;
        button.setAttribute('aria-pressed', String(mode === 'solid'));
        button.addEventListener('click', () => {
          modes.querySelectorAll('button').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
          window.dispatchEvent(new CustomEvent('riose:product-viewer-state', { detail: { view: mode } }));
        });
        modes.append(button);
      }
      viewer.append(modes);
      const note = document.createElement('p');
      note.className = 'tag-viewer-note';
      note.textContent = 'Assembly geometry is provisional.';
      viewer.append(note);
      document.querySelector('.hero').append(viewer);
      if (!embeddedViewer) {
        const back = document.createElement('a');
        back.className = 'tag-viewer-back';
        back.href = '/demo';
        back.textContent = '← Return to farm';
        document.querySelector('.hero').append(back);
      }
    }

    const hero = document.querySelector('.hero');
    const heroStage = document.getElementById('hero-scroll-stage');
    const heroCopy = document.getElementById('hero-copy');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let heroCopyFrame = 0;

    const updateHeroCopy = () => {
      heroCopyFrame = 0;
      const scrollRange = Math.max(1, heroStage.offsetHeight - hero.offsetHeight);
      const stageProgress = -heroStage.getBoundingClientRect().top / scrollRange;
      const progress = Math.max(0, Math.min(1, stageProgress));
      const opacityForState = hero.classList.contains('is-interacting')
        ? 0.32
        : hero.classList.contains('is-hovering-product') ? 0.72 : 1;
      heroCopy.style.setProperty('--hero-copy-opacity', String((1 - progress) * opacityForState));
      heroCopy.style.setProperty('--hero-copy-shift', `${reducedMotion ? 0 : -115 * progress}%`);
    };

    const scheduleHeroCopyUpdate = () => {
      if (!heroCopyFrame) heroCopyFrame = requestAnimationFrame(updateHeroCopy);
    };
    scheduleHeroCopyUpdate();
    window.addEventListener('resize', scheduleHeroCopyUpdate, { passive: true });
    window.addEventListener('scroll', scheduleHeroCopyUpdate, { passive: true });
    window.addEventListener('riose:hero-interaction', scheduleHeroCopyUpdate);

    const header = document.getElementById('floating-header');
    const updateHeader = () => header.classList.toggle('is-scrolled', window.scrollY > 72);
    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });

    const brandMeaning = document.querySelector('.brand-meaning');
    const brandTrigger = brandMeaning.querySelector('.wordmark-trigger');
    const brandPanel = brandMeaning.querySelector('.brand-definition');
    const reducedBrandMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const fineHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    let fadeTimer;
    let shrinkTimer;

    const clearBrandTimers = () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(shrinkTimer);
    };

    const openBrandDefinition = () => {
      clearBrandTimers();
      brandMeaning.classList.remove('is-closing', 'is-fading');
      brandMeaning.classList.add('is-open');
      brandTrigger.setAttribute('aria-expanded', 'true');
      brandPanel.setAttribute('aria-hidden', 'false');
    };

    const closeBrandDefinition = () => {
      clearBrandTimers();
      brandTrigger.setAttribute('aria-expanded', 'false');
      brandPanel.setAttribute('aria-hidden', 'true');
      if (reducedBrandMotion) {
        brandMeaning.classList.remove('is-open', 'is-closing', 'is-fading');
        return;
      }
      if (!brandMeaning.classList.contains('is-open')) return;
      brandMeaning.classList.add('is-fading');
      fadeTimer = window.setTimeout(() => {
        brandMeaning.classList.remove('is-open');
        brandMeaning.classList.add('is-closing');
        shrinkTimer = window.setTimeout(() => {
          brandMeaning.classList.remove('is-closing', 'is-fading');
        }, 680);
      }, 150);
    };

    brandMeaning.addEventListener('pointerenter', event => {
      if (event.pointerType === 'mouse') openBrandDefinition();
    });
    brandMeaning.addEventListener('pointerleave', event => {
      if (event.pointerType === 'mouse' && !brandTrigger.matches(':focus-visible')) closeBrandDefinition();
    });
    brandMeaning.addEventListener('pointermove', event => {
      if (event.pointerType !== 'mouse' || !brandMeaning.classList.contains('is-open')) return;
      const bounds = brandPanel.getBoundingClientRect();
      if (event.clientY < bounds.top || event.clientY > bounds.bottom) return;
      const x = Math.max(0, Math.min(100, ((event.clientX - bounds.left) / bounds.width) * 100));
      const y = Math.max(0, Math.min(100, ((event.clientY - bounds.top) / bounds.height) * 100));
      brandPanel.style.setProperty('--shine-x', `${x}%`);
      brandPanel.style.setProperty('--shine-y', `${y}%`);
    });
    brandMeaning.addEventListener('focusin', () => {
      if (fineHover) openBrandDefinition();
    });
    brandMeaning.addEventListener('focusout', event => {
      if (!brandMeaning.contains(event.relatedTarget)) closeBrandDefinition();
    });
    brandTrigger.addEventListener('click', event => {
      if (fineHover && event.detail > 0) return;
      if (brandMeaning.classList.contains('is-open') && !brandMeaning.classList.contains('is-closing')) closeBrandDefinition();
      else openBrandDefinition();
    });
    brandTrigger.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      closeBrandDefinition();
      brandTrigger.blur();
    });
    document.addEventListener('pointerdown', event => {
      if (event.pointerType === 'touch' && !brandMeaning.contains(event.target)) closeBrandDefinition();
    });

    const sceneWrap = document.getElementById('scene-wrap');
    const sceneObserver = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      const sceneScript = document.createElement('script');
      sceneScript.type = 'module';
      sceneScript.src = '/assets/product-scene.js?v=20261006-6';
      sceneScript.onerror = () => {
        sceneWrap.classList.add('is-error');
        document.getElementById('scene-status').textContent = 'The 3D model could not be loaded. Enable WebGL and reload the page.';
      };
      document.head.append(sceneScript);
      sceneObserver.disconnect();
    }, { rootMargin: '120px 0px' });
    sceneObserver.observe(sceneWrap);
