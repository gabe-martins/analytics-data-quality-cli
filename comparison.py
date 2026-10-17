"""Menu e apresentação do motor; descoberta e cálculos ficam no núcleo."""

from datetime import datetime
from decimal import Decimal
import math

from cli_helpers import choose_from_list, describe
from config import COMPARISONS_PATH, load_connections, load_comparisons, save_comparison
from database import connect
from comparison_engine import execute_comparison
from quality import metadata_family, name_map, validate_saved_result
from sampling import SamplingOptions
from tables import select_table, list_tables, qualified_name

STATUS_LABELS = {
    'compatible_in_sample': 'compatível na amostra',
    'difference_observed': 'diferença observada',
    'profile_only': 'somente perfil', 'inconclusive': 'inconclusivo',
    'descriptive': 'descritivo', 'not_applicable': 'não aplicável',
}

EXPLANATIONS = {
    'population estimates, proportion planning target and pilot numeric variability': 'estimativas de volume, referência para proporções e variabilidade numérica do piloto',
    'both pilot reads exhausted their tables': 'as duas leituras piloto esgotaram suas tabelas',
    'explicit row budget': 'limite de linhas informado',
    'limited by row/cell budget or pilot byte estimate': 'reduzido pelo orçamento de linhas, células ou tamanho estimado',
    'common matched rows': 'linhas com chaves presentes nas duas tabelas',
    'independent profiles; descriptive differences only': 'perfis independentes; diferenças apenas descritivas',
    'A sample cannot establish equality of entire tables.': 'A amostra não comprova igualdade integral das tabelas.',
    'No synchronized snapshot across databases; concurrent changes can affect results.': 'As leituras não têm um snapshot sincronizado; alterações concorrentes podem afetar o resultado.',
    'Random ordering may scan/sort the table; sample limits do not bound server work.': 'O sorteio pode percorrer e ordenar a tabela; o limite amostral não limita o trabalho do servidor.',
    'Catalog row counts are estimates and are not used as proof of missing data.': 'Os volumes do catálogo são estimativas, sem comprovar ausência de registros.',
    'No row alignment: metric and observed-value differences are descriptive only.': 'Sem alinhamento de registros: diferenças de métricas e valores observados são apenas descritivas.',
    'Empty sample: data metrics unavailable; no equality conclusion.': 'Amostra vazia: métricas indisponíveis e nenhuma conclusão de igualdade.',
    'all_null_in_sample': 'todos os valores da amostra são nulos',
    'not_null_violation': 'nulos em campo declarado obrigatório',
    'blank_count': 'textos vazios ou compostos apenas de espaços',
    'unavailable_count': 'valores indisponíveis para comparação',
    'unsupported_count': 'valores não suportados',
    'invalid_numeric_count': 'valores numéricos inválidos',
    'non_finite_count': 'valores numéricos não finitos',
    'invalid_primary_key_in_sample': 'chave primária inválida na amostra',
    'compatible_native_types': 'tipos nativos compatíveis',
    'column_presence': 'presença da coluna', 'type_family': 'família de tipo',
    'nullable': 'permite nulos', 'primary_key': 'chave primária',
    'length': 'comprimento', 'precision': 'precisão', 'scale': 'escala',
    'observation': 'observação', 'violation': 'violação', 'inconclusive': 'inconclusivo',
}


def _explain(text):
    return '; '.join(EXPLANATIONS.get(part, part) for part in text.split('; '))


def _choose_connection(connections):
    names = list(connections)
    print('\nConexão da tabela:')
    for index, name in enumerate(names, 1):
        print(f'{index}. {name} ({describe(connections[name])})')
    print(f'{len(names) + 1}. Voltar')
    index = choose_from_list(range(len(names) + 1))
    return None if index == len(names) else names[index]


