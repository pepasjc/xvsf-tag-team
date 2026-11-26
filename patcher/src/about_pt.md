# Painel lateral da página em português (patcher/make.py lê as seções abaixo; "## chave: Título" = título, "- " = item)
# Mantenha em sintonia com README.md (XvSF) e patcher/src/mshvsf.md (MSHvSF, introdução).

## intro: Quais jogos
- **X-Men vs. Street Fighter** (EUA, SLUS-00627): tag hack 1.4.
- **Marvel Super Heroes vs. Street Fighter** (EUA, SLUS-00793): tag hack 1.1.
- Marvel vs. Capcom (EUA, SLUS-01059): em andamento, esta página ainda não monta ele.
- A página reconhece o jogo pelos arquivos do seu disco e confere o dump exato pelo SHA-1. Outros lançamentos (Japão, Europa), imagens que já estão com patch e dumps alterados são recusados, com o motivo.

## xvsf: O que isto faz
- Os quatro personagens da luta são carregados por completo (o jogo original só carrega um parceiro cortado), sem acesso ao disco durante a luta.
- Troque de personagem a qualquer momento com **HP + HK**. O parceiro entra com um ataque e vira o personagem controlado, com todos os golpes.
- Cada personagem tem a sua barra de vida; as duas aparecem para cada lado.
- Um personagem nocauteado é substituído pelo parceiro. A luta tem um round só e termina quando os dois personagens de um time caem.
- Só o personagem que está no banco recupera vida.
- A CPU troca de personagem sozinha, com a lógica original do arcade.
- Dá para trocar de personagem contra o chefe final.
- Team super e counter assist precisam de um parceiro ainda de pé.
- A música muda para o tema de quem entra depois de um nocaute.
- A dificuldade da CPU sobe durante a primeira luta como no arcade (a versão de PlayStation começava no máximo), e o cronômetro do round usa a velocidade do arcade.
- O carregamento das lutas é mais rápido que no disco original.
- START depois de uma luta vencida pula a fala de vitória, a tela de personagens e a tela de VS e carrega a próxima luta (no Arcade). O movimento livre depois do nocaute agora fica no SELECT.
- **VERSUS CPU** no menu principal (logo abaixo de VERSUS MODE): quem escolhe monta os dois times e luta contra a CPU, na dificuldade do OPTION MODE.
- **EX OPTIONS** no menu principal: ARCADE BALANCE (salvo no memory card; OFF mantém as regras do PlayStation exatamente como antes, ON usa as regras do arcade: metade do ganho de barra de super e sem encadear supers), STAGE ANIM FULL / OFF, ACHIEVEMENT POPUP e INFINITE SUPER METER (desligado por padrão; com ele ligado as conquistas não desbloqueiam). Também: o diálogo do Apocalypse antes da luta (do arcade japonês, com texto em inglês nosso), a fábrica química explode no primeiro nocaute como no arcade, e PERFECT só com o time inteiro sem dano.
- Conquistas embutidas (28): uma página ACHIEVEMENTS no menu principal, avisos de desbloqueio e progresso salvo no memory card. No PS2 ou no PS3 elas se desligam sozinhas e o jogo roda normalmente.
- Uma tela de abertura curta antes do jogo começar e uma linha de versão no menu principal.

## xvsf: Controles
- Troca de personagem: **HP + HK**.
- Botões padrão: HP = R1, HK = R2, 3P = L1, 3K = L2 (ou seja, a troca é R1 + R2).

## xvsf: Quadros restaurados (opcional, 8 MB)
- Montada junto com o seu próprio ROM set do arcade, a imagem também leva quadros de animação que a versão de PlayStation cortou, convertidos dos gráficos do arcade na hora da montagem.
- Restaurados: Wolverine, Cyclops, Storm, Rogue, Gambit, Sabretooth, Juggernaut, Magneto, Dhalsim, Zangief e Cammy (animações do corpo e, onde a versão de PlayStation cortou, capas, rastros de golpes e raios), três sprites cortados do Ryu e a tela de seleção de personagens.
- Não restaurados: Ken, Chun-Li, M. Bison, Akuma, Charlie e Apocalypse usam os quadros da versão de PlayStation. Alguns golpes dos personagens restaurados também mantêm os quadros originais do port.
- Os quadros só são usados num console com 8 MB de RAM (uma opção do emulador, como o "Enable 8MB RAM" do DuckStation, ou um console/core de FPGA preparado para isso). Aí o menu principal mostra "8MB" depois da versão, e o EX OPTIONS ganha a linha ARCADE FRAMES ON / OFF. Num console comum de 2 MB, a mesma imagem roda como o tag hack normal.
- Carregamento mais curto com 8 MB: os personagens ficam na memória entre as lutas, junto com os arquivos das telas de seleção, vitória e VS. Isso economiza uns 3 a 6 segundos entre uma luta e outra.
- ROM sets do arcade suportados: `xmvsf`, `xmvsfu`, `xmvsfu1d` (com o set pai).

