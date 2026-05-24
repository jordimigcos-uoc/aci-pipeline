/**
 * global_charts.js — 10 visualitzacions D3.js v7 per al tauler ACI Pipeline
 *
 * Funcions globals (cridades des de global_index.html.j2):
 *   drawComparisonChart(data, profile)
 *   drawPrinciplesRadar(data, profile)
 *   drawBoxplot(data, profile)
 *   drawStackedBars(data, profile)
 *   drawTopBottom(data, profile)        → dibuixa chart-top10 + chart-bottom10
 *   drawRadarReadability(data)
 *   drawHeatmap(data, profile)
 *   drawLollipop(data, profile)
 *   drawScatter(data, profile)
 *   drawImpactEffort(recommendations)
 *
 * Dependències globals (injectades per la plantilla Jinja2):
 *   D3_DATA, TYPE_COLORS, PROFILE_COLORS, PROFILE_LABELS, METRIC_LABELS, RECOMMENDATIONS
 */

(function (global) {
  "use strict";

  // ── Utilitats comunes ────────────────────────────────────────────────────

  function aciColor(v) {
    return v >= 70 ? "#27ae60" : (v >= 50 ? "#e67e22" : "#e74c3c");
  }

  var _tooltip = null;
  function tip() {
    if (!_tooltip) _tooltip = d3.select("#d3-tooltip");
    return _tooltip;
  }
  function showTip(evt, html) {
    tip()
      .style("display", "block")
      .style("left",  (evt.clientX + 14) + "px")
      .style("top",   (evt.clientY -  8) + "px")
      .html(html);
  }
  function hideTip() {
    tip().style("display", "none");
  }

  function clearEl(id) {
    d3.select("#" + id).selectAll("*").remove();
  }

  function elWidth(id) {
    var el = document.getElementById(id);
    return el ? Math.max(el.clientWidth || 0, 320) : 500;
  }

  function noData(id, msg) {
    d3.select("#" + id).append("div")
      .style("padding", "2rem")
      .style("text-align", "center")
      .style("color", "#9ca3af")
      .style("font-style", "italic")
      .text(msg || "Sense dades disponibles amb els filtres actuals.");
  }

  function trunc(s, n) {
    n = n || 14;
    return s && s.length > n ? s.slice(0, n - 1) + "…" : (s || "");
  }

  function profileScore(d, profile) {
    return ((d.profiles || {})[profile] || {}).score_overall || 0;
  }

  // ── Gràfic 1: Barres agrupades per tipus × perfil ────────────────────────

  global.drawComparisonChart = function (data, profile) {
    var id = "chart-comparison";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var profs   = ["wcag_strict", "readability_first", "visual_first"];
    var byType  = d3.rollup(
      data,
      function (v) {
        var row = { type: v[0].type };
        profs.forEach(function (p) {
          var scores = v.map(function (d) {
            return ((d.profiles[p] || {}).score_overall) || null;
          }).filter(function (s) { return s !== null; });
          row[p] = scores.length ? d3.mean(scores) : null;
        });
        return row;
      },
      function (d) { return d.type; }
    );

    var types = Array.from(byType.keys()).sort();
    if (!types.length) { noData(id); return; }

    var mg  = { top: 30, right: 20, bottom: 70, left: 48 };
    var W   = elWidth(id);
    var H   = 340;
    var iW  = W - mg.left - mg.right;
    var iH  = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var x0 = d3.scaleBand().domain(types).range([0, iW]).padding(0.25);
    var x1 = d3.scaleBand().domain(profs).range([0, x0.bandwidth()]).padding(0.06);
    var y  = d3.scaleLinear().domain([0, 100]).range([iH, 0]);

    // Grid lines
    g.append("g").call(d3.axisLeft(y).ticks(5).tickSize(-iW).tickFormat(""))
      .call(function (gg) { gg.select(".domain").remove(); })
      .selectAll("line").style("stroke", "#f0f0f0");

    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x0).tickFormat(function (t) { return trunc(t, 12); }))
      .selectAll("text")
      .style("font-size", "11px")
      .attr("transform", "rotate(-30)")
      .attr("text-anchor", "end");
    g.append("g").call(d3.axisLeft(y).ticks(5))
      .selectAll("text").style("font-size", "10px");

    // Bars
    types.forEach(function (t) {
      var rd = byType.get(t);
      profs.forEach(function (p) {
        var val = rd[p];
        if (val === null) return;
        g.append("rect")
          .attr("x",      x0(t) + x1(p))
          .attr("y",      y(val))
          .attr("width",  x1.bandwidth())
          .attr("height", iH - y(val))
          .attr("fill",   (PROFILE_COLORS[p] || "#888") + "cc")
          .attr("rx", 2)
          .on("mouseover", function (evt) {
            showTip(evt,
              "<strong>" + t + "</strong><br>" +
              (PROFILE_LABELS[p] || p) + ": <strong>" + val.toFixed(1) + "</strong>");
          })
          .on("mouseleave", hideTip);
      });
    });

    // Legend
    var legG = svg.append("g")
      .attr("transform", "translate(" + mg.left + "," + (H - 18) + ")");
    profs.forEach(function (p, i) {
      var lx = i * Math.floor(iW / 3);
      legG.append("rect").attr("x", lx).attr("y", 0)
        .attr("width", 11).attr("height", 11)
        .attr("fill", PROFILE_COLORS[p] || "#888").attr("rx", 2);
      legG.append("text").attr("x", lx + 15).attr("y", 10)
        .style("font-size", "9px").style("fill", "#374151")
        .text(PROFILE_LABELS[p] || p);
    });
  };

  // ── Gràfic 2: Radar principis WCAG per sector ─────────────────────────────

  global.drawPrinciplesRadar = function (data, profile) {
    var id = "chart-principles";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var axes = [
      { key: "perceptible",  label: "Perceptible"  },
      { key: "operable",     label: "Operable"     },
      { key: "comprensible", label: "Comprensible" },
      { key: "robust",       label: "Robust"       }
    ];
    var byType = d3.rollup(data,
      function (v) {
        var out = {};
        axes.forEach(function (ax) {
          out[ax.key] = d3.mean(v.map(function (d) {
            return (((d.profiles[profile] || {}).wcag_principles) || {})[ax.key] || 0;
          })) || 0;
        });
        return out;
      },
      function (d) { return d.type; }
    );

    var series = Array.from(byType.entries()).map(function (e) {
      return { label: e[0], values: e[1], color: TYPE_COLORS[e[0]] || "#4b5563" };
    });
    _drawRadar(id, axes, series);
  };

  // Funció radar compartida (usada per gràfics 2 i 6)
  function _drawRadar(id, axes, series) {
    var W      = Math.min(elWidth(id), 520);
    var legH   = Math.ceil(series.length / 2) * 18 + 16;
    var H      = W + legH;
    var marg   = 72;
    var radius = (W - marg * 2) / 2;
    var cx     = W / 2;
    var cy     = radius + marg;
    var N      = axes.length;
    var aSlice = (2 * Math.PI) / N;
    var scR    = d3.scaleLinear().domain([0, 100]).range([0, radius]);

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + cx + "," + cy + ")");

    // Grid circles
    [25, 50, 75, 100].forEach(function (v) {
      g.append("circle").attr("r", scR(v))
        .attr("fill", "none").attr("stroke", "#e5e7eb").attr("stroke-width", 1);
      g.append("text").attr("x", 3).attr("y", -scR(v) + 3)
        .style("font-size", "8px").style("fill", "#9ca3af").text(v);
    });

    // Axes
    axes.forEach(function (ax, i) {
      var angle = aSlice * i - Math.PI / 2;
      var xE = radius * Math.cos(angle), yE = radius * Math.sin(angle);
      g.append("line").attr("x1", 0).attr("y1", 0).attr("x2", xE).attr("y2", yE)
        .attr("stroke", "#d1d5db").attr("stroke-width", 1);
      var lx = (radius + 24) * Math.cos(angle);
      var ly = (radius + 24) * Math.sin(angle);
      g.append("text")
        .attr("x", lx).attr("y", ly)
        .attr("text-anchor", Math.abs(lx) < 5 ? "middle" : (lx > 0 ? "start" : "end"))
        .attr("dominant-baseline", ly < 0 ? "auto" : "hanging")
        .style("font-size", "11px").style("font-weight", "600").style("fill", "#1f2937")
        .text(ax.label);
    });

    // Polygons
    var lineGen = d3.line()
      .x(function (p) { return p.x; }).y(function (p) { return p.y; })
      .curve(d3.curveLinearClosed);

    series.forEach(function (s) {
      var pts = axes.map(function (ax, i) {
        var val   = s.values[ax.key] || 0;
        var angle = aSlice * i - Math.PI / 2;
        return { x: scR(val) * Math.cos(angle), y: scR(val) * Math.sin(angle) };
      });
      g.append("path").datum(pts).attr("d", lineGen)
        .attr("fill", s.color + "22").attr("stroke", s.color).attr("stroke-width", 2.5)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + s.label + "</strong><br>" +
            axes.map(function (ax) {
              return ax.label + ": <strong>" + (s.values[ax.key] || 0).toFixed(1) + "</strong>";
            }).join("<br>"));
        })
        .on("mouseleave", hideTip);

      // Dots on vertices
      axes.forEach(function (ax, i) {
        var val   = s.values[ax.key] || 0;
        var angle = aSlice * i - Math.PI / 2;
        g.append("circle")
          .attr("cx", scR(val) * Math.cos(angle)).attr("cy", scR(val) * Math.sin(angle))
          .attr("r", 3).attr("fill", s.color).attr("stroke", "#fff").attr("stroke-width", 1);
      });
    });

    // Legend
    var legG = svg.append("g").attr("transform", "translate(10," + (cy + radius + 24) + ")");
    series.forEach(function (s, i) {
      var col = i % 2;
      var row = Math.floor(i / 2);
      legG.append("rect")
        .attr("x", col * (W / 2 - 10)).attr("y", row * 18)
        .attr("width", 11).attr("height", 11)
        .attr("fill", s.color).attr("rx", 2);
      legG.append("text")
        .attr("x", col * (W / 2 - 10) + 15).attr("y", row * 18 + 10)
        .style("font-size", "10px").style("fill", "#374151")
        .text(trunc(s.label, 18));
    });
  }

  // ── Gràfic 3: Boxplot ACI per sector ─────────────────────────────────────

  global.drawBoxplot = function (data, profile) {
    var id = "chart-boxplot";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var byType = d3.rollup(data,
      function (v) {
        var scores = v.map(function (d) {
          return ((d.profiles[profile] || {}).score_overall) || null;
        }).filter(function (s) { return s !== null; }).sort(d3.ascending);
        if (!scores.length) return null;
        return {
          type:   v[0].type,
          min:    d3.min(scores),
          q1:     d3.quantile(scores, 0.25),
          median: d3.quantile(scores, 0.5),
          q3:     d3.quantile(scores, 0.75),
          max:    d3.max(scores),
          count:  scores.length,
          scores: scores
        };
      },
      function (d) { return d.type; }
    );

    var types = Array.from(byType.entries())
      .filter(function (e) { return e[1] !== null; })
      .map(function (e) { return e[0]; }).sort();
    if (!types.length) { noData(id); return; }

    var mg = { top: 30, right: 20, bottom: 60, left: 50 };
    var W  = elWidth(id);
    var H  = 360;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var x  = d3.scaleBand().domain(types).range([0, iW]).padding(0.4);
    var y  = d3.scaleLinear().domain([0, 100]).range([iH, 0]);

    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x).tickFormat(function (t) { return trunc(t, 12); }))
      .selectAll("text").style("font-size", "11px");
    g.append("g").call(d3.axisLeft(y).ticks(5))
      .selectAll("text").style("font-size", "10px");
    // Y label
    g.append("text").attr("transform", "rotate(-90)").attr("x", -iH / 2).attr("y", -38)
      .attr("text-anchor", "middle").style("font-size", "10px").style("fill", "#6b7280")
      .text("ACI score (0–100)");

    types.forEach(function (t) {
      var d  = byType.get(t);
      if (!d) return;
      var tc = TYPE_COLORS[t] || "#4b5563";
      var bw = x.bandwidth();
      var xc = x(t) + bw / 2;

      // Whiskers
      g.append("line").attr("x1", xc).attr("x2", xc).attr("y1", y(d.max)).attr("y2", y(d.min))
        .attr("stroke", tc).attr("stroke-width", 1.5).attr("stroke-dasharray", "4,2");
      // Caps
      [[d.max], [d.min]].forEach(function (v) {
        g.append("line")
          .attr("x1", xc - bw * 0.15).attr("x2", xc + bw * 0.15)
          .attr("y1", y(v[0])).attr("y2", y(v[0]))
          .attr("stroke", tc).attr("stroke-width", 1.5);
      });
      // IQR box
      g.append("rect")
        .attr("x", x(t) + bw * 0.1)
        .attr("y", y(d.q3))
        .attr("width",  bw * 0.8)
        .attr("height", Math.max(0, y(d.q1) - y(d.q3)))
        .attr("fill", tc + "30").attr("stroke", tc).attr("stroke-width", 2).attr("rx", 3)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + t + "</strong> (N=" + d.count + ")<br>" +
            "Mediana: <strong>" + d.median.toFixed(1) + "</strong><br>" +
            "Q1–Q3: " + d.q1.toFixed(1) + " – " + d.q3.toFixed(1) + "<br>" +
            "Rang: " + d.min.toFixed(1) + " – " + d.max.toFixed(1));
        })
        .on("mouseleave", hideTip);
      // Median line
      g.append("line")
        .attr("x1", x(t) + bw * 0.1).attr("x2", x(t) + bw * 0.9)
        .attr("y1", y(d.median)).attr("y2", y(d.median))
        .attr("stroke", tc).attr("stroke-width", 3);
      // Individual dots (if few data)
      if (d.count <= 6) {
        d.scores.forEach(function (s) {
          g.append("circle")
            .attr("cx", xc + (Math.random() - 0.5) * bw * 0.25)
            .attr("cy", y(s)).attr("r", 4)
            .attr("fill", tc).attr("opacity", 0.7)
            .attr("stroke", "#fff").attr("stroke-width", 1);
        });
      }
    });
  };

  // ── Gràfic 4: Barres apilades sub-puntuacions per domini ──────────────────

  global.drawStackedBars = function (data, profile) {
    var id   = "chart-stacked";
    clearEl(id);
    var max  = 22;
    var sub  = data.slice(0, max);
    if (!sub.length) { noData(id); return; }

    var keys    = ["wcag", "text", "elements", "performance"];
    var kColors = { wcag: "#1d4ed8", text: "#15803d", elements: "#7c3aed", performance: "#d97706" };
    var kLabels = { wcag: "WCAG", text: "Text", elements: "Elements", performance: "Rendiment" };

    var domains   = sub.map(function (d) { return d.domain; });
    var stackData = sub.map(function (d) {
      var ss  = ((d.profiles[profile] || {}).sub_scores_100) || {};
      var row = { domain: d.domain };
      keys.forEach(function (k) { row[k] = ss[k] || 0; });
      return row;
    });

    var mg = { top: 30, right: 90, bottom: 72, left: 48 };
    var W  = Math.max(elWidth(id), domains.length * 28 + mg.left + mg.right);
    var H  = 380;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var x   = d3.scaleBand().domain(domains).range([0, iW]).padding(0.15);
    var y   = d3.scaleLinear().domain([0, 400]).range([iH, 0]);

    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x).tickFormat(function (t) { return trunc(t, 9); }))
      .selectAll("text")
      .style("font-size", "9px")
      .attr("transform", "rotate(-40)")
      .attr("text-anchor", "end");
    g.append("g").call(d3.axisLeft(y).ticks(5))
      .selectAll("text").style("font-size", "10px");
    g.append("text").attr("transform", "rotate(-90)").attr("x", -iH / 2).attr("y", -38)
      .attr("text-anchor", "middle").style("font-size", "10px").style("fill", "#6b7280")
      .text("Suma sub-puntuacions (màx. 400)");

    var stack   = d3.stack().keys(keys);
    var stacked = stack(stackData);

    stacked.forEach(function (layer) {
      var k = layer.key;
      layer.forEach(function (d) {
        g.append("rect")
          .attr("x",      x(d.data.domain))
          .attr("y",      y(d[1]))
          .attr("width",  x.bandwidth())
          .attr("height", Math.max(0, y(d[0]) - y(d[1])))
          .attr("fill",   kColors[k]).attr("opacity", 0.88)
          .on("mouseover", function (evt) {
            showTip(evt,
              "<strong>" + d.data.domain + "</strong><br>" +
              kLabels[k] + ": <strong>" + (d.data[k] || 0).toFixed(1) + "</strong>");
          })
          .on("mouseleave", hideTip);
      });
    });

    // Legend
    var legG = svg.append("g").attr("transform", "translate(" + (W - mg.right + 8) + "," + mg.top + ")");
    keys.forEach(function (k, i) {
      legG.append("rect").attr("x", 0).attr("y", i * 20)
        .attr("width", 12).attr("height", 12).attr("fill", kColors[k]).attr("rx", 2);
      legG.append("text").attr("x", 16).attr("y", i * 20 + 10)
        .style("font-size", "10px").style("fill", "#374151").text(kLabels[k]);
    });
  };

  // ── Gràfic 5a + 5b: Top 10 / Bottom 10 ────────────────────────────────────

  global.drawTopBottom = function (data, profile) {
    _drawHBar("chart-top10",    data, profile, true,  10);
    _drawHBar("chart-bottom10", data, profile, false, 10);
  };

  function _drawHBar(id, data, profile, topN, n) {
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }
    var sorted = data.slice().sort(function (a, b) {
      return profileScore(b, profile) - profileScore(a, profile);
    });
    var subset = topN ? sorted.slice(0, n) : sorted.slice(-n).reverse();

    var mg = { top: 15, right: 55, bottom: 20, left: 130 };
    var W  = elWidth(id);
    var H  = subset.length * 30 + mg.top + mg.bottom;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var y = d3.scaleBand()
      .domain(subset.map(function (d) { return d.domain; }))
      .range([0, iH]).padding(0.28);
    var x = d3.scaleLinear().domain([0, 100]).range([0, iW]);

    g.append("g").call(d3.axisLeft(y).tickFormat(function (t) { return trunc(t, 18); }))
      .selectAll("text").style("font-size", "10px");

    subset.forEach(function (d) {
      var score = profileScore(d, profile);
      var c     = aciColor(score);
      var tc    = TYPE_COLORS[d.type] || "#4b5563";
      g.append("rect")
        .attr("x", 0).attr("y", y(d.domain))
        .attr("width", x(score)).attr("height", y.bandwidth())
        .attr("fill", c).attr("rx", 3).attr("opacity", 0.9)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + d.domain + "</strong><br>" +
            "<span style='color:" + tc + "'>" + d.type + "</span><br>" +
            "ACI: <strong>" + score.toFixed(1) + "</strong>");
        })
        .on("mouseleave", hideTip);
      g.append("text")
        .attr("x", x(score) + 4).attr("y", y(d.domain) + y.bandwidth() / 2 + 4)
        .style("font-size", "11px").style("font-weight", "700").style("fill", c)
        .text(score.toFixed(1));
    });
  }

  // ── Gràfic 6: Radar readability_first sub-puntuacions ─────────────────────

  global.drawRadarReadability = function (data) {
    var id = "chart-radar-readability";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var axes = [
      { key: "wcag",        label: "WCAG"      },
      { key: "text",        label: "Text"       },
      { key: "elements",    label: "Elements"   },
      { key: "performance", label: "Rendiment"  }
    ];

    var byType = d3.rollup(data,
      function (v) {
        var out = {};
        axes.forEach(function (ax) {
          out[ax.key] = d3.mean(v.map(function (d) {
            return (((d.profiles.readability_first || {}).sub_scores_100) || {})[ax.key] || 0;
          })) || 0;
        });
        return out;
      },
      function (d) { return d.type; }
    );

    var series = Array.from(byType.entries()).map(function (e) {
      return { label: e[0], values: e[1], color: TYPE_COLORS[e[0]] || "#4b5563" };
    });
    _drawRadar(id, axes, series);
  };

  // ── Gràfic 7: Heatmap mètriques × dominis ────────────────────────────────

  global.drawHeatmap = function (data, profile) {
    var id = "chart-heatmap";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var maxDom = 20;
    var subset = data.slice(0, maxDom);
    var domains = subset.map(function (d) { return d.domain; });

    var metricKeys = [
      "color_contrast", "focus_visibility", "target_size", "keyboard_nav",
      "aria_roles", "accessible_names", "critical_violations", "high_violations",
      "flesch_reading_ease", "text_complexity", "heading_hierarchy",
      "alt_text_coverage", "landmark_coverage", "medium_violations",
      "low_violations", "performance_lcp"
    ];
    var mShort = {
      "color_contrast": "Contrast",   "focus_visibility": "Focus",
      "target_size": "Mida",          "keyboard_nav": "Teclat",
      "aria_roles": "ARIA",           "accessible_names": "Noms",
      "critical_violations": "Crít.", "high_violations": "Altes",
      "flesch_reading_ease": "Flesch","text_complexity": "Compl.",
      "heading_hierarchy": "Capç.",   "alt_text_coverage": "Alt-text",
      "landmark_coverage": "Landmk.", "medium_violations": "Mod.",
      "low_violations": "Baix",       "performance_lcp": "LCP"
    };

    var cellW  = Math.max(Math.floor((elWidth(id) - 75) / domains.length), 28);
    var cellH  = 22;
    var labelW = 68;
    var topH   = 58;
    var mg     = { top: topH, right: 20, bottom: 10, left: labelW };
    var W      = domains.length * cellW + mg.left + mg.right;
    var H      = metricKeys.length * cellH + topH + 20;

    var colorFn = d3.scaleSequential(d3.interpolateRdYlGn).domain([0, 100]);

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    // Domain labels (rotated)
    domains.forEach(function (dom, j) {
      svg.append("text")
        .attr("x", mg.left + j * cellW + cellW / 2)
        .attr("y", topH - 4)
        .attr("transform",
          "rotate(-42," + (mg.left + j * cellW + cellW / 2) + "," + (topH - 4) + ")")
        .attr("text-anchor", "start")
        .style("font-size", "9px").style("fill", "#374151")
        .text(trunc(dom, 12));
    });

    // Metric rows
    metricKeys.forEach(function (mk, i) {
      g.append("text")
        .attr("x", -5).attr("y", i * cellH + cellH * 0.68)
        .attr("text-anchor", "end").style("font-size", "10px").style("fill", "#374151")
        .text(mShort[mk] || mk);

      subset.forEach(function (d, j) {
        var val = ((d.profiles[profile] || {}).metrics || {})[mk] || 0;
        g.append("rect")
          .attr("x", j * cellW + 1).attr("y", i * cellH + 1)
          .attr("width", cellW - 2).attr("height", cellH - 2)
          .attr("fill", colorFn(val)).attr("rx", 2)
          .on("mouseover", function (evt) {
            showTip(evt,
              "<strong>" + d.domain + "</strong><br>" +
              (mShort[mk] || mk) + ": <strong>" + val.toFixed(1) + "</strong>");
          })
          .on("mouseleave", hideTip);
        if (cellW >= 28) {
          g.append("text")
            .attr("x", j * cellW + cellW / 2)
            .attr("y", i * cellH + cellH * 0.7)
            .attr("text-anchor", "middle")
            .style("font-size", "8px")
            .style("fill", val > 55 ? "#111827" : "#fff")
            .text(val.toFixed(0));
        }
      });
    });
  };

  // ── Gràfic 8: Lollipop universitats (o tots els dominis si no n'hi ha) ────

  global.drawLollipop = function (data, profile) {
    var id = "chart-lollipop";
    clearEl(id);
    var uniData = data.filter(function (d) { return d.type === "universitat"; });
    if (!uniData.length) uniData = data.slice(0, 15);
    if (!uniData.length) { noData(id); return; }

    var sorted = uniData.slice().sort(function (a, b) {
      return profileScore(b, profile) - profileScore(a, profile);
    });

    var mg = { top: 20, right: 60, bottom: 30, left: 140 };
    var W  = elWidth(id);
    var H  = sorted.length * 30 + mg.top + mg.bottom;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var y = d3.scaleBand()
      .domain(sorted.map(function (d) { return d.domain; }))
      .range([0, iH]).padding(0.4);
    var x = d3.scaleLinear().domain([0, 100]).range([0, iW]);

    g.append("g").call(d3.axisLeft(y).tickFormat(function (t) { return trunc(t, 18); }))
      .selectAll("text").style("font-size", "10px");
    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x).ticks(5)).selectAll("text").style("font-size", "10px");

    sorted.forEach(function (d) {
      var score = profileScore(d, profile);
      var cy    = y(d.domain) + y.bandwidth() / 2;
      var c     = aciColor(score);
      // Stem
      g.append("line").attr("x1", 0).attr("x2", x(score))
        .attr("y1", cy).attr("y2", cy)
        .attr("stroke", c).attr("stroke-width", 2).attr("opacity", 0.55);
      // Circle
      g.append("circle").attr("cx", x(score)).attr("cy", cy).attr("r", 9)
        .attr("fill", c).attr("stroke", "#fff").attr("stroke-width", 1.5)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + d.domain + "</strong><br>ACI: <strong>" + score.toFixed(1) + "</strong>" +
            (d.type ? "<br>" + d.type : ""));
        })
        .on("mouseleave", hideTip);
      // Value label
      g.append("text")
        .attr("x", x(score) + 14).attr("y", cy + 4)
        .style("font-size", "11px").style("font-weight", "700").style("fill", c)
        .text(score.toFixed(1));
    });
  };

  // ── Gràfic 9: Dispersió ACI vs cobertura alt text ─────────────────────────

  global.drawScatter = function (data, profile) {
    var id = "chart-scatter";
    clearEl(id);
    if (!data || !data.length) { noData(id); return; }

    var mg = { top: 30, right: 30, bottom: 60, left: 60 };
    var W  = elWidth(id);
    var H  = 380;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var x = d3.scaleLinear().domain([0, 100]).range([0, iW]);
    var y = d3.scaleLinear().domain([0, 100]).range([iH, 0]);

    // Grid
    g.append("g").call(d3.axisLeft(y).ticks(5).tickSize(-iW).tickFormat(""))
      .call(function (gg) { gg.select(".domain").remove(); })
      .selectAll("line").style("stroke", "#f0f0f0");

    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x).ticks(5)).selectAll("text").style("font-size", "10px");
    g.append("g").call(d3.axisLeft(y).ticks(5)).selectAll("text").style("font-size", "10px");

    // Axis labels
    g.append("text").attr("x", iW / 2).attr("y", iH + 46)
      .attr("text-anchor", "middle").style("font-size", "11px").style("fill", "#6b7280")
      .text("Cobertura Alt text (0–100)");
    g.append("text").attr("transform", "rotate(-90)").attr("x", -iH / 2).attr("y", -46)
      .attr("text-anchor", "middle").style("font-size", "11px").style("fill", "#6b7280")
      .text("ACI global (0–100)");

    // Reference lines at 50
    g.append("line").attr("x1", x(50)).attr("x2", x(50))
      .attr("y1", 0).attr("y2", iH)
      .attr("stroke", "#d1d5db").attr("stroke-width", 1).attr("stroke-dasharray", "3,2");
    g.append("line").attr("x1", 0).attr("x2", iW)
      .attr("y1", y(50)).attr("y2", y(50))
      .attr("stroke", "#d1d5db").attr("stroke-width", 1).attr("stroke-dasharray", "3,2");

    // Trend line
    var pts = data.map(function (d) {
      var pd = d.profiles[profile] || {};
      return {
        ax: (pd.metrics || {}).alt_text_coverage || 0,
        sc: pd.score_overall || 0,
        domain: d.domain, type: d.type
      };
    }).filter(function (p) { return p.ax > 0 || p.sc > 0; });

    if (pts.length > 2) {
      var xm = d3.mean(pts, function (p) { return p.ax; });
      var ym = d3.mean(pts, function (p) { return p.sc; });
      var num = d3.sum(pts, function (p) { return (p.ax - xm) * (p.sc - ym); });
      var den = d3.sum(pts, function (p) { return (p.ax - xm) * (p.ax - xm); });
      if (Math.abs(den) > 0.001) {
        var sl = num / den, ic = ym - sl * xm;
        var clamp = function (v) { return Math.min(100, Math.max(0, v)); };
        g.append("line")
          .attr("x1", x(0)).attr("y1", y(clamp(ic)))
          .attr("x2", x(100)).attr("y2", y(clamp(sl * 100 + ic)))
          .attr("stroke", "#94a3b8").attr("stroke-width", 1.5).attr("stroke-dasharray", "6,3");
      }
    }

    // Dots
    pts.forEach(function (p) {
      var tc = TYPE_COLORS[p.type] || "#4b5563";
      g.append("circle")
        .attr("cx", x(p.ax)).attr("cy", y(p.sc)).attr("r", 7)
        .attr("fill", tc).attr("opacity", 0.75)
        .attr("stroke", "#fff").attr("stroke-width", 1.5)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + p.domain + "</strong><br>" +
            "<span style='color:" + tc + "'>" + p.type + "</span><br>" +
            "Alt text: <strong>" + p.ax.toFixed(1) + "</strong><br>" +
            "ACI: <strong>" + p.sc.toFixed(1) + "</strong>");
        })
        .on("mouseleave", hideTip);
    });

    // Type legend
    var typesP = Array.from(new Set(pts.map(function (p) { return p.type; }))).sort();
    var legG = svg.append("g").attr("transform", "translate(" + (mg.left + 8) + "," + mg.top + ")");
    typesP.forEach(function (t, i) {
      var col = Math.floor(i / 4), row = i % 4;
      legG.append("circle").attr("cx", col * 120 + 5).attr("cy", row * 16 + 5).attr("r", 5)
        .attr("fill", TYPE_COLORS[t] || "#4b5563");
      legG.append("text").attr("x", col * 120 + 14).attr("y", row * 16 + 9)
        .style("font-size", "10px").style("fill", "#374151").text(t);
    });
  };

  // ── Gràfic 10: Matriu impacte–esforç de recomanacions ────────────────────

  global.drawImpactEffort = function (recs) {
    var id = "chart-impact-effort";
    clearEl(id);
    if (!recs || !recs.length) { noData(id); return; }

    var mg = { top: 40, right: 30, bottom: 64, left: 64 };
    var W  = elWidth(id);
    var H  = 440;
    var iW = W - mg.left - mg.right;
    var iH = H - mg.top  - mg.bottom;

    var svg = d3.select("#" + id).append("svg")
      .attr("viewBox", "0 0 " + W + " " + H).attr("width", "100%");
    var g = svg.append("g").attr("transform", "translate(" + mg.left + "," + mg.top + ")");

    var x = d3.scaleLinear().domain([0, 1]).range([0, iW]);
    var y = d3.scaleLinear().domain([0, 1]).range([iH, 0]);

    // Quadrant fills
    var qFills = [
      { x: 0,       y: 0,         w: iW * 0.5, h: iH * 0.5, fill: "#fef9c3" }, // ↖ hi-imp, lo-eff
      { x: iW * 0.5, y: 0,        w: iW * 0.5, h: iH * 0.5, fill: "#fff7ed" }, // ↗ hi-imp, hi-eff
      { x: 0,       y: iH * 0.5,  w: iW * 0.5, h: iH * 0.5, fill: "#f0fdf4" }, // ↙ lo-imp, lo-eff
      { x: iW * 0.5, y: iH * 0.5, w: iW * 0.5, h: iH * 0.5, fill: "#fdf2f8" }  // ↘ lo-imp, hi-eff
    ];
    qFills.forEach(function (q) {
      g.append("rect").attr("x", q.x).attr("y", q.y)
        .attr("width", q.w).attr("height", q.h)
        .attr("fill", q.fill).attr("opacity", 0.55);
    });

    // Quadrant labels
    var qText = [
      { x: iW * 0.25, y: 13,        text: "PRIORITAT ALTA",   c: "#854d0e" },
      { x: iW * 0.75, y: 13,        text: "PLANIFICAR",       c: "#9a3412" },
      { x: iW * 0.25, y: iH - 5,    text: "QUICK WINS",       c: "#14532d" },
      { x: iW * 0.75, y: iH - 5,    text: "EVITAR",           c: "#701a75" }
    ];
    qText.forEach(function (qt) {
      g.append("text").attr("x", qt.x).attr("y", qt.y)
        .attr("text-anchor", "middle")
        .style("font-size", "9px").style("font-weight", "700")
        .style("fill", qt.c).style("opacity", "0.65").text(qt.text);
    });

    // Crosshair at 0.5
    g.append("line").attr("x1", x(0.5)).attr("x2", x(0.5)).attr("y1", 0).attr("y2", iH)
      .attr("stroke", "#cbd5e1").attr("stroke-width", 1.5).attr("stroke-dasharray", "4,3");
    g.append("line").attr("x1", 0).attr("x2", iW).attr("y1", y(0.5)).attr("y2", y(0.5))
      .attr("stroke", "#cbd5e1").attr("stroke-width", 1.5).attr("stroke-dasharray", "4,3");

    // Axes
    g.append("g").attr("transform", "translate(0," + iH + ")")
      .call(d3.axisBottom(x).ticks(5).tickFormat(function (d) { return (d * 100) + "%"; }))
      .selectAll("text").style("font-size", "10px");
    g.append("g").call(d3.axisLeft(y).ticks(5).tickFormat(function (d) { return (d * 100) + "%"; }))
      .selectAll("text").style("font-size", "10px");

    // Axis labels
    g.append("text").attr("x", iW / 2).attr("y", iH + 48)
      .attr("text-anchor", "middle").style("font-size", "11px").style("fill", "#4b5563")
      .text("Esforç d'implementació →");
    g.append("text").attr("transform", "rotate(-90)").attr("x", -iH / 2).attr("y", -50)
      .attr("text-anchor", "middle").style("font-size", "11px").style("fill", "#4b5563")
      .text("← Impacte en accessibilitat");

    var rScale = d3.scaleLinear().domain([1, 5]).range([9, 24]);

    recs.forEach(function (r) {
      var bx = x(r.effort);
      var by = y(r.impact);
      var br = rScale(r.priority);
      var bc = r.impact >= 0.75 ? "#1d4ed8" : (r.impact >= 0.5 ? "#15803d" : "#6b7280");

      g.append("circle")
        .attr("cx", bx).attr("cy", by).attr("r", br)
        .attr("fill", bc).attr("opacity", 0.78)
        .attr("stroke", "#fff").attr("stroke-width", 2)
        .on("mouseover", function (evt) {
          showTip(evt,
            "<strong>" + r.name + "</strong><br>" +
            "Impacte: <strong>" + (r.impact * 100).toFixed(0) + "%</strong><br>" +
            "Esforç: <strong>" + (r.effort * 100).toFixed(0) + "%</strong><br>" +
            "Prioritat: " + r.priority + "/5 · " + r.wcag);
        })
        .on("mouseleave", hideTip);

      // Label inside circle
      if (br >= 16) {
        g.append("text").attr("x", bx).attr("y", by + 4)
          .attr("text-anchor", "middle")
          .style("font-size", "8px").style("font-weight", "700").style("fill", "#fff")
          .style("pointer-events", "none")
          .text(r.id);
      }
    });

    // Legend: priority scale
    var legG = svg.append("g").attr("transform", "translate(" + mg.left + ",10)");
    legG.append("text").attr("x", 0).attr("y", 12)
      .style("font-size", "9px").style("fill", "#6b7280").text("Prioritat (mida):");
    [1, 3, 5].forEach(function (p, i) {
      legG.append("circle").attr("cx", 72 + i * 32).attr("cy", 8).attr("r", rScale(p))
        .attr("fill", "#1d4ed8").attr("opacity", 0.65);
      legG.append("text").attr("x", 72 + i * 32).attr("y", 22)
        .attr("text-anchor", "middle").style("font-size", "9px").style("fill", "#374151").text(p);
    });
  };

}(window));