def _sampling_preferences():
    while True:
        choice = input('\nAmostragem: Enter = automática; p = somente perfil; c = configurar limites: ').strip().lower()
        if choice in ('', 'p'):
            return ('auto' if not choice else 'independent_random'), SamplingOptions()
        if choice != 'c':
            print('Escolha Enter, p ou c.')
            continue
        try:
            maximum = int(input('Máximo de linhas [1000]: ').strip() or '1000')
            cells = int(input('Máximo de células por amostra [100000]: ').strip() or '100000')
            mib = int(input('Orçamento estimado por amostra em MiB [16]: ').strip() or '16')
            return 'auto', SamplingOptions(max_rows=maximum, max_cells=cells, max_sample_bytes=mib * 1024 * 1024)
        except ValueError as error:
            print(f'Limites inválidos: {error}')


def compare_table_statistics():
    connections = load_connections()
    if not connections:
        print('\nCadastre pelo menos uma conexão antes de comparar.')
        return
    selected, opened, identities = [], [], set()
    try:
        while len(selected) < 2:
            print(f'\nSelecione a tabela {len(selected) + 1} de 2.')
            name = _choose_connection(connections)
            if name is None:
                return
            conn = connect(connections[name])
            if conn is None:
                print('Execução atual interrompida: não foi possível abrir uma conexão nova.')
                return
            opened.append(conn)
            table = select_table(conn, connections[name])
            if table is None:
                return
            schema, table_name = table
            identity = (name, schema, table_name)
            if identity in identities:
                print('Selecione uma tabela diferente da primeira.')
                conn.close()
                opened.pop()
                continue
            identities.add(identity)
            selected.append({'connection': name, 'creds': connections[name], 'conn': conn,
                             'schema': schema, 'table': table_name})
        _execute_selected_and_save(selected)
    except (EOFError, KeyboardInterrupt):
        print('\nComparação cancelada.')
    except Exception as error:
        print(f'Não foi possível comparar: {type(error).__name__}.')
        if isinstance(error, ValueError):
            print(str(error))
    finally:
        for conn in opened:
            try:
                conn.close()
            except Exception:
                pass


def _execute_selected_and_save(selected):
    """Caminho comum de execução atual; nunca recebe resultados ou amostras salvos."""
    mode, options = _sampling_preferences()
    print('\nNova execução — consultando as fontes agora, com conexões novas.')
    print('Coletando metadados e realizando um novo sorteio de amostras das duas tabelas...')
    print('O sorteio pode repetir registros de execuções anteriores, especialmente em tabelas pequenas.')
    previews = []
    result = execute_comparison(selected, mode=mode, options=options,
                                preview_callback=previews.append, preview_limit=5)
    print_comparison_result(result)
    for preview in previews:
        print_preview(preview)
    label = input('\nNome da comparação (Enter = data e hora): ').strip()
    result['name'] = label or f"Comparação {result['created_at']}"
    save_comparison(_yaml_safe(result))
    print(f"Comparação '{result['name']}' salva em {COMPARISONS_PATH}.")


def repeat_saved_comparison(saved):
    definitions = saved.get('sources') or [saved.get('first', {}), saved.get('second', {})]
    if len(definitions) != 2:
        print('O histórico precisa identificar exatamente duas tabelas; use a opção Comparar duas tabelas.')
        return
    connections = load_connections()
    selected, opened = [], []
    try:
        for definition in definitions:
            name = definition.get('connection')
            if name not in connections:
                print(f'Conexão salva não encontrada: {name}. Cadastre-a antes de repetir a comparação.')
                return
            conn = connect(connections[name])
            if conn is None:
                print('Execução atual interrompida: não foi possível abrir uma conexão nova. O histórico anterior foi preservado.')
                return
            opened.append(conn)
            candidates = list_tables(conn, connections[name]['type'])
            if 'table_name' in definition and 'schema' in definition:
                matches = [table for table in candidates if table == (definition['schema'], definition['table_name'])]
            else:
                matches = [table for table in candidates if qualified_name(*table) == definition.get('table')]
            if len(matches) != 1:
                print(f"Tabela ausente ou ambígua: {definition.get('table')}. Use a opção Comparar duas tabelas para selecionar novamente.")
                return
            schema, table = matches[0]
            selected.append({'connection': name, 'creds': connections[name], 'conn': conn,
                             'schema': schema, 'table': table})
        print('\nSerá feita uma nova leitura. O registro histórico anterior será preservado.')
        _execute_selected_and_save(selected)
    except (EOFError, KeyboardInterrupt):
        print('\nNova comparação cancelada. O histórico anterior foi preservado.')
    except Exception as error:
        print(f'Não foi possível executar a nova comparação: {type(error).__name__}. O histórico anterior foi preservado.')
        if isinstance(error, ValueError):
            print(str(error))
    finally:
        for conn in opened:
            try:
                conn.close()
            except Exception:
                pass


