const ALLOWED_EXTENSIONS = new Set(["csv", "txt", "tsv"]);
const REQUIRED_COLUMNS = ["name", "ra", "dec"];
const OBSERVING_PLAN_KEY = "published/latest/observing_plan.csv";
const OBSERVING_PLAN_MANIFEST_KEY = "published/latest/manifest.json";
const COLUMN_ALIASES = {
  name: ["name", "target", "object", "source", "target_name"],
  ra: ["ra", "raj2000", "ra_deg"],
  dec: ["dec", "dej2000", "dec_deg"],
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return corsPreflightResponse(request, env);
    }

    if (request.method === "GET" && url.pathname === "/") {
      return htmlResponse(renderForm(env));
    }

    if (request.method === "GET" && (url.pathname === "/demo" || url.pathname === "/demo/plan")) {
      return htmlResponse(renderDemoPlanPage());
    }

    if (request.method === "GET" && url.pathname === "/demo/submit") {
      return htmlResponse(renderDemoSubmissionPage());
    }

    if (request.method === "GET" && url.pathname === "/sample.csv") {
      return csvResponse(sampleCsv());
    }

    if (request.method === "GET" && url.pathname === "/observing-plan.csv") {
      return handlePublishedObject(request, env, OBSERVING_PLAN_KEY, "text/csv; charset=utf-8", "skyq_observing_plan.csv");
    }

    if (request.method === "GET" && url.pathname === "/observing-plan-manifest.json") {
      return handlePublishedObject(request, env, OBSERVING_PLAN_MANIFEST_KEY, "application/json; charset=utf-8", null);
    }

    if (request.method === "GET" && url.pathname.startsWith("/products/latest/")) {
      return handlePublishedProduct(request, env, url.pathname);
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse({ ok: true, service: "skyq-submission-worker" });
    }

    if (request.method === "GET" && url.pathname === "/admin/submissions") {
      return handleAdminSubmissions(request, env);
    }

    if (request.method === "POST" && url.pathname === "/submit") {
      return handleSubmit(request, env);
    }

    return htmlResponse(renderNotFound(), 404);
  },
};

async function handleAdminSubmissions(request, env) {
  const token = new URL(request.url).searchParams.get("token") || "";

  if (!env.ADMIN_TOKEN || token !== env.ADMIN_TOKEN) {
    return jsonResponse({ ok: false, error: "Unauthorized" }, 401);
  }

  const listing = await env.SUBMISSIONS.list({
    prefix: "incoming/",
    limit: 100,
  });

  const objects = listing.objects.map((object) => ({
    key: object.key,
    size: object.size,
    uploaded: object.uploaded,
    etag: object.etag,
  }));

  return jsonResponse({
    ok: true,
    count: objects.length,
    truncated: listing.truncated,
    cursor: listing.cursor || null,
    objects,
  });
}

async function handlePublishedObject(request, env, key, contentType, filename) {
  const object = await env.SUBMISSIONS.get(key);

  if (!object) {
    return jsonResponse({
      ok: false,
      error: "Published observing plan is not available yet.",
      key,
    }, 404, corsHeaders(request, env));
  }

  const headers = {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
    ...corsHeaders(request, env),
  };

  if (filename) {
    headers["Content-Disposition"] = `inline; filename="${filename}"`;
  }

  return new Response(object.body, {
    headers,
  });
}

async function handlePublishedProduct(request, env, pathname) {
  const prefix = "/products/latest/";
  const productPath = decodeURIComponent(pathname.slice(prefix.length));

  if (!productPath || productPath.includes("..") || productPath.startsWith("/")) {
    return jsonResponse({ ok: false, error: "Invalid product path" }, 400);
  }

  const key = `published/latest/products/${productPath}`;
  return handlePublishedObject(request, env, key, contentTypeForPath(productPath), null);
}

function contentTypeForPath(path) {
  const lower = path.toLowerCase();

  if (lower.endsWith(".html")) {
    return "text/html; charset=utf-8";
  }

  if (lower.endsWith(".csv")) {
    return "text/csv; charset=utf-8";
  }

  if (lower.endsWith(".json")) {
    return "application/json; charset=utf-8";
  }

  if (lower.endsWith(".png")) {
    return "image/png";
  }

  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
    return "image/jpeg";
  }

  if (lower.endsWith(".svg")) {
    return "image/svg+xml";
  }

  return "application/octet-stream";
}

