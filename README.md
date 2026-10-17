# Analytics Data Quality CLI

Aplicação de terminal para comparar **duas tabelas** usando metadados, valores e indicadores de qualidade calculados sobre amostras. As tabelas podem estar na mesma conexão ou em bancos diferentes.

## Instalação e execução pelo terminal

Requer Python 3.10 ou mais recente. No diretório do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

### Organização local

```text
/home/biel/analytics-data-quality/
├── analytics-data-quality-cli/  # repositório, .venv, aplicação e arquivos locais
├── tests/                      # sete módulos de testes
│   └── validation/             # scripts auxiliares de auditoria
└── docs/                       # especificação, HTML e evidências
```

O repositório está em `/home/biel/analytics-data-quality/analytics-data-quality-cli`.
Os diretórios irmãos `tests/` e `docs/` ficam fora do Git deste repositório e precisam ser incluídos em cópias de segurança da pasta mãe. Os arquivos locais `credentials.yaml` e `comparisons.yaml` continuam ao lado de `main.py`. O ambiente anterior à mudança foi preservado em `../.venv-before-relocation/` como cópia de segurança; para executar, use o ambiente recriado `.venv/` dentro do repositório.

Em execuções posteriores:

```bash
cd /home/biel/analytics-data-quality/analytics-data-quality-cli
source .venv/bin/activate
python main.py
```

Também é possível executar sem ativar o ambiente:

```bash
/home/biel/analytics-data-quality/analytics-data-quality-cli/.venv/bin/python /home/biel/analytics-data-quality/analytics-data-quality-cli/main.py
```

A aplicação usa exclusivamente um **menu interativo**; `main.py` não oferece subcomandos.

```text
=== Analytics Data Quality ===
1. Usar uma conexão salva
2. Cadastrar uma conexão
3. Comparar duas tabelas
4. Consultar comparações salvas
5. Sair
```

### Como comparar as duas tabelas

1. Cadastre as conexões pela opção **2**. Para duas tabelas na mesma base, basta cadastrar uma conexão.
2. Escolha **3 — Comparar duas tabelas**.
3. Escolha a conexão e a primeira tabela.
4. Escolha a conexão e a segunda tabela. É permitido reutilizar a conexão, selecionando outra tabela.
5. Na preferência de amostragem, pressione **Enter** para o planejamento automático. O motor procura uma PK ou chave UNIQUE não nula compatível. Esse modo pressupõe que as chaves identificam as mesmas entidades nas duas tabelas.
6. Leia a conclusão, o plano amostral, os metadados, as diferenças de valores e as estatísticas. Informe um nome ou pressione Enter para salvar com a data e hora.
7. Use a opção **4** para selecionar uma comparação salva e escolher entre **Executar nova comparação destas tabelas**, **Visualizar resultado histórico** e **Voltar**. Ctrl+C ou encerramento da entrada cancelam a seleção sem deixar conexões abertas.

Na preferência de amostragem:

- **Enter:** modo automático, com alinhamento por chave quando seguro; sem chave, compara perfis independentes.
- **p:** compara somente perfis independentes, mesmo quando existe chave comum.
- **c:** configura o máximo de linhas, células e orçamento estimado de tamanho. Os padrões são 1.000 linhas, 100.000 células e 16 MiB por amostra. O máximo configurável é 10.000 linhas.

### Fontes e drivers

| Fonte | Driver utilizado | Informação de conexão |
|---|---|---|
| PostgreSQL | `psycopg2-binary` via SQLAlchemy | Host, porta, usuário, senha e banco |
| MySQL | `pymysql` via SQLAlchemy | Host, porta, usuário, senha e banco |
| SQLite | `sqlite3` do Python via SQLAlchemy | Caminho do arquivo local |
| SQL Server | `mssql-python` | Host, porta, usuário, senha e banco |
| Oracle | `oracledb` via SQLAlchemy | Host, porta, usuário, senha e **service name** |

`requirements.txt` inclui as dependências do projeto. Drivers podem exigir bibliotecas de sistema de acordo com a plataforma, além de acesso de rede e permissão de leitura de dados e catálogos. A senha é solicitada sem eco no terminal.

As conexões ficam em `credentials.yaml` e o histórico em `comparisons.yaml`, **ao lado de `main.py`**, independentemente do diretório de execução. Esses arquivos são locais e ignorados pelo Git. As consultas do motor não fazem sincronização nem alteração de dados.

## Como funciona o motor

O fluxo separa descoberta de metadados, coleta piloto, planejamento, captura final, cálculo e apresentação. O piloto lê até **64 linhas de cada tabela**. O tamanho final comum considera estimativas positivas de volume, quantidade de colunas, tamanho observado dos valores e variabilidade numérica. A referência de proporção usada no planejamento não é apresentada como intervalo de confiança dos resultados.

