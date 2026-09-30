from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Dragon Tory</title>
  <style>
    :root {
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      color: #172033;
      background: #f5f7fb;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; }
    main { max-width: 1040px; margin: 0 auto; padding: 48px 24px; }
    header {
      background: white;
      border: 1px solid #e5e9f2;
      border-radius: 22px;
      padding: 28px;
      box-shadow: 0 16px 40px rgba(27, 39, 68, .06);
    }
    h1 { margin: 0 0 8px; font-size: 34px; }
    .sub { margin: 0; color: #667085; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }
    .card {
      background: white;
      border: 1px solid #e5e9f2;
      border-radius: 18px;
      padding: 20px;
    }
    .label { color: #667085; font-size: 13px; margin-bottom: 8px; }
    .value { font-size: 20px; font-weight: 700; }
    .ok { color: #137a46; }
    .warn { color: #a15c00; }
    .bad { color: #b42318; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
    a {
      display: inline-block;
      text-decoration: none;
      color: #172033;
      background: white;
      border: 1px solid #d5dbea;
      border-radius: 12px;
      padding: 11px 15px;
      font-weight: 600;
    }
    footer { color: #98a2b3; margin-top: 24px; font-size: 13px; }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Дракончик Тоору</h1>
      <p class="sub">Dragon Tory · локальный центр проекта и памяти</p>
      <div class="actions">
        <a href="/docs">API / Swagger</a>
        <a href="/health">Health JSON</a>
        <a href="/v1/memory/guardian/status">Guardian JSON</a>
        <a href="/v1/memory/maintenance/status">Memory Automation JSON</a>
      </div>
    </header>

    <section class="grid">
      <article class="card">
        <div class="label">Backend</div>
        <div class="value" id="backend">Проверка…</div>
      </article>
      <article class="card">
        <div class="label">Memory Guardian</div>
        <div class="value" id="guardian">Проверка…</div>
      </article>
      <article class="card">
        <div class="label">Memory Automation</div>
        <div class="value" id="automation">Проверка…</div>
      </article>
      <article class="card">
        <div class="label">Версия</div>
        <div class="value" id="version">—</div>
      </article>
    </section>

    <footer>
      Страница работает локально. Проект запускается из текущего носителя без
      привязки к букве диска.
    </footer>
  </main>
  <script>
    async function getJson(url) {
      const response = await fetch(url, {cache: "no-store"});
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }
    function setState(id, text, css) {
      const el = document.getElementById(id);
      el.textContent = text;
      el.className = "value " + css;
    }
    async function refresh() {
      try {
        const health = await getJson("/health");
        setState("backend", "Работает", "ok");
        document.getElementById("version").textContent = health.version || "—";
      } catch {
        setState("backend", "Ошибка", "bad");
      }

      try {
        const guardian = await getJson("/v1/memory/guardian/status");
        const pending = guardian.queued_pending || 0;
        setState(
          "guardian",
          pending ? "Ожидают: " + pending : "Работает",
          pending ? "warn" : "ok"
        );
      } catch {
        setState("guardian", "Недоступен", "bad");
      }

      try {
        const auto = await getJson("/v1/memory/maintenance/status");
        setState(
          "automation",
          auto.started ? (auto.running ? "Обслуживание…" : "Активна") : "Выключена",
          auto.started ? "ok" : "warn"
        );
      } catch {
        setState("automation", "Недоступна", "bad");
      }
    }
    refresh();
    setInterval(refresh, 10000);
  </script>
</body>
</html>
"""
