# aabot

Ferramenta de **login + exploração stealth** de `https://adm.autoavaliar.com.br`,
feita para ser chamada por **agentes de IA** (ex.: Hermes): saída `--json` parseável e
**exit code** que decide o próximo passo.

## Instalação

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .   # instala o comando `aabot`
cp .env.example .env                        # preencha AABOT_USER / AABOT_PASS
```

Sem instalar, roda direto: `.venv/Scripts/python aabot.py ...`

## Uso rápido

```bash
aabot --json selfcheck                              # dependências
aabot --json login --no-escalate                    # login (só HTTP)
aabot --json fetch <url> --engine http --out pg.html # página autenticada completa
```

As credenciais entram por ambiente (`.env` é carregado automaticamente).
A sessão é persistida em `.aabot-cookies.json` e reusada entre `login` e `fetch`,
então após o login o agente **explora** páginas internas via `fetch`.

## Para agentes

O contrato completo (campos do JSON, exit codes, fluxo de atestação, troubleshooting)
está em **[agente.md](agente.md)**. Leia antes de automatizar.