async function handleSubmit(request, env) {
  const wantsJson = requestWantsJson(request);

  try {
    const form = await request.formData();

    if (env.TURNSTILE_SECRET_KEY) {
      const token = form.get("cf-turnstile-response");
      const valid = await verifyTurnstile(token, request, env);

      if (!valid) {
        return submissionResponse(request, wantsJson, {
          ok: false,
          title: "Submission blocked",
          messages: ["Turnstile verification failed. Please refresh and try again."],
        }, 400, env);
      }
    }

    const observerName = cleanText(form.get("observer_name"));
    const observerEmail = cleanText(form.get("observer_email"));
    const program = cleanText(form.get("program"));
    const notes = cleanText(form.get("notes"));
    const file = form.get("target_file");

    const errors = validateMetadata(observerName, observerEmail, file, env);

    if (errors.length > 0) {
      return submissionResponse(request, wantsJson, {
        ok: false,
        title: "Submission needs attention",
        messages: errors,
      }, 400, env);
    }

    const text = await file.text();
    const sheetCheck = validateTargetSheet(text);

    if (!sheetCheck.ok) {
      return submissionResponse(request, wantsJson, {
        ok: false,
        title: "Target sheet rejected",
        messages: sheetCheck.errors,
        columns: sheetCheck.columns,
        target_count_estimate: sheetCheck.targetCount,
      }, 400, env);
    }

    const now = new Date();
    const stamp = now.toISOString().replace(/[:.]/g, "-");
    const safeFileName = safeName(file.name);
    const prefix = `incoming/${now.getUTCFullYear()}/${pad2(now.getUTCMonth() + 1)}/${pad2(now.getUTCDate())}`;
    const fileKey = `${prefix}/${stamp}_${safeFileName}`;
    const metadataKey = `${prefix}/${stamp}_${safeFileName}.metadata.json`;

    const metadata = {
      submitted_at_utc: now.toISOString(),
      observer_name: observerName,
      observer_email: observerEmail,
      program,
      notes,
      original_filename: file.name,
      stored_file_key: fileKey,
      stored_metadata_key: metadataKey,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
      parsed_columns: sheetCheck.columns,
      target_count_estimate: sheetCheck.targetCount,
      required_columns: REQUIRED_COLUMNS,
    };

    await env.SUBMISSIONS.put(fileKey, text, {
      httpMetadata: {
        contentType: file.type || contentTypeForExtension(extensionOf(file.name)),
      },
      customMetadata: {
        observer_email: observerEmail,
        observer_name: observerName,
        original_filename: file.name,
      },
    });

    await env.SUBMISSIONS.put(metadataKey, JSON.stringify(metadata, null, 2), {
      httpMetadata: {
        contentType: "application/json",
      },
    });

    return submissionResponse(request, wantsJson, {
      ok: true,
      title: "Submission received",
      messages: [
        `Accepted ${sheetCheck.targetCount} target rows.`,
        `Stored file key: ${fileKey}`,
        "SkyQ will validate the sheet again before adding it to the observing queue.",
      ],
      submission: {
        submitted_at_utc: metadata.submitted_at_utc,
        observer_name: observerName,
        observer_email: observerEmail,
        program,
        original_filename: file.name,
        target_count_estimate: sheetCheck.targetCount,
        stored_file_key: fileKey,
        stored_metadata_key: metadataKey,
      },
    }, 200, env);
  } catch (error) {
    return submissionResponse(request, wantsJson, {
      ok: false,
      title: "Submission failed",
      messages: [
        error instanceof Error ? error.message : "Unknown server error.",
      ],
    }, 500, env);
  }
}

function requestWantsJson(request) {
  const accept = request.headers.get("Accept") || "";
  const requestedWith = request.headers.get("X-Requested-With") || "";

  return accept.includes("application/json") || requestedWith === "fetch";
}

function submissionResponse(request, wantsJson, payload, status, env) {
  if (wantsJson) {
    return jsonResponse(payload, status, corsHeaders(request, env));
  }

  return htmlResponse(
    renderResult(payload.title, payload.messages || [], payload.ok),
    status,
    corsHeaders(request, env),
  );
}

