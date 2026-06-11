(function () {
  function formatLocalTime(date, format) {
    const includeYear = format === "long";

    const options = {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    };

    if (includeYear) {
      options.year = "numeric";
    }

    const formatter = new Intl.DateTimeFormat(undefined, options);
    const parts = formatter.formatToParts(date);
    const values = {};

    for (const part of parts) {
      if (part.type !== "literal") {
        values[part.type] = part.value;
      }
    }

    const datePieces = [values.month, values.day].filter(Boolean).join(" ");

    let dateText = datePieces;
    if (includeYear && values.year) {
      dateText = `${datePieces}, ${values.year}`;
    }

    const timePieces = [values.hour, values.minute].filter(Boolean);
    let timeText = timePieces.join(":");

    if (values.dayPeriod) {
      timeText = `${timeText} ${values.dayPeriod}`;
    }

    if (values.timeZoneName) {
      timeText = `${timeText} ${values.timeZoneName}`;
    }

    return `${dateText} · ${timeText}`;
  }

  function renderLocalTimes() {
    const nodes = document.querySelectorAll("[data-local-time]");

    for (const node of nodes) {
      const rawValue = node.dataset.localTime;
      if (!rawValue) {
        continue;
      }

      const date = new Date(rawValue);
      if (Number.isNaN(date.getTime())) {
        continue;
      }

      const format = node.dataset.localTimeFormat || "short";
      node.textContent = formatLocalTime(date, format);
      node.title = `Local time: ${date.toLocaleString()} (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderLocalTimes);
  } else {
    renderLocalTimes();
  }
})();