Com chaves compatíveis, o motor captura candidatos **nas duas fontes**, escolhe uma união de chaves dentro do orçamento e busca o mesmo conjunto nas duas tabelas. A comparação informa registros ausentes em cada lado, valores diferentes por coluna e células que não puderam ser comparadas. As diferenças de métricas são calculadas sobre as linhas com chaves presentes em ambas; os perfis de cada fonte também mostram todos os registros obtidos na busca.

Sem chave segura, as amostras são independentes. O resultado mostra diferenças descritivas de métricas e sobreposição dos valores observados, sem afirmar correspondência entre linhas. Uma coluna UNIQUE que permite NULL não é usada automaticamente como chave. Chaves temporais exigem conversão explícita e ficam fora do alinhamento automático nesta versão.

Os metadados incluem nomes, tipos declarados, nulabilidade, chaves e tamanho/precisão quando o catálogo disponibiliza essas informações. Nomes são associados sem diferenciar caixa apenas quando o mapeamento é inequívoco. Tipos nativos equivalentes são observações de compatibilidade; diferenças estruturais reais aparecem separadamente.

Os indicadores incluem contagens e taxas de nulos, textos vazios, diversidade e duplicidades observadas, mínimo, máximo, média, mediana, quartis e desvio padrão populacional. A unicidade de uma PK composta é avaliada pela tupla completa. Cada taxa informa seu denominador; valores não finitos, indisponíveis ou não suportados são contabilizados e excluídos das estatísticas em que não podem participar.

Valores numéricos usam Decimal nas estatísticas; a comparação padrão é exata. Textos preservam espaços e caixa. NULL é diferente de texto vazio. Datas preservam a precisão fracionária dos bancos, inclusive além dos seis dígitos suportados por `datetime` do Python. Valores grandes têm limite de materialização e, quando indisponíveis, produzem uma avaliação inconclusiva em vez de igualdade artificial.

### Interpretação do resultado

| Estado | Interpretação |
|---|---|
| **Compatível na amostra** | Chaves correspondentes e valores comparáveis coincidiram no conjunto observado |
| **Diferença observada** | Há diferença estrutural, chave ausente, valor divergente ou violação observada |
| **Somente perfil** | Não houve alinhamento de registros; métricas e distribuições são descritivas |
| **Inconclusivo** | Amostra vazia ou evidência insuficiente para uma conclusão segura |

Uma coluna inteiramente nula gera uma observação para investigação; não é erro automático quando o catálogo permite NULL. Estatísticas de catálogo podem estar desatualizadas e não comprovam diferença de volume.

### Percentuais e prévia dos dados

Cada execução nova mostra **dois indicadores separados**:

- **Concordância entre tabelas:** `valores iguais ÷ posições avaliadas × 100`. O conjunto de posições usa as chaves sorteadas e a união das colunas das duas tabelas. Uma posição de registro/coluna ausente conta como divergência; NULL comparado com NULL é igualdade.
- **Qualidade observada:** `verificações aprovadas ÷ verificações avaliadas × 100`. Os critérios são preenchimento dos campos obrigatórios, validade dos tipos suportados, finitude numérica e integridade observada das chaves declaradas. A nota consolidada usa a soma das verificações das fontes, não a média simples de suas porcentagens.

Ambos mostram contagens e **cobertura**: `avaliações realizadas ÷ avaliações aplicáveis × 100`. Valores indisponíveis ou incompatíveis ficam pendentes e tornam a nota **PARCIAL**; sem avaliações, não há percentual. Sem chave segura, a concordância entre registros não é avaliada, embora os perfis continuem disponíveis.

NULL em coluna opcional não reduz a qualidade. Textos vazios não são falhas de preenchimento de NOT NULL: aparecem como observações, a menos que exista regra específica. Valores e distribuições de negócio não são validados sem regras próprias. Duas tabelas podem ter 100% de concordância e compartilhar problemas de qualidade; por isso as notas permanecem separadas.

A tela apresenta as estatísticas de cada coluna lado a lado, com diferença e denominador: contagens, nulos, distintos, vazios, mínimo, máximo, média, mediana, Q25, Q75 e desvio padrão. As métricas comparativas sobre chaves comuns continuam identificadas separadamente dos perfis de todas as linhas capturadas.

São exibidos até **cinco pares de registros** e **cinco exemplos de divergências**, com chave, coluna, valores das duas fontes e motivo. `<NULL>`, `<REGISTRO AUSENTE>`, `<COLUNA AUSENTE>` e `<VALOR INDISPONÍVEL>` têm significados diferentes; texto vazio aparece como `''`. Sem alinhamento, são mostradas até cinco linhas de cada amostra independente.