function validateMetadata(observerName, observerEmail, file, env) {
  const errors = [];
  const maxBytes = Number(env.MAX_UPLOAD_BYTES || 2097152);

  if (!observerName) {
    errors.push("Observer name is required.");
  }

  if (!observerEmail || !observerEmail.includes("@")) {
    errors.push("A valid observer email is required.");
  }

  if (!(file instanceof File)) {
    errors.push("A target sheet file is required.");
    return errors;
  }

  if (file.size <= 0) {
    errors.push("The uploaded file is empty.");
  }

  if (file.size > maxBytes) {
    errors.push(`The uploaded file is too large. Maximum size is ${Math.round(maxBytes / 1024 / 1024)} MB.`);
  }

  const extension = extensionOf(file.name);

  if (!ALLOWED_EXTENSIONS.has(extension)) {
    errors.push("Target sheet must be a .csv, .tsv, or whitespace-delimited .txt file.");
  }

  return errors;
}

function validateTargetSheet(text) {
  const errors = [];
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));

  if (lines.length < 2) {
    return {
      ok: false,
      errors: ["Target sheet must include a header row and at least one target row."],
      columns: [],
      targetCount: 0,
    };
  }

  const delimiter = detectDelimiter(lines[0]);
  const columns = splitRow(lines[0], delimiter).map(normalizeColumn);
  const present = new Set(columns);

  for (const required of REQUIRED_COLUMNS) {
    const aliases = COLUMN_ALIASES[required];
    const found = aliases.some((alias) => present.has(alias));

    if (!found) {
      errors.push(`Missing required column: ${required}. Accepted aliases: ${aliases.join(", ")}`);
    }
  }

  return {
    ok: errors.length === 0,
    errors,
    columns,
    targetCount: Math.max(lines.length - 1, 0),
  };
}

function detectDelimiter(header) {
  if (header.includes(",")) {
    return ",";
  }

  return "whitespace";
}

function splitRow(row, delimiter) {
  if (delimiter === "whitespace") {
    return row.split(/\s+/);
  }

  return row.split(delimiter).map((value) => value.trim());
}

function normalizeColumn(column) {
  return String(column || "").trim().toLowerCase();
}

async function verifyTurnstile(token, request, env) {
  if (!token) {
    return false;
  }

  const ip = request.headers.get("CF-Connecting-IP") || "";
  const body = new FormData();
  body.append("secret", env.TURNSTILE_SECRET_KEY);
  body.append("response", token);
  body.append("remoteip", ip);

  const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body,
  });

  if (!response.ok) {
    return false;
  }

  const result = await response.json();
  return result.success === true;
}

function sampleCsv() {
  return [
    "name,ra,dec",
    "Demo_Target_1,214.9441569,54.3874410",
    "Demo_Target_2,19:54:30.941,+00:39:50.36",
    "Demo_Target_3,246.2357145,75.9155497",
  ].join("\n") + "\n";
}