def _yaml_safe(value):
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_yaml_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _display(value):
    if value is None:
        return '—'
    if isinstance(value, (Decimal, float)) and value == 0:
        return '0'
    text = str(value)
    return format(value, '.10g') if isinstance(value, (Decimal, float)) and len(text) > 24 else text


def _format_type(info):
    declared = info.get('type', '')
    if '(' in declared:
        return declared
    family = metadata_family(info)
    if info.get('precision') is not None and family == 'decimal':
        scale = f",{info['scale']}" if info.get('scale') is not None else ''
        return f"{declared}({info['precision']}{scale})"
    if info.get('length') is not None and family in {'text', 'binary'}:
        return f"{declared}({info['length']})"
    return declared


def compare_schema(sources):
    maps = [name_map(source['columns']) for source in sources]
    print('\nMetadados — valores na ordem das tabelas selecionadas:')
    print('Coluna | Tipos declarados | Aceita NULL | PK')
    for name in sorted(set().union(*(mapping.keys() for mapping in maps))):
        infos = [source['columns'].get(mapping.get(name), {}) for source, mapping in zip(sources, maps)]
        types = ' / '.join(_format_type(info) if info else 'ausente' for info in infos)
        nullable = ' / '.join('—' if not info else 'sim' if info.get('nullable') else 'não' for info in infos)
        primary = ' / '.join('sim' if info.get('primary_key') else 'não' for info in infos)
        print(f'{name} | {types} | {nullable} | {primary}')


def print_comparison(sources):
    for index, source in enumerate(sources, 1):
        estimate = source.get('estimated_rows')
        print(f"{index}. {source['connection']} — {source['table']}: {source['sample_size']} linhas capturadas; "
              + (f'estimativa de catálogo: {estimate}' if estimate is not None else 'volume estimado indisponível'))
    compare_schema(sources)
    if len(sources) == 2:
        _print_statistics_side_by_side(sources)
        return
    for index, source in enumerate(sources, 1):
        print(f'\nPerfil da amostra da tabela {index}:')
        print('Coluna | Nulos/linhas | Distintos/observados | Vazios | Mín | Média | Mediana | Q25 | Q75 | Desvio | Máx')
        for name, m in source['metrics'].items():
            distinct_n = m.get('distinct_denominator', m['sample_count'] - m['null_count'])
            numeric = ' | '.join(_display(m.get(field)) for field in ('min', 'mean', 'median', 'q25', 'q75', 'stddev', 'max'))
            print(f"{name} | {m['null_count']}/{m['sample_count']} | {m['distinct_count']}/{distinct_n} | {m.get('blank_count', '—')} | {numeric}")


