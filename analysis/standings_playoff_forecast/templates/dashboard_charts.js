(function () {
  "use strict";

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function renderTable(container, captionText, columns, rows, rowClass) {
    clear(container);
    const table = document.createElement("table");
    const caption = element("caption", captionText);
    table.appendChild(caption);
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach((column) => {
      const cell = element("th", column.label);
      cell.scope = "col";
      headRow.appendChild(cell);
    });
    head.appendChild(headRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    rows.forEach((row) => {
      const tableRow = document.createElement("tr");
      const suppliedClass = rowClass ? rowClass(row) : "";
      if (suppliedClass) tableRow.className = suppliedClass;
      columns.forEach((column) => {
        const cell = element("td");
        const value = column.value(row);
        if (value && value.nodeType) cell.appendChild(value);
        else cell.textContent = value === undefined || value === null ? "Unavailable" : String(value);
        cell.dataset.column = column.label;
        tableRow.appendChild(cell);
      });
      body.appendChild(tableRow);
    });
    table.appendChild(body);
    container.appendChild(table);
  }

  function probabilityBar(value, formatted) {
    const wrapper = element("span", null, "probability-bar");
    wrapper.appendChild(element("strong", formatted));
    const track = element("span");
    const fill = element("i");
    fill.style.setProperty("--bar", `${Math.max(0, Math.min(100, Number(value) * 100))}%`);
    track.appendChild(fill);
    wrapper.appendChild(track);
    return wrapper;
  }

  function renderHeatmap(container, teams, matrix, teamCount, formatProbability) {
    const byTeam = new Map();
    matrix.forEach((cell) => {
      if (!byTeam.has(String(cell.team_id))) byTeam.set(String(cell.team_id), new Map());
      byTeam.get(String(cell.team_id)).set(Number(cell.final_rank), Number(cell.probability));
    });
    const columns = [{ label: "Team", value: (row) => row.team_abbreviation }];
    for (let rank = 1; rank <= teamCount; rank += 1) {
      columns.push({
        label: String(rank),
        value: (row) => {
          const probability = byTeam.get(String(row.team_id)).get(rank);
          const cell = element("strong", formatProbability(probability));
          const wrapper = element("span", null, "heat-cell");
          wrapper.style.setProperty("--heat", `${Math.min(92, 8 + probability * 84)}%`);
          wrapper.appendChild(cell);
          wrapper.setAttribute("aria-label", `${row.team_abbreviation}, final rank ${rank}, ${formatProbability(probability)}`);
          return wrapper;
        },
      });
    }
    renderTable(
      container,
      "Probability of every supplied final rank for visible race teams",
      columns,
      teams
    );
  }

  window.ForecastCharts = { clear, element, probabilityBar, renderHeatmap, renderTable };
})();
