// Cole este código no Apps Script da planilha:
// Extensões → Apps Script → substitua o conteúdo → Salvar → rodar syncSheetsToBigQuery uma vez para testar

const BQ_PROJECT = 'leads-ts';
const BQ_DATASET = 'Unnichat_Mentorias';
const BQ_TABLE   = 'sheets_mentoria_tonho';
const SHEET_NAME = 'PBI';

function syncSheetsToBigQuery() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) { Logger.log('Aba "' + SHEET_NAME + '" não encontrada.'); return; }

  const values = sheet.getDataRange().getValues();
  if (values.length < 2) { Logger.log('Sem dados na aba.'); return; }

  const rawHeaders = values[0];
  const dataRows   = values.slice(1).filter(r => r.some(c => c !== '' && c !== null));
  if (dataRows.length === 0) { Logger.log('Nenhuma linha com dados.'); return; }

  // Normaliza nomes de colunas para snake_case compatível com BQ
  const headers = rawHeaders.map(h =>
    String(h).trim().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_|_$/g, '').toLowerCase() || 'col'
  );

  const syncedAt = Utilities.formatDate(new Date(), 'America/Sao_Paulo', 'yyyy-MM-dd HH:mm:ss');

  // Garante que a tabela existe (cria apenas se nunca foi criada)
  ensureTable(headers);

  // Limpa todos os dados existentes via job DML e aguarda conclusão
  truncateAndWait();

  // Streaming insert em lotes de 500 (limite do BQ)
  const BATCH = 500;
  for (let i = 0; i < dataRows.length; i += BATCH) {
    const batch = dataRows.slice(i, i + BATCH);
    const rows = batch.map((row, idx) => {
      const json = { synced_at: syncedAt };
      headers.forEach((h, j) => {
        let val = row[j];
        if (val instanceof Date) val = Utilities.formatDate(val, 'America/Sao_Paulo', 'yyyy-MM-dd HH:mm:ss');
        else if (val === '' || val === null || val === undefined) val = null;
        json[h] = val;
      });
      return { insertId: syncedAt + '_' + (i + idx), json };
    });

    BigQuery.Tabledata.insertAll(
      { rows, skipInvalidRows: false, ignoreUnknownValues: false },
      BQ_PROJECT, BQ_DATASET, BQ_TABLE
    );
    Logger.log('Lote inserido: ' + rows.length + ' linhas.');
  }

  Logger.log('Sync concluído: ' + dataRows.length + ' linhas.');
}

function ensureTable(headers) {
  try {
    BigQuery.Tables.get(BQ_PROJECT, BQ_DATASET, BQ_TABLE);
    // tabela já existe, não faz nada
  } catch (e) {
    const fields = [{ name: 'synced_at', type: 'STRING', mode: 'NULLABLE' }];
    headers.forEach(h => fields.push({ name: h, type: 'STRING', mode: 'NULLABLE' }));
    BigQuery.Tables.insert(
      {
        tableReference: { projectId: BQ_PROJECT, datasetId: BQ_DATASET, tableId: BQ_TABLE },
        schema: { fields }
      },
      BQ_PROJECT, BQ_DATASET
    );
    Logger.log('Tabela criada pela primeira vez: ' + BQ_TABLE);
    Utilities.sleep(5000); // aguarda propagação apenas na criação inicial
  }
}

function truncateAndWait() {
  const query = 'TRUNCATE TABLE `' + BQ_PROJECT + '.' + BQ_DATASET + '.' + BQ_TABLE + '`';

  const job = BigQuery.Jobs.insert(
    { configuration: { query: { query: query, useLegacySql: false } } },
    BQ_PROJECT
  );

  const jobId = job.jobReference.jobId;
  Logger.log('TRUNCATE job iniciado: ' + jobId);

  // Aguarda o job completar antes de prosseguir
  let status;
  do {
    Utilities.sleep(1500);
    status = BigQuery.Jobs.get(BQ_PROJECT, jobId);
  } while (status.status.state !== 'DONE');

  if (status.status.errorResult) {
    throw new Error('TRUNCATE falhou: ' + JSON.stringify(status.status.errorResult));
  }

  Logger.log('TRUNCATE concluído.');
}

// Chame esta função UMA VEZ para registrar o trigger automático de 5 em 5 minutos
function criarTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'syncSheetsToBigQuery')
    .forEach(t => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('syncSheetsToBigQuery')
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log('Trigger criado: syncSheetsToBigQuery a cada 5 min.');
}
