from __future__ import annotations

import re

from sentinel import settings
from sentinel.detector import (
    METRIC_CPU,
    METRIC_DISK,
    METRIC_IO,
    METRIC_NETWORK,
    METRIC_RAM,
)
from sentinel.incidents import METRIC_APP_FAILURE, METRIC_ORPHAN_TREE


# ---------------------------------------------------------------------------
# O catalogo curado: o que o Sentinel sabe sem perguntar a ninguem
# ---------------------------------------------------------------------------
# Base OFFLINE de tutoriais, usada como camada 3 da `.sentinel/kb.db` (ver
# `kbstore`) e como fallback absoluto quando nao ha motor nenhum. Tambem e o
# pontape de qualquer resposta gerada: o modelo local parte daqui e ajusta ao
# que foi medido.
#
# Cada opcao tem cinco campos obrigatorios, e eles sao a diferenca entre um
# tutorial que convence e uma pagina de suporte:
#
#   title  — acao, no imperativo, com o alvo nomeado
#   why    — o MECANISMO: por que isto mexe no problema, e nao "vale tentar"
#   steps  — o caminho concreto, um comando por linha quando cabe
#   proof  — como VOCE sabe que funcionou, no toque, sem reler log
#   risk   — o que doi, e se da pra desfazer
#
# Proibido por regra de redacao (e coberto por teste): "geralmente", "pode
# ser", "recomendamos", e passo que so abre uma janela sem dizer o que mudar
# ali. Nada de frase que sirva pra qualquer maquina: os tokens {proc}, {pid},
# {cpu}, {value} sao preenchidos com o numero que o evento mediu.

_TOKEN = re.compile(r"\{([a-z_]+)\}")


def _opt(
    title: str,
    steps: list[str],
    *,
    why: str,
    proof: str,
    risk: str,
    reversible: bool = True,
    action: dict | None = None,
) -> dict:
    option = {
        "title": title,
        "why": why,
        "steps": steps,
        "proof": proof,
        "risk": risk,
        "reversible": reversible,
    }
    if action is not None:
        option["action"] = action
    return option


# `kill_top_process` nao carrega PID: o alvo vem do evento (top_processes) e
# o tutor resolve o pid real na hora de oferecer a execugao, com confirmacao.
_KILL_TOP = {"type": "kill_top_process"}
_OPEN_TASKMGR = {"type": "open_settings", "target": "taskmgr"}
_OPEN_STORAGE = {"type": "open_settings", "target": "storage"}


