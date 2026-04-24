# Security Hardening Runbook

Data: 2026-04-19

## Objetivo

Colocar o ambiente em conformidade com os defaults endurecidos introduzidos no código:

- key store criptografado por default
- JWT seguro e persistido
- API bind local por default
- cockpit API com service hardening
- SSH com host key checking obrigatório
- MT5 sem senha VNC hardcoded

## Pré-requisitos

- `cryptography` instalado no Python que roda o projeto
- acesso aos segredos reais fora do Git
- `known_hosts` do VPS preparado no host local

## Passo 1: migrar secrets para `config/keys.json.enc`

No host de desenvolvimento, com o plaintext atual presente apenas durante a migração:

```powershell
& 'C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe' tools\maintenance\encrypt_keys.py
```

Escolha uma master password forte e guarde fora do repositório.

## Passo 2: exportar variáveis obrigatórias

PowerShell da sessão atual:

```powershell
$env:AURUM_KEY_PASSWORD = 'COLE_AQUI_A_MASTER_PASSWORD'
$env:MT5_VNC_PASSWORD = 'COLE_AQUI_A_SENHA_VNC'
```

Se precisar de compatibilidade temporária com plaintext durante a janela de migração:

```powershell
$env:AURUM_ALLOW_PLAINTEXT_KEYS = '1'
```

Remova essa variável assim que `keys.json.enc` estiver validado.

## Passo 3: validar readiness

```powershell
& 'C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe' tools\maintenance\security_readiness.py
```

O resultado esperado é:

```text
OK: security readiness check passed
```

## Passo 4: validar runtime seguro

- subir o fluxo que consome keys em modo seguro
- confirmar que o ambiente usa `keys.json.enc`
- confirmar que não há dependência de `AURUM_ALLOW_PLAINTEXT_KEYS`

Checks mínimos:

- API principal sobe bindada em `127.0.0.1` salvo override explícito
- cockpit API sobe com o service endurecido
- launcher/cockpit conseguem ler o bloco `cockpit_api`
- monitor/Telegram continuam funcionais com o encrypted store

## Passo 5: remover plaintext

Somente depois da validação:

```powershell
Remove-Item -LiteralPath 'config\keys.json'
```

## Passo 6: rotacionar segredos previamente expostos

O `config/keys.json` antigo continha valores reais. Esses segredos devem ser tratados como comprometidos.

Rotacionar:

- chaves Binance demo/testnet/live
- bot token e `chat_id` do Telegram, se aplicável
- tokens `read/admin` do cockpit API
- chaves `FRED` e `NewsAPI`
- credenciais/acessos do VPS se houve compartilhamento operacional

## Passo 7: VPS / SSH

Garantir que o bloco `vps_ssh` provisionado contenha:

- `user` não-root, preferencialmente `aurum`
- `key_path` válido
- `known_hosts_path` válido
- host key já aprendida e pinada

Sem isso, o novo fluxo SSH vai recusar conexão.

## Passo 8: MT5 / Docker

Antes de subir `docker compose`:

```powershell
$env:MT5_VNC_PASSWORD = 'COLE_AQUI_A_SENHA_VNC'
docker compose up -d
```

O compose agora exige a variável e publica portas apenas em loopback.