def _print_statistics_side_by_side(sources):
    maps = [name_map(source['metrics']) for source in sources]
    fields = [('sample_count', 'Linhas capturadas'), ('null_count', 'Nulos'), ('null_rate', 'Taxa de nulos'),
              ('distinct_count', 'Distintos observados'), ('distinct_rate', 'Taxa distinta observada'),
              ('blank_count', 'Textos vazios'), ('min', 'Mínimo'), ('max', 'Máximo'), ('mean', 'Média'),
              ('median', 'Mediana'), ('q25', 'Q25'), ('q75', 'Q75'), ('stddev', 'Desvio padrão')]
    print('\nEstatísticas adquiridas lado a lado — incluem todas as linhas capturadas em cada tabela:')
    print('Coluna | Estatística | Tabela 1 | Tabela 2 | Δ (2 − 1) | Denominadores 1/2')
    for name in sorted(maps[0].keys() | maps[1].keys()):
        metrics = [source['metrics'].get(mapping.get(name), {}) for source, mapping in zip(sources, maps)]
        for field, label in fields:
            values = [metric.get(field) for metric in metrics]
            if field in {'min', 'max', 'mean', 'median', 'q25', 'q75', 'stddev'} and all(v is None for v in values):
                continue
            try:
                delta = Decimal(str(values[1])) - Decimal(str(values[0])) if all(v is not None for v in values) else None
            except ArithmeticError:
                delta = None
            denominator_field = ('distinct_denominator' if field in {'distinct_count', 'distinct_rate'} else
                                 'numeric_count' if field in {'min', 'max', 'mean', 'median', 'q25', 'q75', 'stddev'} else
                                 'blank_denominator' if field == 'blank_count' else 'sample_count')
            denominators = '/'.join(str(m.get(denominator_field, m.get('sample_count', '—'))) if m else '—' for m in metrics)
            display = [_display(v) if m else '<COLUNA AUSENTE>' for v, m in zip(values, metrics)]
            print(f'{name} | {label} | {display[0]} | {display[1]} | {_display(delta)} | {denominators}')


def _percentage(value):
    return f'{Decimal(str(value)):.2f}%' if value is not None else 'não avaliado'


def _print_score(label, indicator, noun):
    if indicator['percentage'] is None:
        print(f'{label}: não avaliado — nenhuma avaliação disponível.')
        if indicator.get('total'):
            print(f"  Cobertura: {_percentage(indicator['coverage_percentage'])}; {indicator['pending']} avaliações pendentes.")
        return
    partial = ' — PARCIAL, somente avaliações disponíveis' if indicator['status'] == 'partial' else ''
    print(f"{label}: {_percentage(indicator['percentage'])}{partial}")
    print(f"  {indicator['passed']}/{indicator['evaluated']} {noun}; {indicator['failed']} reprovações; "
          f"{indicator['pending']} pendentes. Cobertura: {_percentage(indicator['coverage_percentage'])} "
          f"({indicator['evaluated']}/{indicator['total']}).")


def print_indicators(result):
    indicators = result.get('indicators')
    if not indicators:
        print('Percentuais não registrados nesta execução. Refaça a comparação para obter os indicadores atuais.')
        return
    agreement = indicators['agreement']
    if agreement.get('reason') == 'no_safe_key_alignment':
        print('Concordância entre registros não avaliada: não há alinhamento seguro por chave.')
    else:
        _print_score('Concordância entre tabelas na amostra', agreement, 'posições iguais')
        print(f"  Valores diferentes: {agreement['different_cells']}; posições de registros/colunas ausentes: {agreement['missing_positions']}.")
    quality = indicators['quality']
    _print_score('Qualidade observada — conformidade com regras', quality['overall'], 'verificações aprovadas')
    for source in quality['sources']:
        _print_score(f"Qualidade da tabela {source['source']}", source, 'verificações aprovadas')
    print('Critérios: campos obrigatórios, validade dos tipos suportados, finitude numérica e integridade observada das chaves.')
    print('NULL permitido e textos vazios sem regra específica não reduzem a nota. As notas não validam regras de negócio não configuradas.')


def _preview_value(cell):
    labels = {'null': '<NULL>', 'record_missing': '<REGISTRO AUSENTE>',
              'column_missing': '<COLUNA AUSENTE>', 'unavailable': '<VALOR INDISPONÍVEL>'}
    if cell['state'] in labels:
        return labels[cell['state']]
    value = cell['value']
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = '0x' + bytes(value).hex()
    elif isinstance(value, str):
        text = repr(value)
    else:
        text = str(value)
    return text if len(text) <= 160 else text[:160] + '… [prévia abreviada]'


