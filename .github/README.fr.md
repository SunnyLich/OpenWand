<div align="center">

<img src="../assets/doll/idle.png" width="112" alt="Icône OpenWand" />

# OpenWand

**OpenWand ambitionne de devenir l'application de référence pour travailler avec l'IA. Plus besoin de changer de fenêtre ni de copier-coller. Il suffit de formuler votre demande.**

OpenWand garde l'IA à vos côtés pendant que vous travaillez. Utilisez automatiquement le contexte disponible ou ajoutez une source en un clic. OpenWand est entièrement gratuit, multiplateforme, extensible, distribué sous une licence permissive et conçu d'abord en Python : vous choisissez son fonctionnement et le modèle qui l'alimente.

[![Plateformes](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-333333?style=flat-square)](#platform-status)
[![Python](https://img.shields.io/badge/python-3.12-3572A5?style=flat-square)](#quick-start)
[![Local d'abord](https://img.shields.io/badge/local--first-context%20and%20memory-4B8F8C?style=flat-square)](#privacy-and-control)
[![Licence](https://img.shields.io/badge/license-MIT-7C3AED?style=flat-square)](#license)

**Langues :** [English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | Français | [Español](README.es.md)

**Site :** [Documentation OpenWand](https://sunnylich.github.io/OpenWand/)

[Démarrage rapide](#quick-start) | [Fonctionnement](#how-openwand-works) | [Démonstrations](#demos) | [Configuration](#configuration) | [API gratuites](#free-model-api-sources) | [Confidentialité](#privacy-and-control)

![Démonstration des invites OpenWand](readme-assets/openwand-prompt-demo.gif)

</div>

---

## Pourquoi OpenWand

OpenWand vous aide à rester productif en intégrant les demandes à l'IA de façon naturelle et fluide dans votre travail.

### Comparaison des étapes

| Chat IA classique — **8 étapes** | OpenWand — **seulement 2 étapes** |
| --- | --- |
| 1. Trouver et copier le premier élément de contexte.<br>2. Passer à une fenêtre de chat IA.<br>3. Coller le contexte.<br>4. Recommencer jusqu'à ce que le modèle ait tout ce dont il a besoin.<br>5. Saisir votre demande.<br>6. Envoyer la requête.<br>7. Attendre la réponse.<br>8. La lire, puis revenir à votre travail. | 1. Appuyer sur un raccourci pour ouvrir OpenWand.<br>2. Lancer une invite prédéfinie. |

Le texte sélectionné et les sources de contexte activées dans les paramètres sont réunis automatiquement. Si nécessaire, une source supplémentaire s'active en un clic. Choisissez ensuite une invite prédéfinie ou saisissez la vôtre.

<a id="how-openwand-works"></a>
## Fonctionnement d'OpenWand

OpenWand vous donne accès à l'IA depuis n'importe quel endroit du bureau. Vos invites réutilisables restent à portée de main, le contexte est recueilli automatiquement et les sources supplémentaires sont accessibles en un clic : chaque requête demande moins d'étapes.

### Interroger l'IA

**Vous :** Appuyez sur un raccourci → `(Ajouter du contexte)` → Choisissez une invite réutilisable ou personnalisée

**OpenWand :** Recueille et prévisualise le contexte → `(Vérifie la confidentialité et les injections d'invite)` → Interroge le modèle choisi → Affiche la réponse

### Demander une reformulation sur place

**Vous :** Sélectionnez le texte → Appuyez sur le raccourci de reformulation → `(Ajoutez du contexte)` → Choisissez une reformulation → Acceptez

**OpenWand :** Capture la sélection → `(Vérifie la confidentialité et les injections d'invite)` → Rédige la réponse → Affiche un aperçu → La recolle à sa place

*Les actions entre parenthèses sont facultatives.*

## Points forts

- **Ignorez la préparation. Demandez, tout simplement.** — Interrogez l'IA où que vous soyez sans vous soucier du contexte.
- **Des réponses mieux présentées** — Chaque réponse devient localement un rendu HTML et CSS soigné, sans appel de modèle ni coût supplémentaire.
- **Intégration de Codex et Claude** — Exécutez l'un ou l'autre agent directement depuis OpenWand.
- **Mode privé** — Alertes et masquage facultatifs pour le contexte sensible.
- **Hautement personnalisable** — Personnalisez les raccourcis, les invites, le contexte, les modèles, la voix, le recollage et l'interface.
- **Puissant, mais accessible** — OpenWand simplifie le contrôle des modèles, de la confidentialité, de la mémoire et du contexte.
- **Le contexte sous contrôle en un clic** — OpenWand le gère automatiquement ou vous laisse l'ajouter d'un seul clic.
- **La saisie est facultative** — Dictez votre demande et écoutez la réponse.
- **Interrogez tout ce qui apparaît à l'écran** — Tracez une zone et transformez-la instantanément en contexte visuel.
- **Reformulation sur place** — Reformulez le texte sélectionné, vérifiez le résultat et recollez-le au même endroit.
- **Utilisez le modèle de votre choix** — De nombreux fournisseurs cloud, des modèles locaux ou tout serveur compatible avec OpenAI sont pris en charge.
- **Une mémoire sous votre contrôle** — Conservez facultativement une mémoire à court et long terme en local, avec la possibilité de la consulter ou de la supprimer.
- **Étendez chaque aspect** — Ajoutez des invites, actions, raccourcis, hooks et outils de modèle grâce aux add-ons et à MCP.
- **Le travail multi-agents simplifié** — Constituez votre équipe dans une interface visuelle guidée en langage clair, puis suivez sa progression et examinez ses résultats.

<a id="demos"></a>
## Démonstrations

![Démonstration du contexte inter-applications OpenWand](readme-assets/openwand-context-demo.gif)

**Contexte inter-applications :** Combinez la sélection active avec le contexte activé du navigateur et de l'application afin de fournir au modèle les éléments nécessaires sans copier-coller manuellement.

![Démonstration de la capture d'écran Ctrl+Alt+Q d'OpenWand](readme-assets/openwand-screen-snip-demo.gif)

**Capture visuelle :** Lorsque le contexte visuel compte, `Ctrl+Alt+Q` vous permet de tracer une zone, d'envoyer uniquement cette capture à un modèle de vision et de garder la réponse dans la superposition sans changer d'application.

![Démonstration de la reformulation OpenWand](readme-assets/openwand-rewrite-demo.gif)

**Reformulation sur place :** Reformulez uniquement le texte sélectionné, examinez la proposition, puis recollez le résultat accepté dans le champ qui était actif à l'ouverture d'OpenWand.

![Démonstration d'une action sensible à l'application dans OpenWand](readme-assets/openwand-app-aware-action-demo.gif)

**Action sensible à l'application :** Utilisez le contexte de l'application active pour analyser ou traiter le travail en cours, avec un résultat clair et une confirmation lorsqu'aucune cellule du document n'a été modifiée.

![Démonstration de l'équipe d'agents OpenWand](readme-assets/openwand-agent-task-demo.gif)

**Équipe d'agents :** Déléguez une tâche plus longue dans l'espace de travail à des rôles de coordination, de réalisation et de révision. Pendant que vous continuez à utiliser OpenWand, l'équipe peut examiner les fichiers du projet, apporter une modification ciblée, exécuter des vérifications et fournir un rapport final ainsi que des livrables révisables.

## Flux de travail

| De votre côté | Ce que fait OpenWand |
| --- | --- |
| Surligner du texte, choisir du contexte ou tracer une capture | Capture uniquement le contexte sélectionné ou activé |
| Appuyer sur le raccourci d'appel et choisir une action ou une invite personnalisée | Construit la requête au modèle à partir de votre invite et du contexte choisi |
| Envoyer la requête | L'envoie directement au fournisseur de modèle configuré |
| Attendre la réponse | Diffuse la réponse dans une bulle, avec lecture TTS automatique facultative |
| Conserver une information utile pour plus tard | La stocke localement uniquement si la mémoire est activée |

### Raccourcis courants

| Lorsque vous souhaitez… | Avec OpenWand |
| --- | --- |
| **Comprendre le texte sélectionné** | Sélectionnez-le, ouvrez OpenWand et choisissez `What is this?` ou `Explain simply`. |
| **Reformuler sans copier-coller** | Sélectionnez le texte, choisissez une reformulation, vérifiez-la, puis recollez la version acceptée à sa place. |
| **Poser votre propre question** | Saisissez une invite personnalisée. Le contexte activé est déjà joint ; les autres sources sont accessibles en un clic. |
| **Interroger tout ce qui apparaît à l'écran** | Appuyez sur `Ctrl+Alt+Q`, tracez une zone autour de l'élément concerné et envoyez-la à votre modèle de vision. |
| **Interroger sans saisir de texte** | Maintenez `F9` et parlez. OpenWand transcrit votre demande et l'envoie au modèle. |
| **Dicter dans n'importe quelle application** | Maintenez `F8` et parlez. Vos mots apparaissent directement dans le champ de texte actif. |

<a id="quick-start"></a>
## Démarrage rapide

### Télécharger l'application

1. Téléchargez la dernière version depuis les [versions GitHub](https://github.com/SunnyLich/OpenWand/releases).
2. Extrayez l'archive et lancez OpenWand.
3. Ouvrez les paramètres et connectez votre modèle.

Vous pouvez installer OpenWand avant de choisir une connexion à un modèle. Si vous n'en avez pas encore, commencez par l'une des [plus de 20 sources d'API gratuites ou d'essai](https://sunnylich.github.io/OpenWand/#free-apis), ou connectez un modèle local.

| Windows | macOS | Linux |
| --- | --- | --- |
| `OpenWand.exe` | `OpenWand.app` | `OpenWand` |

### Exécuter depuis les sources

OpenWand nécessite Python 3.12.

```bash
git clone https://github.com/SunnyLich/OpenWand.git
cd OpenWand
```

Exécutez le lanceur correspondant à votre plateforme :

| Windows | macOS | Linux |
| --- | --- | --- |
| `Start OpenWand.bat` | `Start OpenWand.command` | `Start OpenWand.sh` |

Au premier lancement, l'environnement Python est préparé et les dépendances sont installées. Les lancements suivants ouvrent directement l'application.

Pour empaqueter OpenWand vous-même, consultez [Créer un EXE](../docs/BUILDING_EXE.md).

## Configuration requise

| Niveau | Configuration | Idéal pour |
| --- | --- | --- |
| **Minimum** | Windows 10+, macOS 13+ ou Linux X11 ; 4 Go de RAM ; 2 Go d'espace libre | Fonctions principales de la superposition avec une API cloud ou gratuite |
| **Recommandé** | 8 Go de RAM ou plus ; 6 Go d'espace libre ou plus ; microphone pour les fonctions vocales | Reconnaissance vocale locale, filtre de confidentialité avancé facultatif de 2,8 Go et davantage de marge |

Les modèles d'IA locaux peuvent nécessiter beaucoup plus de RAM, de VRAM et de stockage selon le modèle. La capture d'écran, les raccourcis globaux, le recollage et la voix peuvent demander les autorisations correspondantes du système d'exploitation lorsque vous les utilisez.

<a id="configuration"></a>
## Configuration

Utilisez la fenêtre Paramètres pour la configuration habituelle. `.env.example` sert uniquement de référence pour la configuration avancée depuis les sources.

1. Ouvrez les **Paramètres**.
2. Choisissez un moteur de conversation.
3. Connectez votre fournisseur ou votre compte.
4. Personnalisez le contexte, les raccourcis, la voix, la confidentialité et la mémoire.
5. Exécutez la **Vérification de la configuration**.

### Choisir votre moteur

| Moteur | Comportement |
| --- | --- |
| **OpenWand** | Utilise le fournisseur LLM et le modèle configurés dans OpenWand. |
| **ChatGPT** | Utilise le Codex CLI installé et votre compte ChatGPT/Codex. |
| **Claude Agent** | Utilise Claude Agent avec votre compte Claude Code. |

### Contrôles des agents

- **Continuité** — Poursuivez la conversation dans OpenWand ou reprenez-la avec ChatGPT ou Claude.
- **Progression en direct** — Suivez les réponses, les plans, l'activité des outils, l'état des fichiers et les demandes d'autorisation.
- **Autorisations** — Demandez confirmation avant les changements, autorisez les modifications du projet ou utilisez le mode de planification en lecture seule.
- **Périmètre du projet** — Les écritures de l'agent restent dans le projet sélectionné ; changer de projet démarre une nouvelle session.
- **Historique** — Importez, synchronisez facultativement ou exportez les conversations ChatGPT/Codex et Claude.

### Bon à savoir

- Les clés des fournisseurs et les jetons OAuth sont stockés dans le trousseau du système d'exploitation, pas dans un fichier de configuration en texte brut.
- Les réglages avancés des sources sont documentés dans `.env.example`.
- Pour en savoir plus, consultez le [guide des agents en direct](https://sunnylich.github.io/OpenWand/#live-agents) ou parcourez les [sources d'API de modèles gratuites](https://sunnylich.github.io/OpenWand/#free-apis).

## Raccourcis par défaut

| Raccourci | Action |
| --- | --- |
| `Ctrl+Q` sous Windows, `Ctrl+Alt+Space` sous macOS/Linux | Ouvrir le sélecteur d'actions général |
| `Ctrl+Shift+Q` sous Windows, `Ctrl+Alt+Shift+Space` sous macOS/Linux | Ouvrir le sélecteur de reformulation/recollage |
| `Ctrl+Alt+Q` | Tracer une capture d'écran pour la vision |
| `Alt+Q` | Ajouter la sélection actuelle au tampon de contexte |
| `Alt+W` | Effacer le tampon de contexte |
| `F7` | Lire le texte sélectionné à voix haute |
| Maintenir `F9` | Enregistrer la voix, transcrire et interroger |
| Maintenir `F8` | Dicter directement dans le champ de texte actif |
| `W` / `A` / `D` | Déclencher les actions intégrées |
| `S` | Mode d'invite personnalisée |
| `Esc` | Annuler le sélecteur |

Chaque appelant, raccourci, libellé, invite, source de contexte, réglage de recollage et dimension de l'interface est configurable depuis les Paramètres.

## Add-ons

Profondément extensible, OpenWand se transforme grâce aux add-ons : nouvelles fonctionnalités, nouveaux flux de travail, nouvelles possibilités. Avant son activation, chaque add-on déclare son auteur et les accès OpenWand demandés ; une mise à jour ne redemande votre accord que si ces accès s'élargissent. Les add-ons s'exécutent dans des processus Python séparés, et les paquets déclarés par l'éditeur restent dans des environnements virtuels dédiés. Un add-on contenant du code complet conserve toutefois les permissions normales de votre compte utilisateur : n'installez que des add-ons auxquels vous faites confiance.

Dans les versions portables, OpenWand crée un dossier `addons` à côté de `OpenWand.exe` si cet emplacement est accessible en écriture. Si l'application est installée dans un emplacement en lecture seule, utilisez **Gestionnaire d'add-ons -> Ouvrir le dossier des add-ons** pour ouvrir le dossier de secours accessible en écriture par l'utilisateur.

Un add-on peut intervenir à plusieurs endroits dans OpenWand :

- **Contexte** - lire ou réécrire l'invite et le contexte avant l'envoi d'une requête.
- **Outils** - enregistrer des outils que le modèle peut appeler en cours de réponse.
- **Réponses** - observer les réponses terminées afin de les journaliser, de les enregistrer ou de les transférer.
- **Actions et raccourcis** - ajouter ses propres actions et raccourcis globaux avec des invites personnalisées.
- **Interface** - ajouter des actions dans la zone de notification, des champs de réglage et des notifications.
- **Actions LLM** - exécuter ses propres appels de modèle plafonnés depuis un hook ou un raccourci.

**Ce que les add-ons peuvent faire :** puisqu'un add-on peut injecter du contexte, exposer des outils et réagir aux réponses, les possibilités sont nombreuses. Voici quelques exemples et le hook utilisé par chacun :

| Vous souhaitez… | Hook | Besoins du manifeste |
| --- | --- | --- |
| Ajouter automatiquement votre diff git, votre calendrier ou un ticket ouvert à l'invite | Contexte (`before_query`) | `query = "modify"` |
| Donner au modèle un outil pour chercher dans un wiki interne, interroger une base de données, appeler une API météo ou boursière, ou contrôler un appareil domotique | Outils (`get_tools`) | `tools = true` (plus `[dependencies]` pour les paquets nécessaires) |
| Masquer ou étiqueter le contexte sensible avant son envoi à des fins de conformité | Contexte (`before_query`) | `query = "modify"` |
| Ajouter chaque réponse à un journal quotidien ou l'envoyer vers Notion ou Slack | Réponses (`after_response`) | `response = "read"` |
| Ajouter une action en une touche « reformuler selon notre style » fondée sur sa propre invite | Actions et raccourcis | `[[intents]]` / `[[hotkeys]]`, `hotkeys = true` |

Si vous pouvez l'écrire en Python et que la fonctionnalité correspond à l'un des hooks ci-dessus, vous pouvez l'intégrer à la même superposition pilotée par raccourcis que vous utilisez déjà.

## Client et serveur MCP

### Client MCP : utiliser des serveurs externes dans OpenWand

OpenWand inclut un add-on **MCP bridge** (`addons/mcp_bridge`) qui joue le rôle de client MCP : répertoriez des serveurs [Model Context Protocol](https://modelcontextprotocol.io) dans son fichier `servers.json`, et OpenWand expose l'ensemble de leurs outils à son modèle sous forme d'outils OpenWand. La superposition peut ainsi employer des fonctions MCP externes sans quitter le bureau. Consultez le [guide des add-ons](../addons/README.md) pour le contrat complet des manifestes et hooks, ou la [documentation des Add-ons](https://sunnylich.github.io/OpenWand/#addons).

### Serveur MCP : OpenWand Context Server

OpenWand fournit également un **serveur MCP stdio** local nommé **OpenWand Context Server**. Les clients MCP de confiance, tels que Claude Desktop, Cursor et Codex, peuvent le lancer pour lire le contexte actif du bureau ; l'application OpenWand n'a pas besoin de rester ouverte.

#### Outils

OpenWand Context Server propose cinq outils en lecture seule :

- `get_selected_text` — le texte actuellement sélectionné sur le bureau.
- `get_clipboard` — le texte du presse-papiers.
- `get_active_window` — l'application active, le titre de la fenêtre et, s'il est disponible, l'URL du navigateur.
- `read_browser_page` — le texte de la page visible dans le navigateur.
- `take_screen_snip` — une capture d'écran du moniteur principal.

#### Connecter un client

Lancez OpenWand une fois, puis copiez l'entrée `mcpServers` de `addons/mcp_bridge/claude_config_snippet.json` dans la configuration de votre client MCP. OpenWand génère cet extrait avec le chemin local correct vers son propre interpréteur Python et `addons/mcp_bridge/context_server.py` ; ne le remplacez pas par le Python du système. Consultez le [guide de configuration du serveur MCP Bridge](../addons/mcp_bridge/README.md) pour les remarques propres aux plateformes et le dépannage.

Enregistrez le serveur uniquement auprès de clients de confiance : les résultats des outils peuvent contenir le texte sélectionné, le contenu du presse-papiers, le contenu du navigateur et des captures d'écran de votre bureau.

<a id="privacy-and-control"></a>
## Confidentialité et contrôle

OpenWand ne possède aucune couche de stockage hébergée.

| Domaine | Ce qui se passe |
| --- | --- |
| Données locales | Les paramètres, chats, mémoires, rapports de confidentialité et configurations restent sur votre machine. |
| Requêtes au modèle | Votre invite et le contexte activé sont envoyés directement au fournisseur ou au serveur local choisi. |
| Identifiants | Les clés des fournisseurs et les jetons OAuth sont stockés dans le trousseau de votre système d'exploitation. |
| Aperçus du contexte | Les sources et estimations de jetons sont examinées localement sans être envoyées ni enregistrées. |
| Autorisations | Les sources de contexte et les outils du modèle sont contrôlés séparément ; les fonctions facultatives restent désactivées tant qu'elles ne sont pas configurées. |
| Add-ons | Chaque add-on s'exécute dans un processus isolé et déclare les accès dont il a besoin. |

### Modes de confidentialité

| Mode | Protection |
| --- | --- |
| **Désactivé** | Envoie le contexte choisi sans masquage de confidentialité. |
| **Intégré** | Détecte localement les secrets structurés, tels que les identifiants, jetons et informations de paiement. |
| **Avancé** | Ajoute le modèle local facultatif [OpenAI Privacy Filter](https://openai.com/index/introducing-openai-privacy-filter/) pour les noms, adresses, URL privées, informations de compte et autres données sensibles. |

Le mode avancé nécessite un téléchargement facultatif d'environ 2,8 Go et peut demander un temps de préchauffage. Il peut réduire les divulgations accidentelles, mais ne peut pas garantir que chaque information sensible sera détectée.

### Protection contre l'injection d'invite

Lorsqu'elle est activée, OpenWand recherche dans le texte capturé les tentatives de remplacement des instructions du modèle et vous permet de continuer ou d'annuler avant l'envoi.

Pour signaler une vulnérabilité, consultez la [Politique de sécurité](../SECURITY.md). N'incluez pas de détails sur la vulnérabilité, d'identifiants, de contexte capturé ou de journaux privés dans une issue publique.

<a id="platform-status"></a>
## État des plateformes

| Plateforme | État |
| --- | --- |
| Windows 10+ | Pris en charge |
| macOS 13+ | Pris en charge* |
| Linux X11 | Pris en charge |
| Linux Wayland | En cours — la prise en charge de Wayland est en développement |

*Cette application n'a été testée sous macOS que pendant deux semaines de développement majeur. Mon accès limité au matériel ne me permet plus de la tester. Si vous trouvez des bugs sous macOS, ouvrez une issue dans ce dépôt et je ferai de mon mieux pour les corriger. Mieux encore, si vous pouvez proposer une solution, ouvrez une pull request.

## Aide et retours

- [Résoudre les problèmes courants](https://sunnylich.github.io/OpenWand/#common-issues)
- [Signaler un bug](https://github.com/SunnyLich/OpenWand/issues/new?template=bug_report.yml)
- [Poser une question de configuration ou d'utilisation](https://github.com/SunnyLich/OpenWand/discussions/categories/q-a)
- [Suggérer une fonctionnalité](https://github.com/SunnyLich/OpenWand/discussions/categories/ideas)

Pour signaler un bug, indiquez la version du système, le lanceur, les journaux et l'action qui l'a déclenché. Les journaux peuvent contenir du texte capturé ; supprimez les identifiants et les informations personnelles avant de les partager.

Nous travaillons actuellement à la prise en charge de Linux Wayland ; toute aide pour la tester ou l'améliorer est particulièrement utile. Les tests sous macOS sont également les bienvenus. Ces plateformes présentent le plus de cas limites liés aux intégrations natives : les retours réels provenant de machines, d'environnements de bureau et d'états d'autorisation différents rendent OpenWand meilleur pour tout le monde.

Pour soutenir ce projet et sa mission plus large, vous pouvez contribuer directement au développement ou faire un don [ici](https://buymeacoffee.com/sunnylich).

<details>
<summary>Documentation destinée aux contributeurs</summary>

- [README développeur](../docs/DEVELOPER_README.md) - configuration, points d'entrée d'exécution, vérifications et notes de débogage.
- [Vue d'ensemble du code](../docs/OVERVIEW.md) - responsabilités des sous-systèmes et limites d'exécution.
- [Guide des add-ons](../addons/README.md) - manifeste, autorisations, hooks, outils, raccourcis et empaquetage des add-ons.
- [Créer un EXE](../docs/BUILDING_EXE.md) - remarques sur l'empaquetage Windows.

</details>

<a id="free-model-api-sources"></a>
## Sources d'API de modèles gratuites

Commencez à utiliser OpenWand sans frais grâce à une API gratuite ou à un modèle hébergé localement. Notre guide répertorie plus de 20 sources d'API gratuites ou d'essai, ainsi que des options locales.

[Parcourir le guide des modèles gratuits →](https://sunnylich.github.io/OpenWand/#free-apis)

<a id="license"></a>
## Licence

MIT