function renderDemoPlanPage() {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkyQ Demonstration - Observing Plan</title>
  <style>${demoCss()}</style>
</head>
<body>
  ${demoHeader("plan")}
  <main class="wrap">
    <section class="hero single">
      <div class="panel hero-copy">
        <h1>SkyQ Observing Plan</h1>
      </div>
    </section>

    <section class="panel">
      <div class="table-head">
        <div>
          <h2>Current Observing Plan</h2>
          <div class="data-status" id="plan-status">Loading latest HPCC table...</div>
        </div>
        <div class="table-tools">
          <div class="clock-strip" aria-label="Current time">
            <span><strong>UTC</strong> <time id="utc-clock">--:--:--</time></span>
            <span><strong>CDT</strong> <time id="cdt-clock">--:--:--</time></span>
          </div>
          <a class="button-link" href="/demo/submit">Open submission page</a>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="col-category">Category</th>
              <th class="col-target">Target</th>
              <th class="col-window">Window UTC</th>
              <th class="col-best">Best Time</th>
              <th class="col-airmass">Min Airmass</th>
              <th class="col-moon">Moon Sep</th>
              <th class="col-products">Products</th>
            </tr>
          </thead>
          <tbody id="plan-body">
            <tr>
              <td><span class="badge prime">Prime</span></td>
              <td>NPM_1G+67.0119</td>
              <td>23:43 - 11:00</td>
              <td>05:48</td>
              <td>1.19</td>
              <td>81.2 deg</td>
              <td class="links-cell">
                <a href="#">Observing products</a>
              </td>
            </tr>
            <tr>
              <td><span class="badge prime">Prime</span></td>
              <td>OQ_530</td>
              <td>23:14 - 10:23</td>
              <td>04:50</td>
              <td>1.07</td>
              <td>70.4 deg</td>
              <td class="links-cell">
                <a href="#">Observing products</a>
              </td>
            </tr>
            <tr>
              <td><span class="badge secondary">Secondary</span></td>
              <td>AT2025nqu</td>
              <td>06:06 - 08:46</td>
              <td>07:26</td>
              <td>1.82</td>
              <td>54.6 deg</td>
              <td class="links-cell">
                <a href="#">Observing products</a>
              </td>
            </tr>
            <tr>
              <td><span class="badge blocked">Non-Observable</span></td>
              <td>PKS_1608-83</td>
              <td>none</td>
              <td>none</td>
              <td>n/a</td>
              <td>73.5 deg</td>
              <td class="links-cell">
                <a href="#">Observing products</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const utcClock = document.querySelector("#utc-clock");
    const cdtClock = document.querySelector("#cdt-clock");

    function updateClocks() {
      const now = new Date();
      utcClock.textContent = new Intl.DateTimeFormat("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "UTC"
      }).format(now);
      cdtClock.textContent = new Intl.DateTimeFormat("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: "America/Chicago"
      }).format(now);
    }

    updateClocks();
    setInterval(updateClocks, 1000);

    const planBody = document.querySelector("#plan-body");
    const planStatus = document.querySelector("#plan-status");

    function parseCsv(text) {
      const rows = [];
      let row = [];
      let field = "";
      let inQuotes = false;

      for (let i = 0; i < text.length; i += 1) {
        const char = text[i];
        const next = text[i + 1];

        if (char === '"' && inQuotes && next === '"') {
          field += '"';
          i += 1;
        } else if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === "," && !inQuotes) {
          row.push(field);
          field = "";
        } else if ((char === "\\n" || char === "\\r") && !inQuotes) {
          if (char === "\\r" && next === "\\n") {
            i += 1;
          }
          row.push(field);
          if (row.some((value) => value.trim() !== "")) {
            rows.push(row);
          }
          row = [];
          field = "";
        } else {
          field += char;
        }
      }

      row.push(field);
      if (row.some((value) => value.trim() !== "")) {
        rows.push(row);
      }

      return rows;
    }

    function csvToObjects(text) {
      const rows = parseCsv(text);

      if (rows.length < 2) {
        return [];
      }

      const headers = rows[0].map((header) => header.trim());
      return rows.slice(1).map((row) => {
        const record = {};
        headers.forEach((header, index) => {
          record[header] = row[index] || "";
        });
        return record;
      });
    }

    function value(row, key, fallback) {
      const raw = row[key];
      return raw === undefined || raw === "" ? fallback : raw;
    }

    function shortTime(value) {
      if (!value) {
        return "none";
      }

      const match = String(value).match(/T(\\d{2}:\\d{2})/);
      return match ? match[1] : String(value);
    }

    function numberText(value, digits, fallback) {
      const number = Number(value);

      if (!Number.isFinite(number)) {
        return fallback;
      }

      return number.toFixed(digits);
    }

    function categoryClass(category) {
      if (category === "Prime") {
        return "prime";
      }

      if (category === "Secondary") {
        return "secondary";
      }

      return "blocked";
    }

    function productLinks(row) {
      const href = value(row, "product_page_html", "");

      if (!href) {
        return '<span class="muted">none</span>';
      }

      return '<a href="' + escapeAttribute(href) + '">Observing products</a>';
    }

    function escapeHtmlText(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function escapeAttribute(text) {
      return escapeHtmlText(text).replaceAll("'", "&#39;");
    }

    function renderPlan(rows) {
      planBody.innerHTML = rows.map((row) => {
        const category = value(row, "skyq_category", "Non-Observable");
        const windowStart = shortTime(value(row, "window_start", ""));
        const windowEnd = shortTime(value(row, "window_end", ""));
        const windowText = windowStart === "none" || windowEnd === "none" ? "none" : windowStart + " - " + windowEnd;
        const moonSep = value(row, "min_moon_sep_moon_up", "") || value(row, "min_moon_sep", "");

        return '<tr>'
          + '<td><span class="badge ' + categoryClass(category) + '">' + escapeHtmlText(category) + '</span></td>'
          + '<td>' + escapeHtmlText(value(row, "name", "")) + '</td>'
          + '<td>' + escapeHtmlText(windowText) + '</td>'
          + '<td>' + escapeHtmlText(shortTime(value(row, "best_time", ""))) + '</td>'
          + '<td>' + escapeHtmlText(numberText(value(row, "min_airmass", ""), 2, "n/a")) + '</td>'
          + '<td>' + escapeHtmlText(numberText(moonSep, 1, "n/a")) + ' deg</td>'
          + '<td class="links-cell">' + productLinks(row) + '</td>'
          + '</tr>';
      }).join("");
    }

    async function loadPublishedPlan() {
      try {
        const response = await fetch("/observing-plan.csv?cache=" + Date.now());

        if (!response.ok) {
          throw new Error("No published HPCC table found");
        }

        const text = await response.text();
        const rows = csvToObjects(text);

        if (rows.length === 0) {
          throw new Error("Published HPCC table is empty");
        }

        renderPlan(rows);
        planStatus.textContent = "Loaded " + rows.length + " targets from HPCC published CSV";
      } catch (error) {
        planStatus.textContent = "Using local sample rows until the HPCC run publishes a table";
      }
    }

    loadPublishedPlan();
  </script>
</body>
</html>`;
}

function renderDemoSubmissionPage() {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkyQ Demonstration - Submission</title>
  <style>${demoCss()}</style>
</head>
<body>
  ${demoHeader("submit")}
  <main class="wrap">
    <section class="hero">
      <div class="panel hero-copy">
        <h1>Submit a target sheet to SkyQ.</h1>
        <p>This page demonstrates the observer submission side of the website. The form posts to the Cloudflare Worker, validates the sheet, and stores accepted submissions in R2 for the cluster pipeline.</p>
        <div class="pill-row">
          <span class="pill">Required columns: name, ra, dec</span>
          <span class="pill">CSV, TSV, TXT</span>
          <span class="pill">R2-backed storage</span>
          <span class="pill">JSON response available</span>
        </div>
      </div>
      <div class="panel">
        <h2>Pipeline Flow</h2>
        <div class="flow">
          <div class="flow-step"><div class="num">1</div><div><strong>Observer uploads a sheet</strong><span>The website posts a file to the SkyQ Worker.</span></div></div>
          <div class="flow-step"><div class="num">2</div><div><strong>Worker validates and stores</strong><span>Required columns are checked, then the sheet and metadata are written to R2.</span></div></div>
          <div class="flow-step"><div class="num">3</div><div><strong>Cluster syncs submissions</strong><span>SkyQ pulls new R2 objects into the local inbox.</span></div></div>
          <div class="flow-step"><div class="num">4</div><div><strong>Observing plan is generated</strong><span>Altitude, airmass, Moon, seasonal checks, plots, and operator reports are produced.</span></div></div>
        </div>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Live Submission Demo</h2>
        <p>Use a small test file for the presentation. A successful upload will create a real R2 object, so use demo labels if you do not want it treated like a production submission.</p>
        <form id="skyq-demo-form">
          <label>
            Observer name
            <input name="observer_name" value="SkyQ Demo" required autocomplete="name">
          </label>
          <label>
            Observer email
            <input name="observer_email" type="email" value="demo@example.edu" required autocomplete="email">
          </label>
          <label>
            Program or class
            <input name="program" value="SkyQ demonstration">
          </label>
          <label>
            Target sheet
            <input name="target_file" type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" required>
          </label>
          <label>
            Notes
            <textarea name="notes" rows="4">Temporary demo submission</textarea>
          </label>
          <div class="actions">
            <button type="submit">Submit to SkyQ</button>
            <a class="button-link secondary" href="/sample.csv">Download sample CSV</a>
          </div>
        </form>
      </div>

      <div class="panel result" id="result-panel">
        <h2>Worker Response</h2>
        <div class="status">Waiting for a submission</div>
        <p>The response from <code>POST /submit</code> will appear here as structured JSON.</p>
        <pre id="result-json">No submission yet.</pre>
      </div>
    </section>
  </main>
  <script>
    const form = document.querySelector("#skyq-demo-form");
    const panel = document.querySelector("#result-panel");
    const status = panel.querySelector(".status");
    const output = document.querySelector("#result-json");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      panel.classList.remove("ok", "error");
      status.textContent = "Submitting...";
      output.textContent = "Waiting for Worker response...";

      try {
        const response = await fetch("/submit", {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "X-Requested-With": "fetch"
          },
          body: new FormData(form)
        });
        const data = await response.json();
        panel.classList.add(data.ok ? "ok" : "error");
        status.textContent = data.title || (data.ok ? "Accepted" : "Rejected");
        output.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        panel.classList.add("error");
        status.textContent = "Request failed";
        output.textContent = String(error);
      }
    });
  </script>
</body>
</html>`;
}

