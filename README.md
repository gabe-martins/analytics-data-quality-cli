# Analytics Data Quality CLI

Uma ferramenta de terminal para consultar tabelas e comparar metadados e sinais de qualidade de dados entre duas ou mais tabelas.

## Funcionalidades

- Conectar a PostgreSQL, MySQL, SQLite, SQL Server ou Oracle.
- Salvar conexões para reutilizá-las.
- Escolher uma tabela e visualizar linhas aleatórias com um perfil de qualidade.
- Comparar duas ou mais tabelas, inclusive em bancos diferentes.
- Comparar presença de colunas, famílias de tipos, nulabilidade e chaves primárias.
- Comparar taxa de nulos, taxa de valores distintos e mínimo/média/máximo numéricos na amostra.
- Salvar e consultar comparações anteriores.

## Amostragem e interpretação

Para uma comparação, o programa consulta estimativas de quantidade de linhas nos catálogos de PostgreSQL, MySQL, SQL Server e Oracle. O SQLite não oferece essa estimativa no catálogo usado pela ferramenta. A partir da menor estimativa disponível, o motor define um limite comum de amostra: aproximadamente `10 × √N`, limitado a 200 linhas. Se não houver estimativas, usa até 100 linhas. Todas as tabelas da rodada recebem o mesmo limite e são ordenadas aleatoriamente pelo mecanismo do respectivo banco; tabelas menores podem retornar menos linhas.

O tamanho amostral e a estratégia são comuns ao conjunto comparado, mas os registros são sorteados independentemente em cada tabela. Portanto, isso não alinha as mesmas entidades entre bancos. As taxas e estatísticas descrevem apenas a amostra; estimativas de linhas podem estar desatualizadas. A ordenação aleatória pode ser custosa em tabelas grandes. Use os resultados como triagem de qualidade, não como certificação ou análise completa da tabela.

Comparações salvas mantêm metadados e indicadores agregados. As linhas de amostra não são gravadas.

## Instalação e execução

Requer Python 3 e os drivers dos bancos que serão acessados.

```bash
pip install -r requirements.txt
python main.py
```

No menu, escolha uma conexão salva, cadastre uma nova conexão ou abra **Compare table statistics**. Escolha uma conexão e uma tabela por vez e responda se deseja adicionar mais tabelas. Encerre a seleção depois de escolher pelo menos duas tabelas. As comparações anteriores podem ser abertas pela opção **View saved comparisons**.

As conexões e os resultados são gravados localmente em `credentials.yaml` e `comparisons.yaml`, respectivamente, no diretório em que o programa é executado.

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
.venv/bin/python -m unittest test_sync_append.py
```

## Documentação técnica

Consulte [TECHNICAL.md](TECHNICAL.md) para detalhes sobre módulos, fluxo de execução, consultas, arquivos locais e limitações da comparação.
