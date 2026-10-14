# Analytics Data Quality CLI

Uma ferramenta de terminal para consultar tabelas de bancos de dados e comparar estatísticas numéricas básicas entre duas fontes.

## Funcionalidades

- Conectar a PostgreSQL, MySQL, SQLite, SQL Server ou Oracle.
- Salvar conexões para reutilizá-las.
- Escolher uma tabela e visualizar até 10 linhas aleatórias.
- Ver mínimo, média e máximo das colunas numéricas encontradas na amostra.
- Comparar duas tabelas e salvar o resultado para consulta posterior.

As estatísticas são calculadas sobre amostras aleatórias independentes de até 10 linhas. Use os resultados como uma visão rápida dos dados, não como uma análise completa da tabela.

## Instalação e execução

Requer Python 3 e os drivers dos bancos que serão acessados.

```bash
pip install -r requirements.txt
python main.py
```

No menu, escolha uma conexão salva, cadastre uma nova conexão ou compare tabelas de duas conexões salvas. As comparações anteriores podem ser abertas pela opção **View saved comparisons**.

As conexões e os resultados são gravados localmente em `credentials.yaml` e `comparisons.yaml`, respectivamente, no diretório em que o programa é executado.

## Documentação técnica

Consulte [docs/TECHNICAL.md](docs/TECHNICAL.md) para detalhes sobre módulos, fluxo de execução, consultas, arquivos locais e limitações da comparação.