function demoHeader(active) {
  const planClass = active === "plan" ? "active" : "";
  const submitClass = active === "submit" ? "active" : "";

  return `<header>
    <div class="wrap topbar">
      <div class="brand">
        <strong>SkyQ</strong>
      </div>
      <nav class="demo-nav" aria-label="Demo pages">
        <a class="${planClass}" href="/demo/plan">Observing plan</a>
        <a class="${submitClass}" href="/demo/submit">Submit targets</a>
      </nav>
    </div>
  </header>`;
}

function demoCss() {
  return `
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #121820;
      --panel-soft: #17202b;
      --field: #0e141b;
      --text: #eef2f6;
      --muted: #a9b4c0;
      --accent: #8ab4f8;
      --accent-strong: #b8d3ff;
      --green: #9bd5b5;
      --yellow: #eadf8f;
      --red: #e08b7f;
      --border: #2b3643;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    header {
      border-bottom: 1px solid var(--border);
      background: #0d1218;
    }
    .wrap {
      width: min(1440px, calc(100% - 24px));
      margin: 0 auto;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 18px 0;
    }
    .brand {
      display: grid;
      gap: 4px;
    }
    .brand strong {
      font-size: 22px;
      letter-spacing: 0;
    }
    .brand span,
    .nav-note {
      color: var(--muted);
      font-size: 14px;
    }
    .demo-nav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .demo-nav a {
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--muted);
      padding: 8px 10px;
      text-decoration: none;
      font-size: 14px;
    }
    .demo-nav a.active,
    .demo-nav a:hover {
      border-color: var(--accent);
      color: var(--text);
      background: var(--panel-soft);
    }
    main {
      padding: 34px 0 46px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(320px, 0.95fr);
      gap: 22px;
      align-items: stretch;
      margin-bottom: 22px;
    }
    .hero.single {
      grid-template-columns: 1fr;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 22px;
    }
    .hero-copy {
      border-left: 4px solid var(--accent);
    }
    h1 {
      margin: 0 0 12px;
      font-size: clamp(34px, 6vw, 58px);
      line-height: 1.02;
      letter-spacing: 0;
    }
    h2 {
      margin: 0 0 12px;
      color: var(--accent-strong);
      font-size: 22px;
    }
    p {
      color: var(--muted);
      line-height: 1.5;
      margin: 0 0 14px;
    }
    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }
    .pill {
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--text);
      background: var(--panel-soft);
      padding: 7px 10px;
      font-size: 14px;
    }
    .flow {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .flow-step {
      display: grid;
      grid-template-columns: 30px 1fr;
      gap: 10px;
      align-items: start;
      border: 1px solid var(--border);
      border-radius: 5px;
      background: var(--field);
      padding: 10px;
    }
    .num {
      display: grid;
      place-items: center;
      width: 30px;
      height: 30px;
      border-radius: 50%;
      background: var(--accent);
      color: #07101a;
      font-weight: 700;
    }
    .flow-step strong {
      display: block;
      margin-bottom: 3px;
    }
    .flow-step span {
      color: var(--muted);
      font-size: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 0.86fr);
      gap: 22px;
    }
    form {
      display: grid;
      gap: 14px;
    }
    label {
      display: grid;
      gap: 7px;
      color: var(--text);
      font-size: 15px;
      font-weight: 700;
    }
    input,
    textarea {
      width: 100%;
      border: 1px solid #31415f;
      border-radius: 4px;
      background: var(--field);
      color: var(--text);
      font: 15px Arial, Helvetica, sans-serif;
      padding: 10px 11px;
    }
    input:focus,
    textarea:focus {
      outline: 2px solid var(--accent);
      border-color: var(--accent);
    }
    button,
    .button-link {
      width: fit-content;
      border: 1px solid var(--accent);
      border-radius: 4px;
      background: var(--accent);
      color: #07101a;
      cursor: pointer;
      font: 700 15px Arial, Helvetica, sans-serif;
      padding: 10px 14px;
      text-decoration: none;
    }
    button.secondary,
    .button-link.secondary {
      color: var(--text);
      background: transparent;
    }
    button:hover,
    .button-link:hover {
      background: var(--accent-strong);
      border-color: var(--accent-strong);
      color: #07101a;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .table-head {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: center;
      margin-bottom: 14px;
    }
    .table-tools {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 12px;
      flex-wrap: wrap;
    }
    .data-status {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .clock-strip {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .clock-strip span {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--field);
      color: var(--text);
      padding: 7px 9px;
      font-size: 13px;
      white-space: nowrap;
    }
    .clock-strip strong {
      color: var(--accent-strong);
      font-size: 12px;
    }
    .table-wrap {
      overflow-x: visible;
      border: 1px solid var(--border);
      border-radius: 6px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      background: var(--field);
    }
    th,
    td {
      border-bottom: 1px solid var(--border);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--accent-strong);
      background: var(--panel-soft);
      font-weight: 700;
    }
    .col-category {
      width: 13%;
    }
    .col-target {
      width: 20%;
    }
    .col-window {
      width: 15%;
    }
    .col-best,
    .col-airmass,
    .col-moon {
      width: 10%;
    }
    .col-products {
      width: 22%;
    }
    tr:last-child td {
      border-bottom: 0;
    }
    .badge {
      display: inline-flex;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 3px 7px;
      font-size: 12px;
      white-space: nowrap;
    }
    .badge.prime {
      color: var(--green);
      border-color: rgba(155, 213, 181, 0.55);
    }
    .badge.secondary {
      color: var(--yellow);
      border-color: rgba(234, 223, 143, 0.55);
    }
    .badge.blocked {
      color: var(--red);
      border-color: rgba(224, 139, 127, 0.6);
    }
    .links-cell {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .links-cell a {
      color: var(--accent-strong);
      text-decoration: none;
      border-bottom: 1px solid rgba(184, 211, 255, 0.45);
      font-size: 12px;
      white-space: nowrap;
    }
    .links-cell a:hover {
      color: var(--text);
      border-bottom-color: var(--text);
    }
    .muted {
      color: var(--muted);
    }
    pre,
    code {
      font-family: Consolas, "Liberation Mono", monospace;
    }
    pre {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 5px;
      background: var(--field);
      color: var(--text);
      font-size: 14px;
      line-height: 1.45;
      padding: 12px;
      margin: 12px 0 0;
    }
    .result {
      min-height: 170px;
    }
    .result .status {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border-radius: 999px;
      padding: 6px 9px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 12px;
    }
    .result.ok .status {
      color: var(--green);
      border-color: rgba(155, 213, 181, 0.55);
    }
    .result.error .status {
      color: var(--red);
      border-color: rgba(224, 139, 127, 0.6);
    }
    .facts {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }
    .fact {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
    }
    .fact strong {
      display: block;
      color: var(--accent-strong);
      font-size: 20px;
      margin-bottom: 5px;
    }
    .fact span {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    @media (max-width: 860px) {
      .hero,
      .grid,
      .facts {
        grid-template-columns: 1fr;
      }
      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }
    }
  `;
}

