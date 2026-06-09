(() => {
  function bootDraftPresentation() {
    const dataElement = document.getElementById("draft-picks-data");
    const stateElement = document.getElementById("draft-state-data");
    const shell = document.querySelector(".draft-stage-shell");

    if (!dataElement || !shell) {
      return;
    }

    let picks = [];
    let initialDraftState = {};
    let reconnectTimer = null;
    let draftSocket = null;

    try {
      const parsedPicks = JSON.parse(dataElement.textContent);
      picks = Array.isArray(parsedPicks) ? parsedPicks : [];
    } catch (error) {
      console.error("Could not parse draft picks payload.", error);
      picks = [];
    }

    if (stateElement) {
      try {
        initialDraftState = JSON.parse(stateElement.textContent) || {};
      } catch (error) {
        console.error("Could not parse draft state payload.", error);
        initialDraftState = {};
      }
    }

    const state = {
      index: Number.isInteger(initialDraftState.index) ? initialDraftState.index : -1,
      phase: initialDraftState.phase || "idle", // idle, buffer, manager, team, complete
      timer: null,
      isAutoPlaying: Boolean(initialDraftState.autoplay),
      isBusy: false,
    };

    const canControl = shell.dataset.canControl === "true";
    const leagueSlug = shell.dataset.leagueSlug;

    const urls = {
      state: shell.dataset.draftStateUrl,
      start: shell.dataset.draftStartUrl,
      advance: shell.dataset.draftAdvanceUrl,
      autoplay: shell.dataset.draftAutoplayUrl,
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
      viewerCount: document.getElementById("draft-viewer-count"),
    };

    const requiredElements = [
      elements.card,
      elements.currentPick,
      elements.currentPot,
      elements.remainingPicks,
      elements.managersList,
      elements.teamsList,
      elements.grid,
    ];

    if (requiredElements.some((element) => !element)) {
      console.error("Draft presentation could not be initialized.", elements);
      return;
    }

    let pots = [...new Set(picks.map((pick) => potKey(pick)))];
    let picksSignature = signatureForPicks(picks);

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function signatureForPicks(value) {
      return Array.isArray(value)
        ? value.map((pick) => pick.id || `${pick.manager}:${pick.team}:${pick.pot}`).join("|")
        : "";
    }

    function replacePicks(nextPicks) {
      if (!Array.isArray(nextPicks)) {
        return;
      }

      const nextSignature = signatureForPicks(nextPicks);
      const shouldRerender = nextSignature !== picksSignature;

      picks = nextPicks;
      picksSignature = nextSignature;
      pots = [...new Set(picks.map((pick) => potKey(pick)))];

      if (shouldRerender) {
        renderPotStrip();
        renderQueue();
      }
    }

    function getCookie(name) {
      const cookieValue = document.cookie
        .split("; ")
        .find((row) => row.startsWith(`${name}=`));

      if (!cookieValue) {
        return "";
      }

      return decodeURIComponent(cookieValue.split("=").slice(1).join("="));
    }

    function potKey(pick) {
      return pick.pot || "Unseeded";
    }

    function potLabel(pot) {
      return pot === "Unseeded" ? "Unseeded" : `Pot ${pot}`;
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

    function compareStrings(left, right) {
      return String(left || "").localeCompare(String(right || ""), undefined, {
        sensitivity: "base",
        numeric: true,
      });
    }

    function sortManagerPicksForDisplay(value) {
      return [...value].sort((left, right) => {
        const byManager = compareStrings(left.manager, right.manager);
        if (byManager !== 0) {
          return byManager;
        }
        return compareStrings(left.team, right.team);
      });
    }

    function sortTeamPicksForDisplay(value) {
      return [...value].sort((left, right) => {
        const byTeam = compareStrings(left.team, right.team);
        if (byTeam !== 0) {
          return byTeam;
        }
        return compareStrings(left.manager, right.manager);
      });
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
      if (state.phase === "complete") {
        return true;
      }

      return index < state.index || (index === state.index && state.phase === "team");
    }

    function isManagerRevealed(index) {
      if (state.phase === "complete") {
        return true;
      }

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

        if (state.phase === "complete") {
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

        if (state.phase === "complete") {
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
          card.querySelector(".draft-queue-flag").textContent = pick.flag;
          card.querySelector("strong").textContent = pick.team;
          card.querySelector("small").textContent = pick.manager;
        } else if (managerRevealed) {
          card.querySelector(".draft-queue-flag").textContent = "👤";
          card.querySelector("strong").textContent = pick.manager;
          card.querySelector("small").textContent = "Team hidden";
        } else {
          card.querySelector(".draft-queue-flag").textContent = "?";
          card.querySelector("strong").textContent = "Hidden pick";
          card.querySelector("small").textContent = potLabel(potKey(pick));
        }
      });
    }

    function renderRemainingLists() {
      const activePot = getActivePot();
      const managerPicks = activePot
        ? sortManagerPicksForDisplay(getRemainingManagerPicks(activePot))
        : [];
      const teamPicks = activePot
        ? sortTeamPicksForDisplay(getRemainingTeamPicks(activePot))
        : [];
      const currentPick = getCurrentPick();
      const highlightedManager = state.phase === "manager" && currentPick ? currentPick.manager : null;

      elements.managersList.innerHTML = "";
      elements.teamsList.innerHTML = "";

      if (!managerPicks.length) {
        elements.managersList.innerHTML = `<div class="draft-side-empty">No managers remaining in this pot.</div>`;
      } else {
        managerPicks.forEach((pick) => {
          const item = document.createElement("div");
          item.className = "draft-side-item manager-side-item";
          item.classList.toggle("is-selected", pick.manager === highlightedManager);
          item.innerHTML = `
            <span>${escapeHtml(pick.manager)}</span>
            <small>${escapeHtml(potLabel(pick.pot))}</small>
          `;
          elements.managersList.appendChild(item);
        });
      }

      if (!teamPicks.length) {
        elements.teamsList.innerHTML = `<div class="draft-side-empty">No teams remaining in this pot.</div>`;
      } else {
        teamPicks.forEach((pick) => {
          const item = document.createElement("div");
          item.className = "draft-side-item team-side-item";

          if (highlightedManager && !canManagerTakeTeam(highlightedManager, pick)) {
            item.classList.add("is-unavailable");
          } else if (!highlightedManager && !canAnyRemainingManagerTakeTeam(pick)) {
            item.classList.add("is-unavailable");
          }

          item.innerHTML = `
            <span class="mini-flag">${escapeHtml(pick.flag)}</span>
            <span>${escapeHtml(pick.team)}</span>
            <small>${pick.group ? `Group ${escapeHtml(pick.group)}` : "No group"}</small>
          `;
          elements.teamsList.appendChild(item);
        });
      }

      elements.managerCount.textContent = String(managerPicks.length);
      elements.teamCount.textContent = String(teamPicks.length);
    }

    function updateControls() {
      if (!canControl) {
        return;
      }

      const hasStarted = state.phase !== "idle";
      const isComplete = state.phase === "complete";
      const isActive = hasStarted && !isComplete;

      elements.startButton.classList.toggle("is-draft-control-hidden", hasStarted || isComplete);
      elements.nextButton.classList.toggle("is-draft-control-hidden", !isActive);
      elements.autoButton.classList.toggle("is-draft-control-hidden", !isActive);

      elements.startButton.disabled = hasStarted || isComplete || state.isBusy;
      elements.nextButton.disabled = !isActive || state.isBusy;
      elements.autoButton.disabled = !isActive || state.isBusy;
      elements.autoButton.textContent = state.isAutoPlaying ? "Pause auto-play" : "Auto-play";

      if (state.phase === "buffer") {
        elements.nextButton.textContent = "Draw first manager";
      } else if (state.phase === "manager") {
        elements.nextButton.textContent = "Reveal team";
      } else if (state.phase === "team") {
        elements.nextButton.textContent = state.index >= picks.length - 1 ? "Complete draft" : "Next manager";
      } else {
        elements.nextButton.textContent = "Next pick";
      }

      if (elements.finishLink) {
        elements.finishLink.classList.toggle("is-hidden", !isComplete);
      }
    }

    function updateCounters() {
      const revealed = picks.filter((_, index) => isPickFullyRevealed(index)).length;
      const remaining = Math.max(picks.length - revealed, 0);
      const pct = picks.length ? (revealed / picks.length) * 100 : 0;

      elements.currentPick.textContent = `${revealed} / ${picks.length}`;
      elements.remainingPicks.textContent = String(remaining);
      elements.progressFill.style.width = `${pct}%`;

      const activePot = getActivePot();
      elements.currentPot.textContent = activePot ? potLabel(activePot) : "—";
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

    function renderIdle() {
      elements.card.classList.remove("is-revealing", "is-manager-revealing");
      elements.pickLabel.textContent = "Ready to begin";
      elements.flag.textContent = "🏆";
      elements.teamName.textContent = "World Cup Draft";
      elements.teamMeta.textContent = picks.length
        ? "Press Start draft to reveal the first manager."
        : "Press Start draft to generate hidden assignments and begin the reveal.";
      elements.managerPill.textContent = "Waiting for commissioner";
      updateDraftState();
    }

    function renderBuffer() {
      elements.card.classList.remove("is-revealing", "is-manager-revealing");
      elements.pickLabel.textContent = "Draft started";
      elements.flag.textContent = "🎲";
      elements.teamName.textContent = "Ready for the first draw";
      elements.teamMeta.textContent = "Waiting for the commissioner to start the draft.";
      elements.managerPill.textContent = "Ready for the first draw";
      updateDraftState();
    }

    function renderCurrentManager(shouldAnimate = false) {
      const pick = getCurrentPick();

      if (!pick) {
        renderIdle();
        return;
      }

      if (shouldAnimate) {
        animateCard("manager");
      }

      elements.pickLabel.textContent = `Pick #${pick.pick} · ${potLabel(pick.pot)}`;
      elements.flag.textContent = "👤";
      elements.teamName.textContent = pick.manager;
      elements.teamMeta.textContent = `Manager drawn — now reveal their ${potLabel(pick.pot)} team.`;
      elements.managerPill.textContent = "National team still hidden";
      updateDraftState();
    }

    function renderCurrentTeam(shouldAnimate = false) {
      const pick = getCurrentPick();

      if (!pick) {
        renderIdle();
        return;
      }

      if (shouldAnimate) {
        animateCard("team");
      }

      elements.pickLabel.textContent = `Pick #${pick.pick} · ${potLabel(pick.pot)}`;
      elements.flag.textContent = pick.flag;
      elements.teamName.textContent = pick.team;
      elements.teamMeta.textContent = pickTeamMeta(pick);
      elements.managerPill.textContent = `Assigned to ${pick.manager}`;
      updateDraftState();
    }

    function renderComplete() {
      elements.card.classList.remove("is-revealing", "is-manager-revealing");
      elements.pickLabel.textContent = "Draft complete";
      elements.flag.textContent = "🏆";
      elements.teamName.textContent = "All teams revealed";
      elements.teamMeta.textContent = "The draft presentation is complete.";
      elements.managerPill.textContent = "League assignments are ready";
      updateDraftState();
      stopAutoPlay(false);
    }

    function applyServerState(payload, { animate = true } = {}) {
      replacePicks(payload.picks);

      const previousIndex = state.index;
      const previousPhase = state.phase;

      state.index = Number.isInteger(payload.index) ? payload.index : -1;
      state.phase = payload.phase || "idle";
      state.isAutoPlaying = Boolean(payload.autoplay);

      const shouldAnimate =
        animate &&
        (previousIndex !== state.index || previousPhase !== state.phase);

      if (state.phase === "idle") {
        renderIdle();
      } else if (state.phase === "buffer") {
        renderBuffer();
      } else if (state.phase === "manager") {
        renderCurrentManager(shouldAnimate);
      } else if (state.phase === "team") {
        renderCurrentTeam(shouldAnimate);
      } else if (state.phase === "complete") {
        renderComplete();
      } else {
        renderIdle();
      }

      syncAutoTimer();
      closeDraftSocketIfComplete();
    }

    async function postDraftAction(url, body = null) {
      if (!url || state.isBusy) {
        return;
      }

      state.isBusy = true;
      updateControls();

      try {
        const response = await window.fetch(url, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Accept": "application/json",
          },
          body,
        });

        const payload = await response.json();

        if (!response.ok) {
          throw new Error(payload.error || "Draft action failed.");
        }

        applyServerState(payload);
      } catch (error) {
        console.error(error);
        window.alert(error.message || "Draft action failed.");
        stopAutoPlay();
      } finally {
        state.isBusy = false;
        updateControls();
      }
    }

    function startDraft() {
      postDraftAction(urls.start);
    }

    function advanceDraft() {
      if (!picks.length || state.phase === "complete") {
        stopAutoPlay();
        return;
      }

      postDraftAction(urls.advance);
    }

    function stopAutoPlay(syncServer = true) {
      if (state.timer) {
        window.clearInterval(state.timer);
      }

      state.timer = null;
      state.isAutoPlaying = false;

      if (syncServer && urls.autoplay) {
        const body = new FormData();
        body.append("enabled", "false");
        postDraftAction(urls.autoplay, body);
      } else {
        updateControls();
      }
    }

    function syncAutoTimer() {
      if (state.phase === "complete" || !state.isAutoPlaying) {
        if (state.timer) {
          window.clearInterval(state.timer);
          state.timer = null;
        }
        return;
      }

      if (!state.timer) {
        state.timer = window.setInterval(advanceDraft, 1700);
      }
    }

    function toggleAutoPlay() {
      if (state.isAutoPlaying) {
        stopAutoPlay();
        return;
      }

      if (state.phase === "complete") {
        return;
      }

      const body = new FormData();
      body.append("enabled", "true");
      postDraftAction(urls.autoplay, body).then(() => {
        if (state.phase !== "complete") {
          advanceDraft();
        }
      });
    }

    function websocketUrlForLeague(slug) {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      return `${protocol}://${window.location.host}/ws/draft/${slug}/`;
    }

    async function fetchLatestDraftState() {
      if (!urls.state) {
        return;
      }

      try {
        const response = await window.fetch(urls.state, {
          headers: {
            "Accept": "application/json",
          },
        });

        if (!response.ok) {
          throw new Error("Could not fetch latest draft state.");
        }

        const payload = await response.json();
        applyServerState(payload);
      } catch (error) {
        console.error(error);
      }
    }

    function connectDraftSocket() {
      if (!leagueSlug || state.phase === "complete") {
        return;
      }

      draftSocket = new WebSocket(websocketUrlForLeague(leagueSlug));

      draftSocket.onmessage = (event) => {
        let payload = {};

        try {
          payload = JSON.parse(event.data);
        } catch (error) {
          console.error("Invalid draft websocket payload.", error);
          return;
        }

        if (payload.type === "draft.state_changed" && !state.isBusy) {
          fetchLatestDraftState();
        }

        if (
          payload.type === "draft.viewer_count_changed" &&
          elements.viewerCount
        ) {
          elements.viewerCount.textContent = payload.viewer_count;
        }
      };

      draftSocket.onclose = () => {
        draftSocket = null;

        if (state.phase !== "complete") {
          reconnectTimer = window.setTimeout(connectDraftSocket, 10000);
        }
      };

      draftSocket.onerror = (event) => {
        console.error("Draft websocket error.", event);
      };
    }

    renderPotStrip();
    renderQueue();

    // Defensive initialization: some browsers may restore disabled form-control
    // state when navigating back/forward. Reset explicitly before rendering.
    if (elements.startButton) {
      elements.startButton.disabled = false;
    }

    if (elements.nextButton) {
      elements.nextButton.disabled = true;
    }

    if (elements.autoButton) {
      elements.autoButton.disabled = true;
    }

    if (canControl) {
      elements.startButton.addEventListener("click", startDraft);
      elements.nextButton.addEventListener("click", advanceDraft);
      elements.autoButton.addEventListener("click", toggleAutoPlay);
    }

    function closeDraftSocketIfComplete() {
      if (state.phase !== "complete") {
        return;
      }

      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }

      if (draftSocket && draftSocket.readyState === WebSocket.OPEN) {
        draftSocket.close();
      }
    }

    applyServerState(initialDraftState, { animate: false });
    if (state.phase !== "complete") {
      connectDraftSocket();
    }

    window.addEventListener("beforeunload", () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      if (draftSocket) {
        draftSocket.close();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootDraftPresentation);
  } else {
    bootDraftPresentation();
  }
})();

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;

    await navigator.clipboard.writeText(target.href || target.textContent.trim());
    button.classList.add("copied");

    window.setTimeout(() => {
      button.classList.remove("copied");
    }, 1200);
  });
});