def print_preview(preview):
    print('\nPrévia dos dados — somente nesta tela, sem gravação no histórico:')
    if preview['mode'] == 'independent_random':
        for source in preview['sources']:
            print(f"Tabela {source['source']}: amostra independente, sem correspondência de registros.")
            for row in source['rows']:
                print(' | '.join(f'{column}={_preview_value(cell)}' for column, cell in row.items()))
        return
    print('Até cinco pares com a mesma chave:')
    if not preview['pairs']:
        print('Nenhum par de registros disponível.')
    for pair in preview['pairs']:
        print(f"Chave: {pair['key']}")
        print('Coluna | Tabela 1 | Tabela 2')
        for cell in pair['cells']:
            print(f"{cell['column']} | {_preview_value(cell['reference'])} | {_preview_value(cell['target'])}")
    print('Até cinco exemplos de divergências ou avaliações pendentes:')
    if not preview['differences']:
        print('Nenhuma divergência observada.')
    reasons = {'registro_ausente': 'registro ausente em uma fonte', 'coluna_ausente': 'coluna ausente em uma fonte',
               'registro_indisponivel_nas_duas': 'registro indisponível nas duas leituras',
               'valor_indisponivel': 'valor indisponível', 'tipos_incompativeis': 'tipos incompatíveis',
               'valor_nao_comparavel': 'valor não comparável', 'valor_diferente': 'valor diferente'}
    for item in preview['differences']:
        print(f"Chave: {item['key']} | {item['column']} | {_preview_value(item['reference'])} | "
              f"{_preview_value(item['target'])} | {reasons[item['reason']]}")


def print_comparison_result(result):
    if result.get('execution_id'):
        print(f"\nIdentificação da execução: {result['execution_id']}")
        print(f"Início da coleta: {result['started_at']} | Fim do cálculo: {result['finished_at']}")
    status = result.get('summary', {}).get('status', 'inconclusive')
    print('\nResultado: ' + STATUS_LABELS.get(status, status))
    print_indicators(result)
    plan = result.get('sampling_plan', {})
    if plan:
        mode = 'mesmas chaves nas duas tabelas' if plan['mode'] == 'matched_keys' else 'perfis independentes'
        print(f"Amostragem: {mode}; limite final: {plan['target_rows']}.")
        print(f"Piloto: {plan.get('pilot_observed_rows', 'não registrado')}; etapas: {len(plan.get('rounds', []))}.")
        if plan.get('strategy_reason'):
            print('Critério de tamanho: ' + _explain(plan['strategy_reason']))
        if plan.get('key_columns'):
            print('Chave de comparação: ' + ', '.join(plan['key_columns']))
            print('Pressuposto: as chaves representam as mesmas entidades nas tabelas selecionadas.')
    print_comparison(result['sources'])
    for finding in result.get('schema_findings', []):
        label = 'Observação de compatibilidade' if finding.get('severity') == 'observation' else 'Diferença de metadados'
        print(f"{label}: {finding['column']} — {_explain(finding['kind'])}: {finding['reference']} / {finding['target']}")
    for finding in result.get('quality_findings', []):
        print(f"Qualidade — tabela {finding['source']}, {finding['column']}: {_explain(finding['kind'])}, {finding['count']} linhas ({_explain(finding['severity'])}).")
    for pair in result.get('row_comparisons', []):
        print(f"\nValores: {pair.get('common_keys', pair['matched_keys'])} chaves encontradas nas duas tabelas.")
        print(f"Ausentes na tabela 1: {pair.get('missing_in_reference', 'não avaliado')}; "
              f"ausentes na tabela 2: {pair.get('missing_in_target', pair.get('missing_keys', '—'))}.")
        print(f"Linhas com valores diferentes: {pair['different_rows']}.")
        for column, count in pair.get('different_values', {}).items():
            unknown = pair.get('incomparable_values', {}).get(column, 0)
            print(f'  {column}: {count} valores diferentes; {unknown} não comparáveis.')
    if result.get('metric_comparisons'):
        print('\nDiferenças de métricas (tabela 2 menos tabela 1):')
        print('Coluna | Linhas 1/2 | Denominadores nulos/distintos 1/2 | Δ nulos | Δ média | Δ mediana | Δ desvio | Estado')
        for metric in result['metric_comparisons']:
            counts = metric['sample_counts']
            denominators = metric.get('denominators', {})
            den = ' / '.join(f"{denominators.get(role, {}).get('null_rate', 0)}/{denominators.get(role, {}).get('distinct_rate', 0)}" for role in ('reference', 'target'))
            delta = ' | '.join(_display(metric['deltas'].get(field)) for field in ('null_rate', 'mean', 'median', 'stddev'))
            print(f"{metric['column']} | {counts['reference']}/{counts['target']} | {den} | {delta} | {STATUS_LABELS.get(metric['status'], metric['status'])}")
        print('Escopo das métricas comparadas: ' + _explain(plan.get('metric_scope', 'amostras observadas')))
    if result.get('value_distributions'):
        print('\nSobreposição descritiva de valores observados (não representa correspondência de linhas):')
        for item in result['value_distributions']:
            print(f"{item['column']}: {item['common_occurrences']} ocorrências em comum; "
                  f"observadas {item['reference_observed']}/{item['target_observed']}.")
    print(f"Consultas registradas: {len(result.get('query_log', []))}; parâmetros e linhas brutas não são persistidos.")
    print('Conclusão restrita às amostras; não comprova igualdade integral das tabelas.')
    for warning in result.get('warnings', []):
        print('Nota: ' + _explain(warning))