function renderForm(env) {
  const turnstile = env.TURNSTILE_SITE_KEY
    ? `<div class="cf-turnstile" data-sitekey="${escapeHtml(env.TURNSTILE_SITE_KEY)}"></div>
       <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>`
    : "";

  return pageShell(`
    <section class="hero">
      <h1>SkyQ Target Submission</h1>
      <p>Upload an observer target sheet for automatic validation and queue processing.</p>
    </section>
    <form method="post" action="/submit" enctype="multipart/form-data">
      <label>
        Observer name
        <input name="observer_name" required autocomplete="name">
      </label>
      <label>
        Observer email
        <input name="observer_email" type="email" required autocomplete="email">
      </label>
      <label>
        Program or class
        <input name="program" placeholder="e.g. PHYS 4301, AGN monitoring, transient follow-up">
      </label>
      <label>
        Target sheet
        <input name="target_file" type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" required>
      </label>
      <label>
        Notes
        <textarea name="notes" rows="4" placeholder="Optional context for the observatory operator"></textarea>
      </label>
      ${turnstile}
      <button type="submit">Submit Targets</button>
    </form>
    <section class="schema">
      <h2>Required Sheet Columns</h2>
      <p>Observer sheets only need target identity and coordinates:</p>
      <pre>name,ra,dec</pre>
      <p>Accepted aliases include target/object/source, RAJ2000/ra_deg, and DEJ2000/dec_deg.</p>
    </section>
  `);
}