## xvsf: Problemas conhecidos
- Golpes com sprites muito grandes ficam lentos. O jogo original tem o mesmo problema; este hack tenta igualar a velocidade do original nesses momentos, não superar.
- Uma troca apertada enquanto um golpe ainda está terminando é ignorada; aperte de novo.
- O turbo vem desligado, como no jogo original. O ritmo padrão do arcade americano corresponde a Options → Turbo Speed 2.
- Nos times mais pesados e nos cenários maiores, um ou mais personagens usam uma codificação de sprites mais lenta.
- Com os quadros restaurados, a linha de versão no menu principal sempre aparece (ela mostra o indicador 8MB).

## xvsf: Como cabe em 2 MB
- Quatro personagens completos precisam de uns 2,0 MB; só há uns 1,24 MB livres. Os sprites dos personagens são recodificados com um codec mais compacto e decodificados por uma rotina colocada dentro do jogo, o código dos personagens é realocado na hora do carregamento, e um novo carregador de lutas junta tudo e escolhe, a cada luta, a codificação de sprites mais rápida que ainda cabe.

## mshvsf: O que isto faz
- Os modos Arcade e Versus viram um jogo de tag-team de verdade: dois personagens completos de cada lado, com as regras de troca do próprio modo Cross Over do jogo.
- Troque com **HP + HK** (R1 + R2 no padrão). Uma barra de vida por personagem; só quem está no banco recupera vida; um personagem nocauteado é substituído pelo parceiro e o round acaba quando os dois caem.
- Cada personagem da luta usa o seu próprio banco de som completo (parceiros incluídos), reconstruído a partir do seu disco.
- O modo Training também usa as regras de troca, e os personagens secretos são escolhidos segurando SELECT (Apocalypse: SELECT seis vezes no Akuma).
- START depois de uma luta vencida pula a fala de vitória e o mapa.
- **VERSUS CPU** no menu principal (logo abaixo de VERSUS): quem escolhe monta os dois times e luta contra a CPU.
- **EX OPTIONS** no menu principal: STAGE ANIM, ACHIEVEMENT POPUP, ARCADE BALANCE (as regras do arcade de barra e defesa, desligado por padrão) e INFINITE SUPER METER (desligado por padrão; com ele ligado as conquistas não desbloqueiam).
- **Norimaro** pode ser escolhido, com um texto de final em inglês feito por nós.
- Corrigido na 1.1: o travamento depois do chefe final quando o parceiro estava em campo no nocaute.
- A opção CROSS OVER do menu principal some (este modo substitui ela); a linha de versão no menu principal mostra a versão.

## mshvsf: Conquistas
- Embutidas: 46 conquistas adaptadas do set do RetroAchievements feito por Lowsun, uma página ACHIEVEMENTS no menu principal, avisos de desbloqueio e progresso salvo no memory card.
- No PS2 ou no PS3 elas se desligam sozinhas e o jogo roda normalmente.

## mshvsf: Quadros restaurados (opcional, 8 MB)
- Com o seu ROM set do arcade, a imagem também leva quadros de animação que a versão de PlayStation cortou, reconstruídos dos sprites do arcade na hora da montagem.
- A imagem de 8 MB tem tudo da 1.1, mais **vozes melhoradas**: as vozes vêm da memória extra com qualidade total, e 345 amostras de voz são as gravações do próprio arcade (cerca de 12 kHz, duração completa), convertidas na montagem a partir do seu ROM set. Cada animação restaurada é conferida com os dados do arcade (restaurada inteira ou não).
- Eles só são usados quando o console tem 8 MB de RAM (DuckStation / SwanStation: Settings → Console → Enable 8MB RAM). Aí o menu principal mostra “8MB”. Num console de 2 MB, a mesma imagem roda como o tag hack normal.

## mshvsf: Problemas conhecidos
- Testado num PlayStation de verdade (PSIO), no MiSTer (2 MB e 8 MB), no PSP / PS Vita (Adrenaline) e em emuladores. PS3 (testado): roda, e as conquistas se desligam sozinhas; PS2: testado em emulação com uma BIOS de PS2 (mesmo comportamento).
- Times pesados podem ficar mais lentos nos super golpes (o jogo decodifica mais dados de sprite do que nas lutas originais com dois personagens).
- Nas lutas com quatro personagens, os bancos de som podem ficar com taxa de amostragem reduzida em 2 MB, para os quatro caberem na RAM de som.

## legal: Aviso legal
- Este é um projeto de fã não oficial, sem ligação nem aprovação da editora do jogo ou dos donos dos direitos. Todo o conteúdo do jogo continua sendo propriedade dos seus donos. Use só com um disco que seja seu.