_OPTIONS: dict[str, list[dict]] = {
    METRIC_CPU: [
        _opt(
            "Encerrar o {proc} que esta segurando a CPU",
            [
                "O evento mede {proc} (pid {pid}) em {cpu}% sustentado por "
                "{span}s — nao e pico de abrir janela, e trabalho continuo.",
                "Rode 'sentinel kill {pid}': o Sentinel mostra a arvore, "
                "confirma com voce e recusa nucleo do Windows.",
                "Sem psutil ou preferindo a tecla, Ctrl+Shift+Esc > coluna "
                "CPU > botao direito > Finalizar tarefa.",
            ],
            why="Enquanto {proc} ocupou o nucleo, todo clique seu ficou na "
                "fila do escalonador; o atraso que voce sente e essa fila, "
                "nao a maquina sendo lenta. Encerrar tira o processo da fila "
                "no instante seguinte — o Windows da prioridade a quem estava "
                "esperando, e os {value}% voltam pro lugar sem voce reiniciar "
                "nada.",
            proof="Mexa o mouse e clique em qualquer janela: a resposta volta "
                "a ser imediata, e 'sentinel status' mostra CPU abaixo de "
                "{threshold}% no batimento seguinte.",
            risk="Voce perde o trabalho nao salvo daquele processo. Apps do "
                "Windows reabrem sozinhos quando necessario; nada aqui e "
                "permanente.",
        ),
        _opt(
            "Parar o indexador ou a varredura que rodou na sua hora de uso",
            [
                "Veja se o topo e SearchIndexer.exe, MsMpEng.exe, "
                "TrustedInstaller ou TiWorker: eles sobem sozinhos e comem "
                "nucleo inteiro.",
                "Adie a tarefa pro periodo ocioso no proprio programa "
                "(Windows Security > Protecao antiviral > Configuracoes > "
                "Agendamento de verificacao).",
                "Se quiser so terminar o que comecou, aguarde a barra do "
                "indexador fechar; nao mate esses processos por PID.",
            ],
            why="Essas tarefas sao projetadas pra consumir todos os nucleos "
                "disponiveis 'porque a maquina esta ociosa'. Quando ela nao "
                "esta, o resultado e exatamente o {value}% que o evento "
                "registrou: a tarefa nao sabe que voce chegou. Adiar o "
                "agendamento remove a causa, e nao o sintoma.",
            proof="A CPU cai quando a varredura acaba, e nao volta a subir "
                "no mesmo horario dos proximos dias.",
            risk="Buscar arquivos e verificar virus ficam mais devagar ate a "
                "proxima janela ociosa. Totalmente reversivel.",
            reversible=True,
        ),
        _opt(
            "Cortar o que sobe no boot e nunca mais sai",
            [
                "Ctrl+Shift+Esc > aba 'Aplicativos iniciaveis'.",
                "Desabilite o que voce nao usa todo inicio de dia (launcher "
                "de jogo, suite de criacao, cliente de impressora).",
                "Reinicie e rode 'sentinel status' nos dez primeiros "
                "minutos: o pico de boot deve cair.",
            ],
            why="Cada residente do boot compete por nucleo nos primeiros "
                "minutos, quando o Windows ja esta indexando e atualizando. "
                "O {span}s sustained que o Sentinel viu e o efeito somado "
                "disso. Menos processos no inicio e a unica forma de baixar "
                "o pico sem esperar ele acontecer.",
            proof="O boot fica visivelmente mais rapido e nenhuma anomalia "
                "de CPU aparece na primeira meia hora do dia.",
            risk="Algum programa deixa de ficar disponivel ate voce abri-lo. "
                "Reverter e reabilitar a linha na mesma aba.",
            reversible=True,
        ),
    ],
    METRIC_RAM: [
        _opt(
            "Liberar os {rss} MB que o {proc} esta segurando",
            [
                "O evento mede {proc} (pid {pid}) com {rss} MB de RSS e "
                "{value}% de RAM do sistema.",
                "Se e navegador: feche as abas presas (as mais antigas, e as "
                "com audio mudo que voce esqueceu abertas).",
                "Se travou e nao libera, 'sentinel kill {pid}' fecha o "
                "processo inteiro — o Sentinel confirma antes.",
            ],
            why="RAM em {value}% significa que o Windows ja acabou de "
                "esticar o que tinha e comecou a mover pagina pro arquivo "
                "de paginacao: o custo que voce paga nao e 'falta de "
                "memoria', e o tempo de leitura/escrita desse arquivo. "
                "Liberar o RSS do maior ocupante devolve o trabalho de "
                "paginacao ao regime normal na hora.",
            proof="O clique que hoje demora volta a ser imediato e "
                "'sentinel status' mostra RAM abaixo de {threshold}% dentro "
                "de um batimento.",
            risk="Voce perde o estado nao salvo do {proc}. Navegador reabre "
                "as sessoes; editor nao.",
        ),
        _opt(
            "Confirmar vazamento antes de culpar o app inteiro",
            [
                "Reabra o {proc} do zero e rode 'sentinel status' tres vezes "
                "em dez minutos.",
                "Se o RSS do mesmo pid so sobe e nunca cai depois de fechar "
                "tudo, e leak — nao uso legitimo.",
                "Procure atualizacao do proprio app, e registre o "
                "fingerprint igual em 'sentinel events' como prova.",
            ],
            why="Uso legitimo oscila: abre, trabalha, solta. Vazamento so "
                "sobe. Distinguir os dois decide a agao — no primeiro caso "
                "voce fecha abas, no segundo nada que voce fizer segura o "
                "crescimento, e a unica saida e atualizar ou trocar o app.",
            proof="Depois de atualizar, a curva de RSS volta a cair quando "
                "voce ocioso; o Sentinel para de registrar a mesma "
                "anomalia.",
            risk="Nenhum: este passo so mede. Ele evita o reboot inutil.",
            reversible=True,
        ),
        _opt(
            "Reduzir o que mora na bandeja sem voce pedir",
            [
                "Clique na seta da bandeja e feche o que nao esta em uso "
                "agora (launcher, suite de criacao, sincronizador de "
                "arquivo).",
                "Em cada um, desmarque 'iniciar com o Windows'.",
                "Confira em 'sentinel status' quantos MB a menos o total "
                "mostra.",
            ],
            why="Cada residente de bandeja segura dezenas ou centenas de MB "
                "de working set mesmo ocioso, porque nunca foi projetado pra "
                "ser dispensado. Com {value}% do total em uso, e o working "
                "set ocioso que decide se o app ativo vai caber ou vai "
                "paginar.",
            proof="O numero de RAM cai assim que voce fecha, e o app que "
                "voce abriu de verdade para de travar.",
            risk="Algum atalho que voce usava deixa de existir ate abrir o "
                "programa de novo.",
            reversible=True,
        ),
    ],
    METRIC_DISK: [
        _opt(
            "Liberar espaco no volume que esta em {value}%",
            [
                "Configuracoes > Sistema > Armazenamento: o Windows lista o "
                "que ocupa, por categoria.",
                "Rode 'cleanmgr' e marque 'Arquivos de otimizacao de "
                "armazenamento' e 'Instalacoes anteriores do Windows'.",
                "Esvazie a Lixeira por ultimo — ela so esvazia de verdade "
                "depois que voce apaga o que nao quer.",
            ],
            why="Volume acima de {threshold}% nao e so aperto: o NTFS passa "
                "a fragmentar e o Windows nao consegue mais alocar arquivo "
                "de paginacao nem checkpoint de registro. E por isso que "
                "disco cheio deixa a maquina inteira lenta antes de qualquer "
                "arquivo faltar. Liberar espaco devolve o espaco de alocacao "
                "contiguo — e aqui matar processo nao faz nada, pois o que "
                "ocupa e arquivo, nao RAM.",
            proof="'sentinel status' mostra o volume abaixo de {threshold}% "
                "e as gravacoes que travavam passam na primeira tentativa.",
            risk="Voce perde a capacidade de reverter update ('Instalacoes "
                "anteriores do Windows') e o que estava na Lixeira.",
            reversible=False,
        ),
        _opt(
            "Mover o dado grande que esta na particao errada",
            [
                "Identifique pasta de midia, download ou imagem de maquina "
                "no volume cheio.",
                "Mova pra outro disco ou armazenamento externo; apague a "
                "copia antiga so depois de conferir o tamanho.",
                "Rode 'sentinel status' pra ver o percentual novo.",
            ],
            why="O que costuma encher o volume de sistema nao e o Windows, e "
                "arquivo que so cresce: {value}% de um disco de trabalho e "
                "quase sempre midia, cache de criacao ou VM. Tirar o arquivo "
                "grande do volume resolve de forma definitiva o que a "
                "limpeza temporaria resolve por uma semana.",
            proof="O volume cai abaixo de {threshold}% e nao volta em poucos "
                "dias, porque o arquivo saiu de la em vez de ser apagado.",
            risk="Programas que gravam no caminho antigo precisam ser "
                "reconfigurados pra apontar pro novo. Reversivel movendo de "
                "volta.",
            reversible=True,
        ),
        _opt(
            "Diminuir o teto das copias de sombra",
            [
                "Painel de Controle > Sistema > Protecao do Sistema > "
                "Configurar.",
                "Baixe o 'Uso maximo' de 10% pra 3-5% do volume.",
                "Clique em 'Excluir' para apagar os pontos ja gravados e "
                "liberar o espaco agora.",
            ],
            why="Restauracao do Sistema guarda copias de cada arquivo "
                "alterado, ate o teto definido — e em disco de trabalho esse "
                "tetos sao gigabytes silenciosos que nunca aparecem na "
                "listagem comum. Baixar o teto libera o excedente na hora e "
                "impede que ele cresca de novo.",
            proof="Os GB que faltavam aparecem livres antes de qualquer "
                "outra limpeza, e o volume para de encher sozinho.",
            risk="Menos pontos de restauracao disponiveis pra voltar atras. "
                "Voce continua podendo criar um manualmente antes de mexer "
                "em driver.",
            reversible=True,
        ),
    ],
    METRIC_IO: [
        _opt(
            "Identificar quem esta martelando o disco",
            [
                "Ctrl+Shift+Esc > adicionar coluna 'Disco' > ordene.",
                "Se o topo e {proc}, veja o caminho aberto no Resource "
                "Monitor (resmon) > aba Disco.",
                "Sendo app seu, 'sentinel kill {pid}' fecha; sendo servico, "
                "use 'net stop \"<nome>\"' — nunca mate servico pelo PID.",
            ],
            why="IO em {value}% significa que a fila do disco esta "
                "saturada: cada leitura sua espera atras das que ja estao "
                "la, e e isso que faz o sistema inteiro parecer travado "
                "enquanto a CPU esta livre. Descobrir o autor do trafego e o "
                "passo que decide se voce fecha um app ou adia uma tarefa.",
            proof="A coluna 'Disco' volta pra dois digitos e abrir arquivo "
                "deixa de ter aquele atraso de um a dois segundos.",
            risk="A tarefa que estava rodando e interrompida no meio.",
        ),
        _opt(
            "Adiar sync de nuvem e backup pra fora do seu horario",
            [
                "OneDrive/Dropbox/Backup: configure limite de banda e "
                "agendamento noturno no proprio cliente.",
                "Pause o download grande que esta rodando agora.",
                "Verifique em 'sentinel status' se o IO ficou abaixo de "
                "{threshold}%.",
            ],
            why="Sincronizador foi feito pra esgotar o disco: ele grava "
                " milhares de arquivos pequenos em rajada, e arquivo pequeno "
                "e o pior caso de IO por operacao. Rodando na sua hora de "
                "uso, ele nao compete por nucleos — compete pela fila do "
                "disco, que e onde a maquina trava.",
            proof="Nas proximas semanas o IO alto so aparece de madrugada, "
                "quando nao te custa nada.",
            risk="Os arquivos ficam um pouco mais atrasados na nuvem.",
            reversible=True,
        ),
        _opt(
            "Checar saude do disco antes de culpar software",
            [
                "IO alto COM pouca transferencia (kBs baixo) e a assinatura "
                "de disco morrendo, nao de app guloso.",
                "Rode 'Optimizar Drives' (dfrgui) > 'Otimizar' e veja o "
                "estado; em SSD, confirme que sobram mais de 10% livres.",
                "Antes de qualquer outra coisa, faca backup do que importa.",
            ],
            why="Quando a midia comeca a falhar, o controlador refaz a "
                "leitura varias vezes antes de devolver o dado: o tempo de "
                "resposta explode sem que nenhum processo esteja pedindo "
                "muita banda. Nesse caso nenhuma acao de software resolve, e "
                "cada dia de espera e risco de perda.",
            proof="Se o problema era fisico, o IO continua alto mesmo com "
                "todos os apps fechados — e isso, sozinho, ja e o "
                "diagnostico.",
            risk="Nenhum no disco; o risco e adiar a troca do componente.",
            reversible=True,
        ),
    ],
    METRIC_NETWORK: [
        _opt(
            "Ver quem esta usando a banda agora",
            [
                "Ctrl+Shift+Esc > aba 'Desempenho' > 'Abrir Monitor de "
                "Recursos' > aba Rede.",
                "Leia a coluna 'Bytes total' por processo: update, sync e "
                "streaming aparecem com nome proprio.",
                "Se o nome for de um servico, anote e decida — nao mate "
                "servico por PID.",
            ],
            why="Banda alta nao deixa a maquina lenta por si: e contexto. O "
                "que importa e saber se o trafego e seu (um download que "
                "voce iniciou) ou de um processo que voce nao reconhece. "
                "Este passo so te da o nome, porque sem nome nao ha "
                "decisao.",
            proof="Voce consegue apontar o processo e dizer se ele devia "
                "estar mandando aquilo agora.",
            risk="Nenhum: o passo so abre uma janela e mostra uma coluna.",
            reversible=True,
            action=_OPEN_TASKMGR,
        ),
        _opt(
            "Limitar a banda do upload que esta subindo agora",
            [
                "No cliente de syncbackup, defina teto de upload (ex.: "
                "1 MBs) no horario de trabalho.",
                "Pause o que nao precisa sair nesta hora.",
                "Confira se a latencia do que voce usa voltou ao normal.",
            ],
            why="O que derruba a sensacao de rede rapida nao e o download, e "
                "o upload cheio: link satiado em diregao de subida significa "
                "ACK atrasado, e ACK atrasado segura download. Limitar o "
                "envio devolve a latencia sem desligar nada.",
            proof="Videochamada e jogos param de ter travadinhas de meio "
                "segundo, mesmo com o sync rodando.",
            risk="O backup ou sync demora mais pra terminar.",
            reversible=True,
        ),
        _opt(
            "So confirmar que o pico era esperado",
            [
                "Cruze o horario do evento com o que voce abriu (update do "
                "Windows, loja, backup agendado).",
                "Se coincide, nao ha nada pra consertar: o evento e "
                "registro, nao defeito.",
                "Se nao ha app seu ativo e a banda continua alta, rode "
                "'sentinel events' e procure outros indicadores no mesmo "
                "minuto.",
            ],
            why="O Sentinel marca banda alta como contexto porque ela quase "
                "nunca e a causa do que voce sente. Agir em cima de um pico "
                "legitimo e o erro classico: voce desliga o update, a maquina "
                "continua lenta, e agora falta informacao.",
            proof="Nos proximos dias o mesmo horario repete o mesmo pico, "
                "com o mesmo processo, sem outro sintoma junto.",
            risk="Nenhum.",
            reversible=True,
        ),
    ],
    # --- anomalias de incidente (schema 2): nao ha limiar, ha historia ---
    METRIC_APP_FAILURE: [
        _opt(
            "Ler o relatorio do Windows sobre esta queda",
            [
                "Rode 'eventvwr' > Logs de Windows > Aplicativo.",
                "Procure o registro do mesmo minuto: o Sentinel ja copiou "
                "pra ca o modulo ({module}) e o codigo ({code}) — o log "
                "confirma com a pilha.",
                "Leia o codigo: 0xc0000005 = memoria invalida (um driver ou "
                "plug-in corrompendo o app); 0xc0000409 = abort do proprio "
                "runtime; 0x80000003 = ponto de depuracao, quase sempre "
                "algum antiviral injetado.",
            ],
            why="Sem o modulo culpado voce tem N apps abertos e nenhuma "
                "forma de escolher qual corrigir. O evento que o Windows "
                "gravou nomeia o arquivo exato que causou a excecao, e o "
                "codigo diz o tipo da dor: e a diferenca entre atualizar um "
                "driver e reinstalar um app que nao tinha nada de errado.",
            proof="O modulo listado no relatorio e o mesmo que o Sentinel "
                "guardou em 'detail.module'. Se bater, voce tem a causa; se "
                "divergir, a queda mudou de natureza e vale reobservar.",
            risk="Nenhum: o passo so le.",
            reversible=True,
        ),
        _opt(
            "Atualizar o componente apontado como culpado",
            [
                "Se '{module}' e .dll/.drv de terceiro (nv*, atig*, igd*, "
                "libcef*, *_ocr*), a queda esta la, nao no app.",
                "Atualize o driver pelo site do fabricante (GPU: NVIDIAAMD "
                "Intel direto), nao pelo Windows Update — o do Windows "
                "costuma ser o build atrasado que quebra.",
                "Reabra o {app} e use por alguns minutos; o Sentinel "
                "registra sozinho se cair de novo no mesmo modulo.",
            ],
            why="Uma excecao de acesso invalido dentro de um modulo de "
                "terceiro e bug de compatibilidade daquele modulo com a "
                "versao atual do app — e o unico dos dois que tem patch. "
                "Reinstalar o app nao troca o .dll que falhou: por isso essa "
                "queda costuma voltar exatamente igual depois da "
                "reinstalacao.",
            proof="O app sobrevive ao mesmo cenario que derrubava antes, e "
                "'sentinel events --open-only' para de acumular occurrences "
                "no fingerprint dele.",
            risk="Driver novo pode introduzir outro bug; grave o ponto de "
                "restauracao antes ou tenha o instalador da versao atual a "
                "mao.",
            reversible=True,
        ),
        _opt(
            "Descobrir se a culpa e do app ou do ambiente",
            [
                "Rode 'sentinel events --json' e olhe quantos apps diferentes "
                "cairam no mesmo minuto.",
                "Varios juntos: o culpado e compartilhado (driver de video, "
                "update em curso, disco falhando). Corrigir app nao "
                "adianta.",
                "So um, repetidas vezes: e bug ou desatualizacao dele "
                "mesmo — procure atualizacao do proprio app antes de "
                "qualquer outra coisa.",
            ],
            why="Uma queda isolada e um problema de aplicativo; uma rajada "
                "de quedas no mesmo relogio e um problema de plataforma. O "
                "historico que o Sentinel ja gravou responde isso em um "
                "comando, e escolher o caminho errado custa uma tarde.",
            proof="Se era plataforma, os outros apps tambem param de cair "
                "quando voce corrige o componente comum — e nao quando "
                "atualiza cada app.",
            risk="Nenhum: o passo so consulta o historico local.",
            reversible=True,
        ),
    ],
    METRIC_ORPHAN_TREE: [
        _opt(
            "Decidir pelo consumo, nao pelo medo",
            [
                "Rode 'sentinel status' e compare a RAMCPU com o que o "
                "evento mostra em 'detail.tree'.",
                "Processo ocioso sem RAM e sem CPU nao te custa nada: matar "
                "um processo que nao doi so cria um problema novo.",
                "Se seguram memoria e o {parent} fechou ha tempo, ai sim "
                "esta vazando — va pro passo de encerrar.",
            ],
            why="Um filho sem pai e um registro, nao uma falha. O que "
                "transforma isso em problema e o custo: working set ou "
                "thread segurados por algo que nunca mais vai ser usado. "
                "Olhar o consumo antes decide se voce age em uma anomalia "
                "inofensiva ou em um vazamento real.",
            proof="Se o mapa nao mudou de uma execucao pra outra e o RSS "
                "esta zerado, era ruido: marque como descartado e o "
                "Sentinel para de insistir.",
            risk="Nenhum; evita o risco de encerrar algo que ainda tinha "
                "funcao.",
            reversible=True,
        ),
        _opt(
            "Encerrar os {orphan_count} processo(s) que ficaram sem pai",
            [
                "Pegue os PIDs de 'detail.orphans' no evento.",
                "Rode 'sentinel kill <PID>' em cada um: o Sentinel confirma "
                "um a um, recusa nucleo do Windows e recusa a si mesmo.",
                "Comece pelo mais fundo no mapa (maior 'depth'), senao o "
                "orfao de cima recria o que voce acabou de fechar.",
            ],
            why="O pai morreu, entao nao existe mais ninguem pra fechar esses "
                "filhos: foi exatamente isso que a arvore que o Sentinel "
                "mapeou mostrou. Encerrar por ordem de profundidade evita o "
                "caso classico em que o processo de controle ainda vivo "
                "relanca o auxiliar que voce derrubou.",
            proof="'sentinel status' mostra a RAM que eles seguravam de "
                "volta, e a mesma arvore nao reaparece no proximo batimento.",
            risk="Se um dos orfaos ainda gravava algo, o arquivo pode ficar "
                "inconsistente. Salve o que puder antes de fechar.",
        ),
        _opt(
            "Tratar como normal se o pai morto era launcher ou instalador",
            [
                "Setup, instalador e atualizador saem antes dos filhos de "
                "proposito: quem termina o servico e o filho, e o Windows "
                "nao re-adota a arvore.",
                "So vale agir se o mesmo padrao se repete a cada execucao e "
                "deixa processo crescendo.",
                "Reporte ao fabricante com o nome do pai que morreu e o que "
                "sobrou — e exatamente o que o evento ja guarda.",
            ],
            why="Encerrar um filho de instalador que ainda esta escrevendo "
                "pode deixar meio pacote no disco, e o dano e real. Como o "
                "padrao e intencional na maioria dos launchers, o sinal que "
                "importa nao e a orfa em si, e a repeticao com crescimento "
                "— e e por isso que o Sentinel conta occurrences no mesmo "
                "fingerprint.",
            proof="Na proxima execucao, o mesmo pai morre e os filhos saem "
                "sozinhos minutos depois: entao era rotina, nao vazamento.",
            risk="Ignorar de mais custa memoria acumulado; o Sentinel volta "
                "a avisar se a contagem subir.",
            reversible=True,
        ),
    ],
}


