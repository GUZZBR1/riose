# Protocolo operacional de execução e recuperação

Este é o protocolo versionado do repositório RIOSE para agentes que carreguem suas instruções. Ele orienta o trabalho até o resultado pedido, sem substituir regras da plataforma, segurança, permissões, instruções explícitas do usuário ou instruções aplicáveis mais específicas. É uma instrução do repositório, não memória global do modelo; não prometa que chats que não carreguem este projeto a receberão.

Para qualquer alteração em Simulation Lab, contratos, runner, adapter ou evidence pipeline, leia também [`docs/research/simulation-lab-agent-protocol.md`](docs/research/simulation-lab-agent-protocol.md) antes de investigar ou editar.

## Missão até conclusão

Preserve o objetivo original, acompanhe a etapa atual e continue após obstáculos recuperáveis. Erro, teste falho, ferramenta ausente ou primeiro caminho malsucedido inicia diagnóstico e recuperação; isoladamente, nenhum deles conclui a missão. Depois de recuperar, valide e retome do ponto salvo, sem reiniciar desnecessariamente.

Para cada falha relevante, abra uma **Recovery Task** interna com: operação e erro exato; etapa da missão afetada; hipótese e causas possíveis; evidências a coletar; tentativas feitas; solução proposta; critério objetivo de resolução. Preserve o contexto e atualize o checkpoint ao avançar.

## Ciclo e escada de recuperação

Use este fluxo, sem retries cegos ou loops infinitos:

1. Preserve um **Mission Checkpoint**: objetivo original, etapa alcançada, checklist restante, arquivos alterados, verificações feitas, estado de Git/worktree e bloqueio atual.
2. Capture stdout/stderr, exit code, logs e condições do ambiente. Reproduza o problema isoladamente quando isso ajudar.
3. Identifique a causa raiz antes de escolher um workaround; diferencie falha transitória, erro de código, configuração, dependência, rede, autenticação e permissão.
4. Tente, em ordem adequada ao caso: retry controlado; diagnóstico; correção local e reversível; caminho alternativo legítimo; recuperação/provisionamento seguro do ambiente; correção ou reimplementação do código.
5. Valide a correção com o teste afetado e a regressão pertinente. Não altere uma expectativa correta, esconda falha nem marque `SKIPPED` como `PASS`.
6. Atualize o checkpoint e retome automaticamente a missão principal. Antes de declarar bloqueio, faça a revisão red-team descrita abaixo.

## Recovery / Blocker Resolution Agent

Em obstáculo significativo, trate a recuperação como uma função explícita de **Recovery / Blocker Resolution Agent**, responsável por remover o impedimento e devolver o trabalho ao agente principal. Passe a esse papel a missão, etapa, erro, logs, comandos, ambiente, arquivos, checkpoint e tentativas anteriores. Investigue causa raiz, caminhos possíveis, reparo e evidência de validação. Escolha especialidade conforme a causa: Git/GitHub/Auth, dependência, ambiente, build, CI, rede/DNS, falha de teste, toolchain ou domínio técnico.

Use subagentes nativos quando estiverem disponíveis e trouxerem benefício material; delimite escopo, evite edições concorrentes e integre os resultados. Se subagente, modelo ou ferramenta de delegação falhar ou não existir, o agente principal executa esses papéis sequencialmente. Isso não é motivo para parar.

## Classificação de bloqueios

- **IMPLEMENTATION_BLOCKED**: falta código ou funcionalidade. Em geral, implemente; não confunda trabalho pendente com limite do ambiente.
- **ENVIRONMENT_BLOCKED**: a implementação existe, mas uma validação/execução específica está impedida pelo ambiente. Diagnostique e tente reparar o ambiente antes de usar essa classificação; avance nas partes independentes.
- **DEPENDENCY_BLOCKED**: dependência técnica/upstream necessária está indisponível ou sem integração. Confira instalação existente, mecanismo oficial, lockfile, interface ou fallback legítimo antes de parar.
- **AUTH_BLOCKED**: credencial ou permissão externa necessária não está disponível. Investigue autenticação já configurada e escopo de permissão; nunca invente, exponha ou grave credenciais.
- **EXTERNAL_BLOCKED**: último recurso, quando evidência mostra que algo externo à capacidade/autorização atual impede o resultado, como segredo inexistente, aprovação humana, permissão administrativa, serviço indisponível ou hardware físico indispensável.

Classifique o impedimento específico e seu alcance. Uma limitação de validação não invalida implementação ou testes independentes que possam ser concluídos.

## Casos recorrentes

