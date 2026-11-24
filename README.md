# aabot

Ferramenta de **login + exploração stealth** de `https://adm.autoavaliar.com.br`,
feita para ser chamada por **agentes de IA** (ex.: Hermes): saída `--json` parseável e
**exit code** que decide o próximo passo.

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .   # instala o comando `aabot`
```

Sem instalar, roda direto: `.venv/Scripts/python aabot.py ...`

## Uso rápido

```bash
aabot --json selfcheck                              # dependências
aabot --json login --no-escalate                    # login (só HTTP)
aabot --json fetch <url> --engine http --out pg.html # página autenticada completa
```

A sessão é persistida em `.aabot-cookies.json` e reusada entre `login` e `fetch`,
então após o login o agente **explora** páginas internas via `fetch`.

## Credenciais

Não há arquivo obrigatório. Usuário/senha chegam por, em ordem de precedência:

1. `--user` / `--password` (flags; evite onde o processo seja visível)
2. ambiente `AABOT_USER` / `AABOT_PASS` — **forma recomendada para agentes**, que
   injetam do próprio cofre antes de chamar a ferramenta
3. fallback `USER` / `PASSWORD`
4. opcional (dev local): arquivo `.env` com essas chaves — carregado se existir
   (`.env.example`)

Sem credencial em execução não-interativa, a ferramenta sai com **exit 13** (config),
sem travar em prompt.

## Para agentes

O contrato completo (campos do JSON, exit codes, fluxo de atestação, troubleshooting)
está em **[agente.md](agente.md)**. Leia antes de automatizar.
