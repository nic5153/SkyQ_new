const ALLOWED_EXTENSIONS = new Set(["csv", "txt", "tsv"]);
const REQUIRED_COLUMNS = ["name", "ra", "dec"];
const COLUMN_ALIASES = {
  name: ["name", "target", "object", "source", "target_name"],
  ra: ["ra", "raj2000", "ra_deg"],
  dec: ["dec", "dej2000", "dec_deg"],
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return htmlResponse(renderForm(env));
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

async function handleSubmit(request, env) {
  try {
    const form = await request.formData();

    if (env.TURNSTILE_SECRET_KEY) {
      const token = form.get("cf-turnstile-response");
      const valid = await verifyTurnstile(token, request, env);

      if (!valid) {
        return htmlResponse(renderResult("Submission blocked", [
          "Turnstile verification failed. Please refresh and try again.",
        ], false), 400);
      }
    }

    const observerName = cleanText(form.get("observer_name"));
    const observerEmail = cleanText(form.get("observer_email"));
    const program = cleanText(form.get("program"));
    const notes = cleanText(form.get("notes"));
    const file = form.get("target_file");

    const errors = validateMetadata(observerName, observerEmail, file, env);

    if (errors.length > 0) {
      return htmlResponse(renderResult("Submission needs attention", errors, false), 400);
    }

    const text = await file.text();
    const sheetCheck = validateTargetSheet(text);

    if (!sheetCheck.ok) {
      return htmlResponse(renderResult("Target sheet rejected", sheetCheck.errors, false), 400);
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

    return htmlResponse(renderResult("Submission received", [
      `Accepted ${sheetCheck.targetCount} target rows.`,
      `Stored file key: ${fileKey}`,
      "SkyQ will validate the sheet again before adding it to the observing queue.",
    ], true));
  } catch (error) {
    return htmlResponse(renderResult("Submission failed", [
      error instanceof Error ? error.message : "Unknown server error.",
    ], false), 500);
  }
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

function htmlResponse(html, status = 200) {
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
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