As prévias ficam somente na memória e no terminal. O callback opcional `preview_callback` da API recebe esse material separadamente; o dicionário de resultado e o histórico contêm apenas agregados. `preview_limit` aceita de 0 a 5 e tem padrão 5.

Exemplo da validação em `public.sale` e `dbo.Sale`:

```text
Resultado: compatível na amostra
Concordância entre tabelas na amostra: 100.00%
  4730/4730 posições iguais; cobertura 100.00%.
Qualidade observada — conformidade com regras: 100.00%
  18920/18920 verificações aprovadas; cobertura 100.00%.
Linhas capturadas: 946 em cada tabela.
```

Esse exemplo é amostral. `SaleType` ficou nulo nos dois lados e isso não reduziu a nota, pois a coluna permite NULL.

### Por que uma comparação antiga pode não mostrar estatísticas?

Selecionar uma comparação salva apresenta as ações antes de mostrar resultados. **Visualizar resultado histórico** lê somente o arquivo salvo e exibe **“Resultado histórico — fontes não consultadas agora”**, com nome e data. O registro antigo `tb-sales`, de 13/10/2026, contém estatísticas da primeira fonte, mas `statistics: {}` na segunda. Isso não indica ausência de dados no banco. A tela mostra os valores antigos disponíveis e identifica os demais como **não registrados nesta execução**. Percentuais não são inventados para registros incompletos ou formatos que não os registraram.

Para obter dados e indicadores atuais:

1. Escolha **4 — Consultar comparações salvas** e selecione o registro.
2. Escolha **1 — Executar nova comparação destas tabelas**.
3. Confirme as preferências de amostragem e dê um nome à nova execução.

Tanto a criação quanto a reexecução recarregam as configurações, abrem **duas conexões novas**, inclusive na mesma base, e consultam os metadados atuais. O motor realiza outro piloto, recalcula o plano e sorteia novos candidatos. Com uma chave compatível, consulta o mesmo conjunto de chaves nas duas tabelas. Todos os indicadores e estatísticas são recalculados; nenhuma amostra ou nota histórica é reutilizada.

A saída identifica cada execução por UUID e mostra início da coleta, fim do cálculo, fontes, linhas capturadas, prévias e indicadores com contagens e cobertura. Por exemplo: **4 → tb-sales → 1 → Enter** executa uma nova coleta automática; após ler o resultado, informe um nome, como `tb-sales atualizada`. Um novo registro será acrescentado, preservando o antigo. Para consultar somente o registro antigo, use **4 → tb-sales → 2**.

As conexões são encerradas após sucesso, cancelamento ou erro. Se uma conexão ou tabela não estiver disponível, a execução atual é interrompida com uma mensagem; nenhum resultado antigo é apresentado como atual. Uma prévia antiga não pode ser reconstruída somente a partir dos agregados; reexecute para visualizar registros atuais.

Os limites controlam as linhas e células solicitadas; o orçamento em bytes é uma estimativa do piloto, não uma garantia de memória máxima. A ordenação aleatória pode percorrer e ordenar a tabela inteira. A sessão de consulta usa proteções de leitura e limites de tempo conforme o driver; não existe snapshot sincronizado entre os bancos.

O histórico versionado guarda plano, consultas SQL sem seus parâmetros, contagens, métricas, diferenças e indicadores com critérios e cobertura. **Linhas e chaves sorteadas não são persistidas**. A gravação substitui o histórico atomicamente, preservando o arquivo anterior em caso de falha de serialização. Execute uma instância gravadora por vez. Registros antigos continuam legíveis, com indicação de evidência insuficiente quando necessário.

Nova amostra significa **nova coleta com novo sorteio**, podendo repetir registros de execuções anteriores. Tabelas pequenas podem produzir exatamente o mesmo conjunto. O sorteio do banco não é reproduzível entre execuções. A semente registrada apenas organiza a seleção dentro dos candidatos capturados. Compatibilidade amostral não prova igualdade integral das tabelas.

