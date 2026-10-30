"use strict";
// One thin client for three roles. It holds no clinical logic: every rule lives behind the API.
const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
let session = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

const key = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());

async function api(path, { method = "GET", body, form, idem = false } = {}) {
  const headers = {};
  if (session) headers.Authorization = `Bearer ${session.token}`;
  if (idem) headers["Idempotency-Key"] = key();
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) });
  const type = res.headers.get("content-type") || "";
  let data = null;
  if (type.includes("event-stream")) {
    const line = (await res.text()).split("\n").find((l) => l.startsWith("data: ") && l !== "data: {}");
    data = line ? JSON.parse(line.slice(6)) : null;
  } else if (type.includes("json")) {
    data = await res.json();
  }
  if (!res.ok && !(data && data.status)) {
    const d = data && data.detail;
    const text = typeof d === "string" ? d : d && d.message ? `${d.message}: ${(d.gaps || []).join("; ")}` : `Request failed (${res.status})`;
    throw Object.assign(new Error(text), { status: res.status });
  }
  return data;
}

function guarded(button, work, errorBox) {
  return async (event) => {
    if (event) event.preventDefault();
    button.disabled = true;
    if (errorBox) errorBox.textContent = "";
    try { await work(); }
    catch (e) { if (errorBox) errorBox.textContent = e.message; else alert(e.message); }
    finally { button.disabled = false; }
  };
}