function renderResult(title, messages, ok) {
  const items = messages.map((message) => `<li>${escapeHtml(message)}</li>`).join("");
  const className = ok ? "result ok" : "result error";

  return pageShell(`
    <section class="${className}">
      <h1>${escapeHtml(title)}</h1>
      <ul>${items}</ul>
      <a class="button-link" href="/">Submit another sheet</a>
    </section>
  `);
}

function renderNotFound() {
  return pageShell(`
    <section class="result error">
      <h1>Not found</h1>
      <p>The requested SkyQ submission route does not exist.</p>
      <a class="button-link" href="/">Return to submission form</a>
    </section>
  `);
}

function pageShell(content) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkyQ Target Submission</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #121820;
      --panel-soft: #171f2a;
      --text: #eef2f6;
      --muted: #a9b4c0;
      --accent: #8ab4f8;
      --accent-strong: #b8d3ff;
      --danger: #e06c5f;
      --border: #2b3643;
      --field: #0e141b;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    main {
      width: min(920px, calc(100% - 32px));
      margin: 0 auto;
      padding: 36px 0;
    }
    .hero,
    form,
    .schema,
    .result {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 22px;
    }
    .hero {
      margin-bottom: 14px;
      border-left: 4px solid var(--accent);
    }
    h1 {
      color: var(--text);
      font-size: clamp(28px, 5vw, 42px);
      line-height: 1.1;
      margin: 0 0 8px;
      letter-spacing: 0;
    }
    h2 {
      color: var(--accent-strong);
      font-size: 20px;
      margin-top: 0;
    }
    p {
      color: var(--muted);
      font-size: 16px;
      line-height: 1.45;
    }
    form {
      display: grid;
      gap: 15px;
    }
    label {
      display: grid;
      gap: 7px;
      color: var(--text);
      font-size: 15px;
      font-weight: 700;
    }
    input,
    textarea {
      width: 100%;
      border: 1px solid #31415f;
      border-radius: 4px;
      background: var(--field);
      color: var(--text);
      font: 15px Arial, Helvetica, sans-serif;
      padding: 10px 11px;
    }
    input:focus,
    textarea:focus {
      outline: 2px solid var(--accent);
      border-color: var(--accent);
    }
    button,
    .button-link {
      width: fit-content;
      border: 1px solid var(--accent);
      border-radius: 4px;
      background: var(--accent);
      color: #07101a;
      cursor: pointer;
      font: 700 15px Arial, Helvetica, sans-serif;
      padding: 10px 14px;
      text-decoration: none;
    }
    button:hover,
    .button-link:hover {
      background: var(--accent-strong);
      border-color: var(--accent-strong);
    }
    .schema {
      margin-top: 18px;
    }
    pre {
      overflow: auto;
      border: 1px solid #31415f;
      border-radius: 4px;
      background: var(--field);
      color: var(--text);
      font-size: 15px;
      padding: 12px;
    }
    .result ul {
      color: var(--muted);
      font-size: 18px;
      line-height: 1.5;
      padding-left: 22px;
    }
    .result.ok {
      border-color: var(--accent);
    }
    .result.error {
      border-color: var(--danger);
    }
  </style>