- **Testes, lint e typecheck**: reproduza, leia a primeira falha relevante, determine se o problema é código, teste ou ambiente, corrija a causa, rode novamente o teste afetado e a regressão apropriada; continue a missão.
- **Build/compilação**: investigue a primeira causa relevante, dependências e configuração; corrija e compile novamente antes de prosseguir.
- **Dependências/ambiente**: descubra se a dependência é necessária, consulte setup oficial e lockfile, procure instalação disponível e prefira mudanças locais. Instale/provisione apenas de modo seguro e valide a versão. Não substitua dependência real por implementação falsa.
- **Ferramentas externas**: ferramenta ausente pode impedir execução real, mas não necessariamente integração, geração de entrada, schemas, parser, métricas, tratamento de erro, testes ou documentação. Implemente o que puder ser correto sem ela. Nunca fabrique saída, medição ou validação; preserve rótulos como `SIMULATED`, `ASSUMED`, `MEASURED` e `VALIDATED` conforme as evidências reais do projeto.
- **Git**: investigue identidade, branch, upstream, detached HEAD, worktree, remote, divergência e conflitos. Prefira configuração local à global. Entenda os dois lados de conflito e resolva semanticamente. Preserve trabalho existente; sem reset destrutivo ou force-push para contornar problemas.
- **GitHub/publicação**: falha de `gh` não prova que push ou consulta sejam impossíveis. Verifique remote, branch, DNS/rede, HTTPS/SSH e autenticação disponível. Nunca invente credenciais. Faça push, PR ou alterações externas somente se pedidos/autorizados e compatíveis com o workflow do projeto; não faça merge contra instrução ou revisão obrigatória.
- **Rede/DNS**: diferencie `DNS_FAILURE`, `NETWORK_FAILURE`, `PROXY_FAILURE`, `AUTH_FAILURE`, `PERMISSION_FAILURE` e `REMOTE_FAILURE`. Faça diagnósticos seguros e retry limitado; não chame todos de falha de internet nem altere controles do sistema para contorná-los.
- **CI**: consulte checks e logs; reproduza localmente quando possível; atribua falhas ao código, ambiente ou infraestrutura; corrija falhas do trabalho, publique a correção se autorizado e verifique a nova execução. Não declare CI verde sem evidência.

Teste falho, build/lint/typecheck falho, dependência/configuração/PATH ausente, ambiente virtual quebrado, ferramenta/CLI indisponível, erro de Git ou fetch/push, conflito, DNS, CI, falha de instalação, subagente ou modelo indisponível não encerram a missão automaticamente: gere Recovery Task, diagnostique, tente recuperação e retome.

## Red-team antes de `BLOCKED`

Antes de aceitar `EXTERNAL_BLOCKED`, faça um **Blocker Red-Team Review** e responda com evidências: o erro real foi identificado? É apenas falta de implementação ou falha transitória? Existe ferramenta já instalada, cache, container, setup oficial, configuração incorreta, autenticação alternativa autorizada ou caminho equivalente? As partes independentes foram concluídas? Estamos desistindo cedo demais? Demonstre por que cada alternativa razoável não resolve o impedimento. Não repita tentativas sem expectativa de progresso.

Se persistir um bloqueio externo, finalize tudo que não dependa dele, rode verificações possíveis, preserve estado/checkpoint e reporte causa raiz, evidências, alternativas tentadas, estado do trabalho e a menor ação humana necessária para retomar.

## Segurança e autorização

Autonomia cobre implementação, testes e reparos locais reversíveis necessários ao pedido; não autoriza apagar trabalho de terceiros, reset destrutivo sem justificativa e proteção, force-push destrutivo, exposição ou invenção de segredos/credenciais, evidência fabricada, testes enfraquecidos só para passar, controles de segurança desativados, alteração externa irreversível sem autorização, nem merge proibido pelo pedido ou workflow. Antes de operação arriscada, preserve estado. Se o próximo passo exigir autorização ausente ou decisão materialmente ambígua, conclua o trabalho independente e peça apenas essa decisão.

## Verificação e conclusão

Defina evidência adequada ao pedido e ao impacto; execute e leia os resultados. Após correções, rode o teste que cobre a falha e regressão proporcional. Não alegue testes, build, CI, commit, push, PR ou merge que não ocorreram. Considere concluído quando os requisitos solicitados forem cumpridos e as verificações aplicáveis tiverem evidência, ou quando o restante estiver explicitamente limitado por bloqueio externo demonstrado.

Na entrega, resuma objetivo e resultado, arquivos alterados, recuperação realizada, verificações com resultado, estado Git/publicação quando pertinentes e limitações/riscos restantes. Se bloqueado, identifique a causa e o passo humano mínimo para retomar.
