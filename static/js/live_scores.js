(function () {
  const root = document.querySelector("[data-live-score-tournament-slug]");
  if (!root) {
    return;
  }

  const tournamentSlug = root.dataset.liveScoreTournamentSlug;
  if (!tournamentSlug) {
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socketUrl = `${protocol}://${window.location.host}/ws/tournaments/${tournamentSlug}/scores/`;
  const socket = new WebSocket(socketUrl);

  socket.addEventListener("message", function (event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }

    if (message.type !== "live_scores.match_changed" || !message.match) {
      return;
    }

    updateMatchCards(message.match);
  });

  function updateMatchCards(match) {
    const cards = document.querySelectorAll(`[data-live-score-match-id="${match.id}"]`);
    cards.forEach(function (card) {
      updateCard(card, match);
    });
  }

  function updateCard(card, match) {
    const score = match.score || {};

    card.classList.toggle("has-live-score", Boolean(score.is_live));
    card.classList.toggle("is-complete", Boolean(match.is_complete));

    updateMainScore(card, score);
    updateSplitScores(card, score);
    updateStatus(card, score);
    updateDetail(card, score);
    updateWinner(card, match.winner);
    updateLiveClasses(card, score);
    updateBracketWinnerClasses(card, match);
  }

  function scoreText(score) {
    if (!score.has_score) {
      return "vs";
    }
    return `${score.home_score}–${score.away_score}`;
  }

  function updateMainScore(card, score) {
    card.querySelectorAll("[data-live-score-main-score]").forEach(function (node) {
      node.textContent = scoreText(score);
    });
  }

  function updateSplitScores(card, score) {
    card.querySelectorAll("[data-live-score-home-score]").forEach(function (node) {
      node.textContent = score.has_score ? score.home_score : "";
      node.hidden = !score.has_score;
    });
    card.querySelectorAll("[data-live-score-away-score]").forEach(function (node) {
      node.textContent = score.has_score ? score.away_score : "";
      node.hidden = !score.has_score;
    });
  }

  function updateStatus(card, score) {
    card.querySelectorAll("[data-live-score-status]").forEach(function (node) {
      node.textContent = score.status_label || "";
      node.hidden = !score.status_label;

      const existing = Array.from(node.classList).filter(function (name) {
        // Keep the structural pill class. Only swap status color/state classes
        // such as status-live/status-final/status-scheduled.
        return name.indexOf("status-") === 0 && name !== "status-pill";
      });
      existing.forEach(function (name) {
        node.classList.remove(name);
      });
      if (score.status_class) {
        node.classList.add(`status-${score.status_class}`);
      }
    });
  }

  function updateDetail(card, score) {
    card.querySelectorAll("[data-live-score-detail]").forEach(function (node) {
      node.textContent = score.detail_label || "";
      node.hidden = !score.detail_label;
    });
  }

  function updateWinner(card, winner) {
    card.querySelectorAll("[data-live-score-winner]").forEach(function (node) {
      if (winner) {
        node.textContent = `Winner: ${winner.flag ? winner.flag + " " : ""}${winner.name}`;
        node.hidden = false;
      } else {
        node.textContent = "";
        node.hidden = true;
      }
    });
  }

  function updateLiveClasses(card, score) {
    card.querySelectorAll("[data-live-score-main-score], [data-live-score-home-score], [data-live-score-away-score]").forEach(function (node) {
      node.classList.toggle("is-live", Boolean(score.is_live));
    });
    card.querySelectorAll(".mini-match-score, .match-score").forEach(function (node) {
      node.classList.toggle("is-live", Boolean(score.is_live));
    });
  }

  function updateBracketWinnerClasses(card, match) {
    if (!card.classList.contains("bracket-match-card")) {
      return;
    }

    const winnerId = match.winner && match.winner.id ? String(match.winner.id) : "";
    card.querySelectorAll("[data-live-score-team-id]").forEach(function (teamRow) {
      teamRow.classList.remove("winner", "loser");
      if (!match.is_complete || !winnerId) {
        return;
      }
      if (teamRow.dataset.liveScoreTeamId === winnerId) {
        teamRow.classList.add("winner");
      } else {
        teamRow.classList.add("loser");
      }
    });
  }
})();