## Testes e validação

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest discover -s ../tests -v
```

Os testes cobrem o menu e a reexecução do histórico, as fórmulas dos indicadores e sua cobertura, prévias sem persistência, regras de qualidade, precisão, amostragem e contratos SQL dos cinco adaptadores. SQLite possui integração local real. A validação em servidores PostgreSQL e SQL Server usa as conexões configuradas; MySQL e Oracle precisam de servidores reais para comprovar integração completa.

Na validação deste fluxo, **88 testes passaram**. Duas execuções consecutivas somente de leitura em `public.sale` (PostgreSQL) e `dbo.Sale` (SQL Server) abriram quatro conexões novas, todas encerradas. Cada execução capturou 946 linhas por tabela, com concordância de **4.730/4.730 valores** e conformidade de **18.920/18.920 verificações**, ambas com cobertura de 100%. O histórico original foi preservado; os agregados da validação estão em [../docs/VALIDACAO_NOVAS_EXECUCOES.json](../docs/VALIDACAO_NOVAS_EXECUCOES.json) (diretório externo ao repositório). O teste SQLite com alteração de dados e metadados entre execuções confirmou a atualização do resultado. MySQL e Oracle não tiveram integração em servidor nesta validação.

A ferramenta auxiliar de auditoria também pode ser chamada diretamente:

```bash
# Somente consistência dos agregados históricos:
.venv/bin/python ../tests/validation/validate_comparisons.py

# Consulta atual somente de leitura das tabelas do histórico:
.venv/bin/python ../tests/validation/validate_comparisons.py \
  --live --sample-size 200 --output ../docs/validation-comparisons.json
```

A auditoria atual não reconstrói o estado histórico das tabelas. Seu modo alinhado pressupõe que as chaves comuns representam as mesmas entidades.

## Append manual: PostgreSQL → SQL Server

O script independente `sync_append.py` lê o `credentials.yaml` ao lado dele e usa,
por padrão, `main-db` como origem PostgreSQL e `sql-server` como destino SQL Server.
Pode ser executado de qualquer diretório. Usa as mesmas dependências do projeto.

```bash
# Valida todas as tabelas e mostra a ordem, sem gravar dados:
.venv/bin/python sync_append.py --dry-run

# Executa o append em todas as tabelas da origem:
.venv/bin/python sync_append.py

# Parâmetros opcionais:
.venv/bin/python sync_append.py --credentials /caminho/credentials.yaml \
  --source main-db --target sql-server --batch-size 1000
```

As tabelas precisam existir no destino. O script procura o mesmo schema/nome;
na ausência dele, procura um nome de tabela único, ignorando maiúsculas e
minúsculas (por exemplo, `public.product` → `dbo.Product`). As colunas também são
associadas por nome. Valida a presença de todas as colunas, a mesma chave primária
(inclusive composta) e a ordem de dependências antes da primeira inserção.
Tabelas exclusivas do destino não são copiadas; tabelas sem PK, ausentes ou
ambíguas no destino e ciclos de FKs, inclusive autorreferências, impedem a execução.
Partições PostgreSQL são lidas pela tabela pai, evitando cópia em duplicidade.

Insere somente chaves primárias ausentes: uma segunda execução pula registros já
copiados. Não atualiza nem exclui dados. Uma PK já existente é mantida mesmo que os
demais valores sejam diferentes; portanto, pressupõe que os IDs representem as
mesmas entidades nos dois bancos. Preserva valores de identidade usando
`IDENTITY_INSERT`; colunas calculadas, geradas e `rowversion` do destino são
regeneradas pelo SQL Server. Requer SELECT na origem, leitura dos catálogos,
SELECT/INSERT no destino e, para tabelas com identidade, permissão para
`IDENTITY_INSERT` (proprietário ou ALTER na tabela).

A origem é aberta em uma transação somente leitura com snapshot consistente.
Um cursor de servidor lê lotes, e as inserções são parametrizadas, por registro.
O lote limita memória, mas o commit ocorre **por tabela**: uma falha reverte toda a
tabela em andamento e encerra o processo com código 1; tabelas já concluídas
permanecem gravadas. É possível repetir o comando depois de corrigir o problema.
Execute uma instância por vez, preferencialmente em uma janela sem alterações
concorrentes no destino; tabelas grandes podem manter locks e usar bastante log.

A simulação valida metadados e dependências, sem ler/copiar os registros e sem
garantir conversões de tipos, regras de negócio ou permissões de inserção.
Incompatibilidades de tipos, outras constraints UNIQUE, FKs ou triggers podem
impedir o append real. Não cria tabelas nem faz conversão automática de tipos
especiais, como arrays/JSON/objetos Python para colunas textuais do SQL Server.

Testes locais (sem acessar os bancos configurados):

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest discover -s ../tests -p test_sync_append.py
```

## Documentação técnica

Consulte a [especificação do motor](../docs/MOTOR_DE_COMPARACAO.md) e o [guia visual em HTML](../docs/MOTOR_DE_COMPARACAO.html), que funciona sem internet. Para abrir o HTML, use o navegador ou o painel de arquivos do Codex.

Os documentos e as evidências estão em `../docs/`, fora do repositório; seus links são destinados à estrutura local. Os scripts de auditoria estão em `../tests/validation/`. Nenhum desses arquivos é incluído automaticamente nos commits da aplicação.
