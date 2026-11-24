# aabot — manual do agente

Ferramenta de login/fetch stealth. **Alvo de login embutido:** `https://adm.autoavaliar.com.br`.
Pensada para ser chamada por um agente (ex.: Hermes): sempre com `--json`, saída parseável,
e o **exit code** decide o próximo passo.

Antes de qualquer comando, ative o ambiente e instale as dependências:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Chame sempre a ferramenta pelo python do venv (`.venv\Scripts\python.exe aabot.py ...`).

---

## Contrato de saída

- `--json` → um **único objeto JSON** no stdout. Avisos de diagnóstico vão no **stderr**
  (não contaminam o JSON).
- **Exit codes:** `0` ok · `1` erro inesperado · `10` bloqueado · `11` auth falhou ·
  `12` dependência ausente · `13` config · `14` timeout.
- **Credenciais entram pelo ambiente:** `AABOT_USER`, `AABOT_PASS`. Nunca as imprima,
  nunca as passe em linha de comando visível quando puder usar o ambiente.

### Campos do JSON

`ok`, `engine`, `url`, `final_url`, `status`, `vendors[]`, `needs_interactive`,
`authenticated`, `notes[]`, `cookies{}`, `elapsed_ms`, `html_bytes`,
`html_head` (primeiros 4000 caracteres do HTML).

**Regras de leitura (importantes):**

- A decisão de login é o campo **`authenticated`** — e só ele. **Não** faça grep do
  `html_head`: ele é truncado em 4 KB e o marcador autenticado (`sair`/`logout`) costuma
  estar depois disso num painel grande. `authenticated` já inspeciona o HTML inteiro.
- **`needs_interactive: true`** → o challenge exige humano/captcha. Pare de tentar sozinho
  e reporte.
- **`vendors` não-vazio no alvo oficial** → o alvo ganhou anti-bot (mudou). Pare e reporte.

---

## Comandos

### selfcheck
```
.venv\Scripts\python.exe aabot.py --json selfcheck
```
Verifica `curl_cffi`, `pydoll`, `patchright`, `chrome_sistema`. Qualquer `AUSENTE` → exit `12`.
`chrome_sistema` é **obrigatório** para a camada browser; a camada HTTP funciona sem ele.

### login (alvo embutido)
```
set AABOT_USER=...   &  set AABOT_PASS=...
.venv\Scripts\python.exe aabot.py --json login --no-escalate
```
- Sem subcomando, `python aabot.py` já cai em `login`.
- `--no-escalate` → **só camada HTTP** (não abre Chrome). Aprovação = exit `0` **E**
  `authenticated=true`.
- Sem `--no-escalate` → se o HTTP não autenticar, **escala** para Chrome real
  (`patchright` → `pydoll`).
- `--headed` → Chrome visível (para resolver challenge/captcha ou capturar a DOM pós-login).
- Flags: `--user`, `--password` (prefira o ambiente), `--country` (default `BR`),
  `--proxy`, `--session` (default `.aabot-cookies.json`), `--timeout` (default `45`).

> Em contexto não-interativo, exporte **sempre** `AABOT_USER` e `AABOT_PASS`. Sem elas, a
> ferramenta tentaria perguntar no terminal; com stdin fechado isso vira exit `1`
> (`erro inesperado`), não um login.

### fetch (qualquer URL)
```
.venv\Scripts\python.exe aabot.py --json fetch <url> --engine http
```
- `--engine`: `auto` (http → browser), `http`, `pydoll`, `patchright`.
- Sanidade do alvo: `fetch https://adm.autoavaliar.com.br/ --engine http` deve dar
  `ok=true`, `status=200`, `vendors=[]`.

---

## Fluxo de atestação

1. **Preparo** — `selfcheck`. Se algum item vier `AUSENTE`, instale antes de seguir.
2. **Sanidade HTTP** — `fetch https://adm.autoavaliar.com.br/ --engine http`.
   Esperado: `ok=true`, `status=200`, `vendors=[]`. Se vier vendor → **PARE**, o alvo mudou.
3. **Login HTTP** — `login --no-escalate`. Aprovação = exit `0` **E** `authenticated=true`.
4. **Sinal limpo** — inspecione o arquivo de `--session` (default `.aabot-cookies.json`):
   as chaves `fingerprint` e `fingerprint_detalhes` devem existir, e o detalhes deve ter
   `language=pt-BR` e `timezoneOffset=180`. `authenticated=true` com `__aa_auto` vazio de
   sinais é o comportamento desejado.
5. **Escalonamento** (só se o passo 3 falhar) — repita **sem** `--no-escalate`. Se vier
   `needs_interactive=true`, repita com `--headed` e reporte.

### Saída obrigatória do agente (JSON)
```json
{ "selfcheck": {}, "fetch_http": {"ok": false, "vendors": []},
  "login_http": {"exit": 0, "authenticated": false},
  "login_escalado": null, "veredito": "APROVADO",
  "causa_raiz": null, "ajustes_sugeridos": [] }
```
Regra: **nunca invente resultado**; reporte o **exit code bruto**. Se falhar, o veredito é
`REPROVADO` e `causa_raiz` deve citar o campo JSON que evidenciou a falha.
**Não altere o `aabot.py` durante a atestação — só proponha ajustes.**

---

## Troubleshooting

- **exit `11` / `authenticated=false` no HTTP** — o mais provável é `SHIM["auth_markers"]`
  não casar com a DOM autenticada real. Rode `login --headed`, capture a DOM pós-login e
  ajuste os marcadores no `aabot.py`.
- **exit `1` / `erro inesperado`** — dependência de browser quebrou na escalada, ou o
  arquivo de `--session` está corrompido. Apague o arquivo de `--session` e rode `selfcheck`.
- **`vendors=[cloudflare]` ou outro no alvo** — o alvo passou a ter anti-bot. A camada HTTP
  não vence sozinha; tente `--headed`.

## Premissas e limites honestos

- O `fingerprint` é **sintético e estável** (`fnv1a`), não o hash real de um canvas.
  Serve **se** o servidor apenas armazena/eco o valor; se ele recomputa ou cruza com um
  canvas real do lado servidor, o sintético não casa.
- `_auth_ok` tem um fallback (`"login"` não está no path final) que pode dar
  **falso-positivo** se sucesso e falha caírem em paths sem `login`. O `auth_marker` real
  (capturado via `--headed`) é o critério mais seguro.
