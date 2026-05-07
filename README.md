# Dashboard — Mentoria TS Tonho 2026

Dashboard automático que agrega dados do Google Sheets + BigQuery e publica via GitHub Pages.

---

## Como funciona

```
Google Sheets (alunos)  ──┐
                           ├──► scripts/fetch_data.py ──► dashboard/data.json ──► GitHub Pages
BigQuery (CRM/Unnichat) ──┘
```

O GitHub Actions roda o script Python a cada 5 minutos, atualiza o `data.json` e faz push. O `index.html` já está no ar e refaz o fetch a cada 30 segundos.

---

## Passo 1 — Preparar a Service Account no Google Cloud

A Service Account já existe: `113651380853-compute@developer.gserviceaccount.com`

Você precisa garantir que ela tem permissão nos dois serviços:

### 1a. Acesso ao Google Sheets

1. Abra a planilha no Google Sheets
2. Clique em **Compartilhar** (botão azul no canto superior direito)
3. Cole o e-mail da service account: `113651380853-compute@developer.gserviceaccount.com`
4. Defina como **Leitor** e clique em **Enviar**

### 1b. Acesso ao BigQuery

1. No [Google Cloud Console](https://console.cloud.google.com) → projeto `leads-ts`
2. Menu → **IAM e Administrador** → **IAM**
3. Clique em **Conceder Acesso**
4. Principal: `113651380853-compute@developer.gserviceaccount.com`
5. Papel: **BigQuery Data Viewer** + **BigQuery Job User**
6. Salvar

---

## Passo 2 — Criar o repositório no GitHub

1. Acesse [github.com](https://github.com) e crie um repositório **público** (ex: `mentoria-tonho-dashboard`)
2. Na sua máquina, dentro da pasta `Mentoria Tonho`, rode:

```bash
git init
git add .
git commit -m "feat: estrutura inicial do dashboard"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/mentoria-tonho-dashboard.git
git push -u origin main
```

---

## Passo 3 — Adicionar os GitHub Secrets

Os Secrets são variáveis seguras que o GitHub Actions usa sem expor no código.

1. No seu repositório GitHub, clique em **Settings** (aba no topo)
2. Menu lateral → **Secrets and variables** → **Actions**
3. Clique em **New repository secret** e crie **dois** secrets:

### Secret 1: `GOOGLE_CREDENTIALS`
- **Name:** `GOOGLE_CREDENTIALS`
- **Value:** copie e cole o conteúdo inteiro do arquivo `OtavioPermissao.json`
  (abre o arquivo num editor de texto, seleciona tudo, copia)

### Secret 2: `GCP_PROJECT_ID`
- **Name:** `GCP_PROJECT_ID`
- **Value:** `leads-ts`

---

## Passo 4 — Ativar o GitHub Pages

1. No repositório, clique em **Settings**
2. Menu lateral → **Pages**
3. Em **Source**, selecione **Deploy from a branch**
4. Branch: `main` | Folder: `/dashboard`
5. Clique em **Save**

Após 1-2 minutos, o GitHub vai mostrar a URL do dashboard (algo como `https://seu-usuario.github.io/mentoria-tonho-dashboard/`).

---

## Passo 5 — Verificar se o Actions está rodando

1. Na aba **Actions** do repositório, você verá o workflow `Atualizar Dados do Dashboard`
2. Clique nele para ver os logs de cada execução
3. A cada 5 minutos ele vai rodar automaticamente

> **Nota:** O GitHub pode atrasar workflows de cron por alguns minutos em repositórios com baixa atividade. O atraso máximo costuma ser de 10-15 min.

---

## Testar o script localmente

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. Configure as variáveis de ambiente (PowerShell)
$env:GOOGLE_CREDENTIALS = Get-Content .\OtavioPermissao.json -Raw
$env:GCP_PROJECT_ID = "leads-ts"

# 2. Configure as variáveis de ambiente (bash/macOS/Linux)
export GOOGLE_CREDENTIALS=$(cat OtavioPermissao.json)
export GCP_PROJECT_ID="leads-ts"

# 3. Rode o script
python scripts/fetch_data.py

# 4. Abra o dashboard
# Abra dashboard/index.html no navegador (pode precisar de um servidor local)
# Para Python:
cd dashboard && python -m http.server 8080
# Acesse: http://localhost:8080
```

---

## Estrutura do projeto

```
.github/workflows/update-data.yml   ← GitHub Actions (cron a cada 5 min)
scripts/fetch_data.py               ← script de coleta e agregação
requirements.txt                    ← dependências Python
dashboard/index.html                ← dashboard (GitHub Pages)
dashboard/data.json                 ← gerado automaticamente
README.md                           ← este arquivo
```

---

## FAQ

**O dashboard mostra "Sem dados ainda"**
→ O script ainda não rodou. Vá em Actions → clique no workflow → **Run workflow** para forçar uma execução manual.

**Erro de permissão no Sheets**
→ Certifique-se de ter compartilhado a planilha com o e-mail da service account (Passo 1a).

**Erro de permissão no BigQuery**
→ Verifique se os papéis foram adicionados corretamente no IAM (Passo 1b).

**O indicador mostra "Desatualizado"**
→ O dado tem mais de 10 minutos. Aguarde o próximo ciclo do Actions ou clique em "Atualizar agora" — isso só rebusca o JSON já gerado. Para forçar nova coleta, vá em Actions → Run workflow.
