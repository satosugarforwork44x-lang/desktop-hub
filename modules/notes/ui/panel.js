// notes/ui/panel.js — メモと ToDo。1 行書いて Enter。☐ を押してから書くと ToDo になる。画像は Ctrl+V で貼れる
import { icons } from "/ui/js/icons.js";
import { TOKEN } from "/ui/js/hub.js";

export async function mount(el, ctx) {
  const t = ctx.t;
  let items = [];
  let filter = "all";            // all / todo
  let composeTodo = false;

  el.innerHTML = `
    <div class="notes">
      <div class="note-compose">
        <button type="button" class="note-todo-toggle" aria-pressed="false"></button>
        <textarea rows="1"></textarea>
      </div>
      <div class="note-filter seg seg-sm" role="radiogroup"></div>
      <div class="note-list"></div>
    </div>`;
  const $ = (s) => el.querySelector(s);
  const input = $("textarea");
  const toggle = $(".note-todo-toggle");
  input.placeholder = t("notes.placeholder");
  input.title = t("notes.composeHint");
  toggle.title = t("notes.asTodo");
  toggle.setAttribute("aria-label", t("notes.asTodo"));
  const checkSvg = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>';
  toggle.innerHTML = checkSvg;
  toggle.addEventListener("click", () => { composeTodo = !composeTodo; toggle.setAttribute("aria-pressed", String(composeTodo)); input.focus(); });

  const undoBtn = ctx.addTool(icons.undo, t("notes.undo"), async () => { await ctx.call("restore"); undoBtn.disabled = true; load(); });
  undoBtn.disabled = true;
  const clearBtn = ctx.addTool(icons.trash, t("notes.clearDone"), async () => {
    const r = await ctx.call("clear_done");
    if (r.removed) { undoBtn.disabled = false; ctx.toast(t("notes.cleared", { n: r.removed })); }
    load();
  });

  // ---- 書く ----
  function grow() { input.style.height = "auto"; input.style.height = `${Math.min(140, input.scrollHeight)}px`; }
  input.addEventListener("input", grow);
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {   // 日本語の変換中の Enter は確定に使う
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      try { await ctx.call("add", { text, todo: composeTodo }); input.value = ""; grow(); load(); }
      catch (er) { ctx.toast(er.message, "error"); }
    }
  });
  // 画像の貼り付け（スクリーンショットなど）
  el.addEventListener("paste", async (e) => {
    const file = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"))?.getAsFile();
    if (!file) return;
    e.preventDefault();
    const dataUrl = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(file); });
    try { await ctx.call("add_image", { data_url: dataUrl, text: input.value.trim() }); input.value = ""; grow(); load(); }
    catch (er) { ctx.toast(er.message, "error"); }
  });

  // ---- 絞り込み ----
  const seg = $(".note-filter");
  for (const [v, k] of [["all", "notes.all"], ["todo", "notes.todos"]]) {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "radio");
    b.dataset.v = v;
    b.textContent = t(k);
    b.addEventListener("click", () => { filter = v; render(); });
    seg.append(b);
  }

  // ---- 一覧 ----
  function render() {
    seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.v === filter)));
    const list = $(".note-list");
    list.replaceChildren();
    // ToDo は未完了を上に、完了は下にまとめる
    const shown = items.filter((i) => filter === "all" || i.todo)
      .sort((a, b) => Number(a.todo && a.done) - Number(b.todo && b.done) || b.created - a.created);
    if (!shown.length) {
      const e = document.createElement("div");
      e.className = "empty";
      e.textContent = t(filter === "todo" ? "notes.emptyTodo" : "notes.empty");
      list.append(e);
    }
    for (const it of shown) list.append(card(it));
    const open = items.filter((i) => i.todo && !i.done).length;
    const done = items.filter((i) => i.todo && i.done).length;
    clearBtn.disabled = !done;
    ctx.setStatus(open ? t("notes.left", { n: open }) : "");
  }

  function card(it) {
    const c = document.createElement("div");
    c.className = "note";
    if (it.todo && it.done) c.classList.add("done");
    if (it.todo) {
      const cb = document.createElement("button");
      cb.type = "button";
      cb.className = "note-check";
      cb.setAttribute("role", "checkbox");
      cb.setAttribute("aria-checked", String(!!it.done));
      cb.setAttribute("aria-label", t("notes.done"));
      cb.innerHTML = checkSvg;
      cb.addEventListener("click", async () => { await ctx.call("update", { id: it.id, done: !it.done }); load(); });
      c.append(cb);
    }
    const body = document.createElement("div");
    body.className = "note-body";
    if (it.text) {
      const p = document.createElement("div");
      p.className = "note-text";
      p.textContent = it.text;
      p.title = t("notes.editHint");
      p.addEventListener("dblclick", () => edit(it, p));
      body.append(p);
    }
    if (it.image) {
      const img = document.createElement("img");
      img.className = "note-img";
      img.src = `/blob/notes/${encodeURIComponent(it.image)}?t=${encodeURIComponent(TOKEN)}`;
      img.alt = "";
      img.addEventListener("click", () => img.classList.toggle("big"));
      body.append(img);
    }
    const when = document.createElement("div");
    when.className = "note-when";
    when.textContent = new Date(it.created * 1000).toLocaleString(document.documentElement.lang === "ja" ? "ja-JP" : "en-US",
      { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    body.append(when);
    c.append(body);

    const acts = document.createElement("div");
    acts.className = "note-acts";
    const mk = (ico, label, fn) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "icon-btn";
      b.innerHTML = ico;
      b.title = label;
      b.setAttribute("aria-label", label);
      b.addEventListener("click", fn);
      return b;
    };
    acts.append(
      mk(it.todo ? icons.note : checkSvg, t(it.todo ? "notes.toNote" : "notes.toTodo"), async () => { await ctx.call("update", { id: it.id, todo: !it.todo }); load(); }),
      mk(icons.close, t("notes.delete"), async () => { await ctx.call("remove", { id: it.id }); undoBtn.disabled = false; load(); }),
    );
    c.append(acts);
    return c;
  }

  // その場で書き換える（Enter で確定、Esc で取り消し）
  function edit(it, p) {
    const ta = document.createElement("textarea");
    ta.className = "note-edit";
    ta.value = it.text;
    p.replaceWith(ta);
    ta.style.height = `${ta.scrollHeight}px`;
    ta.focus();
    let done = false;
    const finish = async (ok) => {
      if (done) return;
      done = true;
      if (ok && ta.value.trim() !== it.text) await ctx.call("update", { id: it.id, text: ta.value }).catch((e) => ctx.toast(e.message, "error"));
      load();
    };
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); finish(true); }
      if (e.key === "Escape") finish(false);
    });
    ta.addEventListener("blur", () => finish(true));
  }

  async function load() {
    try { items = await ctx.call("items"); } catch (e) { ctx.toast(e.message, "error"); }
    render();
  }
  await load();
  input.focus();
}