def print_comparison_rows(first_stats, second_stats):
    shared = [name for name in first_stats if name in second_stats]
    if not shared:
        print('Este histórico não registrou pares de estatísticas numéricas para comparar. Isso não indica ausência de dados nas tabelas.')
    for name in shared:
        print(f'{name}: {first_stats[name]} / {second_stats[name]}')


def _print_saved_comparison(result):
    print('\nResultado histórico — fontes não consultadas agora')
    print(f"\n{result['name']} ({result['created_at']})")
    if 'sources' in result:
        print_comparison_result(result)
        if validate_saved_result(result)['issues']:
            print('Histórico inconclusivo: os agregados registrados são insuficientes ou inconsistentes. Uma nova execução pode atualizar a avaliação.')
        print('A prévia de registros não é armazenada. Execute uma nova comparação para visualizar os dados atuais.')
        return
    print('Esta é uma execução antiga. Abrir o histórico não consulta o conteúdo atual das tabelas.')
    for side, label, ordinal in (('first', 'Tabela 1', 'primeira'), ('second', 'Tabela 2', 'segunda')):
        source = result.get(side, {})
        print(f"\n{label}: {source.get('connection', 'não registrada')} — {source.get('table', 'não registrada')}")
        statistics = source.get('statistics') or {}
        if not statistics:
            print(f'Esta comparação foi salva sem as estatísticas da {ordinal} tabela. Isso não indica ausência de dados na base.')
            print('Estatísticas: não registradas nesta execução.')
        else:
            print('Coluna | Mínimo registrado | Média registrada | Máximo registrado')
            for name, values in statistics.items():
                if isinstance(values, (tuple, list)) and len(values) == 3:
                    print(f"{name} | {_display(values[0])} | {_display(values[1])} | {_display(values[2])}")
                else:
                    print(f'{name}: estatísticas incompletas neste registro.')
    print('\nHistórico inconclusivo: esta execução não registrou evidências suficientes sobre amostra, chaves e método.')
    print('Concordância e qualidade: não avaliadas neste histórico. Execute uma nova comparação destas tabelas para obter dados e percentuais atuais.')


def view_saved_comparison():
    try:
        comparisons = load_comparisons()
        if not comparisons:
            print('\nNenhuma comparação salva.')
            return
        for index, item in enumerate(comparisons, 1):
            print(f"{index}. {item['name']} ({item['created_at']})")
        print(f'{len(comparisons) + 1}. Voltar')
        index = choose_from_list(range(len(comparisons) + 1))
        if index < len(comparisons):
            print('\n1. Executar nova comparação destas tabelas')
            print('2. Visualizar resultado histórico — fontes não consultadas agora')
            print('3. Voltar')
            action = choose_from_list(range(3))
            if action == 0:
                repeat_saved_comparison(comparisons[index])
            elif action == 1:
                _print_saved_comparison(comparisons[index])
    except (EOFError, KeyboardInterrupt):
        print('\nConsulta cancelada.')
    except Exception as error:
        print(f'Não foi possível ler o histórico: {type(error).__name__}.')