_TOKENS_FROM_TOP = {"proc": "name", "pid": "pid", "cpu": "cpu", "rss": "rss_mb"}


def _event_tokens(event: dict) -> dict:
    """Os numeros medidos que o evento tem, prontos pra entrar no texto.

    Sem isso o tutorial fala de um processo generico, e a instrucao volta a
    servir pra qualquer maquina — que e exatamente o que o pedido quis
    evitar. Dado ausente nao vira zero inventado: o token fica cru no texto,
    e o teste da base pega o buraco na hora de revisar.
    """
    tokens: dict[str, str] = {}
    top = (event.get("top_processes") or [{}])[0]
    for token, field in _TOKENS_FROM_TOP.items():
        value = top.get(field)
        if value is None:
            continue
        # RSS e CPU sao medidas: um float cru ("3276.0 MB") nao e como se
        # fala de um numero que ja estava redondo.
        tokens[token] = _num(value) if field in ("cpu", "rss_mb") else str(value)
    for key in ("value", "threshold"):
        if key in event:
            tokens[key] = _num(event[key])
    window = event.get("window") or {}
    if window.get("samples"):
        tokens["span"] = _num(float(window.get("span_s", 0.0)))
    detail = event.get("detail") or {}
    for key, token in (
        ("app", "app"),
        ("module", "module"),
        ("exception_code", "code"),
    ):
        if detail.get(key):
            tokens[token] = str(detail[key])
    if detail.get("parent"):
        tokens["parent"] = str(detail["parent"].get("name", ""))
    if detail.get("orphan_count") is not None:
        tokens["orphan_count"] = str(detail["orphan_count"])
    return tokens


