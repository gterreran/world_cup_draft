(() => {
  function bootDraftPresentation() {
    const dataElement = document.getElementById("draft-picks-data");

    if (!dataElement) {
      return;
    }

    let picks = [];
    try {
      const parsedPicks = JSON.parse(dataElement.textContent);
      picks = Array.isArray(parsedPicks) ? parsedPicks : [];
    } catch (error) {
      console.error("Could not parse draft picks payload.", error);
      picks = [];
    }
  const state = {
    index: -1,
    phase: "idle", // idle, manager, team, complete
    timer: null,
    isAutoPlaying: false,
  };

  const elements = {
    card: document.getElementById("draft-reveal-card"),
    currentPick: document.getElementById("draft-current-pick"),
    currentPot: document.getElementById("draft-current-pot"),
    remainingPicks: document.getElementById("draft-remaining-picks"),
    pickLabel: document.getElementById("draft-pick-label"),
    flag: document.getElementById("draft-flag"),
    teamName: document.getElementById("draft-team-name"),
    teamMeta: document.getElementById("draft-team-meta"),
    managerPill: document.getElementById("draft-manager-pill"),
    managerCount: document.getElementById("draft-manager-count"),
    teamCount: document.getElementById("draft-team-count"),
    managersList: document.getElementById("draft-remaining-managers"),
    teamsList: document.getElementById("draft-remaining-teams"),
    potStrip: document.getElementById("draft-pot-strip"),
    startButton: document.getElementById("draft-start-button"),
    nextButton: document.getElementById("draft-next-button"),
    autoButton: document.getElementById("draft-auto-button"),
    finishLink: document.getElementById("draft-finish-link"),
    progressFill: document.getElementById("draft-progress-fill"),
    grid: document.getElementById("draft-pick-grid"),
  };

  const requiredElements = [
    elements.card,
    elements.startButton,
    elements.nextButton,
    elements.autoButton,
  ];

  if (requiredElements.some((element) => !element)) {
    console.error("Draft presentation controls could not be initialized.", elements);
    return;
  }

  const pots = [...new Set(picks.map((pick) => potKey(pick)))];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function potKey(pick) {
    return pick.pot || "Unseeded";
  }

  function potLabel(pot) {
    return `Pot ${pot}`;
  }

  function pickTeamMeta(pick) {
    const parts = [];

    if (pick.group) {
      parts.push(`Group ${pick.group}`);
    }

    if (pick.pot) {
      parts.push(`Pot ${pick.pot}`);
    }

    return parts.join(" · ") || "World Cup team";
  }

  function getCurrentPick() {
    if (state.index < 0) {
      return null;
    }
    return picks[state.index] || null;
  }

  function getActivePot() {
    const currentPick = getCurrentPick();

    if (currentPick) {
      return potKey(currentPick);
    }

    if (!picks.length) {
      return null;
    }

    if (state.phase === "complete") {
      return potKey(picks[picks.length - 1]);
    }

    return potKey(picks[0]);
  }

  function getPotPicks(pot) {
    return picks.filter((pick) => potKey(pick) === pot);
  }

  function isPickFullyRevealed(index) {
    return index < state.index || (index === state.index && state.phase === "team");
  }

  function isManagerRevealed(index) {
    return index < state.index || (index === state.index && ["manager", "team"].includes(state.phase));
  }

  function getRemainingPotPicks(pot) {
    return picks.filter((pick, index) => potKey(pick) === pot && !isPickFullyRevealed(index));
  }

  function getRemainingManagerPicks(pot) {
    return picks.filter((pick, index) => {
      if (potKey(pick) !== pot) {
        return false;
      }

      if (index > state.index) {
        return true;
      }

      return index === state.index && state.phase === "manager";
    });
  }

  function getRemainingTeamPicks(pot) {
    return picks.filter((pick, index) => {
      if (potKey(pick) !== pot) {
        return false;
      }

      if (index > state.index) {
        return true;
      }

      return index === state.index && state.phase === "manager";
    });
  }

  function getGroupsAlreadyHeldByManager(manager) {
    const groups = new Set();

    picks.forEach((pick, index) => {
      if (!isPickFullyRevealed(index)) {
        return;
      }

      if (pick.manager === manager && pick.group) {
        groups.add(pick.group);
      }
    });

    return groups;
  }

  function canManagerTakeTeam(manager, teamPick) {
    if (!manager || !teamPick.group) {
      return true;
    }

    const existingGroups = getGroupsAlreadyHeldByManager(manager);
    return !existingGroups.has(teamPick.group);
  }

  function canAnyRemainingManagerTakeTeam(teamPick) {
    const activePot = getActivePot();
    const remainingManagers = getRemainingManagerPicks(activePot);

    if (!teamPick.group) {
      return true;
    }

    return remainingManagers.some((pick) => canManagerTakeTeam(pick.manager, teamPick));
  }

  function renderPotStrip() {
    elements.potStrip.innerHTML = "";

    pots.forEach((pot) => {
      const potPicks = getPotPicks(pot);
      const pill = document.createElement("div");
      pill.className = "draft-pot-pill";
      pill.dataset.pot = String(pot);
      pill.innerHTML = `
        <span>${escapeHtml(potLabel(pot))}</span>
        <strong>${potPicks.length} picks</strong>
      `;
      elements.potStrip.appendChild(pill);
    });
  }

  function renderQueue() {
    elements.grid.innerHTML = "";

    pots.forEach((pot) => {
      const section = document.createElement("section");
      section.className = "draft-pot-column";
      section.dataset.pot = String(pot);

      const potPicks = getPotPicks(pot);
      section.innerHTML = `
        <div class="draft-pot-column-header">
          <h3>${escapeHtml(potLabel(pot))}</h3>
          <span>${potPicks.length} picks</span>
        </div>
        <div class="draft-pick-grid" data-pot-grid="${escapeHtml(pot)}"></div>
      `;

      const grid = section.querySelector(".draft-pick-grid");
      potPicks.forEach((pick) => {
        const originalIndex = picks.indexOf(pick);
        const item = document.createElement("article");
        item.className = "draft-queue-card";
        item.dataset.index = String(originalIndex);

        item.innerHTML = `
          <span class="draft-queue-number">#${escapeHtml(pick.pick)}</span>
          <span class="draft-queue-flag">?</span>
          <strong>Hidden pick</strong>
          <small>${escapeHtml(potLabel(pot))}</small>
        `;

        grid.appendChild(item);
      });

      elements.grid.appendChild(section);
    });
  }

  function updateQueue() {
    const activePot = getActivePot();
    const cards = elements.grid.querySelectorAll(".draft-queue-card");
    const potColumns = elements.grid.querySelectorAll(".draft-pot-column");
    const potPills = elements.potStrip.querySelectorAll(".draft-pot-pill");

    potColumns.forEach((column) => {
      column.classList.toggle("is-active", column.dataset.pot === String(activePot));
    });

    potPills.forEach((pill) => {
      const pot = pill.dataset.pot;
      const remaining = getRemainingPotPicks(pot).length;
      pill.classList.toggle("is-active", pot === String(activePot));
      pill.classList.toggle("is-complete", remaining === 0);
      pill.querySelector("strong").textContent = `${remaining} left`;
    });

    cards.forEach((card) => {
      const index = Number(card.dataset.index);
      const pick = picks[index];
      const managerRevealed = isManagerRevealed(index);
      const teamRevealed = isPickFullyRevealed(index);

      card.classList.toggle("is-manager-revealed", managerRevealed && !teamRevealed);
      card.classList.toggle("is-revealed", teamRevealed);
      card.classList.toggle("is-current", index === state.index && state.phase !== "complete");

      if (teamRevealed) {
        card.innerHTML = `
          <span class="draft-queue-number">#${escapeHtml(pick.pick)}</span>
          <span class="draft-queue-flag">${escapeHtml(pick.flag)}</span>
          <strong>${escapeHtml(pick.team)}</strong>
          <small>${escapeHtml(pick.manager)}</small>
        `;
      } else if (managerRevealed) {
        card.innerHTML = `
          <span class="draft-queue-number">#${escapeHtml(pick.pick)}</span>
          <span class="draft-queue-flag">👤</span>
          <strong>${escapeHtml(pick.manager)}</strong>
          <small>Team pending</small>
        `;
      } else {
        card.innerHTML = `
          <span class="draft-queue-number">#${escapeHtml(pick.pick)}</span>
          <span class="draft-queue-flag">?</span>
          <strong>Hidden pick</strong>
          <small>${escapeHtml(potLabel(potKey(pick)))}</small>
        `;
      }
    });
  }

  function renderRemainingLists() {
    const activePot = getActivePot();
    const currentPick = getCurrentPick();
    const managerPicks = activePot ? getRemainingManagerPicks(activePot) : [];
    const teamPicks = activePot ? getRemainingTeamPicks(activePot) : [];
    const selectedManager = currentPick && state.phase === "manager" ? currentPick.manager : null;

    elements.currentPot.textContent = activePot ? potLabel(activePot) : "—";
    elements.managerCount.textContent = String(managerPicks.length);
    elements.teamCount.textContent = String(teamPicks.length);

    if (!managerPicks.length) {
      elements.managersList.innerHTML = `<div class="draft-side-empty">This pot is complete.</div>`;
    } else {
      elements.managersList.innerHTML = managerPicks.map((pick) => `
        <div class="draft-side-item manager-side-item ${selectedManager === pick.manager ? "is-selected" : ""}">
          <span>${escapeHtml(pick.manager)}</span>
          ${selectedManager === pick.manager ? "<small>drawn</small>" : ""}
        </div>
      `).join("");
    }

    if (!teamPicks.length) {
      elements.teamsList.innerHTML = `<div class="draft-side-empty">This pot is complete.</div>`;
      return;
    }

    elements.teamsList.innerHTML = teamPicks.map((pick) => {
      const unavailableForSelected = selectedManager && !canManagerTakeTeam(selectedManager, pick);
      const noRemainingFit = !selectedManager && !canAnyRemainingManagerTakeTeam(pick);
      const classes = ["draft-side-item", "team-side-item"];
      const notes = [];

      if (unavailableForSelected || noRemainingFit) {
        classes.push("is-unavailable");
      }

      if (unavailableForSelected) {
        notes.push(`same Group ${escapeHtml(pick.group)}`);
      } else if (noRemainingFit) {
        notes.push("no valid manager left");
      } else if (selectedManager) {
        notes.push("available");
      }

      return `
        <div class="${classes.join(" ")}">
          <span class="mini-flag">${escapeHtml(pick.flag)}</span>
          <span>${escapeHtml(pick.team)}</span>
          ${notes.length ? `<small>${notes.join(" · ")}</small>` : ""}
        </div>
      `;
    }).join("");
  }

  function updateControls() {
    const hasStarted = state.phase !== "idle";
    const isComplete = state.phase === "complete" || (state.index >= picks.length - 1 && state.phase === "team");
    const isActive = hasStarted && !isComplete;

    // The control row is stage-based:
    //   before draft: only Start draft
    //   during draft: only reveal/autoplay controls
    //   after draft: only Back to league
    elements.startButton.classList.toggle("is-draft-control-hidden", hasStarted || isComplete);
    elements.nextButton.classList.toggle("is-draft-control-hidden", !isActive);
    elements.autoButton.classList.toggle("is-draft-control-hidden", !isActive);

    elements.startButton.disabled = !picks.length || hasStarted || isComplete;
    elements.nextButton.disabled = !isActive;
    elements.autoButton.disabled = !isActive;
    elements.autoButton.textContent = state.isAutoPlaying ? "Pause auto-play" : "Auto-play";

    if (state.phase === "manager") {
      elements.nextButton.textContent = "Reveal team";
    } else if (state.phase === "team") {
      elements.nextButton.textContent = state.index >= picks.length - 1 ? "Complete draft" : "Next manager";
    } else {
      elements.nextButton.textContent = "Next pick";
    }

    if (elements.finishLink) {
      elements.finishLink.classList.toggle("is-hidden", !isComplete);
    }

    if (isComplete && state.isAutoPlaying) {
      stopAutoPlay();
    }
  }

  function updateCounters() {
    const revealed = picks.filter((_, index) => isPickFullyRevealed(index)).length;
    const remaining = Math.max(picks.length - revealed, 0);
    const pct = picks.length ? (revealed / picks.length) * 100 : 0;

    elements.currentPick.textContent = `${revealed} / ${picks.length}`;
    elements.remainingPicks.textContent = String(remaining);
    elements.progressFill.style.width = `${pct}%`;
  }

  function updateDraftState() {
    updateQueue();
    renderRemainingLists();
    updateCounters();
    updateControls();
  }

  function animateCard(kind) {
    elements.card.classList.remove("is-revealing", "is-manager-revealing");
    void elements.card.offsetWidth;
    elements.card.classList.add(kind === "manager" ? "is-manager-revealing" : "is-revealing");
  }

  function revealCurrentManager() {
    const pick = getCurrentPick();

    if (!pick) {
      return;
    }

    animateCard("manager");
    elements.pickLabel.textContent = `Pick #${pick.pick} · ${potLabel(pick.pot)}`;
    elements.flag.textContent = "👤";
    elements.teamName.textContent = pick.manager;
    elements.teamMeta.textContent = `Manager drawn — now reveal their ${potLabel(pick.pot)} team.`;
    elements.managerPill.textContent = "National team still hidden";

    updateDraftState();
  }

  function revealCurrentTeam() {
    const pick = getCurrentPick();

    if (!pick) {
      return;
    }

    state.phase = "team";
    animateCard("team");
    elements.pickLabel.textContent = `Pick #${pick.pick} · ${potLabel(pick.pot)}`;
    elements.flag.textContent = pick.flag;
    elements.teamName.textContent = pick.team;
    elements.teamMeta.textContent = pickTeamMeta(pick);
    elements.managerPill.textContent = `Assigned to ${pick.manager}`;

    updateDraftState();

    if (state.index >= picks.length - 1) {
      state.phase = "complete";
      updateControls();
    }
  }

  function advanceDraft() {
    if (!picks.length || state.phase === "complete") {
      stopAutoPlay();
      return;
    }

    if (state.phase === "idle") {
      state.index = 0;
      state.phase = "manager";
      revealCurrentManager();
      return;
    }

    if (state.phase === "manager") {
      revealCurrentTeam();
      return;
    }

    if (state.phase === "team") {
      if (state.index >= picks.length - 1) {
        state.phase = "complete";
        stopAutoPlay();
        updateDraftState();
        return;
      }

      state.index += 1;
      state.phase = "manager";
      revealCurrentManager();
    }
  }

  function startDraft() {
    if (state.phase === "idle") {
      advanceDraft();
    }
  }

  function stopAutoPlay() {
    if (state.timer) {
      window.clearInterval(state.timer);
    }

    state.timer = null;
    state.isAutoPlaying = false;
    updateControls();
  }

  function toggleAutoPlay() {
    if (state.isAutoPlaying) {
      stopAutoPlay();
      return;
    }

    if (state.phase === "complete") {
      return;
    }

    state.isAutoPlaying = true;
    advanceDraft();
    state.timer = window.setInterval(advanceDraft, 1700);
    updateControls();
  }

  function resetPresentation() {
    stopAutoPlay();
    state.index = -1;
    state.phase = "idle";

    elements.card.classList.remove("is-revealing", "is-manager-revealing");
    elements.pickLabel.textContent = "Ready to begin";
    elements.flag.textContent = "🏆";
    elements.teamName.textContent = "World Cup Draft";
    elements.teamMeta.textContent = "Press Start draft to reveal the first manager.";
    elements.managerPill.textContent = "Waiting for commissioner";
    if (elements.finishLink) {
      elements.finishLink.classList.add("is-hidden");
    }

    renderQueue();
    updateDraftState();
  }

  renderPotStrip();

  // Defensive initialization: some browsers may restore disabled form-control
  // state when navigating back/forward. Reset explicitly before wiring events.
  elements.startButton.disabled = false;
  elements.nextButton.disabled = true;
  elements.autoButton.disabled = true;
  elements.startButton.classList.remove("is-draft-control-hidden");
  elements.nextButton.classList.add("is-draft-control-hidden");
  elements.autoButton.classList.add("is-draft-control-hidden");

  elements.startButton.addEventListener("click", startDraft);
  elements.nextButton.addEventListener("click", advanceDraft);
  elements.autoButton.addEventListener("click", toggleAutoPlay);
  resetPresentation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootDraftPresentation);
  } else {
    bootDraftPresentation();
  }
})();