</head>
<body>
  <main>${content}</main>
</body>
</html>`;
}

function htmlResponse(html, status = 200, extraHeaders = {}) {
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

function csvResponse(csv, status = 200) {
  return new Response(csv, {
    status,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": "attachment; filename=\"skyq_sample_targets.csv\"",
      "Cache-Control": "no-store",
    },
  });
}

function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  const allowed = allowedOrigins(env);

  if (!origin || allowed.length === 0) {
    return {};
  }

  if (!allowed.includes(origin)) {
    return {};
  }

  return {
    "Access-Control-Allow-Origin": origin,
    "Vary": "Origin",
  };
}

function corsPreflightResponse(request, env) {
  const headers = corsHeaders(request, env);

  if (!headers["Access-Control-Allow-Origin"]) {
    return new Response(null, { status: 403 });
  }

  return new Response(null, {
    status: 204,
    headers: {
      ...headers,
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Accept, X-Requested-With",
      "Access-Control-Max-Age": "86400",
    },
  });
}

function cleanText(value) {
  return String(value || "").trim().slice(0, 1000);
}

function safeName(name) {
  const cleaned = String(name || "targets.txt")
    .trim()
    .replace(/[^A-Za-z0-9_.-]+/g, "_")
    .replace(/^_+|_+$/g, "");

  return cleaned || "targets.txt";
}

function extensionOf(name) {
  const parts = String(name || "").split(".");
  return parts.length > 1 ? parts.pop().toLowerCase() : "";
}

function contentTypeForExtension(extension) {
  if (extension === "csv") {
    return "text/csv";
  }

  if (extension === "tsv") {
    return "text/tab-separated-values";
  }

  return "text/plain";
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