const when = (iso) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const blockTime = (a, b) => `${when(a)} to ${new Date(b).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- sign in --------------------------------------------------------------------------------

function renderSignIn() {
  session = null;
  $("#who").hidden = true;
  const role = el("select", { id: "role" },
    el("option", { value: "patient" }, "Patient"),
    el("option", { value: "caregiver" }, "Family caregiver"),
    el("option", { value: "doctor" }, "Doctor"),
    el("option", { value: "desk" }, "Front desk"));
  const id = el("input", { id: "actor", value: "P0011", autocomplete: "off" });
  const hint = el("p", { class: "muted small" });
  const hints = { patient: ["P0011", "Any seeded patient, P0001 to P1000."],
    caregiver: ["CG0011", "CG0011 has consent for P0011. CG0041 has expired consent for P0041."],
    doctor: ["D0001", "Any seeded doctor, D0001 to D0500."], desk: ["DESK01", "Any desk id."] };
  const sync = () => { const [v, h] = hints[role.value]; id.value = v; hint.textContent = h; };
  role.addEventListener("change", sync); sync();
  const err = el("p", { class: "error", role: "alert" });
  const go = el("button", { class: "primary", type: "submit" }, "Continue");
  const form = el("form", { class: "card" },
    el("h2", {}, "Choose who to sign in as"),
    el("p", { class: "muted small" }, "A development sign-in, standing in for the hospital's login."),
    el("label", { for: "role" }, "Role"), role,
    el("label", { for: "actor" }, "ID"), id, hint,
    el("div", { class: "row" }, go), err);
  form.addEventListener("submit", guarded(go, async () => {
    const r = await api("/dev/login", { method: "POST", body: { role: role.value, actor_id: id.value.trim() } });
    session = { token: r.token, role: role.value, id: id.value.trim() };
    $("#who-text").textContent = `${role.options[role.selectedIndex].text} · ${session.id}`;
    $("#who").hidden = false;
    ({ patient: renderPatient, caregiver: renderCaregiver, doctor: renderDoctor, desk: renderDesk })[role.value]();
  }, err));
  app.replaceChildren(el("h1", {}, "Welcome"), form);
}
$("#sign-out").addEventListener("click", renderSignIn);

function tabs(items) {
  const bar = el("div", { class: "tabs", role: "tablist" });
  const pane = el("div", {});
  const show = (i) => {
    [...bar.children].forEach((b, n) => b.setAttribute("aria-selected", String(n === i)));
    pane.replaceChildren();
    items[i][1](pane);
  };
  items.forEach(([label], i) => bar.append(el("button", { role: "tab", type: "button", onclick: () => show(i) }, label)));
  app.replaceChildren(bar, pane);
  show(0);
}

// ---- patient --------------------------------------------------------------------------------

const renderPatient = () => tabs([["Find a doctor", findDoctor], ["My reports", reports], ["My appointments", appointments]]);

function findDoctor(pane) {
  const text = el("textarea", { id: "symptoms", placeholder: "For example: pet mein dard hai, 3 din se, thoda bukhar bhi" });
  const err = el("p", { class: "error", role: "alert" });
  const go = el("button", { class: "primary", type: "submit" }, "Continue");
  const out = el("div", { "aria-live": "polite" });
  const form = el("form", { class: "card" },
    el("h2", {}, "What's wrong?"),
    el("label", { for: "symptoms" }, "Describe it in your own words, in English, Hindi or Hinglish"),
    text, el("div", { class: "row" }, go), err);
  form.addEventListener("submit", guarded(go, async () => {
    if (!text.value.trim()) throw new Error("Please describe what's wrong first.");
    out.replaceChildren(el("p", { class: "spin" }, "Checking…"));
    triageReply(out, await api("/w1/triage", { method: "POST", idem: true, body: { text: text.value } }));
  }, err));
  pane.append(form, out);
}

function triageReply(out, r) {
  const resume = (body) => api(`/w1/${r.thread_id}/resume`, { method: "POST", idem: true, body });
  if (r.status === "emergency") {
    out.replaceChildren(el("div", { class: "alert emergency", role: "alert" }, r.message));
  } else if (r.status === "handed_to_desk") {
    out.replaceChildren(el("div", { class: "alert warn", role: "alert" }, r.message));
  } else if (r.status === "clarify") {
    const answer = el("input", { id: "answer" });
    const err = el("p", { class: "error", role: "alert" });
    const send = el("button", { class: "primary", type: "submit" }, "Send");
    const form = el("form", { class: "card" }, el("label", { for: "answer" }, r.question), answer, el("div", { class: "row" }, send), err);
    form.addEventListener("submit", guarded(send, async () => {
      if (!answer.value.trim()) throw new Error("Please type an answer.");
      triageReply(out, await resume({ answer: answer.value }));
    }, err));
    out.replaceChildren(form);
    answer.focus();
  } else if (r.status === "awaiting_choice") {
    const err = el("p", { class: "error", role: "alert" });
    const list = r.candidates.map((c) => {
      const b = el("button", { class: "choice", type: "button" },
        el("strong", {}, c.doctor_name), el("br"),
        el("span", {}, `${c.clinic}, ${c.city}`), el("br"),
        el("span", { class: "muted small" }, `${blockTime(c.block_start, c.block_end)} · ${c.places_left} places left`));
      b.addEventListener("click", guarded(b, async () => triageReply(out, await resume({ slot_id: c.slot_id })), err));
      return b;
    });
    out.replaceChildren(el("div", { class: "card" },
      r.notice ? el("div", { class: "alert warn" }, r.notice) : null,
      el("h2", {}, `Suggested: ${r.specialty.name}`),
      el("p", { class: "muted small" }, "Choose a time block. You get a token number, not an exact minute."), list, err));
  } else if (r.status === "booked") {
    out.replaceChildren(el("div", { class: "alert ok", role: "status" },
      el("strong", {}, `Token ${r.token_no}`), el("p", {}, r.message),
      r.sms_sent ? el("p", { class: "small" }, "A confirmation SMS has been queued (a stub in this demo).") : null));
  }
}

async function appointments(pane) {
  pane.append(el("p", { class: "spin" }, "Loading…"));
  const rows = await api("/w1/appointments");
  pane.replaceChildren(el("div", { class: "card" }, el("h2", {}, "My appointments"),
    rows.length ? rows.map((a) => el("div", { class: "ticket" },
      el("strong", {}, `Token ${a.token_no} · ${a.doctor_name}`), " ",
      el("span", { class: "pill" }, a.status), el("br"),
      el("span", { class: "muted small" }, `${a.clinic} · ${blockTime(a.block_start, a.block_end)}`)))
      : el("p", { class: "muted" }, "Nothing booked yet.")));
}

function reports(pane) { uploadCard(pane); askCard(pane, session.id); }

function uploadCard(pane) {
  const file = el("input", { type: "file", id: "pdf", accept: "application/pdf" });
  const err = el("p", { class: "error", role: "alert" });
  const go = el("button", { class: "primary", type: "submit" }, "Upload");
  const list = el("div", { "aria-live": "polite" });
  const refresh = async () => {
    const docs = await api("/w2/documents");
    list.replaceChildren(...(docs.length ? docs.map((d) => el("div", { class: "ticket" },
      el("span", { class: `pill ${d.status}` }, d.status), " ",
      el("span", {}, `Report from ${when(d.uploaded_at)}`), el("br"),
      el("span", { class: "muted small" }, d.pages_total == null ? "Waiting to be read" :
        `${d.pages_total} pages, ${d.pages_ocr} read from scans, ${d.chunks_indexed ?? 0} parts searchable` +
        (d.chunks_quarantined ? `, ${d.chunks_quarantined} set aside` : "")),
      d.reason ? el("p", { class: "small" }, d.reason) : null))
      : [el("p", { class: "muted small" }, "No reports uploaded yet.")]));
    return docs;
  };
  const form = el("form", { class: "card" }, el("h2", {}, "Upload a report"),
    el("label", { for: "pdf" }, "PDF, up to 20 MB and 50 pages. Scans are fine."), file,
    el("div", { class: "row" }, go), err, el("h3", {}, "Your reports"), list);
  form.addEventListener("submit", guarded(go, async () => {
    if (!file.files[0]) throw new Error("Please choose a PDF first.");
    const data = new FormData(); data.append("file", file.files[0]);
    await api("/w2/documents", { method: "POST", form: data, idem: true });
    file.value = "";
    for (let i = 0; i < 60; i++) {
      const docs = await refresh();
      if (!docs.some((d) => d.status === "queued" || d.status === "parsed")) break;
      await sleep(1500);
    }
  }, err));
  pane.append(form);
  refresh().catch((e) => { err.textContent = e.message; });
}

function askCard(pane, patientId) {
  const q = el("input", { id: "question", placeholder: "What was my HbA1c?" });
  const err = el("p", { class: "error", role: "alert" });
  const go = el("button", { class: "primary", type: "submit" }, "Ask");
  const out = el("div", { "aria-live": "polite" });
  const form = el("form", { class: "card" }, el("h2", {}, "Ask about the reports"),
    el("p", { class: "muted small" }, "It reads reports back and names the page. It doesn't diagnose or suggest medicines."),
    el("label", { for: "question" }, "Your question"), q, el("div", { class: "row" }, go), err, out);
  form.addEventListener("submit", guarded(go, async () => {
    if (!q.value.trim()) throw new Error("Please type a question.");
    out.replaceChildren(el("p", { class: "spin" }, "Reading…"));
    answerView(out, await api("/w2/ask", { method: "POST", body: { question: q.value, patient_id: patientId } }));
  }, err));
  pane.append(form);
}

function answerView(out, r) {
  const style = { emergency: "emergency", handed_to_desk: "warn", blocked: "warn", refused: "warn", not_found: "info" }[r.status];
  if (style) { out.replaceChildren(el("div", { class: `alert ${style}`, role: "alert" }, r.answer)); return; }
  const lines = (r.sentences || []).map((s) => el("p", {}, s.text, " ",
    ...s.citations.map((c) => el("span", { class: "cite" }, `(report ${c.doc_id.slice(0, 8)}, page ${c.page}${c.source === "ocr" ? ", scan" : ""}) `))));
  out.replaceChildren(el("div", { class: "alert info" }, lines),
    r.scan_warning ? el("div", { class: "alert warn" }, r.scan_warning) : null);
}

// ---- caregiver ------------------------------------------------------------------------------

function renderCaregiver() {
  const pid = el("input", { id: "patient", value: session.id === "CG0011" ? "P0011" : "" });
  const pane = el("div", {});
  const go = el("button", { class: "primary", type: "submit" }, "Open records");
  const form = el("form", { class: "card" }, el("h2", {}, "Whose records?"),
    el("label", { for: "patient" }, "Patient ID"), pid,
    el("p", { class: "muted small" }, "You can read them only while the patient's consent is valid. Each read is logged."),
    el("div", { class: "row" }, go));
  form.addEventListener("submit", (e) => { e.preventDefault(); pane.replaceChildren(); askCard(pane, pid.value.trim()); });
  app.replaceChildren(el("h1", {}, "Family access"), form, pane);
}

// ---- doctor ---------------------------------------------------------------------------------

async function renderDoctor() {
  app.replaceChildren(el("h1", {}, "Today's patients"), el("p", { class: "spin" }, "Loading…"));
  const rows = await api("/w3/appointments");
  const err = el("p", { class: "error", role: "alert" });
  const list = rows.map((a) => {
    const b = el("button", { class: "choice", type: "button" },
      el("strong", {}, `${a.patient_name} · token ${a.token_no}`), el("br"),
      el("span", { class: "muted small" }, `${blockTime(a.block_start, a.block_end)} · ${a.status}`));
    b.addEventListener("click", guarded(b, async () => {
      const { encounter_id } = await api("/w3/encounters", { method: "POST", body: { appt_id: a.appt_id } });
      renderDictate(encounter_id, a);
    }, err));
    return b;
  });
  app.replaceChildren(el("h1", {}, "Your patients"),
    el("div", { class: "card" }, rows.length ? list : el("p", { class: "muted" }, "No booked patients. Book one as a patient first."), err));
}

function renderDictate(encounterId, appt) {
  const text = el("textarea", { id: "dictation", placeholder: "Doctor: Knee pain for six months. Probably early osteoarthritis. Start a low dose statin." });
  const err = el("p", { class: "error", role: "alert" });
  const send = el("button", { class: "primary", type: "submit" }, "Make draft");
  const record = el("button", { class: "secondary", type: "button" }, "Record");
  const audio = el("input", { type: "file", id: "audio", accept: "audio/*" });
  const status = el("p", { class: "spin", "aria-live": "polite" });
  const watch = async (thread) => {
    status.textContent = "Listening and drafting…";
    for (let i = 0; i < 240; i++) {
      const d = await api(`/w3/${thread}/draft`);
      if (d.status === "review") return renderReview(thread, d, appt);
      if (d.status === "failed") throw new Error(d.reason || "The draft failed.");
      await sleep(1000);
    }
    throw new Error("The draft is taking too long. Is the worker running?");
  };
  const sendAudio = async (blob, name) => {
    const data = new FormData(); data.append("file", blob, name);
    const { thread_id } = await api(`/w3/encounters/${encounterId}/audio`, { method: "POST", form: data });
    await watch(thread_id);
  };
  let recorder = null;
  record.addEventListener("click", async () => {
    if (recorder) { recorder.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        recorder = null; record.textContent = "Record";
        sendAudio(new Blob(chunks, { type: "audio/webm" }), "dictation.webm").catch((e) => { err.textContent = e.message; status.textContent = ""; });
      };
      recorder.start(); record.textContent = "Stop and make draft";
    } catch { err.textContent = "The microphone isn't available. Type the dictation or upload a recording."; }
  });
  const form = el("form", { class: "card" }, el("h2", {}, `Dictate: ${appt.patient_name}`),
    el("label", { for: "dictation" }, "Type the dictation. Mark speakers with “Doctor:” and “Patient:” if both speak."), text,
    el("div", { class: "row" }, send, record),
    el("label", { for: "audio" }, "Or upload a recording"), audio, status, err,
    el("p", { class: "muted small" }, "Audio stays inside the hospital and is deleted within 24 hours. Nothing is saved to the record until you sign."));
  form.addEventListener("submit", guarded(send, async () => {
    if (audio.files[0]) return sendAudio(audio.files[0], audio.files[0].name);
    if (!text.value.trim()) throw new Error("Type the dictation or choose a recording first.");
    const { thread_id } = await api(`/w3/encounters/${encounterId}/transcript`, { method: "POST", body: { transcript: text.value } });
    await watch(thread_id);
  }, err));
  app.replaceChildren(el("h1", {}, "Consultation"), form);
}

const STOCK = { in_stock: "In stock", low: "Low", out: "Out of stock", unknown: "Stock unknown" };

function renderReview(thread, d, appt) {
  const sections = { subjective: "Subjective", objective: "Objective", assessment: "Assessment", plan: "Plan" };
  const soap = JSON.parse(JSON.stringify(d.soap));
  const soapCard = el("div", { class: "card" }, el("h2", {}, "Draft note"),
    Object.entries(sections).map(([k, label]) => el("div", {}, el("h3", {}, label),
      soap[k].length ? soap[k].map((line) => {
        const box = el("textarea", { "aria-label": label, rows: 2 });
        box.value = line.text;
        box.addEventListener("input", () => { line.text = box.value; });
        return el("div", {}, box, el("p", { class: "quote" }, `“${line.quote}”`));
      }) : el("p", { class: "muted small" }, "Nothing stated."))));
  const meds = d.medicines.map((m) => ({ name: m.name, dose: m.dose || "", stock: m.stock }));
  const gaps = d.gaps.map((g) => ({ ...g, name: "", dose: "", drop: false }));
  const medRow = (m) => {
    const name = el("input", { value: m.name, "aria-label": "Medicine" });
    const dose = el("input", { value: m.dose, "aria-label": "Dose", placeholder: "Dose" });
    name.addEventListener("input", () => { m.name = name.value; });
    dose.addEventListener("input", () => { m.dose = dose.value; });
    const s = m.stock;
    return el("div", { class: "med" }, name, dose, el("span", {},
      el("span", { class: `pill ${s.status}` }, STOCK[s.status]),
      el("span", { class: "muted small" }, s.age_days == null ? "" : ` ${s.qty} left, ${s.age_days}d old${s.stale ? " (stale)" : ""}`)));
  };
  const gapRows = gaps.map((g) => {
    const name = el("input", { "aria-label": `Medicine for ${g.term}`, placeholder: "Specific medicine" });
    const dose = el("input", { "aria-label": `Dose for ${g.term}`, placeholder: "Dose" });
    const drop = el("input", { type: "checkbox", id: `drop-${g.term}`, style: "width:auto" });
    name.addEventListener("input", () => { g.name = name.value; });
    dose.addEventListener("input", () => { g.dose = dose.value; });
    drop.addEventListener("change", () => { g.drop = drop.checked; });
    return el("div", { class: "gap" }, el("strong", {}, g.text), el("p", { class: "quote" }, `“${g.span}”`),
      el("div", { class: "grid2" }, name, dose),
      el("p", { class: "small" }, drop, " ", el("label", { for: drop.id, style: "display:inline;font-weight:400" }, "Remove this: not prescribing it")));
  });
  const err = el("p", { class: "error", role: "alert" });
  const comments = el("textarea", { id: "comments", rows: 2, placeholder: "What should change?" });
  const sign = el("button", { class: "primary", type: "button" }, "Sign note");
  const redo = el("button", { class: "secondary", type: "button" }, "Reject and redraft");
  const edits = () => ({
    soap,
    medicines: [
      ...meds.filter((m) => m.name.trim()).map(({ name, dose }) => ({ name, dose })),
      ...gaps.filter((g) => !g.drop && g.name.trim()).map(({ name, dose }) => ({ name, dose })),
    ],
    gaps: gaps.filter((g) => !g.drop && !g.name.trim()).map(({ term, span, text }) => ({ term, span, text })),
  });
  sign.addEventListener("click", guarded(sign, async () => {
    const r = await api(`/w3/${thread}/resume`, { method: "POST", body: { decision: "sign", edits: edits() } });
    const note = await api(`/w3/notes/${r.note_id}`);
    app.replaceChildren(el("h1", {}, "Signed"), el("div", { class: "alert ok", role: "status" },
      `Note saved for ${appt.patient_name}, version ${note.version}. It can't be changed now.`),
      el("div", { class: "card small" }, el("p", {}, `Review took ${Math.round(note.review_seconds)} seconds.`),
        el("p", { class: "muted" }, `Hash ${note.hash}`),
        el("div", { class: "row" }, el("button", { class: "secondary", type: "button", onclick: renderDoctor }, "Back to patients"))));
  }, err));
  redo.addEventListener("click", guarded(redo, async () => {
    if (!comments.value.trim()) throw new Error("Say what should change.");
    const r = await api(`/w3/${thread}/resume`, { method: "POST", body: { decision: "reject", comments: comments.value } });
    renderReview(thread, r, appt);
  }, err));
  app.replaceChildren(el("h1", {}, `Review: ${appt.patient_name}`),
    d.flags.length ? el("div", { class: "alert warn" }, el("strong", {}, "Removed from the draft:"), el("ul", {}, d.flags.map((f) => el("li", {}, f)))) : null,
    soapCard,
    el("div", { class: "card" }, el("h2", {}, "Medicines"),
      gapRows, meds.length ? meds.map(medRow) : gaps.length ? null : el("p", { class: "muted small" }, "None said.")),
    el("div", { class: "card" }, el("label", { for: "comments" }, "Comments, if you reject"), comments,
      el("div", { class: "row" }, sign, redo), err,
      el("p", { class: "muted small" }, "Nothing is saved until you sign.")),
    d.transcript ? el("details", { class: "card" }, el("summary", {}, "Transcript"), el("p", { class: "small" }, d.transcript)) : null);
}

