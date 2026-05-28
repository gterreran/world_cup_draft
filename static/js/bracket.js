(function () {
  const scrollEl = document.querySelector('[data-bracket-scroll]');
  const boardEl = document.querySelector('[data-bracket-board]');

  if (!scrollEl || !boardEl) {
    return;
  }

  const rounds = Array.from(boardEl.querySelectorAll('.bracket-round'));
  const previousButton = document.querySelector('[data-bracket-prev]');
  const nextButton = document.querySelector('[data-bracket-next]');
  const label = document.querySelector('[data-bracket-label]');

  if (!rounds.length) {
    return;
  }

  // The navigation is page-based rather than free-scroll based.
  // Each page is defined by the leftmost visible round:
  //   0: R32 / R16 / QF
  //   1: R16 / QF / SF
  //   2: QF  / SF  / Final
  //   3: SF  / Final / blank spacer
  // This avoids guessing from card widths and keeps the label, scroll target,
  // and compression density tied to the same state.
  const VISIBLE_ROUNDS = 3;
  const maxPageIndex = Math.max(0, rounds.length - VISIBLE_ROUNDS + 1);

  let activeIndex = 0;
  let rafId = null;
  let programmaticIndex = null;
  let programmaticTimer = null;

  function roundTitle(index) {
    const heading = rounds[index]?.querySelector('h2');
    return heading ? heading.textContent.trim() : '';
  }

  function maxScrollLeft() {
    return Math.max(0, scrollEl.scrollWidth - scrollEl.clientWidth);
  }

  function viewportInset() {
    const value = window.getComputedStyle(scrollEl).getPropertyValue('scroll-padding-left');
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function targetLeftForPage(index) {
    const clamped = Math.max(0, Math.min(index, maxPageIndex));
    const round = rounds[clamped];

    if (!round) {
      return maxScrollLeft();
    }

    const scrollRect = scrollEl.getBoundingClientRect();
    const roundRect = round.getBoundingClientRect();
    const absoluteRoundLeft = scrollEl.scrollLeft + roundRect.left - scrollRect.left;

    return Math.max(0, Math.min(absoluteRoundLeft - viewportInset(), maxScrollLeft()));
  }

  function nearestPageIndex() {
    const currentLeft = scrollEl.scrollLeft;
    let bestIndex = 0;
    let bestDistance = Infinity;

    for (let index = 0; index <= maxPageIndex; index += 1) {
      const distance = Math.abs(targetLeftForPage(index) - currentLeft);

      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    }

    return bestIndex;
  }

  function densityIndexForPage(index) {
    // Density should match the densest leftmost visible round.
    // Page 0 uses R32 density, page 1 uses R16 density, etc.
    return Math.max(0, Math.min(index, rounds.length - 1));
  }

  function setActivePage(index) {
    const clamped = Math.max(0, Math.min(index, maxPageIndex));
    activeIndex = clamped;

    boardEl.classList.remove(
      'is-focus-0',
      'is-focus-1',
      'is-focus-2',
      'is-focus-3',
      'is-focus-4'
    );
    boardEl.classList.add(`is-focus-${densityIndexForPage(clamped)}`);

    rounds.forEach((round, roundIndex) => {
      const visible = roundIndex >= clamped && roundIndex < clamped + VISIBLE_ROUNDS;
      round.classList.toggle('is-active-round', roundIndex === clamped);
      round.classList.toggle('is-visible-page-round', visible);
    });

    if (previousButton) {
      previousButton.disabled = clamped === 0;
    }

    if (nextButton) {
      nextButton.disabled = clamped === maxPageIndex;
    }

    if (label) {
      label.textContent = roundTitle(clamped);
    }
  }

  function clearProgrammaticState() {
    if (programmaticTimer !== null) {
      window.clearTimeout(programmaticTimer);
      programmaticTimer = null;
    }

    programmaticIndex = null;
  }

  function scrollToPage(index) {
    const clamped = Math.max(0, Math.min(index, maxPageIndex));

    clearProgrammaticState();

    // Important: apply compression BEFORE the scroll starts.  The scroll
    // listener is locked to this page during the smooth scroll, so it cannot
    // temporarily revert the board to the previous density.
    setActivePage(clamped);

    programmaticIndex = clamped;
    const targetLeft = targetLeftForPage(clamped);

    scrollEl.scrollTo({ left: targetLeft, behavior: 'smooth' });

    programmaticTimer = window.setTimeout(() => {
      setActivePage(clamped);
      clearProgrammaticState();
    }, 500);
  }

  function syncFromScrollPosition() {
    if (programmaticIndex !== null) {
      setActivePage(programmaticIndex);
      return;
    }

    if (rafId !== null) {
      return;
    }

    rafId = window.requestAnimationFrame(() => {
      rafId = null;
      setActivePage(nearestPageIndex());
    });
  }

  if (previousButton) {
    previousButton.addEventListener('click', () => scrollToPage(activeIndex - 1));
  }

  if (nextButton) {
    nextButton.addEventListener('click', () => scrollToPage(activeIndex + 1));
  }

  scrollEl.addEventListener('scroll', syncFromScrollPosition, { passive: true });

  window.addEventListener('resize', () => {
    clearProgrammaticState();
    const page = Math.max(0, Math.min(activeIndex, maxPageIndex));
    setActivePage(page);
    scrollEl.scrollTo({ left: targetLeftForPage(page), behavior: 'auto' });
  });

  setActivePage(0);
})();