def _num(value) -> str:
    number = float(value)
    return str(int(number)) if number == int(number) else f"{number:.1f}"


def bind(option: dict, event: dict) -> dict:
    """Preenche os tokens do texto com o que foi medido neste evento.

    Regex em vez de `str.format` de proposito: um texto gerado por modelo
    pode conter `{}` de codigo (JSON, shell) e nao pode derrubar
    o tutorial por isso. Token desconhecido fica intacto.
    """
    tokens = _event_tokens(event)
    if not tokens:
        return dict(option)

    def replace(text):
        if not isinstance(text, str):
            return text
        return _TOKEN.sub(
            lambda m: tokens.get(m.group(1), m.group(0)), text
        )

    bound = {
        key: replace(value)
        for key, value in option.items()
        if key != "steps"
    }
    bound["steps"] = [replace(step) for step in option.get("steps", [])]
    return bound


def options_for(metric: str, *, event: dict | None = None) -> list[dict]:
    """Ate MAX_FIX_OPTIONS opcoes offline pra `metric`, com os tokens ja
    preenchidos quando um evento e dado.

    Copia defensiva de verdade (inclusive da lista de passos): quem consome
    pode mutar sem corromper o template.
    """
    base = _OPTIONS.get(metric, [])[: settings.MAX_FIX_OPTIONS]
    copies = [
        {**option, "steps": list(option["steps"])} for option in base
    ]
    if event is None:
        return copies
    return [bind(option, event) for option in copies]


def known_metrics() -> list[str]:
    return sorted(_OPTIONS)
