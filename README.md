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

## Documentação técnica

Consulte [TECHNICAL.md](TECHNICAL.md) para detalhes sobre módulos, fluxo de execução, consultas, arquivos locais e limitações da comparação.