// ---- front desk -----------------------------------------------------------------------------

const KINDS = { er: "Emergency", safety_unchecked: "Safety check didn't run", low_confidence: "Assistant unsure",
  advice_request: "Asked for diagnosis or dose", no_availability: "No free block", model_failure: "Assistant failed",
  ai_booking: "Assistant booked", late_block: "Block running late", doc_held: "Report held", doc_quarantine: "Report text set aside",
  answer_blocked: "Answer blocked" };

async function renderDesk() {
  const body = el("div", { class: "card" }, el("p", { class: "spin" }, "Loading…"));
  const refresh = el("button", { class: "secondary", type: "button", onclick: renderDesk }, "Refresh");
  app.replaceChildren(el("div", { class: "row", style: "justify-content:space-between" }, el("h1", {}, "Front-desk queue"), refresh), body);
  const rows = await api("/desk/queue");
  if (!rows.length) { body.replaceChildren(el("p", { class: "muted" }, "Nothing waiting.")); return; }
  body.replaceChildren(...rows.map(ticketRow));
}

function age(sec) { return sec < 3600 ? `${Math.floor(sec / 60)} min` : `${Math.floor(sec / 3600)} h ${Math.floor((sec % 3600) / 60)} min`; }

function ticketRow(t) {
  const err = el("p", { class: "error", role: "alert" });
  const action = (label, cls, fn) => { const b = el("button", { class: cls, type: "button" }, label); b.addEventListener("click", guarded(b, fn, err)); return b; };
  const claim = t.owner ? null : action("Claim", "secondary", async () => { await api(`/desk/tickets/${t.ticket_id}/claim`, { method: "POST" }); renderDesk(); });
  const close = action("Close", "secondary", async () => { await api(`/desk/tickets/${t.ticket_id}/close`, { method: "POST" }); renderDesk(); });
  const reason = el("input", { "aria-label": "Reason for cancelling", placeholder: "Reason, required to cancel" });
  const cancel = t.appt_id ? action("Cancel booking", "danger", async () => {
    if (reason.value.trim().length < 3) throw new Error("Give a reason to cancel.");
    await api(`/desk/appointments/${t.appt_id}/override`, { method: "POST", idem: true, body: { action: "cancel", reason: reason.value } });
    renderDesk();
  }) : null;
  return el("div", { class: "ticket" },
    el("div", { class: "ticket-head" },
      el("span", {}, el("span", { class: `pill ${t.priority === 0 ? "p0" : ""}` }, KINDS[t.kind] || t.kind), " ",
        el("strong", {}, t.patient_id || "")),
      el("span", { class: "muted small" }, `waiting ${age(t.age_seconds)} · owner ${t.owner || "none"}`)),
    el("p", {}, t.reason),
    t.patient_text ? el("p", { class: "quote" }, t.patient_text) : null,
    t.appt_id ? reason : null,
    el("div", { class: "row" }, claim, close, cancel), err);
}

renderSignIn();
